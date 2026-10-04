"""Devis et factures clients : prestations, impression PDF, conversion devis → facture, règlements."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import auth
import db
import pdf
import regles as R
import ui

NOMS = {"quotes": ("Devis", "devis", "DEVIS"), "invoices": ("Factures", "facture", "FACTURE")}


def document_pdf(kind: str, d: dict, s: dict) -> bytes:
    c = next((x for x in s["clients"] if x["id"] == d["client"]), {})
    lignes = [[l["description"], f"{l['qty']:g}".replace(".", ","), R.money(l["price"], d["currency"]),
               R.money(R.js_round(float(l["qty"]) * l["price"]), d["currency"])] for l in d["lines"]]
    tot = R.total(d)
    blocs = [("p", f"Date : {d['date']}" + (
        f" · {'Valable jusqu’au' if kind == 'quotes' else 'Échéance'} : {d['due']}" if d["due"] else ""))]
    blocs.append(("kv", [("Client", c.get("name", "")), ("Adresse", c.get("address", "")),
                         ("Téléphone", c.get("phone", ""))] + ([("Chantier", R.project_name(s, d["project"]))]
                                                               if d["project"] else [])))
    blocs.append(("table", ["Prestation", "Quantité", f"Prix unitaire ({d['currency']})", "Montant"],
                  lignes + [["", "", "Total", R.money(tot, d["currency"])]], {1, 2, 3}, None, True))
    if kind == "invoices":
        blocs.append(("kv", [("Reçu", R.money(d["paid"], d["currency"])),
                             ("Solde à payer", R.money(tot - d["paid"], d["currency"]))]))
    if d.get("notes"):
        blocs.append(("p", d["notes"]))
    blocs.append(("petit", f"Montants exprimés en {d['currency']}, sans calcul automatique de taxe."))
    snap = d.get("company_snapshot") or R.company_snapshot()
    return pdf.document(f"{NOMS[kind][2]} {d['number']}", snap, blocs,
                        auteur=(auth.utilisateur() or {}).get("nom", ""))


@st.dialog("Document", width="large")
def formulaire(kind: str, did: str | None = None) -> None:
    s = R.charger("clients", "projects", "quotes", "invoices")
    r = next((x for x in s[kind] if x["id"] == did), None) or {}
    k = f"{kind}_{did or 'new'}"
    st.markdown(f"#### {'Modifier' if r else 'Nouveau'} {NOMS[kind][1]}")
    a, b = st.columns(2)
    with a:
        monnaie = ui.devise("Monnaie", f"df_cur_{k}", r.get("currency"))
    taux = None
    if r and monnaie != r["currency"]:
        taux = b.number_input(f"Taux : 1 {r['currency']} = combien de {monnaie} ?", min_value=0.0, value=None,
                              format="%.6f", key=f"df_taux_{k}",
                              help="Les prix saisis ci-dessous (dans l'ancienne monnaie) seront convertis.")
    numero = a.text_input("Numéro *", value=r.get("number") or R.next_number([x["number"] for x in s[kind]], kind),
                          key=f"df_num_{k}")
    with b:
        client = ui.choix("Client *", ui.options_clients(s, r.get("client", "")), f"df_cli_{k}", r.get("client"),
                          vide="Choisir un client")
        projet = ui.choix("Chantier", ui.options_chantiers(s), f"df_proj_{k}", r.get("project", ""), vide="Sans chantier")
    c1, c2, c3 = st.columns(3)
    with c1:
        date = ui.date_txt("Date *", f"df_date_{k}", r.get("date"))
    with c2:
        due = ui.date_txt("Valable jusqu’au" if kind == "quotes" else "Échéance de paiement", f"df_due_{k}",
                          r.get("due"), vide_ok=True)
    statut = c3.selectbox("État", R.QUOTE_STATUSES, index=R.QUOTE_STATUSES.index(r.get("status", "Brouillon")),
                          key=f"df_st_{k}") if kind == "quotes" else "Brouillon"
    devise_saisie = r.get("currency", monnaie) if r else monnaie
    st.markdown(f"**Prestations** — prix unitaires en {devise_saisie}")
    base = pd.DataFrame([{"Description": l["description"], "Quantité": float(l["qty"]), "Prix unitaire": l["price"] / 100}
                         for l in (r.get("lines") or [{"description": "", "qty": 1, "price": 0}])])
    lignes = st.data_editor(base, num_rows="dynamic", width="stretch", key=f"df_lines_{k}", hide_index=True,
                            column_config={
                                "Description": st.column_config.TextColumn(required=True, max_chars=500),
                                "Quantité": st.column_config.NumberColumn(min_value=0.001, max_value=1e6, step=0.001,
                                                                          format="%.3f", required=True, default=1.0),
                                "Prix unitaire": st.column_config.NumberColumn(min_value=0.0, max_value=1e9, step=0.01,
                                                                               format="%.2f", required=True,
                                                                               default=0.0)})
    notes = st.text_area("Conditions / notes", value=r.get("notes", ""), key=f"df_notes_{k}", max_chars=10000)
    try:
        lines = []
        for _, l in lignes.iterrows():
            desc = str(l["Description"] or "").strip() if l["Description"] == l["Description"] else ""
            if not desc and (l["Prix unitaire"] != l["Prix unitaire"] or not l["Prix unitaire"]):
                continue  # ligne vide ignorée
            q = float(l["Quantité"]) if l["Quantité"] == l["Quantité"] else 0.0
            lines.append({"description": desc, "qty": q, "price": R.cents(l["Prix unitaire"] if
                                                                           l["Prix unitaire"] == l["Prix unitaire"] else 0,
                                                                           "Prix unitaire")})
        st.markdown(f"**Total : {R.money(R.total({'lines': lines}), devise_saisie)}**")
    except ValueError as e:
        st.error(str(e))
        lines = None
    st.caption("Montants dans la monnaie choisie, sans calcul automatique de taxe.")
    if st.button("Enregistrer", type="primary", key=f"df_ok_{k}"):
        try:
            if lines is None:
                raise ValueError("Vérifiez les prix des prestations.")
            if not lines:
                raise ValueError("Ajoutez au moins une prestation.")
            if len(lines) > 200:
                raise ValueError("Maximum 200 lignes par document.")
            if any(not l["description"] for l in lines):
                raise ValueError("Indiquez la description de chaque prestation.")
            if any(not 0 < l["qty"] <= 1e6 for l in lines):
                raise ValueError("Chaque quantité doit être positive.")
            if not client:
                raise ValueError("Choisissez un client.")
            if not numero.strip():
                raise ValueError("Indiquez un numéro.")
            if any(x["id"] != did and x["number"] == numero.strip() for x in s[kind]):
                raise ValueError("Ce numéro existe déjà. Choisissez un autre numéro.")
            rec = {"number": numero.strip(), "client": client, "project": projet or "", "date": date, "due": due,
                   "notes": notes.strip(), "status": statut, "lines": lines, "currency": monnaie}
            if kind == "invoices":
                rec["paid"] = r.get("paid", 0)
                rec["quote_id"] = r.get("quote_id", "")
                if rec["paid"] > R.total(rec):
                    raise ValueError("Le total ne peut pas être inférieur aux règlements déjà reçus.")
            if r:
                rec = R.convert_currency(kind, {**rec, "id": r["id"]}, r, taux)
                rec.pop("id")
                with db.transaction(f"Modification {NOMS[kind][1]} {rec['number']}") as t:
                    if kind == "invoices" and t.get(kind, r["id"], verrou=True)["paid"] != r["paid"]:
                        raise ValueError("Un règlement a été enregistré entre-temps sur cette facture. Fermez puis "
                                         "rouvrez-la avant de la modifier.")
                    if kind == "invoices" and r["currency"] != rec["currency"]:
                        _reaffecter_reglements(t, r, rec, taux)
                    t.maj(kind, r["id"], rec)
            else:
                rec["company_snapshot"] = R.company_snapshot()
                with db.transaction(f"Création {NOMS[kind][1]} {rec['number']}") as t:
                    t.inserer(kind, {"id": db.nouvel_id(), **rec})
        except ValueError as e:
            st.error(str(e))
        else:
            ui.succes("Enregistrement effectué.")


def _reaffecter_reglements(t, previous: dict, nxt: dict, rate: float) -> None:
    """Facture convertie : la part de chaque règlement imputée sur la facture est convertie ;
    le mouvement de trésorerie garde le montant et la monnaie réellement reçus."""
    lies = t.lire("select * from movements where invoice_id = :i order by cree_le, id", i=previous["id"])
    if sum(int(m["invoice_amount"] or 0) for m in lies) != previous["paid"]:
        raise ValueError("Les règlements de cette facture sont incohérents.")
    assigne = 0
    for i, m in enumerate(lies):
        conv = nxt["paid"] - assigne if i == len(lies) - 1 else R.js_round(int(m["invoice_amount"] or 0) * rate)
        if conv < 0:
            raise ValueError("Arrondi de conversion incompatible avec les règlements.")
        t.maj("movements", m["id"], {"invoice_amount": conv}, "Conversion de la facture")
        assigne += conv


@st.dialog("Enregistrer un règlement")
def reglement(did: str) -> None:
    d = db.un("invoices", did)
    reste = R.total(d) - d["paid"]
    st.markdown(f"Facture **{d['number']}** · reste à recevoir : **{R.money(reste, d['currency'])}**")
    montant = st.number_input(f"Montant reçu ({d['currency']})", min_value=0.01, max_value=reste / 100,
                              value=reste / 100, step=1.0, format="%.2f")
    date = ui.date_txt("Date du règlement", f"reg_date_{did}", max_aujourdhui=False)
    compte = ui.choix("Reçu sur", R.CASH_ACCOUNTS, f"reg_cpt_{did}", "cash")
    st.caption("Ce règlement sera inscrit une seule fois dans le journal de caisse.")
    if st.button("Enregistrer le règlement", type="primary"):
        try:
            a = R.cents(montant, "Montant", positif=True)
            with db.transaction(f"Règlement de la facture {d['number']}") as t:
                d2 = t.get("invoices", did, verrou=True)  # relu et verrouillé : deux saisies simultanées ne dépassent pas le solde
                if a > R.total(d2) - d2["paid"]:
                    raise ValueError("Le règlement doit être positif et ne pas dépasser le solde.")
                t.inserer("movements", {"id": db.nouvel_id(), "kind": "invoice", "date": date, "account": compte,
                                        "label": f"Règlement {d2['number']}", "direction": "in", "amount": a,
                                        "currency": d2["currency"], "project": d2["project"], "invoice_id": did,
                                        "invoice_amount": a, "expense_id": "", "supplier_payment_id": "",
                                        "supplier_reversal_id": "", "cree_le": db.maintenant()})
                t.maj("invoices", did, {"paid": d2["paid"] + a})
        except ValueError as e:
            st.error(str(e))
        else:
            ui.succes("Règlement et journal mis à jour.")


def page(kind: str) -> None:
    auth.exiger("commercial")
    titre = NOMS[kind][0]
    ui.en_tete(titre, "Préparez et imprimez vos propositions." if kind == "quotes"
               else "Suivez les montants facturés et les règlements.")
    s = R.charger("clients", "projects", "quotes", "invoices")
    ecrit = auth.modifie("commercial")
    if ecrit and st.button(f"Nouveau {NOMS[kind][1]}" if kind == "quotes" else "Nouvelle facture", type="primary",
                           icon=":material/add:"):
        if not ui.options_clients(s):
            st.warning("Ajoutez d’abord un client dans « Clients et fournisseurs ».")
        else:
            formulaire(kind)
    docs = sorted(s[kind], key=lambda d: (d["date"], d["number"]), reverse=True)
    if not docs:
        st.info("Ajoutez les prestations, les quantités et les prix unitaires de votre premier document.")
        return
    if kind == "invoices":
        st.html('<div style="display:flex;gap:16px;flex-wrap:wrap">' + "".join(
            f'<span class="bg-tag">{lbl} : <b>{ui._esc(ui.montants_texte(R.totals_by_currency(docs, fn), True))}</b></span>'
            for lbl, fn in (("Facturé", R.total), ("Reste à encaisser", lambda x: R.total(x) - x["paid"]))) + "</div>")
    rows = []
    for d in docs:
        row = {"_id": d["id"], "num": d["number"], "date": d["date"], "client": R.client_name(s, d["client"]),
               "chantier": R.project_name(s, d["project"]) if d["project"] else "—",
               "total": R.money(R.total(d), d["currency"])}
        if kind == "invoices":
            reste = R.total(d) - d["paid"]
            row.update(recu=R.money(d["paid"], d["currency"]), reste="Réglée" if reste == 0 else R.money(reste, d["currency"]),
                       echeance=d["due"] or "—")
        else:
            row["etat"] = d["status"] + (" · facturé" if any(i["quote_id"] == d["id"] for i in s["invoices"]) else "")
        rows.append(row)
    cols = {"num": "Document", "date": "Date", "client": "Client", "chantier": "Chantier", "total": "Total"}
    cols.update({"recu": "Reçu", "reste": "Reste à payer", "echeance": "Échéance"} if kind == "invoices"
                else {"etat": "État"})
    i = ui.tableau(rows, cols, key=f"tab_{kind}", selection=True)
    if i is None:
        st.caption("Sélectionnez un document pour l’imprimer, le modifier ou " +
                   ("le facturer." if kind == "quotes" else "enregistrer un règlement."))
        return
    d = next(x for x in s[kind] if x["id"] == rows[i]["_id"])
    st.subheader(f"{NOMS[kind][2].capitalize()} {d['number']}")
    b = ui.rangee(4)
    with b[0]:
        ui.telecharger("Imprimer / PDF", document_pdf(kind, d, s), f"{d['number']}.pdf", ui.MIME_PDF,
                       key=f"pdf_{d['id']}", principal=True)
    if ecrit and b[1].button("Modifier", icon=":material/edit:"):
        formulaire(kind, d["id"])
    if ecrit and kind == "quotes":
        if any(x["quote_id"] == d["id"] for x in s["invoices"]):
            b[2].caption("Une facture a déjà été créée pour ce devis.")
        elif b[2].button("Facturer ce devis", icon=":material/receipt_long:"):
            with db.transaction(f"Facturation du devis {d['number']}") as t:
                num = R.next_number([x["number"] for x in s["invoices"]], "invoices")
                t.inserer("invoices", {"id": db.nouvel_id(), "number": num, "client": d["client"],
                                       "project": d["project"], "date": R.today(), "due": "", "notes": d["notes"],
                                       "status": "Brouillon", "lines": d["lines"], "currency": d["currency"],
                                       "company_snapshot": d.get("company_snapshot") or R.company_snapshot(),
                                       "paid": 0, "quote_id": d["id"]})
            ui.succes(f"Facture {num} créée à partir du devis {d['number']}.")
    if ecrit and kind == "invoices":
        if R.total(d) - d["paid"] > 0:
            if b[2].button("Enregistrer un règlement", icon=":material/payments:"):
                reglement(d["id"])
        else:
            b[2].caption("Facture réglée.")
    st.dataframe(pd.DataFrame([{"Prestation": l["description"], "Quantité": l["qty"],
                                "Prix unitaire": R.money(l["price"], d["currency"]),
                                "Montant": R.money(R.js_round(float(l["qty"]) * l["price"]), d["currency"])}
                               for l in d["lines"]]), hide_index=True, width="stretch")
