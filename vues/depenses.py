"""Dépenses de chantier : chaque dépense crée une seule sortie dans le journal de caisse."""
from __future__ import annotations

import streamlit as st

import auth
import db
import gestion_v7 as V
import nav
import regles as R
import ui


def pieces_par_depense() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for p in db.tout("pieces", sans=("content",)):
        if p["expense_id"]:
            out.setdefault(p["expense_id"], []).append(p)
    return out


def justifie(pieces: list[dict], montant: int) -> int:
    return min(montant, sum(p["amount"] for p in pieces if p["status"] == "Validée"))


@st.dialog("Dépense", width="large")
def formulaire(eid: str | None = None) -> None:
    s = R.charger("projects", "clients", "expenses", "movements")
    r = next((x for x in s["expenses"] if x["id"] == eid), None) or {}
    mv = next((m for m in s["movements"] if m["expense_id"] == eid), None) if eid else None
    k = eid or "new"
    a, b = st.columns(2)
    libelle = a.text_input("Libellé *", value=r.get("label", ""), key=f"dp_lib_{k}", max_chars=500)
    with b:
        projet = ui.choix("Chantier *", ui.options_chantiers(s), f"dp_proj_{k}", r.get("project"), vide="Choisir un chantier")
    cats = R.expense_categories(s["company"], r.get("category", ""))
    cat = a.selectbox("Catégorie", cats, index=cats.index(r["category"]) if r.get("category") in cats else 0,
                      key=f"dp_cat_{k}")
    with b:
        fourn = ui.choix("Fournisseur / sous-traitant", ui.options_fournisseurs(s, r.get("supplier_id", "")),
                         f"dp_four_{k}", r.get("supplier_id", ""), vide="Non renseigné")
    with a:
        date = ui.date_txt("Date *", f"dp_date_{k}", r.get("date"))
    with b:
        compte = ui.choix("Payé depuis *", R.CASH_ACCOUNTS, f"dp_cpt_{k}",
                          (mv or {}).get("account") if (mv or {}).get("account") in R.CASH_ACCOUNTS else "cash")
    with a:
        monnaie = ui.devise("Monnaie", f"dp_cur_{k}", r.get("currency"))
    taux = None
    if r and monnaie != r["currency"]:
        taux = b.number_input(f"Taux : 1 {r['currency']} = combien de {monnaie} ?", min_value=0.0, value=None,
                              format="%.6f", key=f"dp_taux_{k}")
    montant = ui.montant(f"Montant ({r.get('currency', monnaie) if r else monnaie}) *", f"dp_mt_{k}", r.get("amount", 0))
    resp = st.text_input("Responsable de la dépense", value=r.get("responsible") or (auth.utilisateur() or {}).get("nom", ""),
                         key=f"dp_resp_{k}")
    if st.button("Enregistrer", type="primary"):
        try:
            if not libelle.strip():
                raise ValueError("Le libellé est obligatoire.")
            if not projet:
                raise ValueError("Choisissez un chantier.")
            if not R.is_date(date):
                raise ValueError("Indiquez une date valide.")
            rec = {"label": libelle.strip(), "project": projet, "category": cat, "date": date,
                   "amount": R.cents(montant, "Montant", positif=True), "currency": monnaie,
                   "supplier_id": fourn or "", "responsible": resp.strip()}
            if r:
                rec = R.convert_currency("expenses", {**rec, "id": r["id"]}, r, taux)
                rec.pop("id")
            if mv and mv.get("journal") and mv["currency"] != rec["currency"]:
                raise ValueError("Ce mouvement possède une imputation de journal. Sa monnaie historique doit être conservée.")
            mouvement = {"kind": "expense", "date": rec["date"], "label": rec["label"], "direction": "out",
                         "amount": rec["amount"], "currency": rec["currency"], "account": compte,
                         "project": rec["project"], "invoice_id": "", "expense_id": "", "supplier_payment_id": "",
                         "supplier_reversal_id": ""}
            V.guard_legacy(projet)
            with db.transaction(f"Dépense {rec['label']}") as t:
                if r:
                    t.maj("expenses", r["id"], rec)
                    mouvement["expense_id"] = r["id"]
                    if mv:
                        t.maj("movements", mv["id"], mouvement)
                    else:
                        t.inserer("movements", {"id": db.nouvel_id(), **mouvement, "cree_le": db.maintenant()})
                else:
                    nid = db.nouvel_id()
                    t.inserer("expenses", {"id": nid, **rec})
                    mouvement["expense_id"] = nid
                    t.inserer("movements", {"id": db.nouvel_id(), **mouvement, "cree_le": db.maintenant()})
        except ValueError as e:
            st.error(str(e))
        else:
            ui.succes("Dépense enregistrée et inscrite au journal de caisse.")


def page() -> None:
    auth.exiger("depenses")
    ui.en_tete("Dépenses", "Matériaux, main-d’œuvre et frais de chantier. Chaque dépense crée une sortie de caisse.")
    s = R.charger("projects", "clients", "expenses", "movements")
    ecrit = auth.modifie("depenses")
    if ecrit and st.button("Nouvelle dépense", type="primary", icon=":material/add:"):
        if not s["projects"]:
            st.warning("Ajoutez d’abord un chantier.")
        else:
            formulaire()
    a, b, c = st.columns([2, 1, 1])
    with a:
        f_proj = ui.choix("Chantier", ui.options_chantiers(s), "dp_f_proj", "", vide="Tous les chantiers")
    with b:
        f_du = ui.date_txt("Du", "dp_f_du", vide_ok=True)
    with c:
        f_au = ui.date_txt("Au", "dp_f_au", vide_ok=True)
    pieces = pieces_par_depense()
    liste = [e for e in s["expenses"] if (not f_proj or e["project"] == f_proj) and (not f_du or e["date"] >= f_du)
             and (not f_au or e["date"] <= f_au)]
    liste.sort(key=lambda e: e["date"], reverse=True)
    ui.carte("Total des dépenses", ui.montants_html(R.totals_by_currency(liste, lambda e: e["amount"])),
             f"{len(liste)} dépense(s) pour ces critères", accent=True)
    if not liste:
        st.info("Gardez la trace de vos dépenses : affectez chaque achat ou frais à un chantier.")
        return
    comptes = {m["expense_id"]: m["account"] for m in s["movements"] if m["expense_id"]}
    rows = [{"_id": e["id"], "date": e["date"], "lib": e["label"], "cat": e["category"],
             "ch": R.project_name(s, e["project"]),
             "four": R.client_name(s, e["supplier_id"]) if e["supplier_id"] else "—",
             "mt": R.money(e["amount"], e["currency"]), "cpt": R.account_name(comptes.get(e["id"])),
             "just": R.money(justifie(pieces.get(e["id"], []), e["amount"]), e["currency"]),
             "np": len(pieces.get(e["id"], []))} for e in liste]
    i = ui.tableau(rows, {"date": "Date", "lib": "Libellé", "cat": "Catégorie", "ch": "Chantier",
                          "four": "Fournisseur", "mt": "Montant", "cpt": "Payé depuis", "just": "Justifié",
                          "np": st.column_config.NumberColumn("Pièces", format="%d")},
                   key="tab_dep", selection=True)
    if i is None:
        st.caption("Sélectionnez une dépense pour la modifier, la supprimer ou joindre ses justificatifs.")
        return
    e = next(x for x in s["expenses"] if x["id"] == rows[i]["_id"])
    st.subheader(e["label"])
    cols = ui.rangee(3)
    bloque = bool(pieces.get(e["id"]))
    if "justificatifs" in nav.PAGES and cols[0].button("Justificatifs", icon=":material/attach_file:", type="primary"):
        st.session_state["just_sel"] = e["id"]
        nav.aller("justificatifs")
    if ecrit:
        if bloque:
            cols[1].caption("Cette dépense possède des justificatifs : retirez-les avant de la modifier ou de la supprimer.")
        else:
            if cols[1].button("Modifier", icon=":material/edit:"):
                formulaire(e["id"])
            if cols[2].button("Supprimer", icon=":material/delete:"):
                st.session_state["dp_suppr"] = e["id"]
            if st.session_state.get("dp_suppr") == e["id"]:
                st.warning("Supprimer cette dépense et sa sortie du journal de caisse ?")
                o, n = ui.rangee(2)
                if o.button("Oui, supprimer", type="primary"):
                    with db.transaction(f"Suppression de la dépense {e['label']}") as t:
                        t.supprimer_ou("movements", db.movements.c.expense_id == e["id"])
                        t.supprimer("expenses", e["id"])
                    st.session_state.pop("dp_suppr", None)
                    ui.succes("Dépense supprimée.")
                if n.button("Annuler"):
                    st.session_state.pop("dp_suppr", None)
                    st.rerun()
