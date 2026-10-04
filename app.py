"""Bâti Gestion — MY DESTINY SARL.

Gestion d'une PME du bâtiment : chantiers, devis et factures, dépenses et justificatifs, caisse et trésorerie,
tiers, personnel et paie, dossiers achats/stocks/matériel/comptabilité. Version Python (Streamlit) du prototype
BatiGestion, avec base centrale, identifiants personnels, droits par rôle et journal d'audit.

Lancement local : streamlit run app.py
"""
from __future__ import annotations

import streamlit as st

import auth
import db
import nav
import ui

st.set_page_config(page_title="Bâti Gestion · MY DESTINY", page_icon=ui.ICONE, layout="wide",
                   initial_sidebar_state="auto")
db.moteur()
auth.assurer_admin_initial()


# ------------------------------------------------------------------ connexion
def page_connexion() -> None:
    ui.appliquer_style(connexion=True)
    _, centre, _ = st.columns([1, 1.15, 1])
    with centre:
        st.html("<div style='height:6vh'></div>")
        st.image(ui.LOGO_CLAIR, width=300)
        if auth.admin_par_defaut_actif():
            st.warning("Première installation : connectez-vous avec l'identifiant **admin** et le mot de passe "
                       "**changez-moi**, puis choisissez un mot de passe personnel.")
        with st.form("connexion"):
            ident = st.text_input("Identifiant", autocomplete="username")
            mdp = st.text_input("Mot de passe", type="password", autocomplete="current-password")
            ok = st.form_submit_button("Se connecter", type="primary", width="stretch")
        if ok:
            u, err = auth.connecter(ident, mdp)
            if err:
                st.error(err)
            else:
                auth.ouvrir_session(u)
                st.rerun()
        st.caption("Identifiant oublié ou compte bloqué : adressez-vous à la direction, qui peut "
                   "réinitialiser votre mot de passe.")


def page_changement_obligatoire() -> None:
    ui.appliquer_style(connexion=True)
    u = auth.utilisateur()
    _, centre, _ = st.columns([1, 1.15, 1])
    with centre:
        st.html("<div style='height:6vh'></div>")
        st.image(ui.LOGO_CLAIR, width=260)
        st.subheader(f"Bienvenue, {u['nom']}")
        st.write("Pour votre première connexion, choisissez un mot de passe personnel : au moins 8 caractères, "
                 "avec une lettre et un chiffre.")
        with st.form("nouveau_mdp"):
            m1 = st.text_input("Nouveau mot de passe", type="password", autocomplete="new-password")
            m2 = st.text_input("Confirmer le mot de passe", type="password", autocomplete="new-password")
            ok = st.form_submit_button("Enregistrer et continuer", type="primary", width="stretch")
        if ok:
            if m1 != m2:
                st.error("Les deux mots de passe ne sont pas identiques.")
            elif err := auth.probleme_mdp(m1):
                st.error(err)
            else:
                auth.changer_mdp(u["id"], m1)
                u["doit_changer_mdp"] = False
                auth.ouvrir_session(u)
                st.rerun()
        if st.button("Se déconnecter"):
            auth.deconnecter()
            st.rerun()


# Session conservée à l'actualisation de la page grâce au jeton signé dans l'adresse.
if auth.utilisateur() is None and (j := st.query_params.get("s")):
    if u := auth.depuis_jeton(j):
        st.session_state["utilisateur"] = u
        st.session_state["jeton"] = j
    else:
        st.query_params.clear()

utilisateur = auth.utilisateur()
if utilisateur is None:
    page_connexion()
    st.stop()
if st.session_state.get("jeton"):
    st.query_params["s"] = st.session_state["jeton"]
if utilisateur.get("doit_changer_mdp"):
    page_changement_obligatoire()
    st.stop()

ui.appliquer_style()

# ------------------------------------------------------------------ navigation
try:
    import accueil, audit, caisse, chantiers, compte, comptes_tiers, depenses  # noqa: E401,E402
    import devis_factures, dossiers, justificatifs, paie, personnel, rapports, recherche  # noqa: E401,E402
    import reprise_historique, sauvegarde, societe, tiers, utilisateurs  # noqa: E401,E402
except ModuleNotFoundError as e:
    st.error(f"Fichier introuvable : {e.name}.py. Déposez tous les fichiers .py du dossier sur GitHub, à côté de "
             "app.py, puis redémarrez l’application.")
    st.stop()
reprise = reprise_historique


def espace(cle: str):
    def _page():
        dossiers.page_espace(cle)
    _page.__name__ = f"espace_{cle}"
    return _page


def doc(kind: str):
    def _page():
        devis_factures.page(kind)
    _page.__name__ = f"doc_{kind}"
    return _page


def tresor(mode: str):
    def _page():
        caisse.page(mode)
    _page.__name__ = f"tresor_{mode}"
    return _page


# (section, titre, url, icône, module(s) requis, fonction)
PAGES = [
    ("Accueil", "Vue d’ensemble", "vue-ensemble", "dashboard", ["accueil"], accueil.page),
    ("Accueil", "Recherche globale", "recherche", "search", ["recherche"], recherche.page),
    ("Accueil", "Rapports et alertes", "rapports", "notifications", ["rapports"], rapports.page),
    ("Commercial", "Devis", "devis", "request_quote", ["commercial"], doc("quotes")),
    ("Commercial", "Factures", "factures", "receipt_long", ["commercial"], doc("invoices")),
    ("Commercial", "Prospects et contrats", "commercial", "handshake", ["commercial"], espace("commercial")),
    ("Projets & Chantiers", "Chantiers", "chantiers", "construction", ["chantiers"], chantiers.page),
    ("Projets & Chantiers", "DQE, situations, qualité", "dossiers-chantier", "fact_check", ["projets"],
     espace("projets")),
    ("Achats & Stocks", "Achats", "achats", "shopping_cart", ["achats"], espace("achats")),
    ("Achats & Stocks", "Stocks", "stocks", "inventory_2", ["achats"], espace("stocks")),
    ("Achats & Stocks", "Matériel et charroi", "charroi", "local_shipping", ["charroi"], espace("charroi")),
    ("RH & Paie", "Personnel et pointage", "personnel", "badge", ["personnel", "pointage"], personnel.page),
    ("RH & Paie", "Paie", "paie", "payments", ["paie"], paie.page),
    ("RH & Paie", "Congés, missions, avances", "dossiers-rh", "event_available", ["personnel"], espace("rh")),
    ("Finance", "Dépenses", "depenses", "shopping_bag", ["depenses"], depenses.page),
    ("Finance", "Justificatifs", "justificatifs", "attach_file", ["justificatifs"], justificatifs.page),
    ("Finance", "Journal de caisse", "caisse", "point_of_sale", ["tresorerie"], tresor("cash")),
    ("Finance", "Trésorerie", "tresorerie", "account_balance", ["tresorerie"], tresor("treasury")),
    ("Tiers", "Clients et fournisseurs", "tiers", "contacts", ["tiers"], tiers.page),
    ("Tiers", "Comptes tiers", "comptes-tiers", "account_balance_wallet", ["comptes"], comptes_tiers.page),
    ("Comptabilité & Documents", "Comptabilité et fiscalité", "comptabilite", "calculate", ["comptabilite"],
     espace("comptabilite")),
    ("Comptabilité & Documents", "Registres, garanties, tâches", "documents", "folder_open", ["documents"],
     espace("administration")),
    ("Comptabilité & Documents", "Reprise historique", "reprise", "history", ["reprise"], reprise.page),
    ("Administration", "Société MY DESTINY", "societe", "apartment", ["societe"], societe.page),
    ("Administration", "Utilisateurs", "utilisateurs", "group", ["utilisateurs"], utilisateurs.page),
    ("Administration", "Paramètres et sauvegarde", "sauvegarde", "settings", ["sauvegarde"], sauvegarde.page),
    ("Administration", "Journal d’audit", "audit", "manage_search", ["audit"], audit.page),
    ("Administration", "Mon compte", "mon-compte", "person", [], compte.page),
]

sections: dict[str, list] = {}
nav.PAGES.clear()
for section, titre, url, icone, modules, fn in PAGES:
    if modules and not any(auth.voit(m) for m in modules):
        continue
    pg = st.Page(fn, title=titre, url_path=url, icon=f":material/{icone}:", default=(url == "vue-ensemble"))
    nav.PAGES[url] = pg
    sections.setdefault(section, []).append(pg)

st.logo(ui.LOGO_SOMBRE, size="large", icon_image=ui.ICONE)
with st.sidebar:
    st.caption(f"Connecté : **{utilisateur['nom']}**  \n{auth.ROLES.get(utilisateur['role'], utilisateur['role'])}")
    if st.button("Se déconnecter", icon=":material/logout:", width="stretch"):
        auth.deconnecter()
        st.rerun()

st.navigation(sections, position="sidebar", expanded=True).run()
