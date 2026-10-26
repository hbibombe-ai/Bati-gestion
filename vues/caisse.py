"""Journal de caisse et trésorerie : entrées, sorties et soldes par compte et par monnaie."""
from __future__ import annotations

import datetime as dt

import streamlit as st

import auth
import caisses as CA
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
    compte_cpt = st.text_input("Compte comptable de contrepartie (SYSCOHADA)", value=v.get("compte", ""),
                               help="Facultatif : sans compte, la contrepartie reste au compte d’attente jusqu’à imputation. "
                                    "Changer ce compte contre-passe l’écriture et la refait sur le bon compte.")
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
            if compte_cpt.strip() and not compte_cpt.strip().isdigit():
                raise ValueError("Le compte comptable est un numéro (chiffres seulement).")
            rec = {**v, "piece": piece.strip(), "centre": centre or "", "imputation": imput.strip(), "invoiceRef": ref.strip(),
                   "compte": compte_cpt.strip(),
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
            ui.succes("Imputation enregistrée sans changer les soldes (écriture comptable mise à jour si la comptabilité "
                      "est démarrée).")


# ------------------------------------------------------------------ soldes, arrêtés et paramètres de caisse
def bandeau(au: str, compte: str = "all") -> None:
    """Solde de chaque caisse, dans sa propre devise (sans conversion), à la date choisie, avec son dernier mouvement."""
    liste = [c for c in CA.caisses(au) if compte == "all" or c["nature"] == compte]
    liste = [c for c in liste if c["nb"] or c["cle"].startswith("v7:")]
    if not liste:
        st.info("Aucun solde à afficher : saisissez le solde de départ de chaque caisse.")
        return
    st.markdown(f"**Solde de caisse au {au}**")
    for i in range(0, len(liste), 3):
        cols = st.columns(3)
        for col, c in zip(cols, liste[i:i + 3]):
            arr = CA.dernier_arrete(c["cle"])
            note = (f"Dernier mouvement : {c['dernier_date']} · {c['dernier_libelle'][:40]} · "
                    f"{'+' if c['dernier_montant'] >= 0 else ''}{R.money(c['dernier_montant'], c['devise'])}"
                    if c["nb"] else "Aucun mouvement")
            note += f" · arrêtée le {arr['date']}" if arr else " · jamais arrêtée"
            valeur = ui._esc(R.money(c["solde"], c["devise"]))
            if c["negatif"]:
                valeur = f'<span style="color:#b42318">{valeur}</span>'
            with col:
                ui.carte(f"{c['libelle']} · {c['devise']}", valeur, note, accent=c["nature"] == "cash")
    negatives = [c for c in liste if c["negatif"]]
    if negatives:
        st.error("Solde négatif : " + ", ".join(f"{c['libelle']} ({R.money(c['solde'], c['devise'])})"
                                                 for c in negatives)
                 + ". Une caisse ne peut pas sortir plus qu’elle ne contient : vérifiez le solde de départ et les "
                   "entrées non saisies.")


def _pv_pdf(a: dict) -> bytes:
    noms = {u["id"]: u["nom"] for u in db.tout("users")}
    lignes = [[R.plain(int(round(float(c) * 100))).rstrip("0").rstrip("."), str(n),
               R.money(int(round(float(c) * 100)) * int(n), a["devise"])]
              for c, n in sorted(a["billetage"].items(), key=lambda x: -float(x[0]))]
    if a["autres"]:
        lignes.append(["Pièces et autres", "", R.money(a["autres"], a["devise"])])
    return pdf.document(
        f"Procès-verbal d’arrêté de caisse du {a['date']}", R.company_snapshot(),
        [("kv", [("Caisse", a["libelle_caisse"]), ("Devise", a["devise"]), ("Date de l’arrêté", a["date"]),
                 ("Statut", a["statut"])]),
         ("h2", "Billetage"), ("table", ["Coupure", "Nombre", "Montant"], lignes, {1, 2}),
         ("kv", [("Montant compté", R.money(a["montant_compte"], a["devise"])),
                 ("Solde théorique (journal)", R.money(a["solde_theorique"], a["devise"])),
                 ("Écart", R.money(a["ecart"], a["devise"])), ("Explication", a["explication"] or "—")]),
         ("kv", [("Compté par", noms.get(a["saisi_par"], "")), ("Le", str(a["saisi_le"])[:16]),
                 ("Décision par", noms.get(a["decide_par"], "") or "—"), ("Le", str(a["decide_le"] or "")[:16] or "—"),
                 ("Motif", a["motif_decision"] or "—")]),
         ("espace", 12), ("p", "Signature du caissier : ______________________        "
                               "Signature du contrôleur : ______________________")],
        auteur=(auth.utilisateur() or {}).get("nom", ""))


def arretes() -> None:
    """Arrêté de caisse : le caissier compte les billets, l'application calcule l'écart, une autre personne valide."""
    valideur = auth.modifie("comptabilite") or auth.modifie("approbation_dg")
    liste = CA.caisses()
    if auth.modifie("tresorerie") and liste:
        noms = {c["cle"]: f"{c['libelle']} · {c['devise']}" for c in liste}
        a, b = st.columns(2)
        with a:
            k = ui.choix("Caisse à arrêter", noms, "ac_caisse", next(iter(noms)))
        with b:
            date_ = ui.date_txt("Date de l’arrêté", "ac_date", R.today(), max_aujourdhui=True)
        c = next(x for x in liste if x["cle"] == k)
        theorique = CA.solde(k, date_)
        st.caption(f"Solde théorique du journal au {date_} : {R.money(theorique, c['devise'])}. Saisissez les billets "
                   "comptés ; l’écart est calculé automatiquement.")
        coupures = CA.coupures(c["devise"])
        billets = {}
        for i in range(0, len(coupures), 5):
            cols = st.columns(5)
            for col, cp in zip(cols, coupures[i:i + 5]):
                billets[str(cp)] = col.number_input(f"{cp:,} {c['devise']}".replace(",", " "), min_value=0, step=1,
                                                    value=0, key=f"ac_b_{k}_{cp}")
        x, y = st.columns(2)
        with x:
            autres = ui.montant(f"Pièces et autres ({c['devise']})", f"ac_aut_{k}", 0)
        try:
            compte = CA.montant_billetage(billets, R.cents(autres or 0, "Complément"))
        except ValueError as e:
            st.error(str(e))
            return
        ecart = compte - theorique
        y.markdown(f"Compté : **{R.money(compte, c['devise'])}**  \nÉcart : **{R.money(ecart, c['devise'])}**"
                   + (" (manquant)" if ecart < 0 else " (excédent)" if ecart > 0 else " — caisse juste"))
        expl = st.text_input("Explication de l’écart" + (" *" if ecart else ""), key=f"ac_exp_{k}")
        if st.button("Soumettre le procès-verbal de comptage", type="primary", key="ac_ok"):
            try:
                CA.proposer_arrete(k, date_, billets, R.cents(autres or 0, "Complément"), expl)
            except ValueError as e:
                st.error(str(e))
            else:
                ui.succes("Procès-verbal soumis : il doit être validé par une autre personne (comptabilité ou DG).")
    tous = CA.arretes()
    if not tous:
        st.caption("Aucun arrêté de caisse enregistré.")
        return
    noms_u = {u["id"]: u["nom"] for u in db.tout("users")}
    lignes = [{"_id": a["id"], "date": a["date"], "caisse": a["libelle_caisse"], "dev": a["devise"],
               "theo": R.money(a["solde_theorique"], a["devise"]), "cpt": R.money(a["montant_compte"], a["devise"]),
               "ecart": R.money(a["ecart"], a["devise"]), "statut": a["statut"], "par": noms_u.get(a["saisi_par"], "")}
              for a in tous]
    i = ui.tableau(lignes, {"date": "Date", "caisse": "Caisse", "dev": "Devise", "theo": "Solde théorique",
                            "cpt": "Compté", "ecart": "Écart", "statut": "Statut", "par": "Compté par"},
                   key="tab_arretes", selection=True)
    if i is None:
        return
    a = next(x for x in tous if x["id"] == lignes[i]["_id"])
    ui.telecharger("Procès-verbal (PDF)", _pv_pdf(a), f"arrete-caisse-{a['date']}-{a['devise']}.pdf", ui.MIME_PDF,
                   key=f"pv_{a['id']}")
    if a["statut"] == "Proposé" and valideur:
        motif = st.text_input("Motif de la décision (obligatoire en cas de rejet)", key=f"ac_motif_{a['id']}")
        b1, b2 = ui.rangee(2)
        for bouton, valider in ((b1, True), (b2, False)):
            if bouton.button("Valider l’arrêté" if valider else "Rejeter", type="primary" if valider else "secondary",
                             key=f"ac_dec_{valider}_{a['id']}"):
                try:
                    CA.decider_arrete(a["id"], valider, motif)
                except ValueError as e:
                    st.error(str(e))
                else:
                    ui.succes("Arrêté validé" + (" : l’écart est régularisé et comptabilisé." if a["ecart"] else ".")
                              if valider else "Arrêté rejeté : le caissier doit recompter.")


def parametres_caisse() -> None:
    p = CA.parametres()
    st.caption("Décision de la DG, motivée et tracée. S’applique à toutes les saisies (écran, import, circuit V7).")
    with st.form("param_caisse"):
        st.markdown("**Interdire un solde négatif**")
        cols = st.columns(3)
        bloque = {n: cols[i].checkbox(lbl, value=bool((p["interdire_negatif"] or {}).get(n)), key=f"pc_neg_{n}")
                  for i, (n, lbl) in enumerate(R.CASH_ACCOUNTS.items())}
        st.markdown("**Coupures du billetage** (séparées par des virgules)")
        cols = st.columns(len(R.CURRENCIES))
        coup = {d: cols[i].text_input(d, ", ".join(str(x) for x in (p["coupures"] or {}).get(d, [])), key=f"pc_c_{d}")
                for i, d in enumerate(R.CURRENCIES)}
        a, b = st.columns(2)
        manquant = a.text_input("Compte des manquants de caisse", p["compte_manquant"])
        excedent = b.text_input("Compte des excédents de caisse", p["compte_excedent"])
        motif = st.text_input("Motif *")
        ok = st.form_submit_button("Enregistrer")
    if ok:
        try:
            coupures = {d: [int(x) for x in v.replace(" ", "").split(",") if x] for d, v in coup.items() if v.strip()}
            CA.configurer({"interdire_negatif": bloque, "coupures": coupures, "compte_manquant": manquant.strip(),
                           "compte_excedent": excedent.strip()}, motif)
        except ValueError as e:
            st.error(str(e) if "invalid literal" not in str(e) else "Coupures : nombres entiers seulement.")
        else:
            ui.succes("Paramètres de caisse enregistrés.")


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
    bandeau(au, compte)
    if mode == "cash":
        n_attente = sum(1 for a in CA.arretes() if a["statut"] == "Proposé")
        with st.expander("Arrêté de caisse" + (f" · {n_attente} en attente de validation" if n_attente else ""),
                         icon=":material/fact_check:", expanded=bool(n_attente) and auth.modifie("comptabilite")):
            arretes()
        if auth.modifie("approbation_dg"):
            with st.expander("Paramètres de caisse (DG)", icon=":material/tune:"):
                parametres_caisse()
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
