"""Mes activités : appels, réunions, relances… planifiés sur les fiches, avec rappels (en retard, aujourd'hui)."""
from __future__ import annotations

import datetime as dt

import streamlit as st

import auth
import composants as C
import db
import erp
import nav
import regles as R
import ui

ORDRE = ["En retard", "Aujourd’hui", "À venir", "Faite"]
TEINTES = {"En retard": "#f0507a", "Aujourd’hui": "#ff9f1c", "À venir": "#12b886", "Faite": "#868e96"}
ETIQ = {"En retard": ("#fdeeec", "#a62d25"), "Aujourd’hui": ("#fff1dc", "#b35c00"), "À venir": ("#e3f7ef", "#0b7a56"),
        "Faite": ("#edf0f7", "#5a6684")}
LIENS = {"": "Aucune (activité générale)", "clients": "Client / fournisseur", "projects": "Chantier",
         "crm_pistes": "Piste CRM"}


def _jour(t: str) -> str:
    try:
        return dt.date.fromisoformat(str(t)[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return str(t or "")


def _carte(r: dict) -> dict:
    fond, txt = ETIQ[r["etat"]]
    return {"titre": r["resume"], "sous_titre": f"{r['type']} · {r['fiche']}", "initiales": C.initiales(r["qui"]),
            "couleur_avatar": C.couleur_nom(r["qui"]), "couleur": TEINTES[r["etat"]],
            "lignes": [f"Échéance : {r['echeance']}", f"Assignée à : {r['qui']}"], "etiquettes": [(r["etat"], fond, txt)]}


@st.dialog("Nouvelle activité", width="large")
def nouvelle() -> None:
    users = erp.utilisateurs_actifs()
    moi = auth.utilisateur()["id"]
    a, b = st.columns(2)
    type_ = a.selectbox("Type", erp.TYPES_ACTIVITE, key="na_type")
    quand = b.date_input("Échéance", value=dt.date.today() + dt.timedelta(days=1), format="DD/MM/YYYY", key="na_date")
    resume = st.text_input("À faire *", placeholder="Ex. Appeler le client lundi pour le devis", max_chars=500,
                           key="na_resume")
    lien = st.selectbox("Rattacher à", list(LIENS), format_func=LIENS.get, key="na_lien")
    objet_id, libelle = "", ""
    if lien:
        if lien == "crm_pistes":
            fiches = {p["id"]: p["titre"] for p in db.tout("crm_pistes")}
        elif lien == "projects":
            fiches = {p["id"]: p["name"] for p in db.tout("projects")}
        else:
            fiches = {p["id"]: p["name"] for p in db.tout("clients") if not p.get("archived")}
        if not fiches:
            st.caption("Aucune fiche de ce type pour l’instant.")
        else:
            objet_id = st.selectbox("Fiche", list(fiches), format_func=fiches.get, key="na_fiche")
            libelle = fiches.get(objet_id, "")
    ids = list(users)
    qui = st.selectbox("Assignée à", ids, index=ids.index(moi) if moi in ids else 0, format_func=users.get, key="na_qui")
    if st.button("Planifier", type="primary", icon=":material/alarm_add:"):
        try:
            erp.planifier(lien or "general", objet_id or "", libelle, type_, resume, quand.isoformat(), qui, moi)
        except ValueError as e:
            st.error(str(e))
        else:
            ui.succes("Activité planifiée.")


def page() -> None:
    auth.exiger("accueil")
    u = auth.utilisateur()
    users = erp.utilisateurs_actifs()
    sel = C.fiche_ouverte("act")
    toutes = u.get("role") == "admin" and st.session_state.get("act_toutes", False)
    lignes = erp.activites(None if toutes else u["id"], inclure_faites=True)
    limite = (dt.date.today() - dt.timedelta(days=30)).isoformat()
    lignes = [a for a in lignes if not a["fait"] or str(a["fait_le"] or "")[:10] >= limite]
    a = next((x for x in lignes if x["id"] == sel), None) if sel else None
    if a:
        fiche(a, users)
        return
    n = erp.rappels(u["id"])
    ui.en_tete("Mes activités", "Appels, réunions, visites et relances planifiés, avec leurs rappels.",
               badge=f"{n['En retard']} en retard · {n['Aujourd’hui']} aujourd’hui")
    with st.container(horizontal=True, gap="small", vertical_alignment="center"):
        if st.button("Nouvelle activité", type="primary", icon=":material/add_alarm:"):
            nouvelle()
        if u.get("role") == "admin":
            st.toggle("Voir les activités de toute l’équipe", key="act_toutes")
    if not lignes:
        st.info("Aucune activité. Planifiez-en depuis une fiche (chantier, client, devis, piste CRM…) ou avec "
                "« Nouvelle activité ».")
        return
    rows = []
    for x in lignes:
        etat = "Faite" if x["fait"] else erp.echeance_etat(x["echeance"])
        rows.append({"_id": x["id"], "resume": x["resume"], "type": x["type"], "etat": etat,
                     "fiche": x["libelle"] or "Activité générale", "objet": db.NOMS_OBJETS.get(x["objet"], "Général"),
                     "echeance": _jour(x["echeance"]), "_ech": x["echeance"], "qui": users.get(x["assigne_a"], "—")})
    rows.sort(key=lambda r: (ORDRE.index(r["etat"]), r["_ech"]))
    filtres = [(t, "Type", (lambda t: lambda r: r["type"] == t)(t)) for t in erp.TYPES_ACTIVITE]
    filtres += [("Ouvertes", "État", lambda r: r["etat"] != "Faite"), ("Faites", "État", lambda r: r["etat"] == "Faite")]
    C.vue_liste("act", rows, {"echeance": "Échéance", "etat": "État", "type": "Type", "resume": "À faire",
                              "fiche": "Fiche", "objet": "Rubrique", "qui": "Assignée à"},
                recherche=("resume", "fiche", "type", "qui"), filtres=filtres,
                regroupements={"État": ("etat", ORDRE), "Type": ("type", erp.TYPES_ACTIVITE), "Assignée à": ("qui", None),
                               "Rubrique": ("objet", None)},
                regroupement_defaut="État", carte=_carte, vue_defaut="Kanban", nom="activité",
                couleurs_groupes=TEINTES)


def fiche(a: dict, users: dict) -> None:
    C.fil_ariane("Mes activités", f"{a['type']} · {a['resume']}", "act")
    etat = "Faite" if a["fait"] else erp.echeance_etat(a["echeance"])
    with st.container(key="bg_feuille"):
        st.subheader(a["resume"])
        st.markdown(f"**Type :** {a['type']}  \n**État :** {etat}  \n**Échéance :** {_jour(a['echeance'])}  \n"
                    f"**Assignée à :** {users.get(a['assigne_a'], '—')}  \n**Fiche :** {a['libelle'] or 'Activité générale'}"
                    f" ({db.NOMS_OBJETS.get(a['objet'], 'Général')})")
        if a["fait"]:
            st.success(f"Faite le {str(a['fait_le'])[:16]}" + (f" — {a['compte_rendu']}" if a["compte_rendu"] else ""))
        cols = ui.rangee(3)
        lien = erp.FICHES.get(a["objet"])
        if lien and lien[1] in nav.PAGES and cols[0].button("Ouvrir la fiche liée", icon=":material/open_in_new:"):
            st.session_state[f"bg_fiche_{lien[0]}"] = a["objet_id"]
            nav.aller(lien[1])
    if not a["fait"]:
        with st.form("act_fait"):
            cr = st.text_area("Compte rendu (facultatif)", height=80)
            c1, c2 = st.columns(2)
            fait = c1.form_submit_button("Marquer comme fait", type="primary", icon=":material/check:")
            d = c2.date_input("Ou reporter au", value=None, format="DD/MM/YYYY")
            rep = c2.form_submit_button("Reporter", icon=":material/event_repeat:")
        if fait:
            erp.terminer(a["id"], cr)
            C.fermer("act")
            ui.succes("Activité terminée.")
        if rep:
            if not d:
                st.error("Choisissez la nouvelle date.")
            else:
                erp.reporter(a["id"], d.isoformat())
                ui.succes(f"Activité reportée au {d.strftime('%d/%m/%Y')}.")
