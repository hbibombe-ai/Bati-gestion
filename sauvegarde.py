"""Paramètres et sauvegarde : catégories de dépenses, export/restauration, reprise des données du prototype."""
from __future__ import annotations

import streamlit as st

import auth
import db
import migration as M
import regles as R
import ui


def page() -> None:
    auth.exiger("sauvegarde")
    ui.en_tete("Paramètres et sauvegarde", "Catégories de dépenses, sauvegardes et reprise des données du prototype.")
    c = R.company()

    st.subheader("Base de données")
    ok, txt = db.description_base()
    (st.success if ok else st.error)(txt)

    st.subheader("Catégories de dépenses")
    with st.form("categories"):
        txt = st.text_area("Une catégorie par ligne", value="\n".join(R.expense_categories(c)), height=200)
        ok = st.form_submit_button("Enregistrer les catégories", type="primary")
    if ok:
        try:
            cats = R.parse_expense_categories(txt)
            with db.transaction("Catégories de dépenses") as t:
                t.parametre("company", {**R.company(), "expenseCategories": cats})
        except ValueError as e:
            st.error(str(e))
        else:
            ui.succes("Catégories enregistrées. Les dépenses déjà saisies conservent leur catégorie.")

    st.subheader("Sauvegarde")
    st.write("La base de données centrale est la référence. Exportez néanmoins une copie régulièrement (par exemple "
             "chaque semaine) et conservez-la dans un dossier sûr.")
    a, b, c2 = st.columns(3)
    if a.button("Préparer la sauvegarde complète (JSON)", icon=":material/backup:"):
        st.session_state["sv_json"] = M.export_json()
    if "sv_json" in st.session_state:
        with a:
            ui.telecharger("Télécharger la sauvegarde", st.session_state["sv_json"],
                           f"bati-gestion-sauvegarde-{R.today()}.json", "application/json", key="sv_dl", principal=True)
    if b.button("Préparer l’export Excel", icon=":material/table_view:"):
        st.session_state["sv_xlsx"] = M.export_excel()
    if "sv_xlsx" in st.session_state:
        with b:
            ui.telecharger("Télécharger l’export Excel", st.session_state["sv_xlsx"], f"bati-gestion-{R.today()}.xlsx",
                           ui.MIME_XLSX, key="sv_xl")
    c2.caption("La sauvegarde JSON contient toutes les données et les justificatifs, mais pas les comptes ni les mots "
               "de passe. L’export Excel (une feuille par table) sert à l’analyse.")

    st.subheader("Restaurer ou reprendre des données")
    st.warning("La restauration d’une sauvegarde ou la reprise du prototype **remplace toutes les données métier** "
               "(chantiers, tiers, documents, trésorerie, personnel, paie, dossiers). Les comptes utilisateurs et le "
               "journal d’audit sont conservés. Exportez d’abord une sauvegarde.")
    choix = st.radio("Fichier à importer", ["proto", "brouillons", "app"], horizontal=False, format_func={
        "proto": "Sauvegarde du prototype BatiGestion (bati-sauvegarde-AAAA-MM-JJ.json)",
        "brouillons": "Brouillons du prototype : lots historiques et pièces (bati-brouillons-AAAA-MM-JJ.json) — ajoutés, "
                      "sans rien remplacer",
        "app": "Sauvegarde de cette application (bati-gestion-sauvegarde-AAAA-MM-JJ.json)"}.get)
    f = st.file_uploader("Fichier JSON", type=["json"], key=f"sv_up_{choix}")
    confirme = choix == "brouillons" or st.checkbox("Je confirme remplacer les données actuelles par ce fichier.")
    if f is not None and st.button("Importer", type="primary", disabled=not confirme):
        try:
            if choix == "proto":
                n = M.import_prototype(f.getvalue())
                msg = "Données du prototype reprises : " + ", ".join(
                    f"{db.NOMS_OBJETS.get(k, k).lower()} {v}" for k, v in n.items() if v) + "."
            elif choix == "brouillons":
                n = M.import_brouillons(f.getvalue(), auth.utilisateur()["id"])
                msg = f"Brouillons repris : {n['lots']} lot(s) historique(s) et {n['pieces']} pièce(s) préparée(s)."
            else:
                n = M.import_json(f.getvalue())
                msg = "Sauvegarde restaurée."
        except (ValueError, KeyError, TypeError) as e:
            st.error(f"Import impossible : {e}")
        except Exception as e:  # noqa: BLE001
            st.error(f"Import impossible : les données ne respectent pas les règles de la base ({type(e).__name__}).")
        else:
            st.session_state.pop("sv_json", None)
            ui.succes(msg)
