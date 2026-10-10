"""Journal de caisse et trésorerie : entrées, sorties et soldes par compte et par monnaie."""
from __future__ import annotations

import datetime as dt

import streamlit as st

import auth
import db
import gestion_v7 as V
import pdf
import regles as R
import ui

TITRES = {"cash": ("Journal de caisse", "Entrées, sorties et solde de vos comptes."),
          "treasury": ("Trésorerie", "Votre argent disponible, par période et par monnaie.")}


@st.dialog("Mouvement de trésorerie", width="large")
def mouvement(mid: str | None = None, direction: str = "in", ouverture: bool = False) -> None:
    s = R.charger("movements", "projects", "invoices")
    r = next((m for m in s["movements"] if m["id"] == mid), None)
    if r and r["kind"] == "v7":
        st.info("Mouvement du circuit V7 : utilisez sa contre-passation depuis Circuit financier V7.")
        return
    if r and (r["supplier_payment_id"] or r["supplier_reversal_id"]):
        st.error("Ce paiement fournisseur est lié à son compte tiers et ne peut pas être modifié directement.")
        return
    lie = bool(r and r["kind"] in ("invoice", "expense"))
    k = mid or f"new_{direction}_{ouverture}"
    a, b = st.columns(2)
    with a:
        date = ui.date_txt("Date de l’opération *", f"mv_date_{k}", (r or {}).get("date") or None)
    with b:
        compte = ui.choix("Compte *", R.CASH_ACCOUNTS, f"mv_cpt_{k}",
                          (r or {}).get("account") if (r or {}).get("account") in R.CASH_ACCOUNTS else "cash")
    libelle = st.text_input("Libellé *", value=(r or {}).get("label") or ("Solde de départ" if ouverture else ""),
                            key=f"mv_lib_{k}")
    if r:
        st.markdown(f"Montant : **{R.money(r['amount'], r['currency'])}** · "
                    f"{'Entrée' if r['direction'] == 'in' else 'Sortie'}"
                    + (f" · opération liée à {'une facture' if r['kind'] == 'invoice' else 'une dépense'}" if lie else ""))
        montant = None if lie else ui.montant(f"Montant ({r['currency']})", f"mv_mt_{k}", r["amount"])
        if lie:
            st.caption("Le montant reste lié à son document d’origine. Vous pouvez préciser ici le compte et la date réelle.")
    else:
        c1, c2, c3 = st.columns(3)
        with c1:
            monnaie = ui.devise("Monnaie", f"mv_cur_{k}")
        with c2:
            montant = ui.montant("Montant *", f"mv_mt_{k}", 0)
        sens = c3.selectbox("Solde positif ou négatif" if ouverture else "Sens", ["in", "out"],
                            index=0 if direction == "in" else 1, key=f"mv_sens_{k}",
                            format_func=lambda x: ("Positif" if x == "in" else "Négatif") if ouverture
                            else ("Entrée" if x == "in" else "Sortie"))
        projet = ui.choix("Chantier (facultatif)", ui.options_chantiers(s), f"mv_proj_{k}", "", vide="Sans chantier")
        if not ouverture:
            st.caption("Pour une facture ou une dépense déjà saisie, utilisez son règlement ou sa modification afin "
                       "d’éviter un doublon.")
    if st.button("Enregistrer", type="primary"):
        try:
            if not R.is_date(date) or compte not in R.CASH_ACCOUNTS or not libelle.strip():
                raise ValueError("La date, le compte et le libellé sont obligatoires.")
            if r:
                vals = {"date": date, "account": compte, "label": libelle.strip()}
                if not lie:
                    vals["amount"] = R.cents(montant, "Montant", positif=True)
                V.guard_legacy(r['project'] if r else projet)
                with db.transaction(f"Mouvement « {libelle.strip()} »") as t:
                    t.maj("movements", r["id"], vals)
                    if r["expense_id"]:
                        t.maj("expenses", r["expense_id"], {"date": date})
            else:
                mt = R.cents(montant, "Montant", positif=True)
                kind = "opening" if ouverture else "manual"
                V.guard_legacy(r['project'] if r else projet)
                with db.transaction(f"Mouvement « {libelle.strip()} »") as t:
                    if ouverture and t.lire("select id from movements where kind = 'opening' and account = :a and "
                                            "currency = :c", a=compte, c=monnaie):
                        raise ValueError("Un solde de départ existe déjà pour ce compte et cette monnaie.")
                    t.inserer("movements", {"id": db.nouvel_id(), "kind": kind, "date": date, "account": compte,
                                            "label": libelle.strip(), "direction": sens, "amount": mt,
                                            "currency": monnaie, "project": projet or "", "invoice_id": "",
                                            "invoice_amount": None, "expense_id": "", "supplier_payment_id": "",
                                            "supplier_reversal_id": "", "cree_le": db.maintenant()})
        except ValueError as e:
            st.error(str(e))
        else:
            ui.succes("Mouvement enregistré.")


@st.dialog("Imputation et pièce du journal", width="large")
def imputation(mid: str) -> None:
    s = R.charger("movements", "projects", "invoices", "erp_dossiers")
    m = next(x for x in s["movements"] if x["id"] == mid)
    v = m.get("journal") or {}
    st.markdown(f"{m['label']} · **{R.money(m['amount'], m['currency'])}** · {m['date'] or 'date à compléter'}")
    centres = {c["id"]: R.link_label(c) for c in s["erp_dossiers"] if c["type"] == "centres"}
    a, b = st.columns(2)
    piece = a.text_input("N° pièce *", value=v.get("piece") or R.next_journal_piece(s["movements"], m["date"] or None))
    with b:
        centre = ui.choix("Centre de coût (obligatoire hors chantier)", centres, f"jv_c_{mid}", v.get("centre", ""),
                          vide="Non renseigné")
    imput = st.text_input("Imputation : activité / poste / nature *", value=v.get("imputation", ""))
    fac = next((i["number"] for i in s["invoices"] if i["id"] == m["invoice_id"]), "")
    a, b = st.columns(2)
    ref = a.text_input("Référence facture", value=v.get("invoiceRef") or fac)
    with b:
        rep = ui.devise("Monnaie de contre-valeur", f"jv_rep_{mid}", v.get("reportingCurrency") or m["currency"])
    taux = a.number_input(f"Taux historique : 1 {m['currency']} = … en contre-valeur", min_value=0.0,
                          value=v.get("rate"), format="%.8f", help="Information historique : ne modifie ni le montant "
                                                                   "ni le solde du journal.")
    remarques = b.text_input("Observations", value=v.get("remarks", ""))
    st.caption("Une sortie reste à justifier jusqu’au contrôle des pièces par la finance ou la direction.")
    if st.button("Enregistrer l’imputation", type="primary"):
        try:
            rec = {**v, "piece": piece.strip(), "centre": centre or "", "imputation": imput.strip(), "invoiceRef": ref.strip(),
                   "remarks": remarques.strip(), "reportingCurrency": rep, "rate": float(taux) if taux else None}
            if not rec["piece"] or not rec["imputation"]:
                raise ValueError("Le numéro de pièce et l’imputation sont obligatoires.")
            if not m["project"] and not rec["centre"]:
                raise ValueError("Choisissez un centre de coût pour cette opération hors chantier.")
            if any(x["id"] != mid and (x.get("journal") or {}).get("piece") == rec["piece"] for x in s["movements"]):
                raise ValueError("Ce numéro de pièce est déjà utilisé.")
            if rep == m["currency"] and rec["rate"] not in (None, 1.0):
                raise ValueError("Pour une même monnaie, le taux est 1 (ou laissez-le vide).")
            with db.transaction(f"Imputation du mouvement « {m['label']} »") as t:
                t.maj("movements", mid, {"journal": rec})
        except ValueError as e:
            st.error(str(e))
        else:
            ui.succes("Imputation enregistrée sans changer les soldes.")


def page(mode: str) -> None:
    auth.exiger("tresorerie")
    titre, sous = TITRES[mode]
    ui.en_tete(titre, sous)
    s = R.charger("movements", "projects", "invoices", "erp_dossiers", "clients")
    ecrit = auth.modifie("tresorerie")
    debut_mois = dt.date.today().replace(day=1).isoformat()
    a, b, c, d = st.columns(4)
    with a:
        du = ui.date_txt("Du", f"cs_du_{mode}", debut_mois)
    with b:
        au = ui.date_txt("Au", f"cs_au_{mode}", R.today())
    with c:
        monnaie = ui.devise("Monnaie du rapport", f"cs_cur_{mode}")
    with d:
        compte = ui.choix("Compte", {"all": "Tous les comptes", **R.CASH_ACCOUNTS}, f"cs_cpt_{mode}",
                          "cash" if mode == "cash" else "all")
    f = {"from": du, "to": au, "currency": monnaie, "account": compte}
    try:
        rep = R.cash_summary(s["movements"], f, s["company"]["defaultCurrency"])
    except ValueError as e:
        st.error(str(e))
        return
    if ecrit:
        bt = ui.rangee(3)
        if bt[0].button("Entrée", icon=":material/add:", type="primary"):
            mouvement(direction="in")
        if bt[1].button("Sortie", icon=":material/remove:"):
            mouvement(direction="out")
        if bt[2].button("Solde de départ", icon=":material/flag:"):
            mouvement(ouverture=True)
    st.caption("Entrées et sorties effectivement enregistrées. Les soldes de départ saisis dans la période apparaissent "
               "dans ses entrées ou sorties.")
    cs = st.columns(4)
    for col, (lbl, val) in zip(cs, [("Solde avant la période", rep["opening"]), ("Entrées de la période", rep["incoming"]),
                                    ("Sorties de la période", rep["outgoing"]), ("Solde en fin de période", rep["closing"])]):
        with col:
            ui.carte(lbl, ui._esc(R.money(val, rep["currency"])), accent=lbl.startswith("Solde en fin"))
    if rep["pending"]:
        with st.expander(f"{len(rep['pending'])} mouvement(s) historique(s) à compléter", icon=":material/warning:"):
            st.write("Les anciennes données ne précisent pas toujours la date ou le compte utilisé. Ces mouvements ne "
                     "sont pas inclus dans les soldes ci-dessus. Complétez-les sans créer une nouvelle opération.")
            for m in rep["pending"]:
                x, y = st.columns([4, 1])
                x.write(f"{m['label']} · {'Entrée' if m['direction'] == 'in' else 'Sortie'} · "
                        f"{R.money(m['amount'], m['currency'])}")
                if ecrit and y.button("Compléter", key=f"cpl_{m['id']}"):
                    mouvement(m["id"])

    # lignes avec solde progressif
    solde = rep["opening"]
    lignes = []
    for n, m in enumerate(rep["rows"], 1):
        solde += m["amount"] if m["direction"] == "in" else -m["amount"]
        v = m.get("journal") or {}
        lignes.append({"_id": m["id"], "n": n, "date": m["date"], "imp": R.journal_imputation(m, s), "lib": m["label"],
                       "cpt": R.account_name(m["account"]),
                       "taux": f"1 {m['currency']} = {v['rate']:g} {v['reportingCurrency']}" if v.get("rate") else "Non renseigné",
                       "ref": v.get("invoiceRef", ""),
                       "ent": R.money(m["amount"], m["currency"]) if m["direction"] == "in" else "—",
                       "sor": R.money(m["amount"], m["currency"]) if m["direction"] == "out" else "—",
                       "solde": R.money(solde, m["currency"]),
                       "obs": " · ".join(x for x in [v.get("remarks", ""), v.get("piece") or "Pièce à attribuer",
                                                      "À justifier" if m["direction"] == "out" else ""] if x)})
    entetes = ["N°", "Date", "Imputation", "Libellé", "Compte", "Taux historique", "Réf. facture", "Entrée", "Sortie",
               "Solde", "Observations / pièce"]
    cles = ["n", "date", "imp", "lib", "cpt", "taux", "ref", "ent", "sor", "solde", "obs"]
    nom_cpt = "Tous les comptes" if compte == "all" else R.account_name(compte)
    x1, x2 = ui.rangee(2)
    csv_rows = [["N°", "Date", "Imputation", "Libellé", "Compte", "Monnaie", "Taux", "Monnaie de contre-valeur",
                 "Référence facture", "Entrée", "Sortie", "Solde", "Observations", "N° pièce"],
                ["", "", "", "Solde avant période", "", rep["currency"], "", "", "", "", "", R.plain(rep["opening"]), "", ""]]
    solde = rep["opening"]
    for n, m in enumerate(rep["rows"], 1):
        solde += m["amount"] if m["direction"] == "in" else -m["amount"]
        v = m.get("journal") or {}
        csv_rows.append([n, m["date"], R.journal_imputation(m, s), m["label"], R.account_name(m["account"]), m["currency"],
                         v.get("rate") or "", v.get("reportingCurrency", ""), v.get("invoiceRef", ""),
                         R.plain(m["amount"]) if m["direction"] == "in" else "",
                         R.plain(m["amount"]) if m["direction"] == "out" else "", R.plain(solde), v.get("remarks", ""),
                         v.get("piece", "")])
    with x1:
        ui.telecharger("Exporter CSV", R.to_csv(csv_rows), f"journal-{rep['currency']}-{du}-{au}.csv", ui.MIME_CSV,
                       key=f"csv_{mode}")
    with x2:
        ui.telecharger("Imprimer / PDF", pdf.document(
            titre, R.company_snapshot(),
            [("p", f"Du {du} au {au} · {rep['currency']} · {nom_cpt}"),
             ("table", ["Solde avant", "Entrées", "Sorties", "Solde final"],
              [[R.money(x, rep["currency"]) for x in (rep["opening"], rep["incoming"], rep["outgoing"], rep["closing"])]],
              {0, 1, 2, 3}),
             ("petit", f"{len(rep['pending'])} mouvement(s) historique(s) incomplet(s) exclus de ce rapport."),
             ("table", entetes, [[l[k] for k in cles] for l in lignes], {7, 8, 9})],
            paysage=True, auteur=auth.utilisateur()["nom"]), f"{mode}-{rep['currency']}-{du}-{au}.pdf", ui.MIME_PDF,
            key=f"pdf_{mode}")

    if mode == "treasury":
        st.subheader("Situation par compte")
        comptes = R.CASH_ACCOUNTS if compte == "all" else {compte: R.CASH_ACCOUNTS[compte]}
        par = []
        for cid, lbl in comptes.items():
            r2 = R.cash_summary(s["movements"], {**f, "account": cid}, s["company"]["defaultCurrency"])
            par.append({"cpt": lbl, "av": R.money(r2["opening"], monnaie), "en": R.money(r2["incoming"], monnaie),
                        "so": R.money(r2["outgoing"], monnaie), "fin": R.money(r2["closing"], monnaie)})
        ui.tableau(par, {"cpt": "Compte", "av": "Solde avant", "en": "Entrées", "so": "Sorties", "fin": "Solde final"},
                   key="tab_par_compte")
        if auth.voit("commercial"):
            st.subheader("Factures restant à encaisser aujourd’hui")
            st.caption("Ces montants ne sont pas encore de l’argent disponible. Liste actuelle, indépendante de la période.")
            ouvertes = [i for i in s["invoices"] if i["currency"] == monnaie and R.total(i) > i["paid"]]
            if ouvertes:
                ui.tableau([{"f": i["number"], "c": R.client_name(s, i["client"]), "e": i["due"] or "Non précisée",
                             "r": R.money(R.total(i) - i["paid"], i["currency"])} for i in ouvertes],
                           {"f": "Facture", "c": "Client", "e": "Échéance", "r": "Reste"}, key="tab_ouvertes")
            else:
                st.caption("Aucune facture en attente dans cette monnaie.")
        return

    st.subheader("Mouvements de la période")
    if not lignes:
        st.info("Aucun mouvement pour ces filtres. Saisissez votre solde de départ ou une première opération.")
        return
    i = ui.tableau(lignes, dict(zip(cles, entetes)), key="tab_journal", selection=True)
    if i is None or not ecrit:
        if ecrit:
            st.caption("Sélectionnez un mouvement pour compléter son imputation ou le modifier.")
        return
    m = next(x for x in rep["rows"] if x["id"] == lignes[i]["_id"])
    b1, b2 = ui.rangee(2)
    if b1.button("Compléter l’imputation", icon=":material/edit_note:", type="primary"):
        imputation(m["id"])
    if m["supplier_payment_id"] or m["supplier_reversal_id"]:
        b2.caption("Paiement fournisseur : à corriger depuis « Comptes tiers » (contre-passation).")
    elif b2.button("Modifier le mouvement", icon=":material/edit:"):
        mouvement(m["id"])
