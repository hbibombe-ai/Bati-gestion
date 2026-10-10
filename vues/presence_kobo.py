"""Présence journalière des agents par KoboCollect : présence du jour, import des fiches, formulaire et réglages."""
from __future__ import annotations

import datetime as dt

import streamlit as st

import auth
import db
import kobo
import nav
import regles as R
import ui

ETATS_ORDRE = [kobo.NOUVEAU, kobo.CONFLIT, kobo.ERREUR, kobo.IDENTIQUE]


def _date_fr(d: str) -> str:
    return dt.date.fromisoformat(d).strftime("%d/%m/%Y") if R.is_date(d) else d


# ------------------------------------------------------------------ présence du jour
def onglet_jour(s: dict) -> None:
    a, _ = st.columns([1, 3])
    with a:
        date = ui.date_txt("Journée", "kb_jour", max_aujourdhui=True)
    j = kobo.presence_du_jour(s, date)
    c = st.columns(4)
    with c[0]:
        ui.carte("Présents (dont mission)", str(j["presents"]), f"{j['heures']:g} h travaillées", accent=True)
    with c[1]:
        ui.carte("Absents", str(j["absents"]), "absence non justifiée")
    with c[2]:
        ui.carte("Congé, maladie, repos", str(j["autres"]), "")
    with c[3]:
        ui.carte("Agents actifs non pointés", str(len(j["manquants"])),
                 "aucune ligne pour cette journée" if j["manquants"] else "tout le monde est pointé")
    st.caption(f"Pointages du {_date_fr(date)} : {len(j['jour'])}, dont {j['kobo']} venant de KoboCollect et "
               f"{len(j['jour']) - j['kobo']} saisis dans l'application.")

    g, d = st.columns([3, 2])
    with g:
        st.subheader("Par lieu")
        if j["par_lieu"]:
            ui.tableau([{"l": x["lieu"], "p": x["presents"], "a": x["absents"], "o": x["autres"],
                         "h": round(x["heures"], 2)} for x in j["par_lieu"]],
                       {"l": "Bureau / chantier", "p": "Présents", "a": "Absents", "o": "Congé, maladie, repos",
                        "h": st.column_config.NumberColumn("Heures", format="%.2f")}, key="kb_lieux")
        else:
            st.caption("Aucun pointage pour cette journée. Importez les fiches KoboCollect dans l'onglet suivant.")
    with d:
        st.subheader("Non pointés")
        if j["manquants"]:
            ui.tableau([{"n": p["name"], "m": p["code"], "a": R.hr_place_label(R.hr_assignment_at(p, date) or p, s)}
                        for p in j["manquants"]], {"n": "Agent", "m": "Matricule", "a": "Affectation"}, key="kb_manq")
            st.caption("Agents actifs, engagés à cette date, sans aucun pointage (ni Kobo ni manuel).")
        else:
            st.caption("Aucun.")

    if j["jour"]:
        noms = {p["id"]: p for p in s["personnel"]}
        with st.expander(f"Détail des {len(j['jour'])} pointages du {_date_fr(date)}"):
            ui.tableau(sorted([{"n": noms[a["person_id"]]["name"], "l": R.hr_place_label(a, s), "s": a["status"],
                                "h": a["hours"], "o": a["note"]} for a in j["jour"]], key=lambda x: (x["l"], x["n"])),
                       {"n": "Agent", "l": "Lieu", "s": "Présence",
                        "h": st.column_config.NumberColumn("Heures", format="%.2f"), "o": "Observation"}, key="kb_det")


# ------------------------------------------------------------------ import des fiches
def onglet_import(s: dict) -> None:
    reg = kobo.reglages()
    ecrit = auth.modifie("pointage")
    api = bool(reg["jeton"] and reg["formulaire"])
    if not ecrit:
        ui.lecture_seule()
        return
    st.write("Récupérez les fiches envoyées par les pointeurs. Chaque ligne est contrôlée avec les mêmes règles que le "
             "pointage manuel ; rien n'est enregistré avant que vous cliquiez sur **Importer**.")
    rangee = ui.rangee(2)
    if api:
        if rangee[0].button("Récupérer les fiches KoboCollect", type="primary", icon=":material/cloud_download:"):
            try:
                with st.spinner("Lecture des fiches sur le serveur Kobo…"):
                    st.session_state["kb_lignes"] = kobo.depuis_api(reg)
                    st.session_state["kb_source"] = "serveur Kobo"
            except ValueError as e:
                st.error(str(e))
    else:
        st.info("La récupération automatique n'est pas encore réglée (onglet « Formulaire et réglages »). En attendant, "
                "importez l'export Excel des fiches.")
    with st.expander("Importer un export Excel de Kobo", expanded=not api):
        st.caption("Dans KoboToolbox : Données › Téléchargements › type XLS, « Valeurs et en-têtes XML ». "
                   "Le fichier contient les fiches et la feuille « agents ».")
        f = st.file_uploader("Export Excel (.xlsx)", type=["xlsx"], key="kb_fichier")
        if f is not None and st.button("Lire le fichier", icon=":material/upload_file:"):
            try:
                st.session_state["kb_lignes"] = kobo.depuis_excel(f.getvalue())
                st.session_state["kb_source"] = f"fichier {f.name}"
            except ValueError as e:
                st.error(str(e))
            except Exception:  # noqa: BLE001
                st.error("Fichier illisible : vérifiez qu'il s'agit bien d'un export XLS de KoboToolbox.")

    lignes = st.session_state.get("kb_lignes")
    if lignes is None:
        return
    analyse = kobo.analyser(lignes, s)
    deja = len(lignes) - len(analyse)
    st.subheader("Contrôle des lignes")
    st.caption(f"{len(lignes)} ligne(s) lue(s) depuis le {st.session_state.get('kb_source')}"
               + (f", dont {deja} déjà traitée(s) lors d'un import précédent et écartée(s)." if deja else "."))
    if not analyse:
        st.success("Rien de nouveau : toutes les fiches ont déjà été importées.")
        return
    par_etat = {e: [r for r in analyse if r["etat"] == e] for e in ETATS_ORDRE}
    c = st.columns(4)
    for col, e in zip(c, ETATS_ORDRE):
        with col:
            ui.carte(e, str(len(par_etat[e])), {kobo.NOUVEAU: "seront ajoutés aux pointages",
                                                  kobo.CONFLIT: "pointage déjà saisi, différent",
                                                  kobo.ERREUR: "ne peuvent pas être importées",
                                                  kobo.IDENTIQUE: "déjà enregistrés, rien à faire"}[e],
                     accent=e == kobo.NOUVEAU)
    ui.tableau([{"e": r["etat"], "d": _date_fr(r["date"]), "n": r["nom"], "m": r["matricule"], "s": r["statut_lib"],
                 "h": r["heures"], "a": r["arrivee"], "p": r["depart"],
                 "l": R.hr_place_label(r["pointage"], s) if r["pointage"] else r["lieu"],
                 "t": r["pointeur"], "x": r["message"] or r["observation"]}
                for r in sorted(analyse, key=lambda r: (ETATS_ORDRE.index(r["etat"]), r["date"], r["nom"]))],
               {"e": "État", "d": "Date", "n": "Agent", "m": "Matricule", "s": "Présence",
                "h": st.column_config.NumberColumn("Heures", format="%.2f"), "a": "Arrivée", "p": "Départ",
                "l": "Lieu", "t": "Pointeur", "x": "Remarque"}, key="kb_analyse")

    remplacer = False
    if par_etat[kobo.CONFLIT]:
        remplacer = st.checkbox(f"Remplacer aussi les {len(par_etat[kobo.CONFLIT])} pointage(s) déjà saisi(s) par ceux de "
                                "KoboCollect", help="Sans cette case, ces lignes restent en attente et l'ancien pointage "
                                                    "est conservé.")
    a_faire = len(par_etat[kobo.NOUVEAU]) + (len(par_etat[kobo.CONFLIT]) if remplacer else 0)
    r = ui.rangee(2)
    if r[0].button(f"Importer {a_faire} pointage(s)", type="primary", icon=":material/how_to_reg:",
                   disabled=a_faire == 0 and not par_etat[kobo.IDENTIQUE]):
        try:
            n = kobo.importer(analyse, remplacer)
        except Exception as e:  # noqa: BLE001 — ex. pointage saisi entre-temps (contrainte d'unicité)
            st.error("Import annulé, rien n'a été enregistré : un pointage a peut-être été saisi entre-temps. "
                     f"Récupérez de nouveau les fiches. ({e.__class__.__name__})")
        else:
            st.session_state.pop("kb_lignes", None)
            ui.succes(f"Pointages KoboCollect : {n['Importé']} ajouté(s), {n['Remplacé']} remplacé(s), "
                      f"{n['Identique']} déjà présent(s).")
    erreurs = par_etat[kobo.ERREUR] + ([] if remplacer else par_etat[kobo.CONFLIT])
    if erreurs and r[1].button(f"Écarter les {len(erreurs)} ligne(s) restante(s)", icon=":material/block:",
                               help="Les lignes à corriger (et les pointages différents non remplacés) ne seront plus "
                                    "proposées. À faire seulement après vérification."):
        kobo.ignorer(erreurs)
        st.session_state.pop("kb_lignes", None)
        ui.succes(f"{len(erreurs)} ligne(s) écartée(s).")
    if par_etat[kobo.ERREUR]:
        st.caption("Lignes « À corriger » : corrigez la fiche dans KoboToolbox (Données › Tableau › modifier) ou la fiche "
                   "du personnel, puis récupérez de nouveau les fiches. Un agent nouvellement engagé n'apparaît dans le "
                   "formulaire qu'après sa mise à jour (onglet « Formulaire et réglages »).")


# ------------------------------------------------------------------ formulaire et réglages
def onglet_formulaire(s: dict) -> None:
    st.subheader("1. Formulaire KoboCollect")
    st.write("Le formulaire contient la liste à jour des agents actifs et des lieux (bureau et chantiers en cours). "
             "Une fiche par lieu et par jour : le pointeur choisit le lieu, puis ajoute une ligne par agent avec sa "
             "présence, ses heures d'arrivée et de départ et la pause.")
    try:
        fichier, info = kobo.xlsform(s)
    except ValueError as e:
        st.warning(str(e))
    else:
        ui.telecharger(f"Télécharger le formulaire ({info['agents']} agents, {info['chantiers']} chantiers)", fichier,
                       f"presence_agents_{info['version']}.xlsx", ui.MIME_XLSX, key="kb_xls", principal=True)
    with st.expander("Mettre le formulaire en service dans KoboToolbox"):
        st.markdown(
            "1. Sur **KoboToolbox**, cliquez sur **Nouveau › Importer un XLSForm** et chargez le fichier téléchargé.\n"
            "2. Cliquez sur **Déployer**. Dans **Paramètres › Partage**, donnez aux pointeurs le droit d'ajouter "
            "des soumissions (ou partagez le compte de collecte).\n"
            "3. Sur chaque téléphone, dans **KoboCollect** : ajoutez le projet avec l'adresse du serveur indiquée dans "
            "KoboToolbox (formulaire › **Formulaire** › **Collecter les données** › Application Android, par ex. "
            "`https://kc.kobotoolbox.org`), puis **Télécharger un formulaire**.\n"
            "4. **Quand le personnel change** (embauche, départ, nouveau chantier), téléchargez de nouveau le formulaire "
            "ici, puis dans KoboToolbox : **Remplacer le formulaire** › **Redéployer**. Les téléphones proposent la "
            "mise à jour. Les fiches déjà envoyées sont conservées.")
    st.subheader("2. Récupération automatique")
    reg = kobo.reglages()
    if auth.modifie("sauvegarde") or auth.modifie("paie"):
        a, b = st.columns(2)
        serveurs = {**kobo.SERVEURS, **({reg["serveur"]: reg["serveur"]} if reg["serveur"] not in kobo.SERVEURS else {})}
        serveur = a.selectbox("Serveur KoboToolbox", list(serveurs), index=list(serveurs).index(reg["serveur"]),
                              format_func=lambda k: f"{serveurs[k]} – {k}", key="kb_srv")
        uid = b.text_input("Identifiant du formulaire", value=reg["formulaire"], key="kb_uid",
                           help="Dans KoboToolbox, ouvrez le formulaire : c'est la suite de lettres et de chiffres "
                                "après /forms/ dans l'adresse (ex. aBcD12eFgH34iJkL).")
        if st.button("Enregistrer les réglages", icon=":material/save:"):
            with db.transaction("Réglages KoboCollect") as t:
                t.parametre("kobo", {"serveur": serveur, "formulaire": uid.strip()})
            ui.succes("Réglages KoboCollect enregistrés.")
    if reg["jeton"]:
        st.success("Jeton d'accès Kobo présent dans les secrets.")
    else:
        st.warning("Jeton d'accès Kobo absent. Dans KoboToolbox : Paramètres du compte › **Sécurité** › **Clé API**, "
                   "copiez la clé, puis ajoutez dans les secrets de l'application (Streamlit Cloud › Settings › Secrets) :")
        st.code('[kobo]\njeton = "votre-cle-api-kobo"', language="toml")
        st.caption("Le jeton reste dans les secrets : il n'est jamais enregistré dans la base ni affiché.")

    st.subheader("3. Historique des lignes traitées")
    hist = sorted(db.tout("kobo_pointages", sans=("donnees",)), key=lambda r: (r["traite_le"] or dt.datetime.min),
                  reverse=True)[:300]
    if hist:
        noms = {p["id"]: p["name"] for p in s["personnel"]}
        ui.tableau([{"q": r["traite_le"].strftime("%d/%m/%Y %H:%M") if r["traite_le"] else "", "r": r["resultat"],
                     "d": _date_fr(r["date"]), "n": noms.get(r["person_id"], r["agent"]), "s": r["statut"],
                     "h": r["heures"], "t": r["pointeur"], "u": r["traite_par"]} for r in hist],
                   {"q": "Traité le", "r": "Résultat", "d": "Date", "n": "Agent", "s": "Présence",
                    "h": st.column_config.NumberColumn("Heures", format="%.2f"), "t": "Pointeur", "u": "Par"},
                   key="kb_hist")
    else:
        st.caption("Aucune ligne KoboCollect importée pour l'instant.")
    if not (auth.modifie("sauvegarde") or auth.modifie("paie")):
        st.caption("Les réglages du serveur sont modifiables par la direction et les RH.")


def page() -> None:
    auth.exiger("pointage")
    ui.en_tete("Présence KoboCollect", "Pointage quotidien des agents sur téléphone, importé dans les pointages.")
    s = R.charger("personnel", "projects", "attendance")
    t1, t2, t3 = st.tabs(["Présence du jour", "Importer les fiches", "Formulaire et réglages"])
    with t1:
        onglet_jour(s)
    with t2:
        onglet_import(s)
    with t3:
        onglet_formulaire(s)
    nav.lien("personnel", "Voir tous les pointages dans « Personnel et pointage »", ":material/badge:")
