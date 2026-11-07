"""Règles de l'extension ERP : pistes commerciales (CRM), activités planifiées (rappels), planning des chantiers
et préférences du tableau de bord. Toutes les écritures passent par db.transaction (journal d'audit compris)."""
from __future__ import annotations

import datetime as dt

import db
import regles as R
from schema_erp import ETAPES_CRM, PERDU, SOURCES_CRM, TYPES_ACTIVITE  # noqa: F401  (réexportés)

# fiche ouverte depuis une activité : table -> (clé de fiche, page)
FICHES = {
    "projects": ("ch", "chantiers"), "clients": ("tiers", "tiers"), "quotes": ("doc_quotes", "devis"),
    "invoices": ("doc_invoices", "factures"), "crm_pistes": ("crm", "crm"), "personnel": ("pers", "personnel"),
    "expenses": ("dep", "depenses"), "ach_demandes": ("da", "achats-stock"),
}
PROBA_ETAPE = {"Nouveau": 10, "Qualifié": 30, "Proposition": 50, "Négociation": 70, "Gagné": 100, PERDU: 0}


def _date(texte: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(texte)[:10])
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ utilisateurs
def utilisateurs_actifs() -> dict[int, str]:
    return {r["id"]: r["nom"] for r in db.requete("select id, nom from users where actif = :a order by nom", a=True)}


# ------------------------------------------------------------------ activités planifiées
def echeance_etat(echeance: str, aujourd_hui: dt.date | None = None) -> str:
    """« En retard », « Aujourd’hui » ou « À venir »."""
    j = aujourd_hui or dt.date.today()
    d = _date(echeance)
    if d is None or d > j:
        return "À venir"
    return "Aujourd’hui" if d == j else "En retard"


def planifier(objet: str, objet_id: str, libelle: str, type_: str, resume: str, echeance: str,
              assigne_a: int | None, auteur: int | None) -> str:
    if type_ not in TYPES_ACTIVITE:
        raise ValueError("Type d’activité inconnu.")
    if not str(resume).strip():
        raise ValueError("Décrivez l’activité (ex. « Appeler le client pour le devis »).")
    if _date(echeance) is None:
        raise ValueError("Indiquez une date d’échéance valide.")
    id_ = db.nouvel_id()
    with db.transaction(f"Activité planifiée : {type_} – {resume.strip()[:80]}") as t:
        t.inserer("activites", {"id": id_, "objet": objet, "objet_id": str(objet_id), "libelle": str(libelle or "")[:500],
                                "type": type_, "resume": resume.strip()[:500], "echeance": str(echeance)[:10],
                                "assigne_a": assigne_a, "cree_par": auteur, "cree_le": db.maintenant(), "fait": False,
                                "fait_le": None, "compte_rendu": ""})
        nom = utilisateurs_actifs().get(assigne_a, "")
        t.evenement("Activité", f"{type_} planifié(e) le {echeance}" + (f" pour {nom}" if nom else "")
                    + f" : {resume.strip()[:200]}", objet, str(objet_id))
    return id_


def terminer(act_id: str, compte_rendu: str = "") -> None:
    a = db.un("activites", act_id)
    if not a or a["fait"]:
        raise ValueError("Cette activité est déjà terminée ou n’existe plus.")
    with db.transaction(f"Activité terminée : {a['type']} – {a['resume'][:80]}") as t:
        t.maj("activites", act_id, {"fait": True, "fait_le": db.maintenant(), "compte_rendu": str(compte_rendu or "")[:2000]})
        t.evenement("Activité", f"{a['type']} fait(e) : {a['resume']}" + (f" — {compte_rendu.strip()}" if
                                                                          str(compte_rendu or "").strip() else ""),
                    a["objet"], a["objet_id"])


def reporter(act_id: str, echeance: str) -> None:
    a = db.un("activites", act_id)
    if not a or a["fait"]:
        raise ValueError("Cette activité est déjà terminée ou n’existe plus.")
    if _date(echeance) is None:
        raise ValueError("Date invalide.")
    with db.transaction(f"Activité reportée au {echeance} : {a['resume'][:80]}") as t:
        t.maj("activites", act_id, {"echeance": echeance})


def activites_de(objet: str, objet_id: str, ouvertes: bool = True) -> list[dict]:
    rows = db.requete("select * from activites where objet = :o and objet_id = :i order by echeance, cree_le",
                      o=objet, i=str(objet_id))
    return [r for r in rows if not r["fait"]] if ouvertes else rows


def activites(uid: int | None = None, inclure_faites: bool = False) -> list[dict]:
    rows = db.requete("select * from activites order by echeance, cree_le")
    if uid is not None:
        rows = [r for r in rows if r["assigne_a"] == uid]
    return rows if inclure_faites else [r for r in rows if not r["fait"]]


def rappels(uid: int) -> dict[str, int]:
    """Nombre d'activités ouvertes de l'utilisateur : en retard et pour aujourd'hui."""
    out = {"En retard": 0, "Aujourd’hui": 0}
    try:
        rows = db.requete("select echeance from activites where assigne_a = :u and fait = :f", u=uid, f=False)
    except Exception:  # noqa: BLE001  (base pas encore migrée : aucun rappel plutôt qu'une erreur)
        return out
    for r in rows:
        e = echeance_etat(r["echeance"])
        if e in out:
            out[e] += 1
    return out


# ------------------------------------------------------------------ CRM
def montant_pondere(p: dict) -> int:
    return int(round(p["montant"] * (p["probabilite"] or 0) / 100))


def enregistrer_piste(valeurs: dict, pid: str | None = None) -> str:
    v = dict(valeurs)
    if not str(v.get("titre", "")).strip():
        raise ValueError("Donnez un titre à la piste (ex. « Clôture du dépôt Kingabwa »).")
    if not v.get("client") and not str(v.get("contact", "")).strip():
        raise ValueError("Choisissez un client existant ou indiquez le nom du prospect.")
    if v.get("etape") not in ETAPES_CRM + [PERDU]:
        raise ValueError("Étape inconnue.")
    v["probabilite"] = max(0, min(100, int(v.get("probabilite") or 0)))
    v["priorite"] = max(0, min(3, int(v.get("priorite") or 0)))
    if v.get("cloture_prevue") and _date(v["cloture_prevue"]) is None:
        raise ValueError("Date de clôture prévue invalide.")
    v["titre"] = v["titre"].strip()
    for k in ("client", "contact", "telephone", "email", "source", "cloture_prevue", "notes", "motif_perte"):
        v[k] = str(v.get(k) or "").strip()
    if pid:
        with db.transaction(f"Modification de la piste {v['titre']}") as t:
            t.maj("crm_pistes", pid, v)
        return pid
    pid = db.nouvel_id()
    with db.transaction(f"Nouvelle piste commerciale {v['titre']}") as t:
        t.inserer("crm_pistes", {"id": pid, "cree_le": db.maintenant(), "archive": False, "motif_perte": "", **v})
    return pid


def changer_etape(pid: str, etape: str, motif: str = "") -> None:
    p = db.un("crm_pistes", pid)
    if not p:
        raise ValueError("Piste introuvable.")
    if etape == PERDU and not motif.strip():
        raise ValueError("Indiquez pourquoi la piste est perdue (prix, délai, concurrent…).")
    vals = {"etape": etape, "probabilite": PROBA_ETAPE.get(etape, p["probabilite"])}
    if etape == PERDU:
        vals["motif_perte"] = motif.strip()[:500]
    with db.transaction(f"Piste {p['titre']} : étape « {etape} »") as t:
        t.maj("crm_pistes", pid, vals)


def creer_client(pid: str) -> str:
    """Transforme le prospect en tiers « client » et rattache la piste à ce tiers."""
    p = db.un("crm_pistes", pid)
    if not p:
        raise ValueError("Piste introuvable.")
    if p["client"]:
        return p["client"]
    nom = p["contact"] or p["titre"]
    cid = db.nouvel_id()
    with db.transaction(f"Client créé depuis la piste {p['titre']}") as t:
        t.inserer("clients", {"id": cid, "code": R.next_party_code(db.tout("clients")), "name": nom,
                              "phone": p["telephone"], "email": p["email"], "address": "", "registration": "",
                              "roles": ["client"], "archived": False})
        t.maj("crm_pistes", pid, {"client": cid})
    return cid


# ------------------------------------------------------------------ planning
def periode_chantier(p: dict) -> tuple[dt.date | None, dt.date | None]:
    return _date(p.get("debut")), _date(p.get("deadline"))


def enregistrer_dates(dates: dict[str, tuple[str, str]]) -> int:
    """{id chantier: (début, fin)} ; renvoie le nombre de chantiers modifiés."""
    n = 0
    with db.transaction("Planning des chantiers : dates mises à jour") as t:
        for pid, (debut, fin) in dates.items():
            if debut and _date(debut) is None or fin and _date(fin) is None:
                raise ValueError("Une date est invalide (format AAAA-MM-JJ).")
            if debut and fin and debut > fin:
                raise ValueError("La date de début doit précéder la date de livraison.")
            p = t.get("projects", pid)
            if p and ((p.get("debut") or "") != (debut or "") or (p.get("deadline") or "") != (fin or "")):
                t.maj("projects", pid, {"debut": debut or None, "deadline": fin or ""})
                n += 1
    return n


# ------------------------------------------------------------------ tableau de bord
def prefs_tableau(uid: int) -> dict | None:
    return db.parametre(f"tdb_{uid}")


def enregistrer_prefs_tableau(uid: int, widgets: list[str], colonnes: int) -> None:
    with db.transaction("Tableau de bord personnalisé") as t:
        t.parametre(f"tdb_{uid}", {"widgets": list(widgets), "colonnes": int(colonnes)})
