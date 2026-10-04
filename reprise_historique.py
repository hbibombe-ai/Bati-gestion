"""Reprise historique : préparer les archives chantier par chantier à partir du modèle Excel."""
from __future__ import annotations

import streamlit as st

import auth
import db
import regles as R
import reprise as RP
import ui
import justificatifs as J


def page() -> None:
    auth.exiger("reprise")
    ui.en_tete("Reprise historique", "Préparez les archives chantier par chantier : modèle Excel, contrôle, conservation.")
    ecrit = auth.modifie("reprise")
    st.markdown("1. Téléchargez et remplissez le modèle Excel (un chantier par classeur).  \n"
                "2. Chargez-le : l’application contrôle la structure, les références, les dates et les montants.  \n"
                "3. Conservez le lot. Ses dépenses apparaissent ensuite dans « Justificatifs ».")
    ui.telecharger("Télécharger le modèle Excel", RP.modele(), "MY-DESTINY-modele-historique.xlsx", ui.MIME_XLSX,
                   key="rp_modele", principal=True)
    lots = sorted(db.tout("history_batches"), key=lambda b: b["created_at"], reverse=True)
    if ecrit:
        f = st.file_uploader("Charger un fichier Excel rempli (.xlsx, 8 Mo au plus)", type=["xlsx"], key="rp_file")
        if f is not None:
            try:
                tables, errs = RP.lire_classeur(f.getvalue())
                res = RP.valider(tables, {b["project_ref"] for b in lots})
                res["errors"] = errs + res["errors"]
                res["valid"] = not res["errors"]
            except ValueError as e:
                st.error(str(e))
            else:
                with st.container(border=True):
                    st.markdown(f"**Contrôle : {f.name}** — {len(res['rows'])} lignes · {len(res['errors'])} anomalie(s) "
                                f"bloquante(s) · {len(res['warnings'])} avertissement(s)")
                    if res["errors"]:
                        ui.tableau(res["errors"][:200], {"sheet": "Feuille", "line": "Ligne", "field": "Champ",
                                                         "message": "Anomalie"}, key="rp_err")
                    else:
                        st.success(f"{(res['project'] or {}).get('nom', '')} · les contrôles de structure sont réussis.")
                    if res["warnings"]:
                        st.caption("Les dépenses restent non justifiées. Les documents nommés dans Excel devront être joints "
                                   "séparément. Vérifiez les montants avec vos archives avant la reprise définitive.")
                    a, b = ui.rangee(2)
                    with a:
                        ui.telecharger("Télécharger le rapport de contrôle", RP.rapport_controle(res),
                                       "controle-historique.xlsx", ui.MIME_XLSX, key="rp_ctrl")
                    if res["valid"] and b.button("Conserver ce lot préparé", type="primary"):
                        with db.transaction(f"Lot historique {res['project']['nom']}") as t:
                            t.inserer("history_batches", {"id": db.nouvel_id(), "project_ref": res["project"]["reference"],
                                                          "project": res["project"], "rows": res["rows"], "source": f.name,
                                                          "created_at": db.maintenant(),
                                                          "created_by": auth.utilisateur()["id"]})
                        ui.succes("Lot préparé. Aucune écriture comptable n’a été créée.")
    st.subheader(f"Lots préparés ({len(lots)})")
    if not lots:
        st.caption("Aucun lot préparé.")
        return
    rows = [{"_id": b["id"], "ch": f"{b['project']['nom']} ({b['project']['reference']})", "src": b["source"],
             "n": len(b["rows"]), "d": b["created_at"]} for b in lots]
    i = ui.tableau(rows, {"ch": "Chantier", "src": "Fichier source", "n": st.column_config.NumberColumn("Lignes"),
                          "d": st.column_config.DatetimeColumn("Préparé le", format="DD/MM/YYYY HH:mm")},
                   key="tab_lots", selection=True)
    if i is None:
        st.caption("Sélectionnez un lot pour le consulter, y joindre des documents ou le supprimer.")
        return
    b = lots[i]
    st.subheader(b["project"]["nom"])
    st.caption("Données historiques · brouillon en lecture seule. Pour corriger, supprimez le lot puis rechargez le "
               "fichier Excel corrigé.")
    feuilles = sorted({r["sheet"] for r in b["rows"]})
    fe = st.pills("Feuille", feuilles, default=feuilles[0], key=f"rp_f_{b['id']}") or feuilles[0]
    sel = [r["values"] for r in b["rows"] if r["sheet"] == fe]
    ui.tableau(sel, {k: k for k in RP.SCHEMA.get(fe, list(sel[0]))}, key=f"rp_rows_{b['id']}_{fe}")
    pieces = [p for p in db.tout("pieces", sans=("content",)) if p["batch_id"] == b["id"] and not p["expense_id"]]
    st.markdown(f"**Documents du chantier** ({len(pieces)})")
    for p in pieces:
        x, y = st.columns([3, 1])
        x.write(f"{p['type']} — {p['name']} · {p['document_date']} · {p['beneficiary']}")
        with y:
            ui.telecharger("Ouvrir", bytes(db.requete("select content from pieces where id = :i", i=p["id"])[0]["content"]),
                           p["name"], p["mime"], key=f"rpdl_{p['id']}")
    if not ecrit:
        return
    with st.form(f"rp_doc_{b['id']}", clear_on_submit=True):
        st.markdown("**Joindre un document de chantier** (PDF, JPEG ou PNG, 5 Mo au plus)")
        a, c = st.columns(2)
        type_ = a.selectbox("Type", R.PIECE_TYPES, index=len(R.PIECE_TYPES) - 1)
        date = c.date_input("Date du document", format="DD/MM/YYYY")
        benef = a.text_input("Émetteur / bénéficiaire *")
        fichier = c.file_uploader("Fichier *", type=["pdf", "jpg", "jpeg", "png"])
        ok = st.form_submit_button("Joindre", type="primary")
    if ok:
        try:
            if fichier is None or not benef.strip():
                raise ValueError("Choisissez un fichier et indiquez l’émetteur.")
            contenu = fichier.getvalue()
            mime = J.mime_de(contenu)
            if not mime or len(contenu) > R.PIECE_MAX:
                raise ValueError("Le contenu doit être un PDF, une photo JPEG ou une image PNG de 5 Mo au plus.")
            import hashlib
            h = hashlib.sha256(contenu).hexdigest()
            if db.requete("select id from pieces where hash = :h", h=h):
                raise ValueError("Ce fichier est déjà enregistré.")
            with db.transaction(f"Document joint au lot {b['project']['nom']}") as t:
                t.inserer("pieces", {"id": db.nouvel_id(), "expense_id": "", "batch_id": b["id"],
                                     "name": J.nom_sur(fichier.name, mime), "mime": mime, "content": contenu,
                                     "size": len(contenu), "hash": h, "type": type_, "beneficiary": benef.strip(),
                                     "document_date": date.isoformat(), "amount": 0, "currency": "", "status": "Préparée",
                                     "reason": "", "uploaded_at": db.maintenant(), "uploaded_by": auth.utilisateur()["id"]})
        except ValueError as e:
            st.error(str(e))
        else:
            ui.succes("Document joint au lot.")
    if st.button("Supprimer ce lot et ses pièces", icon=":material/delete:"):
        st.session_state["rp_suppr"] = b["id"]
    if st.session_state.get("rp_suppr") == b["id"]:
        st.warning("Supprimer ce lot historique et toutes ses pièces ? La comptabilité n’est pas modifiée.")
        o, n = ui.rangee(2)
        if o.button("Oui, supprimer", type="primary"):
            with db.transaction(f"Suppression du lot {b['project']['nom']}") as t:
                t.supprimer_ou("pieces", db.pieces.c.batch_id == b["id"])
                t.supprimer("history_batches", b["id"])
            st.session_state.pop("rp_suppr", None)
            ui.succes("Lot supprimé.")
        if n.button("Annuler"):
            st.session_state.pop("rp_suppr", None)
            st.rerun()
