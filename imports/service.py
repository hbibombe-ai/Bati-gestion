"""Service d'import : lecture, contrôle, aperçu, confirmation transactionnelle, lots et idempotence.

Contrats (spécification §11) :
    parse_file(contenu, fonction, schema_version)      → jeu de données normalisé
    validate_import(dataset, context)                  → rapport (erreurs, alertes, plan, totaux)
    preview_import(dataset, context, ...)              → aperçu conservé côté serveur (lignes + condensat)
    commit_import(preview_id, decisions, fichiers)     → lot créé en une seule transaction, ou rien

Le contexte comprend le mode, la date de bascule, le chantier éventuel et l'utilisateur connecté (relu en base).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

import db
import gestion_v7 as V
from imports import adapters as A
from imports import excel as X
from imports import reconciliation as RC
from imports import schema as S
from imports import validation as VA

DUREE_APERCU = dt.timedelta(hours=2)
STATUTS_PREPARES = ("Préparé", "Validé Finance")


class ImportBloque(Exception):
    """Import refusé : le rapport explique les erreurs ; aucune donnée n'a été enregistrée."""

    def __init__(self, rapport: dict, message: str = "Import refusé : corrigez les erreurs bloquantes."):
        super().__init__(message)
        self.rapport = rapport


def _json(v) -> str:
    return json.dumps(v, ensure_ascii=False, sort_keys=True, default=str)


def condensat(dataset: dict) -> str:
    return hashlib.sha256(_json({k: dataset[k] for k in ("fonction", "params", "feuilles", "empreinte")}).encode()).hexdigest()


def utilisateur_courant() -> dict:
    return V.actor()


# ------------------------------------------------------------------ 1. lecture
def parse_file(contenu: bytes, fonction: str, schema_version: str | None = None) -> dict:
    f = S.fonction(fonction)
    brut = X.lire(contenu, f.feuilles)
    ds = VA.normaliser_dataset(brut, f.cle)
    if schema_version and schema_version != S.VERSION_MODELE:
        ds["errors"].append({"sheet": "Parametres", "line": 0, "field": "version_modele",
                             "message": f"Version de modèle attendue : {schema_version}."})
    return ds


def contexte(mode: str, date_bascule: str = "", chantier: str = "", fichiers: dict | None = None) -> dict:
    if mode not in S.MODES:
        raise ValueError("Mode d’import inconnu.")
    return {"mode": mode, "date_bascule": date_bascule or "", "chantier": chantier or "", "user": utilisateur_courant(),
            "fichiers": fichiers or {}}


# ------------------------------------------------------------------ 2. contrôle
def validate_import(dataset: dict, ctx: dict, etat: VA.Etat | None = None) -> dict:
    return _valider(dataset, ctx, etat)[0].dict()


def _valider(dataset: dict, ctx: dict, etat: VA.Etat | None = None):
    rep = VA.Rapport()
    for e in dataset["errors"]:
        rep.errors.append(e)
    VA.controler_parametres(dataset, ctx, rep)
    VA.controler_droits(dataset, ctx, rep)
    if rep.confidentiel_refuse:
        rep.plan.clear()
        return rep, None
    VA.controler_structure(dataset, ctx, rep)
    ctx = {**ctx, "lot_ref": dataset["params"].get("reference_lot") or "",
           "source_systeme": dataset["params"].get("source_systeme") or "",
           "date_bascule": dataset["params"].get("date_bascule") or ctx.get("date_bascule", "")}
    if etat is None:
        with db.moteur().connect() as cx:
            etat = VA.Etat(cx)
    lot_meme_ref = [l for l in etat.lots if l["reference_lot"] == ctx["lot_ref"] and l["id"] != ctx.get("lot_id")]
    etat.exclure_lots({l["id"] for l in lot_meme_ref if l["statut"] in STATUTS_PREPARES})
    for l in lot_meme_ref:
        if l["statut"] in STATUTS_PREPARES:
            rep.alerte("Parametres", 0, "reference_lot", f"Un lot « {l['statut']} » porte déjà cette référence : la "
                       "confirmation le rejettera et le remplacera avec traçabilité.", decision=True)
        else:
            rep.erreur("Parametres", 0, "reference_lot", f"Référence de lot déjà utilisée (lot {l['statut'].lower()}). "
                       "Un lot activé se corrige par correction ou contre-passation contrôlée, pas par réimport.")
    if ctx["mode"] == "archives":
        for nom in S.ORDRE_FEUILLES:
            for l in dataset["feuilles"].get(nom, []):
                rep.action(nom, l["__line"], "Archive", str(l.get(S.FEUILLES[nom].cle) or l.get("matricule") or ""),
                           "Conservé pour consultation, sans effet", adaptateur="")
        return rep, None
    res = VA.Resolveur(etat)
    for nom, ad in A.ADAPTATEURS.items():
        ad["verifier"](dataset, ctx, etat, res, rep)
    return rep, res


# ------------------------------------------------------------------ 3. aperçu conservé côté serveur
def preview_import(dataset: dict, ctx: dict, contenu: bytes | None = None, nom_fichier: str = "") -> dict:
    rapport = validate_import(dataset, ctx)
    if rapport["confidentiel_refuse"]:
        return {"preview_id": None, "rapport": rapport}
    pid = db.nouvel_id()
    fichiers = {k: hashlib.sha256(v).hexdigest() for k, v in (ctx.get("fichiers") or {}).items()}
    with db.transaction("Aperçu d’import") as t:
        t.cx.execute(db.TABLES["import_previews"].insert().values(
            id=pid, user_id=ctx["user"]["id"], cree_le=db.maintenant(), fonction=dataset["fonction"],
            contexte={"mode": ctx["mode"], "date_bascule": ctx["date_bascule"], "chantier": ctx["chantier"],
                      "fichiers": fichiers},
            donnees=json.loads(_json(dataset)), condensat=condensat(dataset), empreinte=dataset["empreinte"],
            fichier=nom_fichier[:300], contenu=contenu, statut="Ouvert"))
    return {"preview_id": pid, "rapport": rapport}


def _cle(dataset: dict, ctx: dict) -> str:
    base = "|".join([dataset["empreinte"], dataset["fonction"], ctx["mode"], ctx.get("date_bascule", ""),
                     dataset["params"].get("reference_lot", ""), ctx.get("chantier", "")])
    return hashlib.sha256(base.encode()).hexdigest()


def _lot_par_cle(cle: str) -> dict | None:
    rows = db.requete("select id from import_lots where cle = :c", c=cle)
    return lot(rows[0]["id"]) if rows else None


def lot(lot_id: str) -> dict | None:
    t = db.TABLES["import_lots"]
    with db.moteur().connect() as c:
        r = c.execute(sa.select(*[x for x in t.c if x.name != "contenu"]).where(t.c.id == lot_id)).first()
    return dict(r._mapping) if r else None


def lots() -> list[dict]:
    return sorted(db.tout("import_lots", sans=("contenu", "lignes")), key=lambda x: x["cree_le"], reverse=True)


# ------------------------------------------------------------------ 4. confirmation transactionnelle
def commit_import(preview_id: str, decisions: dict | None = None, fichiers: dict | None = None) -> dict:
    decisions = decisions or {}
    u = utilisateur_courant()
    pv_t = db.TABLES["import_previews"]
    with db.moteur().connect() as c:
        pv = c.execute(sa.select(pv_t).where(pv_t.c.id == preview_id)).first()
    if not pv:
        raise ValueError("Aperçu introuvable : relancez le contrôle.")
    pv = dict(pv._mapping)
    if pv["user_id"] != u["id"]:
        raise ValueError("Cet aperçu a été préparé par un autre utilisateur.")
    dataset = pv["donnees"]
    if condensat(dataset) != pv["condensat"]:
        raise ValueError("Aperçu altéré : relancez le contrôle.")
    ctxp = pv["contexte"]
    fichiers = fichiers or {}
    if {k: hashlib.sha256(v).hexdigest() for k, v in fichiers.items()} != (ctxp.get("fichiers") or {}):
        raise ValueError("Les pièces jointes ont changé depuis l’aperçu : relancez le contrôle.")
    ctx = {"mode": ctxp["mode"], "date_bascule": ctxp["date_bascule"], "chantier": ctxp["chantier"], "user": u,
           "fichiers": fichiers, "lot_ref": dataset["params"]["reference_lot"],
           "source_systeme": dataset["params"].get("source_systeme", "")}
    cle = _cle(dataset, ctx)
    existant = _lot_par_cle(cle)
    if existant:
        return {"lot": existant, "existant": True}
    if pv["statut"] != "Ouvert" or db.maintenant() - pv["cree_le"] > DUREE_APERCU:
        raise ValueError("Aperçu expiré ou déjà utilisé : relancez le contrôle.")
    lot_id = db.nouvel_id()
    ctx["lot_id"] = lot_id
    try:
        with db.transaction(f"Import {S.fonction(dataset['fonction']).libelle} — lot {ctx['lot_ref']}") as t:
            # La clé unique est réclamée en premier : une seconde confirmation concurrente échoue ici.
            t.inserer("import_lots", {
                "id": lot_id, "cle": cle, "reference_lot": f"{ctx['lot_ref']}#{lot_id[:8]}", "fonction": dataset["fonction"],
                "version_modele": dataset["params"].get("version_modele", ""), "mode": ctx["mode"],
                "date_bascule": ctx["date_bascule"], "source_systeme": ctx["source_systeme"][:300],
                "empreinte": dataset["empreinte"], "fichier": pv["fichier"], "contenu": pv["contenu"], "statut": "En cours",
                "cree_par": u["id"], "cree_le": db.maintenant(), "historique": []}, resume=f"Lot d’import {ctx['lot_ref']}")
            anciens = [l for l in VA.Etat(t.cx).lots if l["reference_lot"] == ctx["lot_ref"] and l["statut"] in STATUTS_PREPARES]
            if anciens and not decisions.get("remplacer"):
                raise ImportBloque(validate_import(dataset, ctx), "Un lot préparé porte cette référence : confirmez son "
                                                                  "remplacement.")
            for ancien in anciens:
                _rejeter_tx(t, u, ancien["id"], f"Remplacé par le lot {lot_id}", remplace_par=lot_id)
            etat = VA.Etat(t.cx)
            rep_, res = _valider(dataset, ctx, etat)
            rapport = rep_.dict()
            if rapport["errors"]:
                raise ImportBloque(rapport)
            if rapport["decisions"] and not decisions.get("accepter_alertes"):
                raise ImportBloque(rapport, "Des alertes affectent la reprise : une décision explicite est requise.")
            projets = None
            avant = RC.instantane(t.cx, projets)
            crees = []
            for action in rapport["plan"]:
                if ctx["mode"] == "archives" or not action["adaptateur"]:
                    continue
                id_ = A.executer(t, ctx, action, res)
                crees.append({"sheet": action["sheet"], "line": action["line"], "action": action["action"],
                              "ref": action["ref"], "id": id_ or ""})
            apres = RC.instantane(t.cx, projets)
            a_activer = any(a["action"] in ("Reliquat à activer", "Budget à approuver") for a in rapport["plan"])
            statut = ("Archivé" if ctx["mode"] == "archives" else "Préparé" if ctx["mode"] == "reprise" and a_activer
                      else "Importé")
            lignes = dataset["feuilles"]
            t.maj("import_lots", lot_id, {
                "statut": statut, "reference_lot": ctx["lot_ref"],
                "resume": {"comptes": rapport["comptes"], "creations": crees, "totaux": rapport["totaux"]},
                "lignes": json.loads(_json(lignes)),
                "rapport": {"errors": [], "warnings": rapport["warnings"],
                            "decisions_acceptees": bool(decisions.get("accepter_alertes")), "plan": [
                                {k: a[k] for k in ("ordre", "sheet", "line", "action", "ref", "detail")} for a in rapport["plan"]]},
                "rapprochement": {"avant": avant, "apres_import": apres, "ecarts_import": RC.ecarts(avant, apres)},
                "historique": [{"action": "Import", "user": u["id"], "nom": u["nom"], "at": db.maintenant().isoformat(),
                                "statut": statut}]}, resume=f"Lot {ctx['lot_ref']} : {statut}")
            t.cx.execute(pv_t.update().where(pv_t.c.id == preview_id).values(statut="Confirmé"))
    except IntegrityError:
        existant = _lot_par_cle(cle)
        if existant:
            return {"lot": existant, "existant": True}
        raise ValueError("Conflit d’unicité (référence déjà utilisée par une autre saisie) : relancez le contrôle.")
    return {"lot": lot(lot_id), "existant": False}


# ------------------------------------------------------------------ 5. circuit du lot : Finance, DG, rejet
def _lot_tx(t, lot_id):
    l = t.get("import_lots", lot_id, verrou=True)
    if not l:
        raise ValueError("Lot introuvable.")
    return l


def _historique(l, u, action, motif, statut):
    return list(l.get("historique") or []) + [{"action": action, "user": u["id"], "nom": u["nom"], "motif": motif,
                                               "at": db.maintenant().isoformat(), "statut": statut}]


def valider_finance(lot_id: str, motif: str) -> None:
    """Rapprochement vérifié par Finance (personne distincte de l'importateur)."""
    u = V.actor(["finance", "admin"])
    if not motif.strip():
        raise ValueError("Motif / référence du rapprochement obligatoire.")
    with db.transaction("Validation Finance d’un lot de reprise") as t:
        l = _lot_tx(t, lot_id)
        if l["statut"] != "Préparé":
            raise ValueError("Seul un lot préparé peut être validé par Finance.")
        if l["cree_par"] == u["id"]:
            raise ValueError("La validation Finance doit être faite par une autre personne que l’importateur.")
        t.maj("import_lots", lot_id, {"statut": "Validé Finance",
                                      "historique": _historique(l, u, "Validation Finance", motif, "Validé Finance")})


def activer(lot_id: str, motif: str) -> dict:
    """Activation DG : approuve budgets et reliquats du lot dans une seule transaction (tout ou rien)."""
    u = V.actor(["admin"])
    if not motif.strip():
        raise ValueError("Motif d’activation obligatoire.")
    with db.transaction("Activation DG d’un lot de reprise") as t:
        l = _lot_tx(t, lot_id)
        if l["statut"] != "Validé Finance":
            raise ValueError("Validation Finance préalable requise.")
        acteurs = {h["user"] for h in l.get("historique") or [] if h["action"] in ("Import", "Validation Finance")}
        if u["id"] in acteurs:
            raise ValueError("La DG qui active doit être distincte de l’importateur et du validateur Finance.")
        avant = RC.instantane(t.cx)
        recs = V.records(tx=t)
        for b in [r for r in recs if r["kind"] == "budget" and r["data"].get("import_lot") == lot_id
                  and r["data"]["status"] == "À approuver"]:
            V._approve_budget_tx(t, u, b["id"], motif)
        for c in [r for r in recs if r["kind"] == "carryover" and r["data"].get("import_lot") == lot_id
                  and r["data"]["status"] == "À approuver"]:
            V._approve_carryover_tx(t, u, c["id"], motif)
        apres = RC.instantane(t.cx)
        rap = dict(l.get("rapprochement") or {})
        rap.update(avant_activation=avant, apres_activation=apres, ecarts_activation=RC.ecarts(avant, apres))
        t.maj("import_lots", lot_id, {"statut": "Activé", "rapprochement": rap,
                                      "historique": _historique(l, u, "Activation DG", motif, "Activé")})
    return rap


def _rejeter_tx(t, u, lot_id, motif, remplace_par=""):
    l = _lot_tx(t, lot_id)
    if l["statut"] not in STATUTS_PREPARES:
        raise ValueError("Après activation, utilisez une correction ou une contre-passation contrôlée.")
    for r in V.records(tx=t):
        d = r["data"]
        if d.get("import_lot") != lot_id:
            continue
        if r["kind"] == "carryover" and d["status"] == "À approuver":
            V._reject_carryover_tx(t, u, r["id"], motif)
        if r["kind"] == "budget" and d["status"] == "À approuver":
            nd = {**d, "status": "Rejeté", "ref_initiale": r["ref"]}
            V.event(nd, u, "Rejet du lot", motif)
            V.save(t, V.get(t, r["id"], "budget"), nd)
            v7 = db.TABLES["v7_records"]   # libère le code budget pour un lot corrigé (trace dans ref_initiale)
            t.cx.execute(v7.update().where(v7.c.id == r["id"]).values(ref=f"{r['ref']}~REJ-{lot_id[:6]}"[:200]))
            t.evenement("Modification", f"Code budget {r['ref']} libéré après rejet du lot", "v7_records", r["id"])
    m = db.TABLES["import_mappings"]
    t.supprimer_ou("import_mappings", sa.and_(m.c.lot_id == lot_id, m.c.effet.in_(
        ["Reliquat", "Budget à approuver"])), resume=f"Correspondances libérées par le rejet du lot {l['reference_lot']}")
    statut = "Remplacé" if remplace_par else "Rejeté"
    t.maj("import_lots", lot_id, {"statut": statut, "remplace": remplace_par,
                                  "reference_lot": f"{l['reference_lot']}~{lot_id[:8]}",
                                  "historique": _historique(l, u, statut, motif, statut)})


def rejeter(lot_id: str, motif: str) -> None:
    u = V.actor(["admin", "finance"])
    if not motif.strip():
        raise ValueError("Motif du rejet obligatoire.")
    with db.transaction("Rejet d’un lot de reprise") as t:
        _rejeter_tx(t, u, lot_id, motif)


def contenu_lot(lot_id: str) -> bytes | None:
    rows = db.requete("select contenu from import_lots where id = :i", i=lot_id)
    return bytes(rows[0]["contenu"]) if rows and rows[0]["contenu"] is not None else None


def lignes_lot(lot_id: str, role: str) -> dict:
    """Lignes conservées d'un lot ; les champs confidentiels sont masqués hors RH et DG."""
    rows = db.requete("select lignes from import_lots where id = :i", i=lot_id)
    lignes = rows[0]["lignes"] if rows else {}
    if isinstance(lignes, str):
        lignes = json.loads(lignes)
    lignes = lignes or {}
    if role in ("admin", "rh"):
        return lignes
    out = {}
    for nom, ls in lignes.items():
        fe = S.FEUILLES.get(nom)
        if fe and fe.module in ("paie",):
            continue
        conf = {c.nom for c in fe.champs if c.confidentiel} if fe else set()
        out[nom] = [{k: ("<confidentiel>" if k in conf and v not in (None, "") else v) for k, v in l.items()} for l in ls]
    return out
