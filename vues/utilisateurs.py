"""Comptes des usagers : identifiants, modèle de rôle, accès rubrique par rubrique, désactivation, mots de passe."""
from __future__ import annotations

import re

import streamlit as st

import auth
import db
import ui

NIVEAUX = ["Aucun", "Consultation", "Modification"]
CODE_NIVEAU = {"Aucun": None, "Consultation": "r", "Modification": "w"}
INDEX_NIVEAU = {None: 0, "r": 1, "w": 2}


def _identifiants(identifiant: str, mdp: str, nom: str) -> None:
    st.success(f"Identifiants de **{nom}** — à lui transmettre personnellement :")
    st.code(f"Adresse : (lien de l'application)\nIdentifiant : {identifiant}\nMot de passe provisoire : {mdp}",
            language=None)
    st.caption("Ce mot de passe ne sera plus affiché. L'usager devra en choisir un nouveau à sa première connexion.")


def _matrice(prefixe: str, role: str, actuels: dict | None, desactive: bool = False) -> dict:
    """Une ligne par rubrique : Aucun, Consultation ou Modification. Renvoie {rubrique: 'w' | 'r' | None}."""
    if role == "admin":
        st.info("La direction générale garde tous les accès ; ce réglage ne s’applique pas.")
        return {m: "w" for m in auth.MODULES}
    base = actuels if actuels is not None else {m: auth.DROITS.get(role, {}).get(m) for m in auth.MODULES}
    out = {}
    for m in auth.MODULES:
        a, b = st.columns([3, 4])
        a.markdown(auth.MODULE_LABELS.get(m, m))
        approbation = m.startswith("approbation_")  # une approbation s'accorde ou se retire, sans simple consultation
        options = ["Aucun", "Modification"] if approbation else NIVEAUX
        niveau = base.get(m) if not (approbation and base.get(m) == "r") else None
        choix = b.radio(auth.MODULE_LABELS.get(m, m), options, index=options.index(
                        {None: "Aucun", "r": "Consultation", "w": "Modification"}[niveau]),
                        horizontal=True, key=f"{prefixe}_{role}_{m}", label_visibility="collapsed", disabled=desactive)
        out[m] = CODE_NIVEAU[choix]
    return out


def _enregistrer_droits(t, uid: int, identifiant: str, role: str, droits: dict) -> None:
    """Ne garde que les écarts avec le modèle du rôle ; sans écart, le compte revient au modèle."""
    cle = f"droits_utilisateur:{uid}"
    modele = auth.DROITS.get(role, {})
    ecart = {m: (v or "x") for m, v in droits.items() if v != modele.get(m)} or None
    if (db.parametre(cle) or None) == ecart:
        return
    t.parametre(cle, ecart, resume=f"Accès aux rubriques de {identifiant}")


def page() -> None:
    auth.exiger("utilisateurs")
    ui.en_tete("Utilisateurs", "Créer les comptes, choisir le modèle de départ puis régler les accès rubrique par rubrique.")
    if info := st.session_state.pop("identifiants_crees", None):
        _identifiants(*info)
    with st.expander("Nouvel utilisateur", icon=":material/person_add:"):
        role = st.selectbox("Modèle de départ (rôle)", list(auth.ROLES), format_func=auth.ROLES.get, index=3,
                            key="nu_role", help="Pré-remplit les accès ci-dessous ; vous pouvez ensuite les modifier.")
        st.markdown("\n".join(f"- **{auth.ROLES[r]}** : {d}" for r, d in auth.DESCRIPTION_ROLES.items()))
        with st.form("nouvel_utilisateur", clear_on_submit=True):
            a, b = st.columns(2)
            nom = a.text_input("Nom complet *")
            ident = b.text_input("Identifiant de connexion *", placeholder="ex. j.mukendi",
                                 help="Lettres minuscules, chiffres, point, tiret ou soulignement.")
            tel = a.text_input("Téléphone")
            st.markdown("**Accès aux rubriques**")
            droits_nouveaux = _matrice("nu", role, None)
            ok = st.form_submit_button("Créer le compte", type="primary")
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
                uid = db.requete("select id from users where identifiant = :i", i=ident_n)[0]["id"]
                if role != "admin":
                    with db.transaction(f"Accès initiaux de {ident_n}") as t:
                        _enregistrer_droits(t, uid, ident_n, role, droits_nouveaux)
                st.session_state["identifiants_crees"] = (ident_n, mdp, nom.strip())
                st.rerun()

    us = sorted(db.tout("users", sans=("mdp_hash",)), key=lambda u: (not u["actif"], u["nom"].lower()))
    rows = [{"_id": u["id"], "nom": u["nom"], "id": u["identifiant"], "role": auth.ROLES.get(u["role"], u["role"]),
             "acces": "Personnalisés" if auth.personnalise(u["id"]) else "Modèle du rôle",
             "tel": u["telephone"], "actif": bool(u["actif"]), "der": u["derniere_connexion"]} for u in us]
    i = ui.tableau(rows, {"nom": "Nom", "id": "Identifiant", "role": "Modèle de départ", "acces": "Accès",
                          "tel": "Téléphone", "actif": st.column_config.CheckboxColumn("Actif"),
                          "der": st.column_config.DatetimeColumn("Dernière connexion", format="DD/MM/YYYY HH:mm")},
                   key="tab_users", selection=True)
    if i is None:
        st.caption("Sélectionnez un compte pour modifier ses accès, le désactiver ou réinitialiser son mot de passe.")
        return
    u = next(x for x in us if x["id"] == rows[i]["_id"])
    moi = auth.utilisateur()["id"]
    st.subheader(f"{u['nom']} ({u['identifiant']})")
    roles = list(auth.ROLES)
    role_m = st.selectbox("Modèle de départ (rôle)", roles, index=roles.index(u["role"]), format_func=auth.ROLES.get,
                          disabled=u["id"] == moi, key=f"mod_role_{u['id']}",
                          help="Changer le rôle remet les accès au modèle de ce rôle ; vous pouvez ensuite les ajuster.")
    anciens = auth.droits_de(u["id"], u["role"])
    with st.form(f"modif_{u['id']}"):
        a, b = st.columns(2)
        nom = a.text_input("Nom complet", value=u["nom"])
        tel = b.text_input("Téléphone", value=u["telephone"] or "")
        actif = b.toggle("Compte actif", value=bool(u["actif"]), disabled=u["id"] == moi,
                         help="Un compte désactivé ne peut plus se connecter ; son historique est conservé.")
        st.markdown("**Accès aux rubriques**" + ("" if auth.personnalise(u["id"]) or role_m != u["role"]
                                                 else " — modèle du rôle, non modifié"))
        actuels = anciens if role_m == u["role"] else None
        droits = _matrice(f"mod{u['id']}", role_m, actuels, desactive=u["id"] == moi)
        ok = st.form_submit_button("Enregistrer les modifications", type="primary")
    if ok:
        vals = {"nom": nom.strip() or u["nom"], "telephone": tel.strip()}
        novelles = None
        if u["id"] != moi:
            vals.update(role=role_m, actif=actif)
            if role_m != "admin":
                novelles = droits
        bascule = u["id"] != moi and (role_m != u["role"] or not actif
                                      or (novelles is not None and novelles != anciens))
        with db.transaction(f"Modification du compte {u['identifiant']}") as t:
            if bascule:  # ferme les sessions ouvertes : les nouveaux accès s'appliquent tout de suite
                vals["version_session"] = int(u["version_session"] or 0) + 1
            t.maj("users", u["id"], vals)
            if novelles is not None:
                _enregistrer_droits(t, u["id"], u["identifiant"], role_m, novelles)
        ui.succes("Compte mis à jour.")
        st.rerun()
    if auth.personnalise(u["id"]) and u["id"] != moi:
        if st.button("Revenir au modèle du rôle", icon=":material/restart_alt:",
                     help="Supprime les accès personnalisés : le compte reprend les accès de son rôle."):
            with db.transaction(f"Retour au modèle du rôle pour {u['identifiant']}") as t:
                t.parametre(f"droits_utilisateur:{u['id']}", None, resume=f"Retour au modèle du rôle : {u['identifiant']}")
                t.maj("users", u["id"], {"version_session": int(u["version_session"] or 0) + 1})
            st.rerun()
    if st.button("Réinitialiser le mot de passe", icon=":material/lock_reset:", disabled=u["id"] == moi,
                 help="Pour votre propre compte, utilisez « Mon compte »."):
        mdp = auth.reinitialiser_mdp(u["id"])
        st.session_state["identifiants_crees"] = (u["identifiant"], mdp, u["nom"])
        st.rerun()
