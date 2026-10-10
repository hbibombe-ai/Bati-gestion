"""Comptes des usagers : identifiants, rôles, désactivation, réinitialisation des mots de passe."""
from __future__ import annotations

import re

import streamlit as st

import auth
import db
import ui


def _identifiants(identifiant: str, mdp: str, nom: str) -> None:
    st.success(f"Identifiants de **{nom}** — à lui transmettre personnellement :")
    st.code(f"Adresse : (lien de l'application)\nIdentifiant : {identifiant}\nMot de passe provisoire : {mdp}",
            language=None)
    st.caption("Ce mot de passe ne sera plus affiché. L'usager devra en choisir un nouveau à sa première connexion.")


def page() -> None:
    auth.exiger("utilisateurs")
    ui.en_tete("Utilisateurs", "Créer les identifiants et attribuer les rôles.")
    if info := st.session_state.pop("identifiants_crees", None):
        _identifiants(*info)
    with st.expander("Nouvel utilisateur", icon=":material/person_add:"):
        with st.form("nouvel_utilisateur", clear_on_submit=True):
            a, b = st.columns(2)
            nom = a.text_input("Nom complet *")
            ident = b.text_input("Identifiant de connexion *", placeholder="ex. j.mukendi",
                                 help="Lettres minuscules, chiffres, point, tiret ou soulignement.")
            tel = a.text_input("Téléphone")
            role = b.selectbox("Rôle", list(auth.ROLES), format_func=auth.ROLES.get, index=3)
            ok = st.form_submit_button("Créer le compte", type="primary")
        st.markdown("\n".join(f"- **{auth.ROLES[r]}** : {d}" for r, d in auth.DESCRIPTION_ROLES.items()))
        if ok:
            ident_n = ident.strip().lower()
            if not nom.strip() or not ident_n:
                st.error("Le nom et l'identifiant sont obligatoires.")
            elif not re.fullmatch(r"[a-z0-9._-]{3,50}", ident_n):
                st.error("Identifiant invalide : 3 à 50 caractères, lettres minuscules, chiffres, . _ ou -.")
            elif db.requete("select id from users where identifiant = :i", i=ident_n):
                st.error("Cet identifiant existe déjà.")
            else:
                mdp = auth.creer_utilisateur(ident_n, nom, role, tel)
                st.session_state["identifiants_crees"] = (ident_n, mdp, nom.strip())
                st.rerun()

    us = sorted(db.tout("users", sans=("mdp_hash",)), key=lambda u: (not u["actif"], u["nom"].lower()))
    rows = [{"_id": u["id"], "nom": u["nom"], "id": u["identifiant"], "role": auth.ROLES.get(u["role"], u["role"]),
             "tel": u["telephone"], "actif": bool(u["actif"]), "der": u["derniere_connexion"]} for u in us]
    i = ui.tableau(rows, {"nom": "Nom", "id": "Identifiant", "role": "Rôle", "tel": "Téléphone",
                          "actif": st.column_config.CheckboxColumn("Actif"),
                          "der": st.column_config.DatetimeColumn("Dernière connexion", format="DD/MM/YYYY HH:mm")},
                   key="tab_users", selection=True)
    if i is None:
        st.caption("Sélectionnez un compte pour le modifier, le désactiver ou réinitialiser son mot de passe.")
        return
    u = next(x for x in us if x["id"] == rows[i]["_id"])
    moi = auth.utilisateur()["id"]
    st.subheader(f"{u['nom']} ({u['identifiant']})")
    with st.form(f"modif_{u['id']}"):
        a, b = st.columns(2)
        nom = a.text_input("Nom complet", value=u["nom"])
        tel = b.text_input("Téléphone", value=u["telephone"] or "")
        roles = list(auth.ROLES)
        role = a.selectbox("Rôle", roles, index=roles.index(u["role"]), format_func=auth.ROLES.get, disabled=u["id"] == moi)
        actif = b.toggle("Compte actif", value=bool(u["actif"]), disabled=u["id"] == moi,
                         help="Un compte désactivé ne peut plus se connecter ; son historique est conservé.")
        ok = st.form_submit_button("Enregistrer les modifications", type="primary")
    if ok:
        vals = {"nom": nom.strip() or u["nom"], "telephone": tel.strip()}
        if u["id"] != moi:
            vals.update(role=role, actif=actif)
            if role != u["role"] or not actif:
                vals["version_session"] = int(u["version_session"] or 0) + 1  # ferme ses sessions ouvertes
        with db.transaction(f"Modification du compte {u['identifiant']}") as t:
            t.maj("users", u["id"], vals)
        ui.succes("Compte mis à jour.")
    if st.button("Réinitialiser le mot de passe", icon=":material/lock_reset:", disabled=u["id"] == moi,
                 help="Pour votre propre compte, utilisez « Mon compte »."):
        mdp = auth.reinitialiser_mdp(u["id"])
        st.session_state["identifiants_crees"] = (u["identifiant"], mdp, u["nom"])
        st.rerun()
