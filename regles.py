"""Règles de gestion de Bâti Gestion, reprises du prototype (V3/V7) sans modification de fond.

Montants en centimes entiers. Trois monnaies tenues séparément (USD, CDF, EUR) : aucune conversion
automatique ; un taux n'est appliqué que lorsque l'usager change explicitement la monnaie d'un document.
Aucun taux fiscal ou social n'est prédéfini.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import math
import re
import unicodedata

import db

CURRENCIES = ["USD", "CDF", "EUR"]
CURRENCY_LABELS = {"USD": "USD — Dollar américain", "CDF": "CDF — Franc congolais", "EUR": "EUR — Euro"}
CASH_ACCOUNTS = {"cash": "Caisse (espèces)", "bank": "Banque", "mobile": "Mobile money"}
STATUSES = ["À démarrer", "En cours", "Suspendu", "Terminé"]
QUOTE_STATUSES = ["Brouillon", "Envoyé", "Accepté", "Refusé"]
BASE_EXPENSE_CATEGORIES = ["Matériaux", "Main-d’œuvre", "Transport", "Location de matériel", "Autre"]
PARTY_ROLES = {"client": "Client", "supplier": "Fournisseur", "subcontractor": "Sous-traitant"}
ATTENDANCE_STATUSES = ["Présent", "Absent", "Congé", "Maladie", "Mission", "Repos"]
ZERO_HOUR_STATUSES = {"Absent", "Congé", "Maladie", "Repos"}
HR_CONTRACTS = ["À préciser", "CDI", "CDD", "Journalier", "Autre"]
HR_PAY_PERIODS = ["Mois", "Jour", "Heure"]
HR_V7_FIELDS = [("establishment", "Établissement"), ("team", "Équipe"), ("costCentre", "Centre de frais"),
                ("category", "Catégorie professionnelle"), ("cnss", "N° CNSS"), ("civilStatus", "État civil")]
PAY_FIELDS = [("bonus", "Primes"), ("allowances", "Indemnités"), ("overtime", "Heures supplémentaires (montant)"),
              ("absence", "Retenue pour absences"), ("advance", "Avances à déduire"),
              ("social", "Cotisations salariales"), ("tax", "Impôt sur rémunération"), ("other", "Autres retenues")]
PAY_V7_EXTRA = [("holidays", "Jours fériés (rémunération supplémentaire)"), ("family", "Allocations"),
                ("loan", "Remboursement de prêt"), ("cnssEmployer", "CNSS patronale"), ("onem", "ONEM"),
                ("inpp", "INPP"), ("employerOther", "Autres charges employeur")]
PAY_RATE_FIELDS = [("social", "Cotisations salariales / CNSS"), ("tax", "IPR / impôt"),
                   ("cnssEmployer", "CNSS patronale"), ("onem", "ONEM"), ("inpp", "INPP")]
PIECE_TYPES = ["Facture", "Reçu", "Bon de caisse", "Bordereau bancaire", "Preuve de paiement", "Bon de livraison",
               "Photo", "Document de chantier"]
PIECE_MAX = 5 * 1024 * 1024


# ------------------------------------------------------------------ outils
def js_round(x: float) -> int:
    """Arrondi comme Math.round en JavaScript (demi vers le haut), pour des résultats identiques au prototype."""
    return int(math.floor(x + 0.5))


def today() -> str:
    return dt.date.today().isoformat()


def is_date(v) -> bool:
    if not isinstance(v, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return False
    try:
        return dt.date.fromisoformat(v).isoformat() == v
    except ValueError:
        return False


def is_month(v) -> bool:
    return isinstance(v, str) and bool(re.fullmatch(r"\d{4}-\d{2}", v)) and is_date(v + "-01")


def money(n: int | float | None, currency: str = "USD") -> str:
    """1234567 centimes → « 12 345,67 USD » (espaces insécables)."""
    n = int(n or 0)
    signe = "-" if n < 0 else ""
    n = abs(n)
    entier, cent = divmod(n, 100)
    groupes = f"{entier:,}".replace(",", " ")
    return f"{signe}{groupes},{cent:02d} {currency}"


def plain(n: int | None) -> str:
    """Montant pour les exports : 1234.56"""
    return f"{(n or 0) / 100:.2f}"


def cents(valeur, libelle: str = "Montant", positif: bool = False) -> int:
    """Convertit une saisie (nombre ou texte) en centimes ; deux décimales au maximum."""
    raw = str(valeur if valeur is not None else "").strip().replace(",", ".").replace(" ", "").replace(" ", "")
    if raw == "":
        raw = "0"
    if not re.fullmatch(r"\d+(?:\.\d{1,9})?", raw):
        raise ValueError(f"{libelle} : nombre positif attendu.")
    v = float(raw)
    c = js_round(v * 100)
    if abs(c / 100 - v) > 1e-6:
        raise ValueError(f"{libelle} : deux décimales au maximum.")
    if c > 10**14:
        raise ValueError(f"{libelle} : montant trop élevé.")
    if positif and c <= 0:
        raise ValueError(f"{libelle} : le montant doit être positif.")
    return c


def normaliser(v) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(v or "")) if unicodedata.category(c) != "Mn").lower()


def total(doc: dict) -> int:
    return sum(js_round(float(l["qty"]) * int(l["price"])) for l in doc.get("lines") or [])


def totals_by_currency(records, value) -> dict[str, int]:
    t = {c: 0 for c in CURRENCIES}
    for r in records:
        t[r["currency"]] += value(r)
    return t


def account_name(a: str | None) -> str:
    return CASH_ACCOUNTS.get(a or "", "À préciser")


def party_roles(p: dict) -> list[str]:
    return list(p.get("roles") or ["client"])


def csv_cell(value) -> str:
    text = "" if value is None else str(value)
    if re.match(r"^[=+@\-\t\r]", text):  # protège contre l'injection de formules dans Excel
        text = "'" + text
    return text


def to_csv(rows: list[list]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    for r in rows:
        w.writerow([csv_cell(v) for v in r])
    return ("﻿" + buf.getvalue()).encode("utf-8")


# ------------------------------------------------------------------ état courant
COLLECTIONS = ["clients", "projects", "quotes", "invoices", "expenses", "movements", "supplier_invoices",
               "supplier_payments", "supplier_allocations", "supplier_reversals", "personnel", "attendance",
               "payroll", "erp_dossiers"]


def charger(*noms: str) -> dict:
    """Charge les collections demandées (toutes par défaut) dans un dictionnaire, comme l'état du prototype."""
    s = {n: db.tout(n) for n in (noms or COLLECTIONS)}
    s["company"] = company()
    return s


def company() -> dict:
    c = db.parametre("company")
    if not c:
        c = {"name": "MY DESTINY SARL", "address": "", "phone": "", "registration": "", "defaultCurrency": "USD"}
    c.setdefault("defaultCurrency", "USD")
    return c


def expense_categories(c: dict | None = None, current: str = "") -> list[str]:
    c = c or company()
    out = list(dict.fromkeys(list(c.get("expenseCategories") or BASE_EXPENSE_CATEGORIES) + ([current] if current else [])))
    return out


def parse_expense_categories(value: str) -> list[str]:
    items = [s.strip() for s in str(value).splitlines() if s.strip()]
    if not items or len(items) > 30:
        raise ValueError("Indiquez entre 1 et 30 catégories, une par ligne.")
    if any(len(s) > 80 for s in items):
        raise ValueError("Chaque catégorie est limitée à 80 caractères.")
    if len({s.lower() for s in items}) != len(items):
        raise ValueError("Une catégorie est indiquée plusieurs fois.")
    return items


def name_of(records: list[dict], id_: str, defaut: str) -> str:
    for r in records:
        if r["id"] == id_:
            return r.get("name") or r.get("ref") or defaut
    return defaut


def client_name(s: dict, id_: str) -> str:
    return name_of(s.get("clients", []), id_, "Sans client")


def project_name(s: dict, id_: str) -> str:
    return name_of(s.get("projects", []), id_, "Sans chantier")


# ------------------------------------------------------------------ société
V7_COMPANY = {
    "name": "MY DESTINY BUREAU SERVICE ET DES CONSEILS SARL",
    "phone": "+243 853 774 745 ; +243 821 062 666 ; +243 892 030 653 ; +243 998 842 148",
    "registration": "CD/KNG/RCCM/13-B-01142",
    "v7": {
        "usualName": "MDY SARL / MY DESTINY SARL", "legalForm": "SARL", "country": "République Démocratique du Congo",
        "city": "Kinshasa", "year": "2013", "nationalId": "01-F4200-N77086G", "taxId": "A1402351X",
        "vatId": "0637/DGI/DUI/CDI/VWUB/TVA/2016", "director": "Patrick Kanku Tshinkenke",
        "beneficialOwner": "Mme Kasongo Mwimbi Nancy — 100 %", "headcount": "20",
        "website": "www.mydestinycongo.com", "email": "mydestinycongo@gmail.com ; direction.mydestinycongo@gmail.com",
        "address1": "Avenue Urbanisme n°4511, Quartier Bon Marché, Commune de Barumbu, Kinshasa (Réf. : Paroisse Saint Éloi)",
        "address2": "Avenue Usoke n°160, Galerie Nathalie, Kinshasa, RDC",
        "officialAddress": "", "operatingAddress": "", "footer": "",
    },
}
V7_FIELDS = [("usualName", "Sigle / nom usuel"), ("legalForm", "Forme juridique"), ("country", "Pays"),
             ("city", "Lieu d’immatriculation"), ("year", "Année de création"),
             ("nationalId", "Identification nationale"), ("taxId", "NIF / numéro impôt"), ("vatId", "Numéro TVA"),
             ("director", "Gérant / DG"), ("beneficialOwner", "Bénéficiaire effectif (interne)"),
             ("headcount", "Effectif de référence (ne crée pas de salariés)"), ("website", "Site internet"),
             ("email", "E-mails"), ("address1", "Adresse 1"), ("address2", "Adresse 2"),
             ("footer", "Mention de pied de page")]
SNAPSHOT_LABELS = {"name": "Raison sociale", "phone": "Téléphones", "rccm": "RCCM", "nationalId": "ID NAT",
                   "taxId": "NIF", "vatId": "TVA", "address": "Adresse du siège", "email": "E-mails",
                   "website": "Site internet", "footer": "Pied de page"}


def company_snapshot(c: dict | None = None) -> dict:
    """En-tête figé sur chaque document à sa création (raison sociale, adresse du siège, identifiants)."""
    c = c or company()
    v = c.get("v7") or {}
    official = v.get("officialAddress") or ""
    return {"name": c.get("name", ""), "phone": c.get("phone", ""), "rccm": c.get("registration", ""),
            "nationalId": v.get("nationalId", ""), "taxId": v.get("taxId", ""), "vatId": v.get("vatId", ""),
            "address": (v.get("address" + official, "") if official else "") if c.get("v7") else c.get("address", ""),
            "email": v.get("email", ""), "website": v.get("website", ""), "footer": v.get("footer", ""),
            "capturedAt": dt.datetime.now().isoformat(timespec="seconds")}


# ------------------------------------------------------------------ numérotation
def next_number(existing: list[str], kind: str, year: int | None = None) -> str:
    prefix = "DEV" if kind == "quotes" else "FAC"
    year = year or dt.date.today().year
    used = set(existing)
    n = 1
    while f"{prefix}-{year}-{n:04d}" in used:
        n += 1
    return f"{prefix}-{year}-{n:04d}"


def next_party_code(clients: list[dict]) -> str:
    used = {c.get("code") for c in clients}
    n = 1
    while f"T-{n:05d}" in used:
        n += 1
    return f"T-{n:05d}"


def dossier_next_ref(dossiers: list[dict], type_: str) -> str:
    used = {d["ref"].upper() for d in dossiers if d["type"] == type_}
    n = 1
    while f"{type_.upper()}-{n:04d}" in used:
        n += 1
    return f"{type_.upper()}-{n:04d}"


def next_journal_piece(movements: list[dict], date: str | None = None) -> str:
    prefix = "PJ-" + (date or today())[:7].replace("-", "") + "-"
    used = {(m.get("journal") or {}).get("piece") for m in movements}
    n = 1
    while f"{prefix}{n:04d}" in used:
        n += 1
    return f"{prefix}{n:04d}"


# ------------------------------------------------------------------ changement de monnaie
def convert_currency(kind: str, record: dict, previous: dict, rate: float | None) -> dict:
    """Si la monnaie d'un enregistrement existant change, convertit ses montants avec le taux saisi."""
    if record.get("currency") not in CURRENCIES:
        raise ValueError("Choisissez USD, CDF ou EUR.")
    if not previous.get("id") or previous.get("currency") == record["currency"]:
        return record
    if rate is None or not math.isfinite(rate) or rate <= 0 or rate > 1e12:
        raise ValueError(f"Indiquez un taux de change positif : 1 {previous['currency']} = … {record['currency']}.")
    out = dict(record)

    def conv(v):
        c = js_round(v * rate)
        if c < 0 or c > 10**14:
            raise ValueError("Le montant converti est trop élevé.")
        return c
    if kind == "projects":
        out["budget"] = conv(record["budget"])
    if kind == "expenses":
        out["amount"] = conv(record["amount"])
    if kind in ("quotes", "invoices"):
        original = total(record)
        out["lines"] = [{**l, "price": conv(l["price"])} for l in record["lines"]]
        converted = total(out)
        if converted > 10**14:
            raise ValueError("Le total converti est trop élevé.")
        if kind == "invoices":
            out["paid"] = converted if record.get("paid", 0) == original else conv(record.get("paid", 0))
            if out["paid"] > converted:
                raise ValueError("Les arrondis font dépasser les règlements du total. Utilisez un taux plus précis.")
    return out


# ------------------------------------------------------------------ trésorerie
def cash_complete(m: dict) -> bool:
    return is_date(m.get("date")) and m.get("account") in CASH_ACCOUNTS


def cash_summary(movements: list[dict], f: dict, default_currency: str) -> dict:
    currency = f.get("currency") or default_currency
    if currency not in CURRENCIES or not is_date(f.get("from")) or not is_date(f.get("to")) or f["from"] > f["to"]:
        raise ValueError("Choisissez une période valide : la date de fin doit suivre la date de début.")

    def matches(m):
        return m["currency"] == currency and (f.get("account", "all") == "all" or m["account"] == f["account"])
    known = [m for m in movements if cash_complete(m) and matches(m)]

    def sign(m):
        return m["amount"] if m["direction"] == "in" else -m["amount"]
    opening = sum(sign(m) for m in known if m["date"] < f["from"])
    rows = sorted([m for m in known if f["from"] <= m["date"] <= f["to"]],
                  key=lambda m: (m["date"], str(m.get("cree_le") or ""), m["id"]))
    incoming = sum(m["amount"] for m in rows if m["direction"] == "in")
    outgoing = sum(m["amount"] for m in rows if m["direction"] == "out")
    pending = [m for m in movements if m["currency"] == currency and not cash_complete(m)]
    return {"currency": currency, "opening": opening, "incoming": incoming, "outgoing": outgoing,
            "closing": opening + incoming - outgoing, "rows": rows, "pending": pending}


def journal_imputation(m: dict, s: dict) -> str:
    v = m.get("journal") or {}
    if m.get("project"):
        lieu = project_name(s, m["project"])
    else:
        lieu = next((c["ref"] for c in s.get("erp_dossiers", []) if c["id"] == v.get("centre")), "À préciser")
    return " → ".join(x for x in [lieu, v.get("imputation", "")] if x)


# ------------------------------------------------------------------ fournisseurs
def supplier_reversed(s: dict, payment_id: str) -> bool:
    return any(r["payment_id"] == payment_id for r in s.get("supplier_reversals", []))


def supplier_paid(s: dict, invoice_id: str) -> int:
    return sum(a["amount"] for a in s.get("supplier_allocations", [])
               if a["invoice_id"] == invoice_id and not supplier_reversed(s, a["payment_id"]))


def supplier_advance(s: dict, payment_id: str) -> int:
    p = next((p for p in s.get("supplier_payments", []) if p["id"] == payment_id), None)
    if not p or supplier_reversed(s, payment_id):
        return 0
    return p["amount"] - sum(a["amount"] for a in s.get("supplier_allocations", []) if a["payment_id"] == payment_id)


# ------------------------------------------------------------------ rapports
def erp_forecast(s: dict, as_of: str) -> dict:
    res = {c: {"balance": 0, "overdueIn": 0, "overdueOut": 0, "undatedIn": 0,
               "horizons": {d: {"incoming": 0, "outgoing": 0} for d in (7, 30, 60, 90)}} for c in CURRENCIES}
    for m in s["movements"]:
        if cash_complete(m) and m["date"] <= as_of:
            res[m["currency"]]["balance"] += m["amount"] if m["direction"] == "in" else -m["amount"]

    def add(currency, due, remaining, direction):
        if remaining <= 0:
            return
        r = res[currency]
        if not is_date(due):
            if direction == "incoming":
                r["undatedIn"] += remaining
            return
        if due < as_of:
            r["overdueIn" if direction == "incoming" else "overdueOut"] += remaining
            return
        days = (dt.date.fromisoformat(due) - dt.date.fromisoformat(as_of)).days
        for h in (7, 30, 60, 90):
            if days <= h:
                r["horizons"][h][direction] += remaining
    for i in s["invoices"]:
        if i["date"] <= as_of:
            add(i["currency"], i["due"], total(i) - i["paid"], "incoming")
    for i in s["supplier_invoices"]:
        if i["date"] <= as_of:
            add(i["currency"], i["due"], i["amount"] - supplier_paid(s, i["id"]), "outgoing")
    import gestion_v7 as V
    for op in V.records("operation"):
        d=op["data"]
        if d["status"] in ("Brouillon","Soumise","Annulée"):continue
        remaining=d["amount"]-sum(x["amount"] for x in d["payments"] if not x.get("reversed"))
        add(op["currency"],d["due"],remaining,"outgoing")
    for due in V.records("fiscal"):
        d=due["data"]
        if d["status"]!="Déposée et réglée":add(due["currency"],d["due"],d["amount"],"outgoing")
    return res


def erp_alerts(s: dict, as_of: str, avec_rh: bool = True) -> list[dict]:
    alerts = []
    limit = (dt.date.fromisoformat(as_of) + dt.timedelta(days=30)).isoformat()
    for p in s.get("projects", []):
        if is_date(p["deadline"]) and p["deadline"] < as_of and p["status"] != "Terminé":
            alerts.append({"kind": "Chantier", "label": p["name"], "date": p["deadline"], "reason": "Chantier en retard"})
    for i in s.get("invoices", []):
        if i["date"] <= as_of and is_date(i["due"]) and i["due"] < as_of and total(i) > i["paid"]:
            alerts.append({"kind": "Facture client", "label": i["number"], "date": i["due"], "reason": "Créance échue"})
    for i in s.get("supplier_invoices", []):
        if i["date"] <= as_of and i["due"] < as_of and i["amount"] > supplier_paid(s, i["id"]):
            alerts.append({"kind": "Facture fournisseur", "label": i["reference"], "date": i["due"], "reason": "Dette échue"})
    if avec_rh:
        for p in s.get("personnel", []):
            end = (p.get("details") or {}).get("contractEnd", "")
            if p["active"] and is_date(end) and end <= limit:
                alerts.append({"kind": "Personnel", "label": p["name"], "date": end,
                               "reason": "Contrat arrivé à échéance" if end < as_of else "Contrat à échéance sous 30 jours"})
    return sorted(alerts, key=lambda a: a["date"])


def client_account_report(s: dict, f: dict, as_of: str) -> dict:
    if (f.get("from") and not is_date(f["from"])) or (f.get("to") and not is_date(f["to"])) or \
            (f.get("from") and f.get("to") and f["from"] > f["to"]):
        raise ValueError("Période invalide.")
    rows = []
    for i in s["invoices"]:
        if (f.get("party") and i["client"] != f["party"]) or (f.get("project") and i["project"] != f["project"]) or \
                (f.get("currency") and i["currency"] != f["currency"]) or (f.get("from") and i["date"] < f["from"]) or \
                (f.get("to") and i["date"] > f["to"]):
            continue
        amount = total(i)
        remaining = amount - i["paid"]
        days = max(0, (dt.date.fromisoformat(as_of) - dt.date.fromisoformat(i["due"])).days) if is_date(i["due"]) else None
        bucket = ("Échéance manquante" if days is None else "Non échue" if days == 0 else "1–30 jours" if days <= 30
                  else "31–60 jours" if days <= 60 else "61–90 jours" if days <= 90 else "> 90 jours")
        rows.append({"id": i["id"], "number": i["number"], "party": i["client"], "project": i["project"],
                     "date": i["date"], "due": i["due"], "currency": i["currency"], "amount": amount,
                     "paid": i["paid"], "remaining": remaining, "days": days, "bucket": bucket})
    rows.sort(key=lambda r: r["due"] or "9999")
    totals = {c: {"amount": 0, "paid": 0, "remaining": 0, "overdue": 0, "undated": 0} for c in CURRENCIES}
    for r in rows:
        t = totals[r["currency"]]
        t["amount"] += r["amount"]
        t["paid"] += r["paid"]
        t["remaining"] += r["remaining"]
        if r["days"] and r["days"] > 0:
            t["overdue"] += r["remaining"]
        if r["days"] is None:
            t["undated"] += r["remaining"]
    return {"rows": rows, "totals": totals}


# ------------------------------------------------------------------ RH et paie
def hr_place_label(a: dict | None, s: dict) -> str:
    if not a or not a.get("location"):
        return "À préciser"
    return "Bureau" if a["location"] == "Bureau" else project_name(s, a.get("project", ""))


def hr_assignment_at(person: dict, date: str) -> dict | None:
    rows = sorted([a for a in person.get("assignments") or [] if a["date"] <= date], key=lambda a: a["date"], reverse=True)
    return rows[0] if rows else None


def payroll_rate_amount(base: int, rate: float) -> int | None:
    """Assiette × taux (%), taux à quatre décimales au plus, arrondi au centime en arithmétique entière."""
    if not isinstance(base, int) or base < 0 or rate is None or not math.isfinite(rate) or rate < 0 or rate > 100:
        return None
    units = js_round(rate * 10000)
    if abs(units / 10000 - rate) > 1e-9:
        return None
    return (base * units + 500000) // 1000000


def payroll_totals(r: dict) -> dict:
    e = r.get("elements") or {}
    g = lambda k: int(e.get(k) or 0)  # noqa: E731
    base = js_round(float(r["rate"]) * float(r["quantity"]))
    gross = base + g("bonus") + g("allowances") + g("overtime") + g("holidays") + g("family")
    deductions = g("absence") + g("advance") + g("social") + g("tax") + g("other") + g("loan")
    employer = g("cnssEmployer") + g("onem") + g("inpp") + g("employerOther")
    return {"base": base, "gross": gross, "deductions": deductions, "net": gross - deductions,
            "employer": employer, "cost": gross + employer}


def seniority_months(month: str, start: str) -> int:
    return (int(month[:4]) - int(start[:4])) * 12 + int(month[5:7]) - int(start[5:7])


# ------------------------------------------------------------------ dossiers préparatoires (V7)
# (clé, libellé, type, obligatoire, options) ; type : text, date, money, quantity, select, link
ERP_DOSSIERS = {
    "conges": {"label": "Demandes de congé", "group": "RH", "fields": [
        ("employee", "Employé", "link", True, "personnel"), ("start", "Du", "date", True), ("end", "Au", "date", True),
        ("name", "Type / motif", "text", True)]},
    "missions": {"label": "Missions du personnel", "group": "RH", "analytical": True, "fields": [
        ("employee", "Employé", "link", True, "personnel"), ("name", "Objet", "text", True),
        ("location", "Destination", "text", True), ("start", "Du", "date", True), ("end", "Au", "date", True),
        ("amount", "Budget proposé", "money", True)]},
    "avancesrh": {"label": "Demandes d’avance / prêt salarié", "group": "RH", "analytical": True, "fields": [
        ("employee", "Employé", "link", True, "personnel"), ("amount", "Montant demandé", "money", True),
        ("name", "Motif", "text", True), ("terms", "Modalités de remboursement", "text", True)]},
    "evaluations": {"label": "Évaluations du personnel", "group": "RH", "fields": [
        ("employee", "Employé", "link", True, "personnel"), ("name", "Période / objet", "text", True),
        ("owner", "Évaluateur", "text", True), ("result", "Appréciation", "text", True),
        ("action", "Actions prévues", "text", False)]},
    "centres": {"label": "Centres de coûts", "group": "Administration", "fields": [
        ("name", "Désignation", "text", True), ("service", "Service", "text", True)]},
    "crm": {"label": "Prospects et opportunités", "group": "Commercial", "fields": [
        ("name", "Prospect / opportunité", "text", True), ("contact", "Contact", "text", True),
        ("source", "Origine", "text", False), ("owner", "Responsable commercial", "text", False),
        ("deadline", "Prochaine échéance", "date", False), ("amount", "Montant estimé", "money", False),
        ("stage", "Étape", "select", True, ["Prospect", "Opportunité", "Offre", "Négociation", "Gagné", "Perdu"])]},
    "appels": {"label": "Appels d’offres", "group": "Commercial", "fields": [
        ("name", "Objet", "text", True), ("deadline", "Date limite", "date", True), ("lots", "Lots", "text", False),
        ("amount", "Montant estimé", "money", False), ("owner", "Responsable", "text", False)]},
    "contrats": {"label": "Contrats clients", "group": "Commercial", "analytical": True, "fields": [
        ("name", "Objet du contrat", "text", True), ("amount", "Montant initial", "money", True),
        ("start", "Début", "date", True), ("end", "Fin prévue", "date", False),
        ("terms", "Conditions de paiement", "text", False)]},
    "dqe": {"label": "Lignes DQE / budget", "group": "Projets", "analytical": True, "fields": [
        ("name", "Désignation des travaux", "text", True), ("unit", "Unité", "text", True),
        ("quantity", "Quantité prévue", "quantity", True), ("cost", "Prix de revient unitaire", "money", True),
        ("price", "Prix de vente unitaire", "money", True)]},
    "engagements": {"label": "Engagements à soumettre", "group": "Achats & Stocks", "analytical": True, "fields": [
        ("name", "Objet", "text", True), ("amount", "Montant à engager", "money", True),
        ("deadline", "Échéance", "date", False), ("origin", "Contrat / commande d’origine", "text", True)]},
    "demandes": {"label": "Demandes d’achat", "group": "Achats & Stocks", "analytical": True, "fields": [
        ("name", "Article / besoin", "text", True), ("quantity", "Quantité", "quantity", True),
        ("unit", "Unité", "text", True), ("reason", "Justification", "text", True),
        ("deadline", "Date souhaitée", "date", False)]},
    "commandes": {"label": "Commandes fournisseurs", "group": "Achats & Stocks", "analytical": True, "fields": [
        ("request", "Demande d’achat", "link", True, "demandes"), ("name", "Article / prestation", "text", True),
        ("quantity", "Quantité commandée", "quantity", True), ("price", "Prix unitaire", "money", True),
        ("deadline", "Livraison prévue", "date", True), ("terms", "Conditions", "text", False)]},
    "magasins": {"label": "Magasins", "group": "Achats & Stocks", "fields": [
        ("name", "Nom du magasin", "text", True), ("location", "Localisation", "text", True),
        ("owner", "Responsable", "text", True)]},
    "articles": {"label": "Articles", "group": "Achats & Stocks", "fields": [
        ("name", "Désignation", "text", True),
        ("category", "Famille", "select", True, ["Matériaux", "Consommables", "Outillage", "Pièces de rechange", "EPI",
                                                 "Carburant", "Autres"]),
        ("unit", "Unité", "text", True), ("minimum", "Seuil minimum", "quantity", False),
        ("maximum", "Stock maximum", "quantity", False)]},
    "receptions": {"label": "Réceptions à contrôler", "group": "Achats & Stocks", "analytical": True, "fields": [
        ("order", "Commande", "link", True, "commandes"), ("article", "Article", "link", True, "articles"),
        ("warehouse", "Magasin destination", "link", True, "magasins"), ("quantity", "Quantité reçue", "quantity", True),
        ("rejected", "Quantité rejetée", "quantity", False), ("delivery", "Référence BL", "text", True),
        ("owner", "Réceptionnaire", "text", True)]},
    "transferts": {"label": "Transferts à préparer", "group": "Achats & Stocks", "analytical": True, "fields": [
        ("article", "Article", "link", True, "articles"), ("source", "Magasin source", "link", True, "magasins"),
        ("destination", "Magasin destination", "link", True, "magasins"),
        ("quantity", "Quantité à transférer", "quantity", True), ("owner", "Responsable", "text", True)]},
    "consommations": {"label": "Consommations à contrôler", "group": "Achats & Stocks", "analytical": True, "fields": [
        ("article", "Article", "link", True, "articles"), ("warehouse", "Magasin", "link", True, "magasins"),
        ("quantity", "Quantité déclarée consommée", "quantity", True), ("work", "Travaux concernés", "text", True),
        ("owner", "Responsable", "text", True)]},
    "inventaires": {"label": "Comptages d’inventaire", "group": "Achats & Stocks", "analytical": True, "fields": [
        ("warehouse", "Magasin", "link", True, "magasins"), ("article", "Article", "link", True, "articles"),
        ("theoretical", "Quantité théorique déclarée", "quantity", True),
        ("physical", "Quantité comptée", "quantity", True), ("owner", "Responsable du comptage", "text", True),
        ("reason", "Explication de l’écart", "text", False)]},
    "equipements": {"label": "Matériel, véhicules et immobilisations", "group": "Matériel & Charroi", "analytical": True,
                    "fields": [
                        ("name", "Désignation", "text", True),
                        ("category", "Catégorie", "select", True, ["Équipement", "Véhicule", "Engin", "Outillage", "Mobilier"]),
                        ("serial", "Série / châssis", "text", False), ("registration", "Immatriculation", "text", False),
                        ("amount", "Coût d’acquisition", "money", True), ("serviceDate", "Mise en service", "date", False),
                        ("owner", "Détenteur", "text", True), ("location", "Localisation", "text", True)]},
    "maintenance": {"label": "Interventions de maintenance", "group": "Matériel & Charroi", "analytical": True, "fields": [
        ("asset", "Équipement", "link", True, "equipements"), ("name", "Travaux / diagnostic", "text", True),
        ("amount", "Coût déclaré", "money", True), ("deadline", "Prochaine échéance", "date", False),
        ("owner", "Intervenant", "text", True)]},
    "carburant": {"label": "Relevés de carburant", "group": "Matériel & Charroi", "analytical": True, "fields": [
        ("asset", "Véhicule / équipement", "link", True, "equipements"), ("quantity", "Litres", "quantity", True),
        ("meter", "Compteur (km ou heures)", "quantity", True),
        ("unit", "Unité du compteur", "select", True, ["km", "heures"]), ("amount", "Montant", "money", True),
        ("owner", "Conducteur", "text", True)]},
    "soustraitance": {"label": "Contrats de sous-traitance", "group": "Commercial", "analytical": True, "fields": [
        ("name", "Travaux confiés", "text", True), ("amount", "Montant", "money", True), ("start", "Début", "date", True),
        ("end", "Fin prévue", "date", False), ("retention", "Retenue prévue (montant)", "money", False)]},
    "situations": {"label": "Situations de travaux", "group": "Projets", "analytical": True, "fields": [
        ("contract", "Contrat client", "link", True, "contrats"), ("name", "Travaux exécutés", "text", True),
        ("start", "Période du", "date", True), ("end", "Au", "date", True), ("amount", "Montant demandé", "money", True),
        ("retention", "Retenue proposée", "money", False)]},
    "garanties": {"label": "Garanties et assurances", "group": "Administration", "fields": [
        ("name", "Objet / type", "text", True), ("issuer", "Banque / assureur", "text", True),
        ("amount", "Montant couvert", "money", True), ("end", "Échéance", "date", True),
        ("beneficiary", "Bénéficiaire", "text", True)]},
    "avenants": {"label": "Avenants et réclamations", "group": "Projets", "analytical": True, "fields": [
        ("contract", "Contrat client", "link", True, "contrats"), ("name", "Motif / objet", "text", True),
        ("amount", "Montant demandé", "money", True), ("delay", "Impact délai (jours)", "quantity", False),
        ("origin", "Ordre de service / pièce", "text", True)]},
    "qualite": {"label": "HSE, qualité et réceptions", "group": "Projets", "analytical": True, "fields": [
        ("category", "Type", "select", True, ["Incident HSE", "Inspection", "Non-conformité", "Réception provisoire",
                                              "Réception définitive", "Réserve"]),
        ("name", "Constat", "text", True), ("action", "Action corrective", "text", False),
        ("owner", "Responsable", "text", True), ("deadline", "Échéance", "date", False)]},
    "documents": {"label": "Registre documentaire", "group": "Administration", "fields": [
        ("name", "Titre", "text", True), ("category", "Type de document", "text", True),
        ("version", "Version", "text", True), ("owner", "Responsable", "text", True),
        ("end", "Expiration éventuelle", "date", False), ("location", "Emplacement / référence du fichier", "text", True)]},
    "taches": {"label": "Tâches et suivi", "group": "Administration", "fields": [
        ("name", "Tâche", "text", True), ("owner", "Responsable", "text", True), ("deadline", "Échéance", "date", True),
        ("priority", "Priorité", "select", True, ["Normale", "Haute", "Urgente"])]},
    "comptes": {"label": "Plan comptable à configurer", "group": "Comptabilité", "fields": [
        ("number", "Numéro de compte", "text", True), ("name", "Libellé", "text", True)]},
    "ecritures": {"label": "Écritures préparatoires simples", "group": "Comptabilité", "analytical": True, "fields": [
        ("journal", "Journal", "select", True, ["Achats", "Ventes", "Banque", "Caisse", "Paie", "Stocks / immobilisations",
                                                "Opérations diverses"]),
        ("name", "Libellé", "text", True), ("debit", "Compte débité", "link", True, "comptes"),
        ("credit", "Compte crédité", "link", True, "comptes"),
        ("amount", "Montant au débit et au crédit", "money", True),
        ("origin", "Référence de la pièce métier", "text", True)]},
    "fiscalite": {"label": "Échéances fiscales préparatoires", "group": "Comptabilité", "analytical": True, "fields": [
        ("name", "Taxe / déclaration", "text", True), ("period", "Période", "text", True),
        ("base", "Base déclarée", "money", True), ("amount", "Montant déclaré", "money", True),
        ("deadline", "Échéance", "date", True), ("owner", "Responsable", "text", True)]},
}
# Groupe de dossiers → module de droits (auth.DROITS)
DOSSIER_MODULE = {"RH": "personnel", "Administration": "documents", "Commercial": "commercial", "Projets": "projets",
                  "Achats & Stocks": "achats", "Matériel & Charroi": "charroi", "Comptabilité": "comptabilite"}
# Espaces de travail V7 : types de dossiers regroupés
V7_SPACES = {
    "commercial": ("Espace commercial", ["crm", "appels", "contrats", "soustraitance"]),
    "achats": ("Achats", ["demandes", "engagements", "commandes", "receptions"]),
    "stocks": ("Stocks", ["magasins", "articles", "transferts", "consommations", "inventaires"]),
    "charroi": ("Matériel & Charroi", ["equipements", "maintenance", "carburant"]),
    "projets": ("Dossiers de chantier", ["dqe", "situations", "avenants", "qualite"]),
    "rh": ("Dossiers RH", ["conges", "missions", "avancesrh", "evaluations"]),
    "comptabilite": ("Comptabilité & Fiscalité", ["comptes", "ecritures", "fiscalite"]),
    "administration": ("Documents & administration", ["documents", "garanties", "taches", "centres"]),
}


def field_spec(f: tuple) -> tuple:
    key, label, kind, required = f[0], f[1], f[2], f[3]
    options = f[4] if len(f) > 4 else None
    return key, label, kind, required, options


def dossier_links(s: dict, target: str) -> list[dict]:
    if target == "personnel":
        return s.get("personnel", [])
    return [d for d in s.get("erp_dossiers", []) if d["type"] == target]


def link_label(d: dict) -> str:
    v = d.get("values") or {}
    nom = v.get("name") or d.get("name") or ""
    ref = d.get("ref") or d.get("code") or ""
    return f"{ref} — {nom}" if ref and nom and ref != nom else (ref or nom)


def dossier_value(s: dict, r: dict, f: tuple) -> str:
    key, label, kind, _, options = field_spec(f)
    v = (r.get("values") or {}).get(key)
    if v is None or v == "":
        return "Non renseigné"
    if kind == "money":
        return money(v, r["currency"])
    if kind == "link":
        d = next((d for d in dossier_links(s, options) if d["id"] == v), None)
        return link_label(d) if d else "Introuvable"
    if kind == "quantity":
        return f"{v:g}".replace(".", ",")
    return str(v)


def validate_dossier(r: dict, s: dict) -> None:
    spec = ERP_DOSSIERS.get(r["type"])
    if not spec:
        raise ValueError("Type de dossier inconnu.")
    if not r.get("ref", "").strip() or len(r["ref"]) > 100:
        raise ValueError("Indiquez une référence unique (100 caractères au plus).")
    if any(d["id"] != r["id"] and d["type"] == r["type"] and d["ref"].lower() == r["ref"].lower()
           for d in s.get("erp_dossiers", [])):
        raise ValueError("Cette référence existe déjà pour ce type de dossier.")
    if not is_date(r["date"]):
        raise ValueError("Indiquez une date valide.")
    if spec.get("analytical") and not r.get("project") and not r.get("centre"):
        raise ValueError("Choisissez un chantier ou créez un centre de coût pour cette opération.")
    for f in spec["fields"]:
        key, label, kind, required, options = field_spec(f)
        v = r["values"].get(key)
        if v is None or v == "":
            if required:
                raise ValueError(f"Renseignez : {label}.")
            continue
        if kind == "money" and (not isinstance(v, int) or v < 0 or v > 10**12):
            raise ValueError(f"{label} : montant invalide.")
        if kind == "quantity" and (not isinstance(v, (int, float)) or v < 0 or v > 1e9):
            raise ValueError(f"{label} : quantité invalide.")
        if kind == "date" and not is_date(v):
            raise ValueError(f"{label} : date invalide.")
        if kind == "select" and v not in options:
            raise ValueError(f"{label} : choix invalide.")
        if kind == "link" and not any(d["id"] == v for d in dossier_links(s, options)):
            raise ValueError(f"{label} : élément introuvable.")
    v = r["values"]
    if v.get("start") and v.get("end") and v["start"] > v["end"]:
        raise ValueError("La date de fin doit suivre la date de début.")
    if r["type"] == "transferts" and v.get("source") == v.get("destination"):
        raise ValueError("Le magasin source et le magasin destination doivent être différents.")
    if r["type"] == "ecritures" and v.get("debit") == v.get("credit"):
        raise ValueError("Le compte débité et le compte crédité doivent être différents.")
    if r["type"] == "articles" and v.get("maximum") is not None and v.get("minimum") is not None \
            and v["maximum"] < v["minimum"]:
        raise ValueError("Le stock maximum ne peut être inférieur au seuil minimum.")
    if r["type"] == "receptions" and (v.get("rejected") or 0) > (v.get("quantity") or 0):
        raise ValueError("La quantité rejetée ne peut dépasser la quantité reçue.")


def dossier_rows(s: dict, r: dict) -> list[tuple[str, str]]:
    spec = ERP_DOSSIERS[r["type"]]
    centre = next((d["ref"] for d in s.get("erp_dossiers", []) if d["id"] == r.get("centre")), "")
    return ([("Référence", r["ref"]), ("Date", r["date"]), ("Chantier", project_name(s, r.get("project", ""))),
             ("Centre de coût", centre), ("Tiers", client_name(s, r.get("party", "")) if r.get("party") else ""),
             ("Monnaie", r["currency"])]
            + [(field_spec(f)[1], dossier_value(s, r, f)) for f in spec["fields"]]
            + [("Observations", r.get("notes", "")), ("État", "Brouillon non validé")])


# ------------------------------------------------------------------ recherche globale
def erp_search(s: dict, query: str, collections: set[str]) -> list[dict]:
    words = [w for w in normaliser(query).split() if w]
    if not words:
        return []
    out = []

    def add(kind, r, label, context, extra=""):
        text = normaliser(" ".join([str(label), str(context), str(extra)]))
        if all(w in text for w in words):
            out.append({"kind": kind, "id": r["id"], "label": label, "context": context})
    if "projects" in collections:
        for r in s["projects"]:
            add("Chantier", r, r["name"], client_name(s, r["client"]), f"{r['location']} {r['status']}")
    if "clients" in collections:
        for r in s["clients"]:
            add("Tiers", r, r["name"], r.get("code", ""), f"{r['phone']} {r['email']}")
    for kind, nom in (("quotes", "Devis"), ("invoices", "Facture client")):
        if kind in collections:
            for r in s[kind]:
                add(nom, r, r["number"], f"{client_name(s, r['client'])} · {project_name(s, r['project'])}", r["notes"])
    if "expenses" in collections:
        for r in s["expenses"]:
            add("Dépense", r, r["label"], project_name(s, r["project"]), r["category"])
    if "personnel" in collections:
        for r in s["personnel"]:
            add("Employé", r, r["name"], r["code"], f"{r['job']} {r['service']}")
    if "supplier_invoices" in collections:
        for r in s["supplier_invoices"]:
            add("Facture fournisseur", r, r["reference"], f"{client_name(s, r['party_id'])} · {project_name(s, r['project'])}")
    if "movements" in collections:
        for r in s["movements"]:
            add("Mouvement de trésorerie", r, r["label"], project_name(s, r["project"]))
    if "erp_dossiers" in collections:
        for r in s["erp_dossiers"]:
            spec = ERP_DOSSIERS.get(r["type"], {})
            add("Dossier", r, r["ref"], spec.get("label", ""), (r.get("values") or {}).get("name", ""))
    return out
