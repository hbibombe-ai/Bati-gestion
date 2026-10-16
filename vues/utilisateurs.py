"""Comptes des usagers : identifiants, poste (modèle de départ), chantiers affectés, accès rubrique par rubrique,
désactivation, mots de passe ; postes standards et profils personnalisés.

Le poste pré-remplit les accès ; les accès réglés pour une personne restent prioritaires sur le modèle."""
from __future__ import annotations

import re

import streamlit as st

import auth
import db
import ui

NIVEAUX = ["Aucun", "Consultation", "Modification"]
CODE_NIVEAU = {"Aucun": None, "Consultation": "r", "Modification": "w"}
INDEX_NIVEAU = {None: 0, "r": 1, "w": 2}
SANS_POSTE = ""


def _identifiants(identifiant: str, mdp: str, nom: str) -> None:
    st.success(f"Identifiants de **{nom}** — à lui transmettre personnellement :")
    st.code(f"Adresse : (lien de l'application)\nIdentifiant : {identifiant}\nMot de passe provisoire : {mdp}",
            language=None)
    st.caption("Ce mot de passe ne sera plus affiché. L'usager devra en choisir un nouveau à sa première connexion.")


def _matrice(prefixe: str, role: str, actuels: dict | None, desactive: bool = False, poste: str | None = None) -> dict:
    """Une ligne par rubrique : Aucun, Consultation ou Modification. Renvoie {rubrique: 'w' | 'r' | None}."""
    if role == "admin":
        st.info("La direction générale garde tous les accès ; ce réglage ne s’applique pas.")
        return {m: "w" for m in auth.MODULES}
    modele = auth.modele_droits(role, poste)
    base = actuels if actuels is not None else {m: modele.get(m) for m in auth.MODULES}
    out = {}
    for m in auth.MODULES:
        a, b = st.columns([3, 4])
        a.markdown(auth.MODULE_LABELS.get(m, m))
        approbation = m.startswith("approbation_")  # une approbation s'accorde ou se retire, sans simple consultation
        options = ["Aucun", "Modification"] if approbation else NIVEAUX
        niveau = base.get(m) if not (approbation and base.get(m) == "r") else None
        choix = b.radio(auth.MODULE_LABELS.get(m, m), options, index=options.index(
                        {None: "Aucun", "r": "Consultation", "w": "Modification"}[niveau]),
                        horizontal=True, key=f"{prefixe}_{role}_{poste or 'role'}_{m}", label_visibility="collapsed",
                        disabled=desactive)
        out[m] = CODE_NIVEAU[choix]
    return out


def _enregistrer_droits(t, uid: int, identifiant: str, role: str, droits: dict, poste: str | None = None) -> None:
    """Ne garde que les écarts avec le modèle du poste (ou du rôle) ; sans écart, le compte revient au modèle."""
    cle = f"droits_utilisateur:{uid}"
    modele = auth.modele_droits(role, poste)
    ecart = {m: (v or "x") for m, v in droits.items() if v != modele.get(m)} or None
    if (db.parametre(cle) or None) == ecart:
        return
    t.parametre(cle, ecart, resume=f"Accès aux rubriques de {identifiant}")


def _avertir_incompatibilites(droits: dict, role: str) -> None:
    if role != "admin" and (conflits := auth.incompatibilites(droits)):
        st.warning("Séparation des tâches : " + " ; ".join(conflits) + ". Le réglage reste possible pour cette "
                   "personne ; les contrôles du circuit empêchent quand même qu’elle agisse deux fois sur la même demande.")


def _roles_permis() -> list[str]:
    """Seule la direction générale crée ou modifie un compte administrateur."""
    return list(auth.ROLES) if auth.est_admin() else [r for r in auth.ROLES if r != "admin"]


def _choix_poste(role: str, key: str, courant: str | None = None) -> str:
    postes = {k: p for k, p in auth.profils(actifs_seulement=True).items() if p["role"] == role}
    options = [SANS_POSTE] + list(postes)
    if courant not in options:
        courant = SANS_POSTE
    choix = st.selectbox("Poste (modèle de départ des accès)", options, index=options.index(courant), key=key,
                         format_func=lambda k: f"Aucun — modèle « {auth.ROLES[role]} »" if k == SANS_POSTE
                         else postes[k]["libelle"] + ("" if postes[k]["standard"] else " (profil personnalisé)"),
                         help="Pré-remplit les accès ci-dessous ; vous pouvez ensuite les ajuster pour cette personne.")
    if choix and postes[choix].get("description"):
        st.caption(postes[choix]["description"])
    return choix


def _choix_projets(key: str, courant: list[str] | None, desactive: bool = False) -> list[str]:
    projets = db.tout("projects")
    noms = {p["id"]: p["name"] for p in projets}
    return st.multiselect("Chantiers affectés (vide = tous les chantiers)", list(noms),
                          default=[p for p in (courant or []) if p in noms], format_func=noms.get, key=key,
                          disabled=desactive,
                          help="Limite les demandes d’achat que la personne crée, valide ou voit à ces chantiers.")


# ------------------------------------------------------------------ comptes
def _nouveau_compte() -> None:
    with st.expander("Nouvel utilisateur", icon=":material/person_add:"):
        roles = _roles_permis()
        a, b = st.columns(2)
        with a:
            role = st.selectbox("Famille de rôle", roles, format_func=auth.ROLES.get,
                                index=roles.index("chantier"), key="nu_role",
                                help="Fixe ce que les services autorisent (circuit V7, imports…).")
        with b:
            poste = _choix_poste(role, "nu_poste")
        st.markdown("\n".join(f"- **{auth.ROLES[r]}** : {d}" for r, d in auth.DESCRIPTION_ROLES.items() if r in roles))
        with st.form("nouvel_utilisateur", clear_on_submit=True):
            a, b = st.columns(2)
            nom = a.text_input("Nom complet *")
            ident = b.text_input("Identifiant de connexion *", placeholder="ex. j.mukendi",
                                 help="Lettres minuscules, chiffres, point, tiret ou soulignement.")
            tel = a.text_input("Téléphone")
            projets = _choix_projets("nu_projets", None, desactive=role == "admin")
            st.markdown("**Accès aux rubriques**")
            droits_nouveaux = _matrice("nu", role, None, poste=poste or None)
            ok = st.form_submit_button("Créer le compte", type="primary")
        if ok:
            ident_n = ident.strip().lower()
            if not nom.strip() or not ident_n:
                st.error("Le nom et l'identifiant sont obligatoires.")
            elif not re.fullmatch(r"[a-z0-9._-]{3,50}", ident_n):
                st.error("Identifiant invalide : 3 à 50 caractères, lettres minuscules, chiffres, . _ ou -.")
            elif db.requete("select id from users where identifiant = :i", i=ident_n):
                st.error("Cet identifiant existe déjà.")
            elif role not in roles:
                st.error("Seule la direction générale crée un compte administrateur.")
            else:
                mdp = auth.creer_utilisateur(ident_n, nom, role, tel)
                uid = db.requete("select id from users where identifiant = :i", i=ident_n)[0]["id"]
                try:
                    with db.transaction(f"Accès initiaux de {ident_n}") as t:
                        auth.enregistrer_affectation(t, uid, ident_n, role, poste or None,
                                                     None if role == "admin" else projets)
                        if role != "admin":
                            _enregistrer_droits(t, uid, ident_n, role, droits_nouveaux, poste or None)
                except ValueError as e:
                    st.error(f"Compte créé, mais poste et accès non enregistrés : {e}")
                    return
                st.session_state["identifiants_crees"] = (ident_n, mdp, nom.strip())
                st.rerun()


def _comptes() -> None:
    _nouveau_compte()
    us = sorted(db.tout("users", sans=("mdp_hash",)), key=lambda u: (not u["actif"], u["nom"].lower()))
    noms_projets = {p["id"]: p["name"] for p in db.tout("projects")}
    rows = [{"_id": u["id"], "nom": u["nom"], "id": u["identifiant"], "poste": auth.libelle_poste(u["id"], u["role"]),
             "acces": "Personnalisés" if auth.personnalise(u["id"]) else "Modèle du poste",
             "chantiers": ", ".join(noms_projets.get(p, p) for p in auth.projets_de(u["id"]) or []) or "Tous",
             "tel": u["telephone"], "actif": bool(u["actif"]), "der": u["derniere_connexion"]} for u in us]
    i = ui.tableau(rows, {"nom": "Nom", "id": "Identifiant", "poste": "Poste", "acces": "Accès",
                          "chantiers": "Chantiers", "tel": "Téléphone",
                          "actif": st.column_config.CheckboxColumn("Actif"),
                          "der": st.column_config.DatetimeColumn("Dernière connexion", format="DD/MM/YYYY HH:mm")},
                   key="tab_users", selection=True)
    if i is None:
        st.caption("Sélectionnez un compte pour modifier son poste, ses chantiers et ses accès, le désactiver ou "
                   "réinitialiser son mot de passe.")
        return
    u = next(x for x in us if x["id"] == rows[i]["_id"])
    moi = auth.utilisateur()["id"]
    verrou = u["id"] == moi or (u["role"] == "admin" and not auth.est_admin())
    st.subheader(f"{u['nom']} ({u['identifiant']})")
    roles = _roles_permis() if u["role"] in _roles_permis() else list(auth.ROLES)
    a, b = st.columns(2)
    with a:
        role_m = st.selectbox("Famille de rôle", roles, index=roles.index(u["role"]), format_func=auth.ROLES.get,
                              disabled=verrou, key=f"mod_role_{u['id']}",
                              help="Changer de famille remet les accès au modèle ; vous pouvez ensuite les ajuster.")
    poste_actuel = auth.poste_de(u["id"])
    with b:
        if verrou:
            st.text_input("Poste", value=auth.libelle_poste(u["id"], u["role"]), disabled=True, key=f"mod_pl_{u['id']}")
            poste_m = poste_actuel if role_m == u["role"] else None
        else:
            poste_m = _choix_poste(role_m, f"mod_poste_{u['id']}_{role_m}",
                                   poste_actuel if role_m == u["role"] else None) or None
    anciens = auth.droits_de(u["id"], u["role"])
    meme_modele = role_m == u["role"] and poste_m == poste_actuel
    with st.form(f"modif_{u['id']}"):
        a, b = st.columns(2)
        nom = a.text_input("Nom complet", value=u["nom"])
        tel = b.text_input("Téléphone", value=u["telephone"] or "")
        actif = b.toggle("Compte actif", value=bool(u["actif"]), disabled=verrou,
                         help="Un compte désactivé ne peut plus se connecter ; son historique est conservé.")
        projets = _choix_projets(f"mod_projets_{u['id']}", auth.projets_de(u["id"]),
                                 desactive=verrou or role_m == "admin")
        st.markdown("**Accès aux rubriques**" + ("" if auth.personnalise(u["id"]) or not meme_modele
                                                 else " — modèle du poste, non modifié"))
        droits = _matrice(f"mod{u['id']}", role_m, anciens if meme_modele else None, desactive=verrou, poste=poste_m)
        _avertir_incompatibilites(droits, role_m)
        ok = st.form_submit_button("Enregistrer les modifications", type="primary")
    if ok:
        vals = {"nom": nom.strip() or u["nom"], "telephone": tel.strip()}
        novelles = None
        if not verrou:
            vals.update(role=role_m, actif=actif)
            if role_m != "admin":
                novelles = droits
        bascule = not verrou and (role_m != u["role"] or not actif or poste_m != poste_actuel
                                  or sorted(projets) != sorted(auth.projets_de(u["id"]) or [])
                                  or (novelles is not None and novelles != anciens))
        try:
            with db.transaction(f"Modification du compte {u['identifiant']}") as t:
                if bascule:  # ferme les sessions ouvertes : les nouveaux accès s'appliquent tout de suite
                    vals["version_session"] = int(u["version_session"] or 0) + 1
                t.maj("users", u["id"], vals)
                if not verrou:
                    auth.enregistrer_affectation(t, u["id"], u["identifiant"], role_m, poste_m,
                                                 None if role_m == "admin" else projets)
                if novelles is not None:
                    _enregistrer_droits(t, u["id"], u["identifiant"], role_m, novelles, poste_m)
        except ValueError as e:
            st.error(str(e))
            return
        ui.succes("Compte mis à jour.")
    if auth.personnalise(u["id"]) and not verrou:
        if st.button("Revenir au modèle du poste", icon=":material/restart_alt:",
                     help="Supprime les accès personnalisés : le compte reprend les accès de son poste (ou de son rôle)."):
            with db.transaction(f"Retour au modèle pour {u['identifiant']}") as t:
                t.parametre(f"droits_utilisateur:{u['id']}", None, resume=f"Retour au modèle : {u['identifiant']}")
                t.maj("users", u["id"], {"version_session": int(u["version_session"] or 0) + 1})
            st.rerun()
    if st.button("Réinitialiser le mot de passe", icon=":material/lock_reset:", disabled=verrou,
                 help="Pour votre propre compte, utilisez « Mon compte »."):
        mdp = auth.reinitialiser_mdp(u["id"])
        st.session_state["identifiants_crees"] = (u["identifiant"], mdp, u["nom"])
        st.rerun()


# ------------------------------------------------------------------ postes et profils
def _resume_droits(droits: dict) -> str:
    w = [auth.MODULE_LABELS[m] for m in auth.MODULES if droits.get(m) == "w"]
    r = [auth.MODULE_LABELS[m] for m in auth.MODULES if droits.get(m) == "r"]
    return ("Modification : " + ", ".join(w) if w else "") + (" · Consultation : " + ", ".join(r) if r else "")


def _profils() -> None:
    tous = auth.profils()
    usages: dict[str, int] = {}
    for u in db.tout("users", sans=("mdp_hash",)):
        if (p := auth.poste_de(u["id"])) and u["actif"]:
            usages[p] = usages.get(p, 0) + 1
    rows = [{"_id": k, "libelle": p["libelle"], "code": k, "famille": auth.ROLES.get(p["role"], p["role"]),
             "type": "Standard" if p["standard"] else "Personnalisé", "actif": p["actif"], "usagers": usages.get(k, 0),
             "description": p.get("description", "")} for k, p in tous.items()]
    i = ui.tableau(rows, {"libelle": "Poste / profil", "code": "Code", "famille": "Famille de rôle", "type": "Type",
                          "actif": st.column_config.CheckboxColumn("Actif"), "usagers": "Comptes actifs",
                          "description": "Description"}, key="tab_profils", selection=True)
    st.caption("Un poste est un modèle de départ. Les accès réglés pour une personne dans l’onglet Comptes restent "
               "prioritaires sur le modèle.")
    if i is not None:
        code = rows[i]["_id"]
        p = tous[code]
        with st.container(border=True):
            st.markdown(f"**{p['libelle']}** ({code}) — {auth.ROLES[p['role']]}")
            if p["standard"]:
                st.write(_resume_droits(p["droits"]))
                st.caption("Poste standard : non modifiable. Créez un profil personnalisé à partir de ce poste pour "
                           "l’adapter.")
            elif auth.modifie("utilisateurs"):
                with st.form(f"profil_{code}"):
                    libelle = st.text_input("Libellé", value=p["libelle"])
                    description = st.text_area("Description", value=p.get("description", ""))
                    actif = st.toggle("Profil actif", value=p["actif"],
                                      help="Désactivé : ses usagers reprennent le modèle de leur famille de rôle.")
                    droits = _matrice(f"pr_{code}", p["role"], {m: p["droits"].get(m) for m in auth.MODULES})
                    ok = st.form_submit_button("Enregistrer le profil", type="primary")
                if ok:
                    try:
                        auth.modifier_profil(code, libelle, droits, description, actif)
                    except ValueError as e:
                        st.error(str(e))
                    else:
                        ui.succes("Profil mis à jour ; les sessions de ses usagers sont fermées.")
    if not auth.modifie("utilisateurs"):
        return
    with st.expander("Créer un profil personnalisé", icon=":material/badge:"):
        roles = [r for r in auth.ROLES if r != "admin"]
        a, b = st.columns(2)
        with a:
            role = st.selectbox("Famille de rôle", roles, format_func=auth.ROLES.get, key="np_role")
        with b:
            bases = {k: p for k, p in tous.items() if p["role"] == role and p["actif"]}
            base = st.selectbox("Partir du poste", [""] + list(bases), key="np_base",
                                format_func=lambda k: "Modèle de la famille de rôle" if not k else bases[k]["libelle"])
        with st.form("nouveau_profil", clear_on_submit=True):
            a, b = st.columns(2)
            code = a.text_input("Code *", placeholder="ex. acheteur_junior", help="Minuscules, chiffres et _.")
            libelle = b.text_input("Libellé *", placeholder="ex. Acheteur junior")
            description = st.text_area("Description (rôle de ce poste dans le circuit)")
            st.markdown("**Accès du profil**")
            depart = bases[base]["droits"] if base else auth.DROITS.get(role, {})
            droits = _matrice(f"np_{base or 'role'}", role, {m: depart.get(m) for m in auth.MODULES})
            _avertir_incompatibilites(droits, role)
            ok = st.form_submit_button("Créer le profil", type="primary")
        if ok:
            try:
                auth.creer_profil(code, libelle, role, droits, description)
            except ValueError as e:
                st.error(str(e))
            else:
                ui.succes(f"Profil « {libelle.strip()} » créé : il est proposé comme poste dans l’onglet Comptes.")


def page() -> None:
    auth.exiger("utilisateurs")
    ui.en_tete("Utilisateurs", "Comptes, postes (modèles de départ), chantiers affectés et accès rubrique par rubrique.")
    if info := st.session_state.pop("identifiants_crees", None):
        _identifiants(*info)
    comptes, postes = st.tabs(["Comptes", "Postes et profils"])
    with comptes:
        _comptes()
    with postes:
        _profils()
