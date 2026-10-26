"""Société MY DESTINY : identité, adresses qualifiées, en-tête des documents et historique des modifications."""
from __future__ import annotations

import json

import streamlit as st

import auth
import db
import regles as R
import ui


@st.dialog("Société — référentiel", width="large")
def formulaire(reference: bool = False) -> None:
    c = R.company()
    if reference:
        importee = st.session_state.get("fiche_importee") or {}
        c = {**c, **{k: v for k, v in importee.items() if k != "v7"}, "v7": dict(importee.get("v7") or {})}
        st.info("Fiche préremplie depuis le fichier importé. Vérifiez puis enregistrez.")
    v = c.get("v7") or {}
    k = "ref" if reference else "mod"
    a, b = st.columns(2)
    nom = a.text_input("Raison sociale *", value=c.get("name", ""), key=f"so_nom_{k}")
    rccm = b.text_input("RCCM", value=c.get("registration", ""), key=f"so_rccm_{k}")
    tel = a.text_input("Téléphones", value=c.get("phone", ""), key=f"so_tel_{k}")
    with b:
        cur = ui.devise("Monnaie proposée pour les saisies", f"so_cur_{k}", c.get("defaultCurrency"))
    prof = {}
    cols = st.columns(2)
    for n, (cle, lbl) in enumerate(R.V7_FIELDS):
        prof[cle] = cols[n % 2].text_input(lbl, value=v.get(cle, ""), key=f"so_{cle}_{k}")
    adr = {"": "À qualifier", "1": "Adresse 1", "2": "Adresse 2"}
    a, b = st.columns(2)
    with a:
        siege = ui.choix("Adresse du siège social", adr, f"so_siege_{k}", v.get("officialAddress", ""))
    with b:
        bureau = ui.choix("Adresse du bureau", adr, f"so_bur_{k}", v.get("operatingAddress", ""))
    motif = st.text_input("Motif de la mise à jour *",
                          value="Import de la fiche société" if reference else "", key=f"so_mot_{k}")
    st.caption("Les deux adresses sont conservées. Seule une adresse qualifiée comme siège figure dans les nouveaux en-têtes. "
               "Les documents déjà munis d’un en-tête mémorisé le conservent. Le bénéficiaire effectif et l’effectif "
               "restent internes.")
    if st.button("Enregistrer", type="primary"):
        st.session_state.pop("fiche_importee", None)
        try:
            if not motif.strip():
                raise ValueError("Indiquez le motif de cette modification.")
            if not nom.strip():
                raise ValueError("La raison sociale est obligatoire.")
            profil = {k_: x.strip() for k_, x in prof.items()}
            profil.update(officialAddress=siege, operatingAddress=bureau)
            if siege and not profil["address" + siege]:
                raise ValueError("Renseignez l’adresse choisie pour le siège.")
            if bureau and not profil["address" + bureau]:
                raise ValueError("Renseignez l’adresse choisie pour le bureau.")
            avant_c = R.company()
            nouveau = {**avant_c, "name": nom.strip(), "registration": rccm.strip(), "phone": tel.strip(),
                       "defaultCurrency": cur, "v7": profil, "address": profil["address" + siege] if siege else ""}
            with db.transaction("Mise à jour du référentiel société") as t:
                t.parametre("company", nouveau)
                t.inserer("company_history", {"before": R.company_snapshot(avant_c), "after": R.company_snapshot(nouveau),
                                              "reason": motif.strip(), "user_nom": auth.utilisateur()["nom"]})
        except ValueError as e:
            st.error(str(e))
        else:
            ui.succes("Référentiel société enregistré.")


CHAMPS_FICHE = {"name", "phone", "registration", "address", "defaultCurrency", "v7"}


def fiche_json(c: dict) -> bytes:
    fiche = {k: v for k, v in c.items() if k in CHAMPS_FICHE}
    return json.dumps({"format": "bati-gestion-fiche-societe", "version": 1, "fiche": fiche}, ensure_ascii=False,
                      indent=1).encode("utf-8")


def lire_fiche(contenu: bytes) -> dict:
    """Fiche société exportée par l'application (format contrôlé, champs connus seulement)."""
    try:
        d = json.loads(contenu.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("Fichier illisible : fiche JSON exportée par Bâti Gestion attendue.") from None
    if not isinstance(d, dict) or d.get("format") != "bati-gestion-fiche-societe" or not isinstance(d.get("fiche"), dict):
        raise ValueError("Ce fichier n’est pas une fiche société Bâti Gestion.")
    f = {k: v for k, v in d["fiche"].items() if k in CHAMPS_FICHE}
    connus = {k for k, _ in R.V7_FIELDS} | {"officialAddress", "operatingAddress"}
    f["v7"] = {k: str(v) for k, v in (f.get("v7") or {}).items() if k in connus}
    if any(not isinstance(f.get(k, ""), str) for k in ("name", "phone", "registration", "address")):
        raise ValueError("Champs de la fiche invalides.")
    return f


def page() -> None:
    auth.exiger("societe")
    ui.en_tete("Société", "Identité, coordonnées et historique des modifications.")
    c = R.company()
    snap = R.company_snapshot(c)
    if auth.modifie("societe"):
        a, b = ui.rangee(2)
        if a.button("Modifier la société", type="primary", icon=":material/edit:"):
            formulaire()
        ui.telecharger("Exporter la fiche (JSON)", fiche_json(c), "fiche-societe.json", "application/json",
                       key="so_export")
        with st.expander("Importer une fiche société (JSON)", icon=":material/upload_file:"):
            st.caption("Les données d’identité ne sont plus écrites dans le code de l’application : elles se saisissent "
                       "ici ou s’importent depuis le fichier de fiche fourni par la direction, puis s’enregistrent avec "
                       "un motif.")
            f = st.file_uploader("Fichier de fiche société", type=["json"], key="so_import")
            if f is not None and st.button("Préremplir depuis ce fichier", icon=":material/auto_fix_high:"):
                try:
                    st.session_state["fiche_importee"] = lire_fiche(f.getvalue())
                except ValueError as e:
                    st.error(str(e))
                else:
                    formulaire(reference=True)
    st.subheader("En-tête des documents")
    with st.container(border=True):
        st.markdown(f"**{snap['name']}**  \n{snap['address'] or 'Adresse officielle à qualifier'}  \n{snap['phone']}  \n"
                    + " · ".join(x for x in (snap["email"], snap["website"]) if x) + "  \n"
                    + " · ".join(f"{k} : {v}" for k, v in (("RCCM", snap["rccm"]), ("ID NAT", snap["nationalId"]),
                                                          ("NIF", snap["taxId"]), ("TVA", snap["vatId"])) if v))
    v = c.get("v7") or {}
    st.subheader("Adresses à qualifier")
    st.markdown(f"Adresse 1 : {v.get('address1') or 'Non renseignée'}  \nAdresse 2 : {v.get('address2') or 'Non renseignée'}"
                f"  \nSiège social : {'adresse ' + v['officialAddress'] if v.get('officialAddress') else 'à qualifier'} · "
                f"Bureau : {'adresse ' + v['operatingAddress'] if v.get('operatingAddress') else 'à qualifier'}")
    if v and auth.modifie("societe"):
        st.markdown("**Informations internes** (non reprises dans les en-têtes)  \n"
                    f"Gérant / DG : {v.get('director') or '—'} · Bénéficiaire effectif : {v.get('beneficialOwner') or '—'}"
                    f" · Effectif de référence : {v.get('headcount') or '—'}")
    st.subheader("Historique des coordonnées diffusées")
    hist = sorted(db.tout("company_history"), key=lambda h: h["id"], reverse=True)
    if not hist:
        st.caption("Aucune modification enregistrée.")
        return
    rows = [{"_id": h["id"], "d": h["after"].get("capturedAt", "")[:16].replace("T", " "), "m": h["reason"], "u": h["user_nom"],
             "a": h["before"].get("name", ""), "n": h["after"].get("name", "")} for h in hist]
    i = ui.tableau(rows, {"d": "Date", "m": "Motif", "u": "Par", "a": "Ancienne raison sociale",
                          "n": "Nouvelle raison sociale"}, key="tab_hist_soc", selection=True)
    if i is not None:
        h = hist[i]
        diff = [{"c": R.SNAPSHOT_LABELS.get(k, k), "a": h["before"].get(k, ""), "n": h["after"].get(k, "")}
                for k in R.SNAPSHOT_LABELS if h["before"].get(k) != h["after"].get(k)]
        if diff:
            ui.tableau(diff, {"c": "Champ", "a": "Avant", "n": "Après"}, key="tab_diff_soc")
        else:
            st.caption("Aucune différence dans les coordonnées diffusées.")
