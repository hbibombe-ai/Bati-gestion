"""Sauvegarde, restauration et reprise des données du prototype BatiGestion (fichiers JSON du navigateur).

- export_json / import_json : sauvegarde complète de cette application (hors comptes et mots de passe).
- import_prototype : reprend une sauvegarde « bati-sauvegarde-AAAA-MM-JJ.json » du prototype (versions 1 à 3).
- import_brouillons : reprend « bati-brouillons-AAAA-MM-JJ.json » (lots historiques et pièces préparées).
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import io
import json
import re

import openpyxl

import db
import regles as R

METIER = ["clients", "projects", "quotes", "invoices", "expenses", "movements", "supplier_invoices", "supplier_payments",
          "supplier_allocations", "supplier_reversals", "personnel", "attendance", "payroll", "erp_dossiers",
          "company_history", "history_batches", "pieces"]
FORMAT = "bati-gestion-python-1"


def _snake(k: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", k).lower()


def _serial(v):
    if isinstance(v, (bytes, bytearray, memoryview)):
        return {"__b64__": base64.b64encode(bytes(v)).decode()}
    if isinstance(v, (dt.datetime, dt.date)):
        return {"__dt__": v.isoformat()}
    return v


def _deserial(v):
    if isinstance(v, dict) and "__b64__" in v:
        return base64.b64decode(v["__b64__"])
    if isinstance(v, dict) and "__dt__" in v:
        return dt.datetime.fromisoformat(v["__dt__"])
    return v


# ------------------------------------------------------------------ sauvegarde de cette application
def export_json(avec_pieces: bool = True) -> bytes:
    data = {"format": FORMAT, "exported_at": dt.datetime.now().isoformat(timespec="seconds"),
            "company": R.company(), "tables": {}}
    for t in METIER:
        sans = () if (avec_pieces or t != "pieces") else ("content",)
        data["tables"][t] = [{k: _serial(v) for k, v in r.items()} for r in db.tout(t, sans=sans)]
    return json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8")


def export_excel() -> bytes:
    """Une feuille par table, pour l'analyse (sans le contenu des fichiers)."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for t in METIER:
        rows = db.tout(t, sans=("content",) if t == "pieces" else ())
        ws = wb.create_sheet(db.NOMS_OBJETS.get(t, t)[:31])
        cols = [c.name for c in db.TABLES[t].c if c.name != "content"]
        ws.append(cols)
        for r in rows:
            ws.append([json.dumps(r[c], ensure_ascii=False) if isinstance(r[c], (dict, list)) else r[c] for c in cols])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _remplacer(tables: dict, company: dict | None, resume: str) -> dict:
    compte = {}
    with db.transaction(resume) as t:
        for nom in reversed(METIER):
            t.cx.execute(db.TABLES[nom].delete())
        if company:
            t.parametre("company", company)
        for nom in METIER:
            rows = tables.get(nom) or []
            if rows:
                t.cx.execute(db.TABLES[nom].insert(), rows)
            compte[nom] = len(rows)
        t.evenement("Restauration", f"{resume} : " + ", ".join(f"{db.NOMS_OBJETS.get(k, k)} {v}"
                                                                for k, v in compte.items() if v))
    return compte


def import_json(contenu: bytes) -> dict:
    data = json.loads(contenu.decode("utf-8"))
    if data.get("format") != FORMAT:
        raise ValueError("Ce fichier n’est pas une sauvegarde Bâti Gestion (version Python).")
    tables = {}
    for nom in METIER:
        cols = {c.name for c in db.TABLES[nom].c}
        tables[nom] = [{k: _deserial(v) for k, v in r.items() if k in cols} for r in data["tables"].get(nom, [])]
    if any("content" not in p for p in tables["pieces"]):
        raise ValueError("Cette sauvegarde ne contient pas les fichiers des justificatifs ; restauration impossible.")
    return _remplacer(tables, data.get("company"), "Restauration d'une sauvegarde")


# ------------------------------------------------------------------ prototype (navigateur)
def _upgrade(s: dict) -> dict:
    """Mise à niveau des anciennes sauvegardes du prototype, comme upgradeState()."""
    if s.get("version") == 1:
        s["version"] = 2
        s["company"]["defaultCurrency"] = "USD"
        for kind in ("projects", "quotes", "invoices", "expenses"):
            for r in s.get(kind, []):
                r["currency"] = "USD"
    if s.get("version") == 2:
        s["version"] = 3
        s["movements"] = []
        for e in s.get("expenses", []):
            s["movements"].append({"id": "legacy-exp-" + e["id"], "kind": "expense", "date": e["date"],
                                   "account": "unassigned", "label": e["label"], "direction": "out",
                                   "amount": e["amount"], "currency": e["currency"], "project": e["project"],
                                   "invoiceId": "", "expenseId": e["id"]})
        for i in s.get("invoices", []):
            if i.get("paid", 0) > 0:
                s["movements"].append({"id": "legacy-pay-" + i["id"], "kind": "invoice", "date": "",
                                       "account": "unassigned", "label": "Ancien règlement " + i["number"],
                                       "direction": "in", "amount": i["paid"], "invoiceAmount": i["paid"],
                                       "currency": i["currency"], "project": i["project"], "invoiceId": i["id"],
                                       "expenseId": ""})
    if s.get("version") != 3:
        raise ValueError("Sauvegarde BatiGestion invalide ou version inconnue.")
    return s


def _ligne(nom: str, src: dict, defauts: dict | None = None) -> dict:
    cols = {c.name for c in db.TABLES[nom].c}
    out = {}
    for k, v in src.items():
        sk = {"journalV7": "journal", "companySnapshot": "company_snapshot",
              "employeeSnapshot": "employee_snapshot"}.get(k, _snake(k))
        if sk in cols:
            out[sk] = v
    for k, v in (defauts or {}).items():
        out.setdefault(k, v)
    return out


def _verifier(s: dict) -> None:
    """Contrôles de cohérence repris de validState() du prototype (trésorerie, factures, fournisseurs)."""
    def ent(v):
        return isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 10**14
    for kind in ("projects", "quotes", "invoices", "expenses", "movements"):
        for r in s.get(kind, []):
            if r.get("currency") not in R.CURRENCIES:
                raise ValueError(f"Monnaie invalide dans {kind}.")
    for kind in ("clients", "projects", "quotes", "invoices", "expenses", "movements", "personnel", "payroll",
                 "erpDossiers", "supplierInvoices", "supplierPayments", "supplierAllocations", "supplierReversals"):
        ids = [r.get("id") for r in s.get(kind, [])]
        if any(not i for i in ids) or len(set(ids)) != len(ids):
            raise ValueError(f"Identifiants manquants ou en double dans {kind}.")
    for kind in ("quotes", "invoices"):
        numeros = [r["number"] for r in s.get(kind, [])]
        if len(set(numeros)) != len(numeros):
            raise ValueError("Numéros de devis ou de factures en double.")
    for i in s.get("invoices", []):
        if not ent(i.get("paid", 0)) or i.get("paid", 0) > R.total(i):
            raise ValueError(f"Facture {i.get('number')} : les règlements dépassent le total.")
    for e in s.get("expenses", []):
        if not ent(e.get("amount")):
            raise ValueError(f"Dépense « {e.get('label')} » : montant invalide.")
    # trésorerie : une sortie par dépense, identique à la dépense ; règlements = montant payé des factures
    depenses = {e["id"]: e for e in s.get("expenses", [])}
    factures = {i["id"]: i for i in s.get("invoices", [])}
    liens, sommes = {}, {}
    for m in s.get("movements", []):
        if m.get("direction") not in ("in", "out") or m.get("kind") not in ("manual", "opening", "invoice", "expense") \
                or not ent(m.get("amount")):
            raise ValueError("Mouvement de trésorerie invalide.")
        if m["kind"] == "invoice":
            if m.get("invoiceId") not in factures or m["direction"] != "in" or not ent(m.get("invoiceAmount")):
                raise ValueError("Règlement relié à une facture absente.")
            sommes[m["invoiceId"]] = sommes.get(m["invoiceId"], 0) + m["invoiceAmount"]
        if m["kind"] == "expense":
            e = depenses.get(m.get("expenseId"))
            if not e or m["direction"] != "out" or m["amount"] != e["amount"] or m["currency"] != e["currency"] \
                    or m.get("date", "") != e["date"] or m.get("project", "") != e["project"] or e["id"] in liens:
                raise ValueError(f"La sortie de caisse de la dépense « {(e or {}).get('label', '?')} » ne correspond pas.")
            liens[e["id"]] = m["id"]
    if any(eid not in liens for eid in depenses):
        raise ValueError("Une dépense n’a pas de sortie de caisse correspondante.")
    if any(sommes.get(iid, 0) != i.get("paid", 0) for iid, i in factures.items()):
        raise ValueError("Le montant payé d’une facture ne correspond pas à ses règlements.")
    # fournisseurs
    paiements = {p["id"]: p for p in s.get("supplierPayments", [])}
    fact_f = {i["id"]: i for i in s.get("supplierInvoices", [])}
    contre = {r["paymentId"] for r in s.get("supplierReversals", [])}
    if any(r.get("paymentId") not in paiements for r in s.get("supplierReversals", [])):
        raise ValueError("Contre-passation reliée à un paiement absent.")
    affecte, regle = {}, {}
    for a in s.get("supplierAllocations", []):
        p, i = paiements.get(a.get("paymentId")), fact_f.get(a.get("invoiceId"))
        if not p or not i or p["partyId"] != i["partyId"] or p["currency"] != i["currency"] or not ent(a.get("amount")):
            raise ValueError("Affectation d’avance fournisseur incohérente.")
        affecte[p["id"]] = affecte.get(p["id"], 0) + a["amount"]
        if p["id"] not in contre:
            regle[i["id"]] = regle.get(i["id"], 0) + a["amount"]
    if any(v > paiements[k]["amount"] for k, v in affecte.items()) or \
            any(v > fact_f[k]["amount"] for k, v in regle.items()):
        raise ValueError("Les affectations fournisseurs dépassent un paiement ou une facture.")
    for p in s.get("supplierPayments", []):
        if sum(1 for m in s.get("movements", []) if m.get("supplierPaymentId") == p["id"]) != 1:
            raise ValueError("Chaque paiement fournisseur doit avoir une seule sortie de caisse.")


def import_prototype(contenu: bytes) -> dict:
    if len(contenu) > 20_000_000:
        raise ValueError("Fichier trop volumineux (20 Mo maximum).")
    s = _upgrade(json.loads(contenu.decode("utf-8")))
    _verifier(s)
    company = dict(s["company"])
    company.setdefault("defaultCurrency", "USD")
    tables: dict[str, list] = {}
    codes = {c.get("code") for c in s["clients"] if c.get("code")}
    clients = []
    n = 1
    for c in s["clients"]:
        code = c.get("code")
        if not code:
            while f"T-{n:05d}" in codes:
                n += 1
            code = f"T-{n:05d}"
            codes.add(code)
        clients.append(_ligne("clients", {**c, "code": code}, {"registration": "", "roles": ["client"], "archived": False}))
    tables["clients"] = clients
    tables["projects"] = [_ligne("projects", p) for p in s["projects"]]
    tables["quotes"] = [_ligne("quotes", q) for q in s["quotes"]]
    tables["invoices"] = [_ligne("invoices", i, {"quote_id": ""}) for i in s["invoices"]]
    tables["expenses"] = [_ligne("expenses", e, {"supplier_id": "", "responsible": ""}) for e in s["expenses"]]
    tables["movements"] = [_ligne("movements", m, {"invoice_id": "", "expense_id": "", "supplier_payment_id": "",
                                                   "supplier_reversal_id": "", "project": ""}) for m in s["movements"]]
    for m in tables["movements"]:
        m["cree_le"] = db.maintenant()
        m["date"] = m.get("date") or ""
    for src, dst in (("supplierInvoices", "supplier_invoices"), ("supplierPayments", "supplier_payments"),
                     ("supplierAllocations", "supplier_allocations"), ("supplierReversals", "supplier_reversals")):
        tables[dst] = [_ligne(dst, r) for r in s.get(src, [])]
    tables["personnel"] = [_ligne("personnel", p, {"assignments": None}) for p in s.get("personnel", [])]
    tables["attendance"] = [_ligne("attendance", a) for a in s.get("attendance", [])]
    elems = [k for k, _ in R.PAY_FIELDS + R.PAY_V7_EXTRA]
    tables["payroll"] = [_ligne("payroll", {**p, "elements": {k: p.get(k, 0) or 0 for k in elems}})
                         for p in s.get("payroll", [])]
    tables["erp_dossiers"] = [_ligne("erp_dossiers", d) for d in s.get("erpDossiers", [])]
    tables["company_history"] = [{"before": h["before"], "after": h["after"], "reason": h["reason"],
                                  "user_nom": "Prototype (navigateur)"} for h in s.get("companyHistory", [])]
    # les lots historiques et les pièces (autre fichier) sont conservés s'ils existent déjà
    tables["history_batches"] = db.tout("history_batches")
    tables["pieces"] = db.tout("pieces")
    return _remplacer(tables, company, "Reprise d'une sauvegarde du prototype BatiGestion")


def import_brouillons(contenu: bytes, user_id: int | None) -> dict:
    """Lots historiques et pièces préparées exportés par le prototype (format bati-preparation-1)."""
    import reprise
    data = json.loads(contenu.decode("utf-8"))
    if data.get("format") != "bati-preparation-1" or not isinstance(data.get("batches"), list) \
            or not isinstance(data.get("pieces"), list):
        raise ValueError("Ce fichier n’est pas une sauvegarde de brouillons BatiGestion.")
    existants = {b["project_ref"] for b in db.tout("history_batches")}
    hashes = {p["hash"] for p in db.tout("pieces", sans=("content",))}
    n_lots = n_pieces = 0
    with db.transaction("Reprise des brouillons du prototype") as t:
        for b in data["batches"]:
            tables: dict[str, list] = {}
            for row in b.get("rows", []):
                tables.setdefault(row["sheet"], []).append(row["values"])
            res = reprise.valider(tables, existants)
            if not res["valid"]:
                raise ValueError(f"Lot « {b.get('source', '')} » invalide : {res['errors'][0]['message']}")
            t.inserer("history_batches", {"id": b["id"], "project_ref": res["project"]["reference"],
                                          "project": res["project"], "rows": res["rows"], "source": b.get("source", ""),
                                          "created_at": dt.datetime.fromisoformat(b["createdAt"].replace("Z", "")),
                                          "created_by": user_id})
            existants.add(res["project"]["reference"])
            n_lots += 1
        for p in data["pieces"]:
            contenu_p = base64.b64decode(p["bytes"])
            h = hashlib.sha256(contenu_p).hexdigest()
            if h != p.get("hash") or h in hashes:
                continue
            if not contenu_p or len(contenu_p) > R.PIECE_MAX:
                continue
            t.inserer("pieces", {"id": p["id"], "expense_id": p.get("expenseId", ""), "batch_id": p.get("batchId", ""),
                                 "name": p["name"], "mime": p["mime"], "content": contenu_p, "size": len(contenu_p),
                                 "hash": h, "type": p.get("type", "Document de chantier"),
                                 "beneficiary": p.get("beneficiary", ""), "document_date": p["documentDate"],
                                 "amount": int(p.get("amount") or 0), "currency": p.get("currency", ""),
                                 "status": "Préparée", "reason": "",
                                 "uploaded_at": dt.datetime.fromisoformat(p["uploadedAt"].replace("Z", "")),
                                 "uploaded_by": user_id})
            hashes.add(h)
            n_pieces += 1
    return {"lots": n_lots, "pieces": n_pieces}
