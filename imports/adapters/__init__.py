"""Adaptateurs métier : un adaptateur par fonction, qui convertit les lignes et appelle les services existants.

Chaque adaptateur fournit :
- verifier(ds, ctx, etat, res, rep) : contrôles métier et ajout des actions au plan (aucune écriture) ;
- executer(t, ctx, action, res) : exécution d'une action dans la transaction globale du lot.
L'ordre d'ADAPTATEURS est l'ordre d'import : référentiels, chantiers, budgets, dossiers, reliquats,
trésorerie et comptabilité, pointages, pièces.
"""
from __future__ import annotations

from imports.adapters import budgets, documents, referentiels, reliquats, tresorerie

ADAPTATEURS = {
    "tiers": referentiels.TIERS,
    "chantiers": referentiels.CHANTIERS,
    "personnel": referentiels.PERSONNEL,
    "affectations": referentiels.AFFECTATIONS,
    "budgets": budgets.BUDGETS,
    "cumuls": budgets.CUMULS,
    "besoins": budgets.BESOINS,
    "fournisseurs": reliquats.FOURNISSEURS,
    "tresorerie": tresorerie.COMPTES,
    "comptabilite": tresorerie.ECRITURES,
    "presences": referentiels.PRESENCES,
    "documents": documents.DOCUMENTS,
}


def executer(t, ctx, action, res):
    return ADAPTATEURS[action["adaptateur"]]["executer"](t, ctx, action, res)
