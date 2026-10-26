"""Référentiel du stock (familles, articles, magasins) et demandes d'achat à lignes d'articles, depuis Excel.

Mêmes contrôles qu'à l'écran (stocks.py, achats.py) : comptes de famille, nature d'article, magasin de chantier
unique, budget DQE approuvé, devise du budget, poste DQE, chantiers affectés, fournisseur enregistré.
Les demandes importées sont en brouillon : leur demandeur les soumet au circuit N0 → N1 → N2 → N3 → DG.
"""
from __future__ import annotations

import sqlalchemy as sa

import achats as A
import db
import regles as R
import stocks as S
from imports.adapters.commun import correspondance, lignes, ok, provenance, verifier_chantier_contexte
from imports.validation import norm


def _code(v) -> str:
    return str(v or "").strip().upper()


def _familles(ds, etat) -> dict:
    out = {_code(f["code"]): f for f in etat.familles}
    for l in lignes(ds, "Familles_Articles"):
        if l.get("reference_externe"):
            out[_code(l["reference_externe"])] = {"code": _code(l["reference_externe"]), "actif": True,
                                                   "compte_stock": l.get("compte_stock") or ""}
    return out


def _articles(ds, etat) -> dict:
    out = {_code(a["code"]): a for a in etat.articles}
    for l in lignes(ds, "Articles"):
        if l.get("reference_externe"):
            out[_code(l["reference_externe"])] = {"code": _code(l["reference_externe"]), "actif": True,
                                                   "nature": l.get("nature"), "a_qualifier": False}
    return out


def _magasins(ds, etat) -> dict:
    out = {_code(m["code"]): m for m in etat.magasins}
    for l in lignes(ds, "Magasins"):
        if l.get("reference_externe"):
            out[_code(l["reference_externe"])] = {"code": _code(l["reference_externe"]), "actif": True}
    return out


# ------------------------------------------------------------------ familles
def verifier_familles(ds, ctx, etat, res, rep):
    existantes = {_code(f["code"]) for f in etat.familles}
    for l in lignes(ds, "Familles_Articles"):
        if not ok(l, "reference_externe", "libelle", "compte_charge"):
            continue
        comptes = [l.get("compte_charge"), l.get("compte_stock"), l.get("compte_variation")]
        if any(c and not str(c).strip().isdigit() for c in comptes):
            rep.erreur("Familles_Articles", l["__line"], "compte_charge", "Comptes SYSCOHADA en chiffres seulement.")
            continue
        if bool(l.get("compte_stock")) != bool(l.get("compte_variation")):
            rep.erreur("Familles_Articles", l["__line"], "compte_stock", "Compte de stock et compte de variation vont ensemble.")
            continue
        code = _code(l["reference_externe"])
        rep.action("Familles_Articles", l["__line"], "Mise à jour" if code in existantes else "Création", code,
                   l["libelle"], "famille_article", {k: l.get(k) for k in ("libelle", "compte_charge", "compte_stock",
                                                                           "compte_variation")},
                   adaptateur="familles_articles")


def executer_familles(t, ctx, a, res):
    p = a["payload"]
    return S._famille_tx(t, ctx["user"], a["ref"], p["libelle"], p["compte_charge"], p.get("compte_stock") or "",
                         p.get("compte_variation") or "")


# ------------------------------------------------------------------ articles
def verifier_articles(ds, ctx, etat, res, rep):
    familles = _familles(ds, etat)
    existants = {_code(a["code"]): a for a in etat.articles}
    for l in lignes(ds, "Articles"):
        if not ok(l, "reference_externe", "libelle", "famille", "nature", "unite_stock"):
            continue
        line, code = l["__line"], _code(l["reference_externe"])
        f = familles.get(_code(l["famille"]))
        if not f or not f.get("actif", True):
            rep.erreur("Articles", line, "famille", "Famille inconnue ou inactive.")
            continue
        if l["nature"] == "stocke" and not f.get("compte_stock"):
            rep.erreur("Articles", line, "famille", "Article stocké : famille avec compte de stock requise.")
            continue
        avant = existants.get(code)
        if avant and (avant["nature"] != l["nature"] or avant["unite_stock"] != l["unite_stock"]) \
                and avant.get("qte_totale"):
            rep.erreur("Articles", line, "nature", "Article déjà mouvementé : nature et unité de stock inchangeables.")
            continue
        rep.action("Articles", line, "Mise à jour" if avant else "Création", code, l["libelle"], "article",
                   {k: (str(l[k]) if k in ("coefficient", "seuil_min", "seuil_max") and l.get(k) is not None else l.get(k))
                    for k in ("libelle", "famille", "nature", "unite_stock", "unite_achat", "coefficient", "seuil_min",
                              "seuil_max")}, adaptateur="articles")


def executer_articles(t, ctx, a, res):
    p = a["payload"]
    existant = t.cx.execute(sa.select(S.T("stk_articles").c.id).where(S.T("stk_articles").c.code == a["ref"])).scalar()
    return S._enregistrer_article_tx(t, ctx["user"], a["ref"], p["libelle"], _code(p["famille"]), p["nature"],
                                     p["unite_stock"], p.get("unite_achat") or "", p.get("coefficient") or "1",
                                     p.get("seuil_min"), p.get("seuil_max"), True, existant)


# ------------------------------------------------------------------ magasins
def verifier_magasins(ds, ctx, etat, res, rep):
    existants = {_code(m["code"]): m for m in etat.magasins}
    for l in lignes(ds, "Magasins"):
        if not ok(l, "reference_externe", "libelle", "type"):
            continue
        line, code = l["__line"], _code(l["reference_externe"])
        projet = None
        if l.get("chantier_ref"):
            c = res.chantier(l["chantier_ref"])
            if not c or not c.get("id"):
                rep.erreur("Magasins", line, "chantier_ref", "Chantier existant requis.")
                continue
            projet = c["id"]
        if l["type"] == "chantier" and not projet:
            rep.erreur("Magasins", line, "chantier_ref", "Un magasin de chantier est rattaché à un chantier.")
            continue
        rep.action("Magasins", line, "Mise à jour" if code in existants else "Création", code, l["libelle"], "magasin",
                   {"libelle": l["libelle"], "type": l["type"], "projet": projet}, adaptateur="magasins")


def executer_magasins(t, ctx, a, res):
    p = a["payload"]
    existant = t.cx.execute(sa.select(S.T("stk_magasins").c.id).where(S.T("stk_magasins").c.code == a["ref"])).scalar()
    return S._magasin_tx(t, ctx["user"], a["ref"], p["libelle"], p["type"], p["projet"], id_=existant)


# ------------------------------------------------------------------ demandes d'achat
def verifier_demandes(ds, ctx, etat, res, rep):
    u = ctx["user"]
    articles, magasins = _articles(ds, etat), _magasins(ds, etat)
    par_demande: dict[str, list] = {}
    for l in lignes(ds, "Lignes_Demande_Achat"):
        par_demande.setdefault(l.get("demande_ref"), []).append(l)
    for h in lignes(ds, "Demandes_Achat"):
        if not ok(h, "reference_externe", "chantier_ref", "date_souhaitee", "devise"):
            continue
        ref, line = h["reference_externe"], h["__line"]
        if not verifier_chantier_contexte(ctx, res, "Demandes_Achat", h, rep):
            continue
        if etat.mapping("demande_achat_v8", ref):
            rep.erreur("Demandes_Achat", line, "reference_externe", "Demande déjà importée.")
            continue
        c = res.chantier(h["chantier_ref"])
        if not c or not c.get("id"):
            rep.erreur("Demandes_Achat", line, "chantier_ref", "Chantier existant avec budget DQE approuvé requis.")
            continue
        if not etat.sur_chantier(u, c["id"]):
            rep.erreur("Demandes_Achat", line, "chantier_ref", "Chantier hors de votre périmètre (chantiers affectés).")
            continue
        b = next((x for x in etat.budgets_actifs() if x["project"] == c["id"]), None)
        if not b or b["data"]["status"] != "Approuvé":
            rep.erreur("Demandes_Achat", line, "chantier_ref", "Budget DQE approuvé requis.")
            continue
        if h["devise"] != b["currency"]:
            rep.erreur("Demandes_Achat", line, "devise", f"Le budget est en {b['currency']} : aucune conversion implicite.")
            continue
        if h.get("magasin_ref") and _code(h["magasin_ref"]) not in magasins:
            rep.erreur("Demandes_Achat", line, "magasin_ref", "Magasin inconnu.")
            continue
        enfants = sorted(par_demande.get(ref, []), key=lambda x: x.get("numero_ligne") or 0)
        if not enfants:
            rep.erreur("Demandes_Achat", line, "reference_externe", "Aucune ligne dans Lignes_Demande_Achat.")
            continue
        postes = {x["code"] for x in b["data"]["lines"]}
        sorties, valide, total = [], True, 0
        for e in enfants:
            if not ok(e, "numero_ligne", "article_ref", "code_dqe", "quantite"):
                valide = False
                continue
            a = articles.get(_code(e["article_ref"]))
            if not a or not a.get("actif", True):
                rep.erreur("Lignes_Demande_Achat", e["__line"], "article_ref", "Article inconnu ou inactif.")
                valide = False
            elif a.get("nature") == "stocke" and not h.get("magasin_ref"):
                rep.erreur("Demandes_Achat", line, "magasin_ref", "Magasin de livraison requis pour un article stocké.")
                valide = False
            if e["code_dqe"] not in postes:
                rep.erreur("Lignes_Demande_Achat", e["__line"], "code_dqe", "Poste DQE absent du budget.")
                valide = False
            if not e["quantite"]:
                rep.erreur("Lignes_Demande_Achat", e["__line"], "quantite", "Quantité positive requise.")
                valide = False
            if e.get("fournisseur_ref"):
                t_ = res.tiers(e["fournisseur_ref"])
                roles = set(R.party_roles(t_["fiche"])) if t_ and t_["source"] == "base" else \
                    {"supplier"} if t_ and "fourn" in norm((t_.get("row") or {}).get("roles")) else set()
                if not roles & {"supplier", "subcontractor"}:
                    rep.erreur("Lignes_Demande_Achat", e["__line"], "fournisseur_ref", "Fournisseur introuvable.")
                    valide = False
            total += A.cents(S.D(e["quantite"]) * (e.get("prix_estime") or 0))
            sorties.append({"article_ref": _code(e["article_ref"]), "poste": e["code_dqe"], "quantite": str(e["quantite"]),
                            "prix_estime": e.get("prix_estime") or 0, "fournisseur_ref": e.get("fournisseur_ref") or "",
                            "motif_hors_stock": e.get("motif_hors_stock") or "", "note": e.get("note") or ""})
        if not valide:
            continue
        rep.action("Demandes_Achat", line, "Demande d’achat en brouillon", ref,
                   f"{len(sorties)} ligne(s) · à soumettre au circuit N0 → DG", "demande_achat_v8",
                   {"chantier_ref": h["chantier_ref"], "date": h["date_souhaitee"],
                    "magasin_ref": _code(h.get("magasin_ref")) if h.get("magasin_ref") else "",
                    "urgence": h.get("urgence") or "Normale", "justification": h.get("justification") or "",
                    "lignes": sorties},
                   effet={"rubrique": "Demandes d’achat en brouillon (estimation)", "devise": h["devise"], "montant": total},
                   adaptateur="demandes_achat")


def executer_demandes(t, ctx, a, res):
    p = a["payload"]
    art = {r[0]: r[1] for r in t.cx.execute(sa.select(S.T("stk_articles").c.code, S.T("stk_articles").c.id))}
    mag = {r[0]: r[1] for r in t.cx.execute(sa.select(S.T("stk_magasins").c.code, S.T("stk_magasins").c.id))}
    lignes_ = [{"article": art[l["article_ref"]], "poste": l["poste"], "quantite": l["quantite"],
                "prix_estime": l["prix_estime"], "motif_hors_stock": l["motif_hors_stock"], "note": l["note"],
                "fournisseur": res.id("tiers", l["fournisseur_ref"]) if l["fournisseur_ref"] else None}
               for l in p["lignes"]]
    id_ = A._creer_demande_tx(t, ctx["user"], res.id("chantier", p["chantier_ref"]), p["date"],
                              mag.get(p["magasin_ref"]) if p["magasin_ref"] else None, p["urgence"], p["justification"],
                              lignes_, origine=f"import {ctx.get('lot_ref', '')} / {a['ref']}")
    correspondance(t, ctx, "demande_achat_v8", a["ref"], id_, "Demande d’achat en brouillon")
    return id_


FAMILLES = {"verifier": verifier_familles, "executer": executer_familles}
ARTICLES = {"verifier": verifier_articles, "executer": executer_articles}
MAGASINS = {"verifier": verifier_magasins, "executer": executer_magasins}
DEMANDES = {"verifier": verifier_demandes, "executer": executer_demandes}
