"""Contrôles d'import : erreurs par feuille, ligne et champ ; résolution des références ; droits ; plan d'effets.

L'état de la base est relu au moment du contrôle (aperçu) puis de nouveau dans la transaction de confirmation :
le serveur ne fait jamais confiance à un résultat de contrôle transmis par l'interface.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

import sqlalchemy as sa

import auth
import db
import regles as R
from imports import excel as X
from imports import schema as S


class Rapport:
    def __init__(self):
        self.errors: list[dict] = []
        self.warnings: list[dict] = []
        self.plan: list[dict] = []
        self.totaux: dict[tuple, int] = defaultdict(int)
        self.confidentiel_refuse = False

    def erreur(self, feuille, ligne, champ, message):
        self.errors.append({"sheet": feuille, "line": ligne, "field": champ, "message": message})

    def alerte(self, feuille, ligne, champ, message, decision=False):
        self.warnings.append({"sheet": feuille, "line": ligne, "field": champ, "message": message, "decision": decision})

    def action(self, feuille, ligne, action, ref="", detail="", entite="", payload=None, effet=None, adaptateur=""):
        self.plan.append({"ordre": len(self.plan) + 1, "sheet": feuille, "line": ligne, "action": action, "ref": ref,
                          "detail": detail, "entite": entite, "payload": payload or {}, "effet": effet,
                          "adaptateur": adaptateur})
        if effet:
            self.totaux[(effet["rubrique"], effet["devise"], effet.get("compte", ""))] += effet["montant"]

    def dict(self) -> dict:
        comptes = defaultdict(int)
        for a in self.plan:
            comptes[a["action"]] += 1
        return {"valid": not self.errors, "errors": self.errors, "warnings": self.warnings,
                "decisions": [w for w in self.warnings if w["decision"]],
                "plan": self.plan, "comptes": dict(comptes), "confidentiel_refuse": self.confidentiel_refuse,
                "totaux": [{"rubrique": k[0], "devise": k[1], "compte": k[2], "montant": v}
                           for k, v in sorted(self.totaux.items())]}


# ------------------------------------------------------------------ état de la base (lecture dans la transaction)
class Etat:
    """Photographie des données utiles, lue avec la connexion fournie (transaction de confirmation ou lecture)."""

    def __init__(self, cx):
        lire = lambda nom, sans=(): [dict(r._mapping) for r in cx.execute(  # noqa: E731
            sa.select(*[c for c in db.TABLES[nom].c if c.name not in sans]))]
        self.clients = lire("clients")
        self.projects = lire("projects")
        self.personnel = lire("personnel")
        self.attendance = lire("attendance")
        self.v7 = lire("v7_records")
        self.mappings = lire("import_mappings")
        self.lots = lire("import_lots", ("contenu", "lignes"))
        self.pieces = lire("pieces", ("content",))
        self.movements = lire("movements")
        self.expenses = lire("expenses")

    def exclure_lots(self, ids: set) -> None:
        """Ignore les effets de lots préparés destinés à être remplacés (aperçu d'un lot corrigé)."""
        if not ids:
            return
        self.mappings = [m for m in self.mappings if m["lot_id"] not in ids]
        self.v7 = [r for r in self.v7 if (r["data"] or {}).get("import_lot") not in ids]

    def v7_kind(self, kind):
        return [r for r in self.v7 if r["kind"] == kind]

    def budgets_actifs(self):
        return [r for r in self.v7_kind("budget") if r["data"].get("status") != "Rejeté"]

    def mapping(self, entite, ref):
        return next((m for m in self.mappings if m["entite"] == entite and m["reference_externe"] == ref), None)


def norm(v) -> str:
    return R.normaliser(str(v or "").strip())


class Resolveur:
    """Résout les codes externes lisibles vers les identifiants internes (fichier d'abord, puis base)."""

    def __init__(self, etat: Etat):
        self.etat = etat
        self.fichier: dict[tuple, dict] = {}     # (entité, référence) -> {"id": None|str, "row": ..., "sheet": ...}

    def declarer(self, entite, ref, row, sheet):
        self.fichier[(entite, ref)] = {"id": None, "row": row, "sheet": sheet}

    def fixer(self, entite, ref, id_):
        self.fichier.setdefault((entite, ref), {"row": {}, "sheet": ""})["id"] = id_

    def dans_fichier(self, entite, ref):
        return self.fichier.get((entite, ref))

    def tiers(self, ref):
        if (f := self.dans_fichier("tiers", ref)):
            return {"source": "fichier", **f}
        m = self.etat.mapping("tiers", ref)
        c = next((c for c in self.etat.clients if (m and c["id"] == m["id_interne"]) or norm(c["code"]) == norm(ref)), None)
        return {"source": "base", "id": c["id"], "fiche": c} if c else None

    def chantier(self, ref):
        if (f := self.dans_fichier("chantier", ref)):
            return {"source": "fichier", **f}
        m = self.etat.mapping("chantier", ref)
        if m:
            p = next((p for p in self.etat.projects if p["id"] == m["id_interne"]), None)
            if p:
                return {"source": "base", "id": p["id"], "fiche": p}
        p = next((p for p in self.etat.projects if p["id"] == ref), None)
        if p:
            return {"source": "base", "id": p["id"], "fiche": p}
        homonymes = [p for p in self.etat.projects if norm(p["name"]) == norm(ref)]
        if len(homonymes) == 1:
            return {"source": "base", "id": homonymes[0]["id"], "fiche": homonymes[0]}
        return None

    def personne(self, ref):
        if (f := self.dans_fichier("personnel", ref)):
            return {"source": "fichier", **f}
        p = next((p for p in self.etat.personnel if norm(p["code"]) == norm(ref)), None)
        return {"source": "base", "id": p["id"], "fiche": p} if p else None

    def compte(self, ref):
        if (f := self.dans_fichier("compte_tresorerie", ref)):
            return {"source": "fichier", **f}
        a = next((a for a in self.etat.v7_kind("account") if a["ref"] == ref.strip().upper()), None)
        return {"source": "base", "id": a["id"], "fiche": a} if a else None

    def id(self, entite, ref):
        """Identifiant interne à l'exécution (les créations du même lot sont fixées au fil de l'import)."""
        f = self.dans_fichier(entite, ref)
        if f and f.get("id"):
            return f["id"]
        r = {"tiers": self.tiers, "chantier": self.chantier, "personnel": self.personne, "compte_tresorerie": self.compte}[entite](ref)
        if not r or not r.get("id"):
            raise ValueError(f"Référence {entite} « {ref} » non résolue au moment de l’import.")
        return r["id"]


# ------------------------------------------------------------------ normalisation et contrôles génériques
def normaliser_dataset(brut: dict, fonction: str) -> dict:
    """Convertit chaque cellule selon le registre ; les erreurs sont rattachées à la feuille, la ligne et le champ."""
    f = S.fonction(fonction)
    errors = list(brut["errors"])
    feuilles = {}
    for nom, lignes in brut["feuilles"].items():
        fe = S.FEUILLES[nom]
        out = []
        for l in lignes:
            row = {"__line": l["__line"]}
            for c in fe.champs:
                try:
                    row[c.nom] = X.normaliser(c, l.get(c.nom))
                except ValueError as e:
                    errors.append({"sheet": nom, "line": l["__line"], "field": c.nom, "message": str(e)})
                    row[c.nom] = None
            out.append(row)
        feuilles[nom] = out
    p = brut["params"]
    params = {}
    for k in S.PARAMETRES:
        v = p.get(k)
        params[k] = X.texte(v) if v is not None else ""
    if isinstance(p.get("date_bascule"), (dt.date, dt.datetime)):
        params["date_bascule"] = X.normaliser(S.Champ("d", "date"), p["date_bascule"])
    inconnus = [k for k in p if k not in S.PARAMETRES]
    if inconnus:
        errors.append({"sheet": "Parametres", "line": 0, "field": ", ".join(inconnus), "message": "Paramètre inconnu."})
    return {"fonction": f.cle, "params": params, "feuilles": feuilles, "errors": errors,
            "empreinte": brut["empreinte"], "taille": brut.get("taille", 0)}


def controler_parametres(ds: dict, ctx: dict, rep: Rapport) -> None:
    p = ds["params"]
    if p.get("version_modele") != S.VERSION_MODELE:
        rep.erreur("Parametres", 0, "version_modele", f"Modèle {p.get('version_modele') or 'inconnu'} : téléchargez le "
                                                      f"modèle {S.VERSION_MODELE}.")
    if p.get("mode_import") not in S.MODES:
        rep.erreur("Parametres", 0, "mode_import", "Choisir archives, reprise ou en_cours.")
    elif p["mode_import"] != ctx["mode"]:
        rep.erreur("Parametres", 0, "mode_import", f"Le classeur indique « {p['mode_import']} » mais le mode choisi à "
                                                   f"l’écran est « {ctx['mode']} ».")
    if not p.get("reference_lot"):
        rep.erreur("Parametres", 0, "reference_lot", "Référence du lot obligatoire.")
    else:
        try:
            X.normaliser(S.Champ("reference_lot", "ref", True), p["reference_lot"])
        except ValueError as e:
            rep.erreur("Parametres", 0, "reference_lot", str(e))
    d = p.get("date_bascule") or ""
    if ctx["mode"] == "reprise" and not d:
        rep.erreur("Parametres", 0, "date_bascule", "Date de bascule obligatoire en reprise.")
    if d:
        if not R.is_date(d):
            rep.erreur("Parametres", 0, "date_bascule", "Date de bascule au format AAAA-MM-JJ.")
        elif ctx.get("date_bascule") and d != ctx["date_bascule"]:
            rep.erreur("Parametres", 0, "date_bascule", "Date de bascule différente de celle choisie à l’écran.")
    if len(p.get("source_systeme") or "") > 300:
        rep.erreur("Parametres", 0, "source_systeme", "300 caractères au plus.")


def autorise(role: str, fe: S.Feuille) -> bool:
    if fe.roles:
        return role in fe.roles and auth.DROITS.get(role, {}).get(fe.module) == "w"
    return auth.DROITS.get(role, {}).get(fe.module) == "w"


def controler_droits(ds: dict, ctx: dict, rep: Rapport) -> None:
    role = ctx["user"]["role"]
    for nom, lignes in ds["feuilles"].items():
        if not lignes:
            continue
        fe = S.FEUILLES[nom]
        confidentiels = [c.nom for c in fe.champs if c.confidentiel]
        if confidentiels and role not in ("admin", "rh") and any(l.get(c) not in (None, "") for l in lignes for c in confidentiels):
            rep.confidentiel_refuse = True
            rep.erreur(nom, 0, "", "Données de rémunération réservées aux RH et à la DG : import refusé, contenu non affiché.")
        if not autorise(role, fe):
            rep.erreur(nom, 0, "", "Votre rôle ne permet pas d’importer cette feuille (mêmes droits que la saisie).")
            if fe.module in ("personnel", "paie"):
                rep.confidentiel_refuse = True


def controler_structure(ds: dict, ctx: dict, rep: Rapport) -> None:
    mode = ctx["mode"]
    for nom, lignes in ds["feuilles"].items():
        if not lignes:
            continue
        fe = S.FEUILLES[nom]
        if mode not in fe.modes:
            rep.erreur(nom, 0, "", "Fonction préparatoire pour ce mode : seul le mode Archives est disponible "
                                   "(import actif à développer)." if fe.statut != "réalisé" else
                       f"Cette feuille n’est pas prévue en mode « {S.MODES[mode]} ».")
        if fe.cle:
            vus = {}
            for l in lignes:
                k = l.get(fe.cle)
                if k is None:
                    continue
                if k in vus:
                    rep.erreur(nom, l["__line"], fe.cle, f"Référence en double dans la feuille (ligne {vus[k]}).")
                vus.setdefault(k, l["__line"])
        if fe.parent:
            champ, parente = fe.parent
            cles_parent = {l.get(S.FEUILLES[parente].cle) for l in ds["feuilles"].get(parente, [])}
            vus = set()
            for l in lignes:
                if l.get(champ) and l[champ] not in cles_parent:
                    rep.erreur(nom, l["__line"], champ, f"Référence absente de la feuille {parente}.")
                if "numero_ligne" in fe.colonnes and l.get("numero_ligne") is not None:
                    k = (l.get(champ), l["numero_ligne"])
                    if k in vus:
                        rep.erreur(nom, l["__line"], "numero_ligne", "Numéro de ligne en double pour ce parent.")
                    vus.add(k)
        for l in lignes:
            for c in ("date_fin", "fin_contrat"):
                debut = l.get("date_debut") or l.get("date_engagement")
                if l.get(c) and debut and l[c] < debut:
                    rep.erreur(nom, l["__line"], c, "La fin précède le début.")
