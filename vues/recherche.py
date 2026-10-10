"""Recherche globale dans les données auxquelles l'usager a accès."""
from __future__ import annotations

import streamlit as st

import auth
import regles as R
import ui

ACCES = {"projects": "chantiers", "clients": "tiers", "quotes": "commercial", "invoices": "commercial",
         "expenses": "depenses", "personnel": "personnel", "supplier_invoices": "comptes", "movements": "tresorerie"}


def page() -> None:
    auth.exiger("recherche")
    ui.en_tete("Recherche globale", "Retrouvez vos informations sans parcourir les rubriques.")
    q = st.text_input("Chantier, tiers, référence, facture, paiement ou employé", max_chars=200,
                      placeholder="Ex. : nom du chantier, nom d’un client, FAC-2026-0001")
    if not q.strip():
        st.caption("Saisissez un nom ou une référence. Les accents et majuscules sont ignorés.")
        return
    s = R.charger()
    collections = {c for c, m in ACCES.items() if auth.voit(m)}
    s["erp_dossiers"] = [d for d in s["erp_dossiers"]
                         if auth.voit(R.DOSSIER_MODULE[R.ERP_DOSSIERS.get(d["type"], {}).get("group", "Administration")])]
    collections.add("erp_dossiers")
    res = R.erp_search(s, q, collections)
    st.subheader(f"{len(res)} résultat(s)")
    if not res:
        st.info("Aucun résultat. Essayez un nom ou une référence plus courte.")
        return
    ui.tableau([{"t": r["kind"], "l": r["label"], "c": r["context"]} for r in res[:200]],
               {"t": "Type", "l": "Référence / nom", "c": "Contexte"}, key="tab_rech")
    if len(res) > 200:
        st.caption("Les 200 premiers résultats sont affichés. Précisez votre recherche.")
