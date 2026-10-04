"""Vue d'ensemble : l'essentiel de l'activité, selon les droits de l'usager."""
from __future__ import annotations

import streamlit as st

import auth
import nav
import regles as R
import ui
from vues import chantiers as vch


def page() -> None:
    auth.exiger("accueil")
    s = R.charger()
    ui.en_tete("Vue d’ensemble", f"{s['company'].get('name', 'MY DESTINY')} — l’essentiel de votre activité.")

    cols = st.columns(3)
    en_cours = [p for p in s["projects"] if p["status"] == "En cours"]
    with cols[0]:
        ui.carte("Chantiers en cours", str(len(en_cours)), f"{len(s['projects'])} chantier(s) au total", accent=True)
    if auth.voit("depenses"):
        with cols[1]:
            ui.carte("Dépenses enregistrées", ui.montants_html(R.totals_by_currency(s["expenses"], lambda e: e["amount"])),
                     "Tous les chantiers")
    if auth.voit("commercial"):
        with cols[2]:
            ui.carte("À encaisser", ui.montants_html(R.totals_by_currency(s["invoices"], lambda i: R.total(i) - i["paid"])),
                     "Solde par monnaie, sans conversion")

    liens = [("Enregistrer une dépense", "depenses", ":material/shopping_bag:"),
             ("Journal de caisse", "caisse", ":material/point_of_sale:"),
             ("Personnel et pointage", "personnel", ":material/badge:"),
             ("Clients et fournisseurs", "comptes-tiers", ":material/account_balance_wallet:"),
             ("Alertes et prévisions", "rapports", ":material/notifications:"),
             ("Rechercher", "recherche", ":material/search:")]
    dispo = [x for x in liens if x[1] in nav.PAGES]
    if dispo:
        st.markdown("**Actions courantes**")
        with st.container(horizontal=True, gap="medium"):
            for label, url, icone in dispo:
                nav.lien(url, label, icone)

    if auth.voit("rapports"):
        alertes = R.erp_alerts(s, R.today(), avec_rh=auth.voit("personnel"))
        if alertes:
            st.warning(f"{len(alertes)} alerte(s) à traiter : " + ", ".join(
                f"{a['reason'].lower()} ({a['label']})" for a in alertes[:4]) + ("…" if len(alertes) > 4 else ""))

    st.subheader("Suivi des chantiers")
    if s["projects"]:
        ordre = sorted(s["projects"], key=lambda p: (p["status"] != "En cours", p["deadline"] or "9999"))
        ui.tableau(vch.lignes(s, ordre[:8]), vch.COLONNES, key="acc_ch")
    else:
        st.info("Votre premier chantier commence ici : ajoutez un chantier, son client et son budget dans "
                "« Chantiers ».")
    if auth.voit("depenses"):
        st.subheader("Dernières dépenses")
        dep = sorted(s["expenses"], key=lambda e: e["date"], reverse=True)[:6]
        if dep:
            ui.tableau([{"date": e["date"], "libelle": e["label"], "cat": e["category"],
                         "chantier": R.project_name(s, e["project"]), "montant": R.money(e["amount"], e["currency"])}
                        for e in dep],
                       {"date": "Date", "libelle": "Libellé", "cat": "Catégorie", "chantier": "Chantier",
                        "montant": "Montant"}, key="acc_dep")
        else:
            st.caption("Aucune dépense enregistrée.")
