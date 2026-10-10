"""Journal d'audit : qui a fait quoi et quand (lecture seule)."""
from __future__ import annotations

import json

import streamlit as st

import auth
import db
import regles as R
import ui


def page() -> None:
    auth.exiger("audit")
    ui.en_tete("Journal d’audit", "Chaque création, modification, suppression et connexion, avec l’auteur et l’heure.")
    a, b, c = st.columns(3)
    users = sorted({r["user_nom"] for r in db.requete("select distinct user_nom from audit") if r["user_nom"]})
    qui = a.selectbox("Utilisateur", [""] + users, format_func=lambda x: x or "Tous")
    objets = {k: v for k, v in db.NOMS_OBJETS.items()}
    quoi = b.selectbox("Objet", [""] + list(objets), format_func=lambda x: objets.get(x, "Tous"))
    n = c.selectbox("Afficher", [200, 1000, 5000], format_func=lambda x: f"{x} dernières lignes")
    sql = "select * from audit where 1=1"
    params = {}
    if qui:
        sql += " and user_nom = :u"
        params["u"] = qui
    if quoi:
        sql += " and objet = :o"
        params["o"] = quoi
    rows = db.requete(sql + f" order by id desc limit {int(n)}", **params)
    if not rows:
        st.info("Aucune ligne pour ces critères.")
        return
    lignes = [{"_id": r["id"], "q": r["quand"], "u": r["user_nom"], "a": r["action"],
               "o": db.NOMS_OBJETS.get(r["objet"], r["objet"]), "r": r["resume"]} for r in rows]
    ui.telecharger("Exporter CSV", R.to_csv([["Date", "Utilisateur", "Action", "Objet", "Identifiant", "Résumé", "Avant",
                                              "Après"]] + [[r["quand"], r["user_nom"], r["action"], r["objet"],
                                                            r["objet_id"], r["resume"],
                                                            json.dumps(r["avant"], ensure_ascii=False) if r["avant"] else "",
                                                            json.dumps(r["apres"], ensure_ascii=False) if r["apres"] else ""]
                                                           for r in rows]), f"audit-{R.today()}.csv", ui.MIME_CSV, key="aud_csv")
    i = ui.tableau(lignes, {"q": st.column_config.DatetimeColumn("Date", format="DD/MM/YYYY HH:mm:ss"),
                            "u": "Utilisateur", "a": "Action", "o": "Objet", "r": "Résumé"}, key="tab_audit",
                   selection=True)
    if i is not None:
        r = rows[i]
        x, y = st.columns(2)
        x.markdown("**Avant**")
        x.json(r["avant"] or {}, expanded=True)
        y.markdown("**Après**")
        y.json(r["apres"] or {}, expanded=True)
