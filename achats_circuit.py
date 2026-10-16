"""Circuit des demandes d'achat matériel et matériaux (plusieurs chantiers, plusieurs projets).

Étapes :
  1. Demande d'achat (DA) multi-lignes, saisie ou importée par l'équipe chantier ; prix et fournisseur facultatifs.
  2. Validation du besoin par le chef de chantier ou le directeur de projet (rubrique « approbation_chantier »).
  3. Chiffrage par les achats : fournisseur et prix pour chaque ligne, confirmation ou correction des prix
     proposés, quantité servie par le stock (rubrique « chiffrage_achats »).
  4. Validation du coordonnateur de projet au-delà du seuil de la devise, ou si un poste DQE dépasse son
     disponible (rubrique « approbation_coordonnateur »).
  5. Transmission au circuit financier V7 : une opération « Achat » par fournisseur et par poste DQE, soumise
     automatiquement, qui suit ensuite N1 → N2 → N3 → DG, la commande, la réception, la facture et le paiement.
  6. Commande groupée : une même référence de bon de commande pour plusieurs opérations approuvées d'un fournisseur.

Règles conservées du circuit V7 : montants entiers en centimes, devise du budget sans conversion implicite, poste DQE
obligatoire, budget approuvé requis, une personne distincte à chaque contrôle, historique dans la fiche.
La demande est conservée dans v7_records (type « purchase_request ») : sauvegarde, restauration et audit inchangés.
"""
from __future__ import annotations

import re
from copy import deepcopy
from decimal import ROUND_HALF_UP, Decimal

import sqlalchemy as sa

import auth
import db
import gestion_v7 as V
import regles as R

KIND = "purchase_request"
STATUTS = ("Brouillon", "Soumise", "Validée chantier", "À valider coordonnateur", "Transmise au circuit V7",
           "Servie par stock", "Rejetée", "Annulée")
COMPTE_DEFAUT = "602"          # Achats de matières (plan proposé du circuit V7)
POLITIQUE_DEFAUT = {"seuil_coordonnateur": {c: 0 for c in R.CURRENCIES}, "compte": COMPTE_DEFAUT}
LIGNES_MAX = 200
QTE_MAX = Decimal("1000000000")


# ------------------------------------------------------------------ outils
def politique(tx=None) -> dict:
    """Seuils par devise (centimes) au-delà desquels le coordonnateur valide ; 0 = toujours."""
    if tx is not None:
        v = tx.cx.execute(sa.select(db.settings.c.valeur).where(db.settings.c.cle == "achats_politique")).scalar()
    else:
        v = db.parametre("achats_politique")
    p = deepcopy(POLITIQUE_DEFAUT)
    if isinstance(v, dict):
        p["seuil_coordonnateur"].update({k: int(x) for k, x in (v.get("seuil_coordonnateur") or {}).items()
                                         if k in R.CURRENCIES})
        p["compte"] = v.get("compte") or COMPTE_DEFAUT
    return p


def configurer_politique(seuils: dict, compte: str = COMPTE_DEFAUT) -> None:
    u = V.actor()
    V._exiger(u, "approbation_dg", "Réglage réservé à la DG.")
    propres = {}
    for c in R.CURRENCIES:
        propres[c] = V.amount(int(seuils.get(c, 0)))
    if compte not in V.CHART or not compte.startswith(("6", "2", "3")):
        raise ValueError("Compte de coût ou d’actif du plan proposé requis.")
    with db.transaction("Seuils du circuit des demandes d’achat") as t:
        t.parametre("achats_politique", {"seuil_coordonnateur": propres, "compte": compte})


def _exiger(u: dict, module: str, projet: str | None, message: str, tx=None) -> None:
    if not V.peut(u, module):
        raise ValueError(message)
    if projet and not auth.sur_chantier(u, projet, tx):
        raise ValueError("Ce chantier n’est pas dans votre périmètre (chantiers affectés).")


def _qte(v, libelle="Quantité") -> float:
    try:
        d = Decimal(str(v).replace(",", ".").strip())
    except Exception:  # noqa: BLE001
        raise ValueError(f"{libelle} invalide.") from None
    if not d.is_finite() or d <= 0 or d > QTE_MAX:
        raise ValueError(f"{libelle} positive requise.")
    return float(d)


def montant_ligne(quantite: float, prix: int) -> int:
    return int((Decimal(str(quantite)) * Decimal(prix)).quantize(Decimal("1"), ROUND_HALF_UP))


def a_acheter(l: dict) -> float:
    return max(0.0, float(l["quantite"]) - float(l.get("qte_stock") or 0))


def montant_total(d: dict) -> int:
    return sum(montant_ligne(a_acheter(l), l["prix"]) for l in d["lignes"] if l.get("prix") is not None and a_acheter(l))


def _fournisseur_ok(tx, party: str) -> bool:
    c = tx.get("clients", party)
    return bool(c) and not c.get("archived") and bool(set(R.party_roles(c)) & {"supplier", "subcontractor"})


def _nettoyer_lignes(tx, budget: dict, lignes: list[dict]) -> list[dict]:
    if not lignes:
        raise ValueError("Au moins une ligne d’article est requise.")
    if len(lignes) > LIGNES_MAX:
        raise ValueError(f"{LIGNES_MAX} lignes au plus par demande.")
    postes = {x["code"] for x in budget["data"]["lines"]}
    out = []
    for i, l in enumerate(lignes, 1):
        article = str(l.get("article") or "").strip()
        if not article or len(article) > 300:
            raise ValueError(f"Ligne {i} : désignation de l’article requise (300 caractères au plus).")
        post = str(l.get("post") or "").strip()
        if post not in postes:
            raise ValueError(f"Ligne {i} : poste DQE absent du budget du chantier.")
        prix = l.get("prix")
        if prix not in (None, ""):
            prix = V.amount(int(prix), True)
        else:
            prix = None
        fournisseur = str(l.get("fournisseur") or "").strip()
        if fournisseur and not _fournisseur_ok(tx, fournisseur):
            raise ValueError(f"Ligne {i} : fournisseur introuvable, archivé ou sans rôle fournisseur.")
        out.append(dict(n=i, post=post, article=article, unite=str(l.get("unite") or "").strip()[:30],
                        quantite=_qte(l.get("quantite"), f"Ligne {i} : quantité"), prix=prix, fournisseur=fournisseur,
                        source_prix="chantier" if prix is not None else "", qte_stock=0.0,
                        note=str(l.get("note") or "").strip()[:500]))
    return out


def _prochaine_ref(tx) -> str:
    annee = R.today()[:4]
    nums = [int(m.group(1)) for r in V.records(KIND, tx) if (m := re.fullmatch(rf"DA-{annee}-(\d+)", r["ref"]))]
    return f"DA-{annee}-{max(nums, default=0) + 1:04d}"


def _acteurs(d: dict) -> dict:
    return {k: v["user"] for k, v in (d.get("validations") or {}).items()}


# ------------------------------------------------------------------ 1. création et soumission
def creer(projet: str, objet: str, lieu: str, date_besoin: str, lignes: list[dict], ref: str = "") -> str:
    u = V.actor(["admin", "finance", "chantier"])
    _exiger(u, "demandes_achat", projet, "Votre profil ne permet pas de créer une demande d’achat.")
    with db.transaction("Demande d’achat") as t:
        return _creer_tx(t, u, projet, objet, lieu, date_besoin, lignes, ref)


def _creer_tx(t, u, projet, objet, lieu, date_besoin, lignes, ref="", extra=None) -> str:
    V.date(date_besoin)
    if not (objet or "").strip():
        raise ValueError("Objet de la demande requis.")
    b = V.budget_for(projet, t)
    d = dict(objet=objet.strip()[:300], lieu=(lieu or "").strip()[:300], date_besoin=date_besoin,
             lignes=_nettoyer_lignes(t, b, lignes), statut="Brouillon", creator=u["id"], validations={},
             operations=[], history=[], **(extra or {}))
    V.event(d, u, "Création" + (f" (import {extra['import_lot_ref']})" if extra and extra.get("import_lot_ref") else ""))
    return V.insert(t, KIND, (ref or "").strip() or _prochaine_ref(t), projet, b["currency"], d)


def modifier(id_: str, objet: str, lieu: str, date_besoin: str, lignes: list[dict]) -> None:
    u = V.actor(["admin", "finance", "chantier"])
    V.date(date_besoin)
    with db.transaction("Modification de la demande d’achat") as t:
        r = V.get(t, id_, KIND)
        d = deepcopy(r["data"])
        if d["creator"] != u["id"] or d["statut"] not in ("Brouillon", "Rejetée"):
            raise ValueError("Seul le demandeur modifie une demande en brouillon ou rejetée.")
        if not (objet or "").strip():
            raise ValueError("Objet de la demande requis.")
        b = V.budget_for(r["project"], t)
        d.update(objet=objet.strip()[:300], lieu=(lieu or "").strip()[:300], date_besoin=date_besoin,
                 lignes=_nettoyer_lignes(t, b, lignes), statut="Brouillon", validations={})
        V.event(d, u, "Modification (validations remises à zéro)")
        V.save(t, r, d)


def soumettre(id_: str) -> None:
    u = V.actor(["admin", "finance", "chantier"])
    with db.transaction("Soumission de la demande d’achat") as t:
        r = V.get(t, id_, KIND)
        d = deepcopy(r["data"])
        _exiger(u, "demandes_achat", r["project"], "Votre profil ne permet pas de soumettre une demande d’achat.", t)
        if d["creator"] != u["id"] or d["statut"] not in ("Brouillon", "Rejetée"):
            raise ValueError("Seul le demandeur soumet sa demande en brouillon ou rejetée.")
        d.update(statut="Soumise", validations={})
        V.event(d, u, "Soumission au chef de chantier / directeur de projet")
        V.save(t, r, d)


def annuler(id_: str, motif: str) -> None:
    u = V.actor()
    with db.transaction("Annulation de la demande d’achat") as t:
        r = V.get(t, id_, KIND)
        d = deepcopy(r["data"])
        if d["creator"] != u["id"] and not V.peut(u, "approbation_dg"):
            raise ValueError("Seul le demandeur ou la DG annule une demande.")
        if d["statut"] in ("Transmise au circuit V7", "Servie par stock", "Annulée"):
            raise ValueError("Demande déjà transmise, servie ou annulée : annulez les opérations V7 concernées.")
        if not (motif or "").strip():
            raise ValueError("Motif obligatoire.")
        d["statut"] = "Annulée"
        V.event(d, u, "Annulation", motif)
        V.save(t, r, d)


# ------------------------------------------------------------------ 2. validation chantier
def valider_chantier(id_: str, commentaire: str, rejeter: bool = False) -> None:
    u = V.actor(["admin", "finance", "chantier"])
    with db.transaction("Validation chantier de la demande d’achat") as t:
        r = V.get(t, id_, KIND)
        d = deepcopy(r["data"])
        _exiger(u, "approbation_chantier", r["project"], "Validation réservée au chef de chantier ou au directeur de projet.", t)
        if d["statut"] != "Soumise":
            raise ValueError("Aucune validation chantier en attente.")
        if u["id"] == d["creator"]:
            raise ValueError("Séparation des responsabilités : le demandeur ne valide pas sa propre demande.")
        if not (commentaire or "").strip():
            raise ValueError("Commentaire de contrôle obligatoire.")
        if rejeter:
            d.update(statut="Rejetée", validations={})
            V.event(d, u, "Rejet chantier", commentaire)
        else:
            d["validations"]["chantier"] = dict(user=u["id"], nom=u["nom"], at=db.maintenant().isoformat(), note=commentaire)
            d["statut"] = "Validée chantier"
            V.event(d, u, "Besoin validé (chantier)", commentaire)
        V.save(t, r, d)


# ------------------------------------------------------------------ 3. chiffrage par les achats
def chiffrer(id_: str, cotations: dict, commentaire: str = "") -> dict:
    """cotations : {numéro de ligne: {"fournisseur": id, "prix": centimes, "qte_stock": quantité}}.
    Une ligne sans prix doit recevoir une cotation ; une ligne avec prix proposé et fournisseur est confirmée
    telle quelle si elle n'est pas citée. Renvoie {"statut", "montant", "alertes"}."""
    u = V.actor(["admin", "finance"])
    with db.transaction("Chiffrage de la demande d’achat") as t:
        return _chiffrer_tx(t, u, id_, cotations, commentaire)


def _chiffrer_tx(t, u, id_, cotations, commentaire="", extra_note="") -> dict:
    r = V.get(t, id_, KIND)
    d = deepcopy(r["data"])
    _exiger(u, "chiffrage_achats", None, "Chiffrage réservé au service achats.")
    if d["statut"] != "Validée chantier":
        raise ValueError(f"Demande {r['ref']} : chiffrage possible après la validation chantier seulement.")
    if u["id"] in (d["creator"], _acteurs(d).get("chantier")):
        raise ValueError("Séparation des responsabilités : le chiffrage est fait par une autre personne que le "
                         "demandeur et le valideur du chantier.")
    cot = {int(k): v for k, v in (cotations or {}).items()}
    numeros = {l["n"] for l in d["lignes"]}
    if inconnues := sorted(set(cot) - numeros):
        raise ValueError(f"Lignes inconnues dans la demande : {', '.join(map(str, inconnues))}.")
    erreurs = []
    for l in d["lignes"]:
        c = cot.get(l["n"]) or {}
        if c.get("qte_stock") not in (None, ""):
            q = float(Decimal(str(c["qte_stock"]).replace(",", ".")))
            if q < 0 or q > l["quantite"]:
                erreurs.append(f"ligne {l['n']} : quantité servie par le stock entre 0 et {l['quantite']:g}")
                continue
            l["qte_stock"] = q
        if not a_acheter(l):
            l.update(source_prix="stock")
            continue
        if c.get("prix") not in (None, ""):
            prix = V.amount(int(c["prix"]), True)
            ancien = l.get("prix")
            l["source_prix"] = ("achats" if ancien is None else
                                "chantier confirmé achats" if ancien == prix else
                                f"achats (corrige {R.money(ancien, r['currency'])} proposé)")
            l["prix"] = prix
        if c.get("fournisseur"):
            l["fournisseur"] = str(c["fournisseur"]).strip()
        if l.get("prix") is None or not l.get("fournisseur"):
            erreurs.append(f"ligne {l['n']} : " + ("prix et fournisseur" if l.get("prix") is None else "fournisseur")
                           + " à renseigner")
            continue
        if not _fournisseur_ok(t, l["fournisseur"]):
            erreurs.append(f"ligne {l['n']} : fournisseur introuvable, archivé ou sans rôle fournisseur")
            continue
        if l["source_prix"] == "chantier":
            l["source_prix"] = "chantier confirmé achats"
    if erreurs:
        raise ValueError(f"Demande {r['ref']} incomplète : " + " ; ".join(erreurs) + ".")

    total = montant_total(d)
    alertes = _alertes_budget(t, r, d)
    d["validations"]["chiffrage"] = dict(user=u["id"], nom=u["nom"], at=db.maintenant().isoformat(),
                                         note=commentaire, montant=total, alertes=alertes)
    V.event(d, u, f"Chiffrage : {R.money(total, r['currency'])}" + (f" ({extra_note})" if extra_note else ""),
            commentaire)
    if total == 0:
        d["statut"] = "Servie par stock"
        V.event(d, u, "Entièrement servie par le stock : aucun achat")
        V.save(t, r, d)
        return {"statut": d["statut"], "montant": 0, "alertes": alertes}
    seuil = politique(t)["seuil_coordonnateur"].get(r["currency"], 0)
    if total > seuil or alertes or seuil == 0:
        d["statut"] = "À valider coordonnateur"
        V.save(t, r, d)
    else:
        _transmettre(t, u, r, d)
    return {"statut": d["statut"], "montant": total, "alertes": alertes}


def _alertes_budget(t, r: dict, d: dict) -> list[str]:
    """Postes DQE dont le disponible ne couvre pas le montant chiffré (information pour le coordonnateur)."""
    b = V.budget_for(r["project"], t)
    m = V.metrics(b, V.records("operation", t), tx=t)
    dispo = {x["code"]: x["available"] for x in m["lines"]}
    besoin: dict[str, int] = {}
    for l in d["lignes"]:
        if l.get("prix") is not None and a_acheter(l):
            besoin[l["post"]] = besoin.get(l["post"], 0) + montant_ligne(a_acheter(l), l["prix"])
    return [f"Poste {p} : {R.money(v, r['currency'])} demandé pour {R.money(dispo.get(p, 0), r['currency'])} disponible"
            for p, v in besoin.items() if v > dispo.get(p, 0)]


# ------------------------------------------------------------------ 4. coordonnateur
def valider_coordonnateur(id_: str, commentaire: str, rejeter: bool = False) -> None:
    u = V.actor(["admin", "finance", "chantier"])
    with db.transaction("Validation coordonnateur de la demande d’achat") as t:
        r = V.get(t, id_, KIND)
        d = deepcopy(r["data"])
        _exiger(u, "approbation_coordonnateur", r["project"], "Validation réservée au coordonnateur de projet.", t)
        if d["statut"] != "À valider coordonnateur":
            raise ValueError("Aucune validation coordonnateur en attente.")
        if u["id"] in (d["creator"], *_acteurs(d).values()):
            raise ValueError("Séparation des responsabilités : le coordonnateur n’a pas déjà agi sur cette demande.")
        if not (commentaire or "").strip():
            raise ValueError("Commentaire de contrôle obligatoire.")
        if rejeter:
            d.update(statut="Rejetée", validations={})
            V.event(d, u, "Rejet coordonnateur", commentaire)
            V.save(t, r, d)
            return
        d["validations"]["coordonnateur"] = dict(user=u["id"], nom=u["nom"], at=db.maintenant().isoformat(),
                                                 note=commentaire)
        V.event(d, u, "Validée coordonnateur", commentaire)
        _transmettre(t, u, r, d)


# ------------------------------------------------------------------ 5. transmission au circuit V7
def _transmettre(t, u: dict, r: dict, d: dict) -> list[str]:
    """Crée une opération « Achat » par fournisseur et par poste DQE, soumise au circuit N1 → N2 → N3 → DG."""
    demandeur = t.get("users", d["creator"])
    if not demandeur:
        raise ValueError("Demandeur introuvable.")
    groupes: dict[tuple, list[dict]] = {}
    for l in d["lignes"]:
        if a_acheter(l) and l.get("prix") is not None:
            groupes.setdefault((l["fournisseur"], l["post"]), []).append(l)
    compte = politique(t)["compte"]
    ids = []
    for k, ((party, post), lignes) in enumerate(sorted(groupes.items()), 1):
        valeur = sum(montant_ligne(a_acheter(l), l["prix"]) for l in lignes)
        detail = [dict(n=l["n"], article=l["article"], unite=l["unite"], quantite=a_acheter(l), prix=l["prix"])
                  for l in lignes]
        libelle = f"{d['objet']} — {r['ref']} ({len(lignes)} ligne{'s' if len(lignes) > 1 else ''})"
        op_id = V._create_operation_tx(t, demandeur, f"{r['ref']}-{k:02d}", r["project"], post, party, libelle[:300],
                                       "Achat", valeur, d["date_besoin"], compte, r["currency"],
                                       extra=dict(demande_achat=r["id"], demande_ref=r["ref"], lignes_da=detail))
        op = V.get(t, op_id, "operation")
        od = deepcopy(op["data"])
        od.update(status="Soumise", level=0)
        V.event(od, u, "Soumission N1 automatique", f"Demande d’achat {r['ref']} validée et chiffrée")
        V.save(t, op, od)
        ids.append(op_id)
    d["operations"] = ids
    d["statut"] = "Transmise au circuit V7"
    V.event(d, u, f"Transmise au circuit V7 : {len(ids)} opération(s) à valider N1 → DG")
    V.save(t, r, d)
    return ids


# ------------------------------------------------------------------ 6. commande groupée
def commande_groupee(operations: list[str], ref: str, date_: str) -> None:
    """Une référence de bon de commande pour plusieurs opérations approuvées d'un même fournisseur."""
    u = V.actor(["admin", "finance"])
    _exiger(u, "chiffrage_achats", None, "Commande réservée au service achats.")
    V.date(date_)
    if not operations or not (ref or "").strip():
        raise ValueError("Choisissez au moins une opération et une référence de commande.")
    with db.transaction("Commande groupée") as t:
        rows = [V.get(t, i, "operation") for i in dict.fromkeys(operations)]
        if len({r["data"]["party"] for r in rows}) != 1 or len({r["currency"] for r in rows}) != 1:
            raise ValueError("Une commande groupée porte sur un seul fournisseur et une seule devise.")
        refs = [r["ref"] for r in rows]
        for r in rows:
            V._order_tx(t, u, r["id"], ref.strip(), date_, note=f"{ref.strip()} (commande groupée : {', '.join(refs)})")


# ------------------------------------------------------------------ consultation
def demandes(u: dict | None = None) -> list[dict]:
    """Demandes visibles par l'usager (chantiers affectés ; tout pour l'administrateur et les achats)."""
    rows = V.records(KIND)
    if u is None:
        return rows
    if V.peut(u, "chiffrage_achats") or u.get("role") == "admin":
        return rows
    return [r for r in rows if auth.sur_chantier(u, r["project"])]


def execution(r: dict, ops: list[dict] | None = None) -> str:
    """Avancement des opérations V7 issues de la demande (commande, réception, facture, paiement)."""
    ids = set(r["data"].get("operations") or [])
    if not ids:
        return r["data"]["statut"]
    ops = V.records("operation") if ops is None else ops
    statuts = [o["data"]["status"] for o in ops if o["id"] in ids]
    compte = {s: statuts.count(s) for s in dict.fromkeys(statuts)}
    return " · ".join(f"{n} {s.lower()}" for s, n in compte.items())


def a_traiter(u: dict) -> dict[str, list[dict]]:
    """Demandes en attente d'une action de l'usager, par étape."""
    out = {"chantier": [], "chiffrage": [], "coordonnateur": [], "mes_brouillons": []}
    for r in demandes(u):
        d = r["data"]
        acteurs = {d["creator"], *_acteurs(d).values()}
        if d["statut"] == "Soumise" and V.peut(u, "approbation_chantier") and u["id"] != d["creator"] \
                and auth.sur_chantier(u, r["project"]):
            out["chantier"].append(r)
        elif d["statut"] == "Validée chantier" and V.peut(u, "chiffrage_achats") and u["id"] not in acteurs:
            out["chiffrage"].append(r)
        elif d["statut"] == "À valider coordonnateur" and V.peut(u, "approbation_coordonnateur") \
                and u["id"] not in acteurs and auth.sur_chantier(u, r["project"]):
            out["coordonnateur"].append(r)
        elif d["statut"] in ("Brouillon", "Rejetée") and d["creator"] == u["id"]:
            out["mes_brouillons"].append(r)
    return out
