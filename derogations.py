"""Dérogations nominatives à la séparation des fonctions (mémo V8, § 10.2).

Pour une petite équipe, la DG peut autoriser une personne à cumuler deux fonctions normalement séparées, pour
une règle précise, une période datée et un motif écrit. Chaque dérogation est inscrite au journal d'audit
(paramètre « derogations ») et listée dans l'état des dérogations ; elle ne s'applique qu'aux contrôles qui la
consultent explicitement.
"""
from __future__ import annotations

import sqlalchemy as sa

import db
import gestion_v7 as V
import regles as R

REGLES = {
    "validateur_distinct": "Valider une demande d’achat qu’on a créée ou déjà validée à un autre niveau",
    "receptionnaire_demandeur": "Réceptionner une marchandise qu’on a demandée",
    "acheteur_facture": "Valider la facture d’une commande qu’on a émise",
    "saisie_validation_facture": "Valider une facture d’achat qu’on a saisie",
    "tresorier_distinct": "Payer une facture d’achat qu’on a demandée, validée ou dont on a validé la demande",
    "compteur_ecarts": "Valider les écarts d’un inventaire qu’on a compté",
    "arrete_caisse": "Valider un arrêté de caisse qu’on a compté",
}


def _toutes(tx=None) -> list[dict]:
    if tx is not None:
        v = tx.cx.execute(sa.select(db.settings.c.valeur).where(db.settings.c.cle == "derogations")).scalar()
    else:
        v = db.parametre("derogations")
    return list(v) if isinstance(v, list) else []


def accorder(user_id: int, regle: str, debut: str, fin: str, motif: str) -> str:
    u = V.actor()
    V._exiger(u, "approbation_dg", "Dérogation réservée à la DG.")
    V.date(debut)
    V.date(fin)
    if regle not in REGLES:
        raise ValueError("Règle de séparation inconnue.")
    if debut > fin or not (motif or "").strip():
        raise ValueError("Période cohérente et motif obligatoires.")
    cible = db.un("users", user_id)
    if not cible or not cible["actif"]:
        raise ValueError("Utilisateur introuvable ou inactif.")
    if cible["id"] == u["id"]:
        raise ValueError("La DG ne s’accorde pas une dérogation à elle-même.")
    id_ = db.nouvel_id()
    with db.transaction(f"Dérogation {regle} pour {cible['identifiant']}") as t:
        liste = _toutes(t) + [dict(id=id_, user=user_id, nom=cible["nom"], regle=regle, debut=debut, fin=fin,
                                   motif=motif.strip(), accordee_par=u["id"], accordee_nom=u["nom"],
                                   accordee_le=db.maintenant().isoformat(), revoquee=False)]
        t.parametre("derogations", liste, resume=f"Dérogation « {REGLES[regle]} » à {cible['nom']} du {debut} au {fin}")
    return id_


def revoquer(id_: str, motif: str) -> None:
    u = V.actor()
    V._exiger(u, "approbation_dg", "Révocation réservée à la DG.")
    if not (motif or "").strip():
        raise ValueError("Motif obligatoire.")
    with db.transaction("Révocation de dérogation") as t:
        liste = _toutes(t)
        d = next((x for x in liste if x["id"] == id_), None)
        if not d or d.get("revoquee"):
            raise ValueError("Dérogation introuvable ou déjà révoquée.")
        d.update(revoquee=True, revoquee_par=u["id"], revoquee_le=db.maintenant().isoformat(), motif_revocation=motif)
        t.parametre("derogations", liste, resume=f"Révocation de la dérogation {d['regle']} de {d['nom']}")


def active(user_id: int, regle: str, date_: str | None = None, tx=None) -> bool:
    date_ = date_ or R.today()
    return any(d["user"] == user_id and d["regle"] == regle and not d.get("revoquee")
               and d["debut"] <= date_ <= d["fin"] for d in _toutes(tx))


def exiger_distinct(tx, user_id: int, autres: set, regle: str, message: str, date_: str | None = None) -> None:
    """Refuse si l'usager figure parmi « autres », sauf dérogation nominative active pour cette règle."""
    if user_id in {x for x in autres if x is not None} and not active(user_id, regle, date_, tx):
        raise ValueError(f"Séparation des fonctions : {message} (dérogation DG possible : « {REGLES[regle]} »).")


def etat() -> list[dict]:
    return sorted(_toutes(), key=lambda d: d["accordee_le"], reverse=True)
