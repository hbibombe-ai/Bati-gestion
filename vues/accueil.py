"""Vue d'ensemble : l'essentiel de l'activité, selon les droits de l'usager."""
from __future__ import annotations

import streamlit as st

import auth
import gestion_v7 as V
import nav
import regles as R
import ui
from vues import chantiers as vch


def carte_tresorerie() -> None:
    """Soldes de toutes les caisses, banques et Mobile money, chacun dans sa devise ; alerte si une caisse est négative
    ou si la trésorerie de l'application ne concorde pas avec la comptabilité."""
    import caisses as CA
    liste = [c for c in CA.caisses() if c["nb"] or c["cle"].startswith("v7:")]
    if not liste:
        return
    rouge = ' style="color:#b42318"'
    lignes = "<br>".join(
        f'{ui._esc(c["libelle"])} : <b{rouge if c["negatif"] else ""}>'
        f'{ui._esc(R.money(c["solde"], c["devise"]))}</b>' for c in liste)
    alertes = []
    if any(c["negatif"] for c in liste):
        alertes.append("caisse négative")
    if auth.voit("comptabilite"):
        try:
            import comptabilisation as CPT
            if any(x["ecart"] for x in CPT.controle_tresorerie()):
                alertes.append("écart avec la comptabilité")
        except Exception:  # noqa: BLE001 — l'accueil ne doit jamais tomber pour un contrôle
            pass
    attente = sum(1 for a in CA.arretes() if a["statut"] == "Proposé")
    if attente:
        alertes.append(f"{attente} arrêté(s) de caisse à valider")
    ui.carte("Trésorerie disponible", f'<div class="bg-montants" style="font-size:1rem;font-weight:500;'
                                      f'letter-spacing:0">{lignes}</div>',
             ("À vérifier : " + ", ".join(alertes)) if alertes else "Soldes du jour, chacun dans sa devise",
             accent=bool(alertes))
    if alertes and "caisse" in nav.PAGES:
        nav.lien("caisse", "Ouvrir le journal de caisse", ":material/point_of_sale:")


def page() -> None:
    auth.exiger("accueil")
    s = R.charger()
    en_cours = [p for p in s["projects"] if p["status"] == "En cours"]
    ui.en_tete("Vue d’ensemble", f"{(s['company'].get('name') or 'Bâti Gestion')} — l’essentiel de votre activité.",
               badge=f"{len(en_cours)} chantier{'s' if len(en_cours) > 1 else ''} en cours")

    cols = st.columns(3)
    with cols[0]:
        ui.carte("Chantiers en cours", str(len(en_cours)), f"{len(s['projects'])} chantier(s) au total", accent=True)
    if auth.voit("depenses"):
        with cols[1]:
            ui.carte("Dépenses historiques", ui.montants_html(R.totals_by_currency(s["expenses"], lambda e: e["amount"])),
                     "Tous les chantiers")
    if auth.voit("commercial"):
        with cols[2]:
            ui.carte("À encaisser", ui.montants_html(R.totals_by_currency(s["invoices"], lambda i: R.total(i) - i["paid"])),
                     "Solde par monnaie ; total converti indicatif")

    if auth.voit("tresorerie"):
        carte_tresorerie()

    if auth.modifie("tresorerie") or auth.modifie("comptabilite"):
        import devises as DV
        manquants = [e["paire"] for e in DV.etat_du_jour() if not e["du_jour"]]
        if manquants:
            st.info(f"Taux du jour non saisi : {', '.join(manquants)}. Les totaux consolidés utilisent le dernier taux connu.")
            nav.lien("taux", "Saisir les taux du jour", ":material/currency_exchange:")
    if auth.voit("depenses"):
        v7 = V.alerts()
        if v7:st.warning(f"{len(v7)} alerte(s) du circuit V7 à traiter.")
    liens = [("Circuit financier V7", "circuit-v7", ":material/account_tree:"), ("Enregistrer une dépense", "depenses", ":material/shopping_bag:"),
             ("Journal de caisse", "caisse", ":material/point_of_sale:"),
             ("Personnel et pointage", "personnel", ":material/badge:"),
             ("Clients et fournisseurs", "comptes-tiers", ":material/account_balance_wallet:"),
             ("Alertes et prévisions", "rapports", ":material/notifications:"),
             ("Rechercher", "recherche", ":material/search:")]
    dispo = [x for x in liens if x[1] in nav.PAGES]
    if dispo:
        st.markdown("**Actions courantes**")
        with st.container(horizontal=True, gap="medium", key="bg_actions"):
            for label, url, icone in dispo:
                nav.lien(url, label, icone)

    if auth.voit("rapports"):
        alertes = R.erp_alerts(s, R.today(), avec_rh=auth.voit("personnel"))
        if alertes:
            st.warning(f"{len(alertes)} alerte(s) à traiter : " + ", ".join(
                f"{a['reason'].lower()} ({a['label']})" for a in alertes[:4]) + ("…" if len(alertes) > 4 else ""))

    st.subheader("Suivi des chantiers")
    if s["projects"]:
        vch.carte(s, s["projects"], hauteur=360)
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
