"""Mon compte : changement du mot de passe."""
from __future__ import annotations

import streamlit as st

import auth
import ui


def page() -> None:
    u = auth.utilisateur()
    ui.en_tete("Mon compte", f"{u['nom']} · {auth.ROLES.get(u['role'], u['role'])}")
    with st.form("mdp", clear_on_submit=True):
        actuel = st.text_input("Mot de passe actuel", type="password", autocomplete="current-password")
        m1 = st.text_input("Nouveau mot de passe", type="password", autocomplete="new-password")
        m2 = st.text_input("Confirmer le nouveau mot de passe", type="password", autocomplete="new-password")
        ok = st.form_submit_button("Changer le mot de passe", type="primary")
    if ok:
        if not auth.mdp_correct(u["id"], actuel):
            st.error("Mot de passe actuel incorrect.")
        elif m1 != m2:
            st.error("Les deux nouveaux mots de passe ne sont pas identiques.")
        elif err := auth.probleme_mdp(m1):
            st.error(err)
        else:
            auth.changer_mdp(u["id"], m1)
            st.success("Mot de passe changé.")
    st.caption("Votre session reste ouverte 12 heures sur cet appareil. « Se déconnecter » la ferme sur tous vos appareils.")
