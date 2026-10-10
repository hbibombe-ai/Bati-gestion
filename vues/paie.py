"""Paie : préparation des bulletins, états de paie par mois. Aucun taux légal n'est appliqué automatiquement."""
from __future__ import annotations

import datetime as dt

import streamlit as st

import auth
import db
import pdf
import regles as R
import ui


def mois_options(n: int = 30) -> list[str]:
    d = dt.date.today().replace(day=1)
    out = []
    y, m = d.year, d.month + 1
    for _ in range(n):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append(f"{y}-{m:02d}")
    nxt = (d + dt.timedelta(days=32)).replace(day=1)
    return [f"{nxt.year}-{nxt.month:02d}"] + out


def bulletin_pdf(r: dict, s: dict) -> bytes:
    t = R.payroll_totals(r)
    e = r.get("elements") or {}
    cur = r["currency"]
    lignes = [[f"Base : {r['quantity']:g} × {R.money(r['rate'], cur)} / {r['period'].lower()}", R.money(t["base"], cur)]]
    lignes += [[lbl, R.money(e.get(k, 0), cur)] for k, lbl in R.PAY_FIELDS + R.PAY_V7_EXTRA]
    lignes += [["Brut proposé", R.money(t["gross"], cur)], ["Total des retenues", R.money(t["deductions"], cur)],
               ["Net proposé", R.money(t["net"], cur)],
               ["Charges employeur (non déduites du net)", R.money(t["employer"], cur)],
               ["Coût employeur proposé", R.money(t["cost"], cur)]]
    blocs = [("kv", [("Référence", r["id"][:8]), ("Mois", r["month"]), ("Préparé le", r["prepared"]),
                     ("Employé", f"{r['name']} · matricule {r['code']}"), ("Fonction", r["job"]),
                     ("Affectation", R.hr_place_label(r, s)), ("Mode de paiement prévu", R.account_name(r["method"]))]),
             ("table", ["Élément", f"Montant ({cur})"], lignes, {1})]
    p = r.get("employee_snapshot")
    if p:
        blocs.append(("h2", "Informations salarié"))
        blocs.append(("kv", [(lbl, p.get(k, "")) for k, lbl in R.HR_V7_FIELDS] + [
            ("Service", p.get("service", "")), ("Date d’engagement", p.get("start", "")),
            ("Ancienneté à la fin du mois", f"{R.seniority_months(r['month'], p['start'])} mois" if p.get("start") else ""),
            ("Enfants", "Non renseigné" if p.get("children") is None else str(p["children"]))]))
    if r.get("rules"):
        blocs.append(("h2", "Paramètres mémorisés"))
        blocs.append(("table", ["Rubrique", "Mode", "Assiette", "Taux"],
                      [[lbl, "Assiette × taux" if r["rules"][k]["mode"] == "rate" else "Montant saisi",
                        R.money(r["rules"][k]["base"], cur) if r["rules"][k]["mode"] == "rate" else "—",
                        f"{r['rules'][k]['rate']} %" if r["rules"][k]["mode"] == "rate" else "—"]
                       for k, lbl in R.PAY_RATE_FIELDS if k in r["rules"]]))
    if r.get("notes"):
        blocs.append(("p", r["notes"]))
    blocs.append(("mention", "DOCUMENT PRÉPARATOIRE — NON VALIDÉ, NON PAYÉ"))
    blocs.append(("petit", "Montants saisis manuellement. Calculs fiscaux et sociaux RDC à contrôler. Ce document ne vaut "
                           "pas preuve de paiement."))
    return pdf.document("Bulletin de paie — préparation", r.get("company_snapshot") or R.company_snapshot(), blocs,
                        auteur=auth.utilisateur()["nom"])


@st.dialog("Préparer la paie", width="large")
def formulaire(person_id: str, rid: str | None = None) -> None:
    s = R.charger("personnel", "projects", "payroll")
    person = next(p for p in s["personnel"] if p["id"] == person_id)
    r = next((x for x in s["payroll"] if x["id"] == rid), None) or {}
    e = r.get("elements") or {}
    sal = person.get("salary") or {}
    k = rid or f"new_{person_id}"
    st.markdown(f"**{person['name']}** · {person['code']} · {person['job']}")
    st.caption("Les champs de primes et de retenues sont des montants, pas des taux. Renseignez les montants contrôlés "
               "pour la période.")
    a, b, c = st.columns(3)
    mois_l = mois_options()
    mois = a.selectbox("Mois de paie", mois_l if not r or r["month"] in mois_l else [r["month"]] + mois_l,
                       index=(mois_l.index(r["month"]) if r and r["month"] in mois_l else (0 if r else 1)), key=f"py_m_{k}")
    with b:
        cur = ui.devise("Monnaie", f"py_cur_{k}", r.get("currency") or sal.get("currency"))
    periode = c.selectbox("Base", R.HR_PAY_PERIODS, index=R.HR_PAY_PERIODS.index(r.get("period") or sal.get("period") or "Mois"),
                          key=f"py_per_{k}")
    with a:
        taux = ui.montant("Tarif brut de base *", f"py_rate_{k}", r["rate"] if r else sal.get("amount", 0))
    qte = b.number_input("Quantité : mois, jours ou heures *", min_value=0.01, max_value=1000.0, step=0.5,
                         value=float(r.get("quantity", 1)), key=f"py_q_{k}")
    vals = {}
    st.markdown("**Primes et retenues**")
    cols = st.columns(4)
    for n, (cle, lbl) in enumerate(R.PAY_FIELDS + R.PAY_V7_EXTRA):
        with cols[n % 4]:
            vals[cle] = ui.montant(lbl, f"py_{cle}_{k}", e.get(cle, 0))
    regles = {}
    with st.expander("Calculs par taux — paramètres à vérifier"):
        st.caption("Sans taux prédéfini. Pour chaque rubrique, choisissez un montant saisi ou une assiette × un taux. "
                   "Vérifiez les assiettes, plafonds, tranches et règles applicables avec votre responsable paie.")
        for cle, lbl in R.PAY_RATE_FIELDS:
            rule = (r.get("rules") or {}).get(cle) or {}
            x, y, z = st.columns(3)
            mode = x.selectbox(lbl, ["amount", "rate"], index=0 if rule.get("mode", "amount") == "amount" else 1,
                               format_func=lambda m: "Montant saisi" if m == "amount" else "Assiette × taux",
                               key=f"py_mode_{cle}_{k}")
            with y:
                base = ui.montant("Assiette", f"py_base_{cle}_{k}", rule.get("base", 0))
            tx = z.number_input("Taux (%)", min_value=0.0, max_value=100.0, value=rule.get("rate"), format="%.4f",
                                key=f"py_tx_{cle}_{k}")
            regles[cle] = (mode, base, tx)
    a, b = st.columns(2)
    with a:
        methode = ui.choix("Mode de paiement prévu", R.CASH_ACCOUNTS, f"py_meth_{k}",
                           r.get("method") or (person.get("v7") or {}).get("paymentMethod") or "bank")
    lieux = {"bureau": "Bureau", **{f"project:{p['id']}": p["name"] for p in s["projects"]}}
    courant = r.get("location") or person["location"]
    defaut = f"project:{r.get('project', person['project'])}" if courant == "Chantier" else "bureau"
    lieu = b.selectbox("Affectation de la paie", list(lieux), format_func=lieux.get,
                       index=list(lieux).index(defaut) if defaut in lieux else 0, key=f"py_lieu_{k}")
    notes = st.text_input("Observations / détail des retenues", value=r.get("notes", ""), key=f"py_notes_{k}")
    try:
        apercu = {"rate": R.cents(taux), "quantity": qte, "elements": {c_: R.cents(v) for c_, v in vals.items()}}
        for cle, (mode, base, tx) in regles.items():
            if mode == "rate" and tx is not None:
                apercu["elements"][cle] = R.payroll_rate_amount(R.cents(base), tx) or 0
        t = R.payroll_totals(apercu)
        st.info(f"Brut proposé : **{R.money(t['gross'], cur)}** · retenues : {R.money(t['deductions'], cur)} · "
                f"net proposé : **{R.money(t['net'], cur)}** · coût employeur : {R.money(t['cost'], cur)}")
    except ValueError:
        pass
    st.caption("Les jours et heures sont saisis ; ils ne sont pas calculés depuis le pointage.")
    if st.button("Enregistrer la préparation", type="primary"):
        try:
            rec = {"person_id": person_id, "month": mois, "name": r.get("name") or person["name"],
                   "code": r.get("code") or person["code"], "job": r.get("job") or person["job"], "currency": cur,
                   "period": periode, "quantity": float(qte), "rate": R.cents(taux, "Tarif"), "method": methode,
                   "notes": notes.strip(), "location": "Bureau" if lieu == "bureau" else "Chantier",
                   "project": lieu[8:] if lieu.startswith("project:") else "", "prepared": R.today(),
                   "status": "Préparation"}
            elements = {c_: R.cents(v, lbl) for (c_, lbl), v in zip(R.PAY_FIELDS + R.PAY_V7_EXTRA, vals.values())}
            rules = {}
            for cle, (mode, base, tx) in regles.items():
                rules[cle] = {"mode": mode, "base": R.cents(base, "Assiette"), "rate": tx}
                if mode == "rate":
                    if tx is None:
                        raise ValueError(f"Renseignez le taux pour {dict(R.PAY_RATE_FIELDS)[cle]}.")
                    calc = R.payroll_rate_amount(rules[cle]["base"], tx)
                    if calc is None:
                        raise ValueError("Taux invalide : quatre décimales au maximum, entre 0 et 100 %.")
                    elements[cle] = calc
            rec["elements"] = elements
            rec["rules"] = rules
            if not rec["quantity"] > 0:
                raise ValueError("La quantité doit être positive.")
            if mois < person["start"][:7]:
                raise ValueError("Le mois précède la date d’engagement.")
            if not r and sal and mois < sal.get("effective", "")[:7]:
                raise ValueError("Le salaire enregistré prend effet après ce mois. Vérifiez et mettez à jour la fiche "
                                 "salariale avant préparation.")
            if any(v > 10**12 for v in list(rec["elements"].values()) + [rec["rate"]]) or \
                    any(v > 10**12 for v in R.payroll_totals(rec).values()):
                raise ValueError("Un montant dépasse la limite autorisée.")
            if R.payroll_totals(rec)["net"] < 0:
                raise ValueError("Les retenues dépassent le brut. Vérifiez les montants.")
            if any(x["id"] != rid and x["person_id"] == person_id and x["month"] == mois for x in s["payroll"]):
                raise ValueError("Une préparation existe déjà pour cet employé et ce mois. Modifiez-la depuis la liste.")
            with db.transaction(f"Paie {mois} de {person['name']}") as t:
                if r:
                    t.maj("payroll", rid, rec)
                else:
                    v7 = person.get("v7") or {}
                    rec["employee_snapshot"] = {**{c_: v7.get(c_, "") for c_, _ in R.HR_V7_FIELDS},
                                                "children": v7.get("children"), "start": person["start"],
                                                "service": person["service"]}
                    rec["company_snapshot"] = R.company_snapshot()
                    t.inserer("payroll", {"id": db.nouvel_id(), **rec})
        except ValueError as err:
            st.error(str(err))
        else:
            ui.succes("Préparation enregistrée. Le bulletin est disponible dans la liste.")


def page() -> None:
    auth.exiger("paie")
    ui.en_tete("Paie", "Préparation des bulletins et états de paie. Aucun taux légal n’est appliqué automatiquement.")
    s = R.charger("personnel", "projects", "payroll")
    ecrit = auth.modifie("paie")
    actifs = {p["id"]: f"{p['name']} ({p['code']})" for p in s["personnel"] if p["active"]}
    if ecrit:
        if not actifs:
            st.info("Ajoutez d’abord le personnel dans « Personnel et pointage ».")
        else:
            a, b = st.columns([2, 1])
            pre = st.session_state.pop("paie_personne", None)
            with a:
                pid = ui.choix("Employé", actifs, "py_choix", pre or next(iter(actifs)))
            b.html("<div style='height:1.75rem'></div>")
            if b.button("Préparer la paie", type="primary", icon=":material/add:") or pre:
                formulaire(pid)
    st.subheader("États de paie")
    mois_dispo = sorted({r["month"] for r in s["payroll"]}, reverse=True)
    a, b, c = st.columns([1, 1, 1])
    mois = a.selectbox("Période des états", [""] + mois_dispo, format_func=lambda m: m or "Toutes les périodes")
    rows = [r for r in s["payroll"] if not mois or r["month"] == mois]
    if rows:
        sommes = {c_: {k: 0 for k in ("gross", "deductions", "net", "employer", "cost")} for c_ in R.CURRENCIES}
        for r in rows:
            t = R.payroll_totals(r)
            for k in sommes[r["currency"]]:
                sommes[r["currency"]][k] += t[k]
        etat = [[r["month"], f"{r['code']} {r['name']}", f"{R.hr_place_label(r, s)} {(r.get('employee_snapshot') or {}).get('service', '')}",
                 R.account_name(r["method"])] + [R.money(R.payroll_totals(r)[k], r["currency"])
                                                 for k in ("gross", "deductions", "net", "employer", "cost")] for r in rows]
        with b:
            ui.telecharger("État de paie / PDF", pdf.document(
                "État préparatoire de paie", R.company_snapshot(),
                [("p", f"Période : {mois or 'toutes les périodes'} — NON VALIDÉ, NON PAYÉ"),
                 ("table", ["Mois", "Matricule / salarié", "Affectation / service", "Mode prévu", "Brut", "Retenues",
                            "Net", "Charges employeur", "Coût employeur"], etat, {4, 5, 6, 7, 8}),
                 ("h2", "Totaux séparés par monnaie"),
                 ("table", ["Monnaie", "Brut", "Retenues", "Net", "Charges employeur", "Coût employeur"],
                  [[c_] + [R.money(sommes[c_][k], c_) for k in ("gross", "deductions", "net", "employer", "cost")]
                   for c_ in R.CURRENCIES], {1, 2, 3, 4, 5}),
                 ("petit", "Ces coûts proposés ne sont pas comptabilisés ni payés. Les règles et taux saisis doivent être "
                           "contrôlés.")], paysage=True, auteur=auth.utilisateur()["nom"]),
                f"etat-paie-{mois or 'toutes-periodes'}.pdf", ui.MIME_PDF, key="py_etat_pdf")
        with c:
            ui.telecharger("État de paie CSV", R.to_csv(
                [["Mois", "Matricule", "Salarié", "Affectation", "Service", "Mode prévu", "Monnaie", "Brut", "Retenues",
                  "Net", "Charges employeur", "Coût employeur", "Statut"]]
                + [[r["month"], r["code"], r["name"], R.hr_place_label(r, s), (r.get("employee_snapshot") or {}).get("service", ""),
                    R.account_name(r["method"]), r["currency"]]
                   + [R.plain(R.payroll_totals(r)[k]) for k in ("gross", "deductions", "net", "employer", "cost")]
                   + ["Préparation non validée"] for r in rows]),
                f"etat-paie-{mois or 'toutes-periodes'}.csv", ui.MIME_CSV, key="py_etat_csv")
        st.markdown("**Totaux par monnaie** — " + " · ".join(
            f"{c_} : net {R.money(sommes[c_]['net'], c_)}, coût {R.money(sommes[c_]['cost'], c_)}"
            for c_ in R.CURRENCIES if sommes[c_]["cost"]))
    st.subheader("Préparations")
    if not rows:
        st.info("Aucune paie préparée. Choisissez un employé puis « Préparer la paie ».")
        return
    lignes = [{"_id": r["id"], "m": r["month"], "e": r["name"], "c": r["code"],
               "b": R.money(R.payroll_totals(r)["gross"], r["currency"]),
               "n": R.money(R.payroll_totals(r)["net"], r["currency"]), "s": "Préparation"}
              for r in sorted(rows, key=lambda r: (r["month"], r["name"]), reverse=True)]
    i = ui.tableau(lignes, {"m": "Mois", "e": "Employé", "c": "Matricule", "b": "Brut proposé", "n": "Net proposé",
                            "s": "Statut"}, key="tab_paie", selection=True)
    if i is None:
        st.caption("Sélectionnez une préparation pour la modifier ou éditer son bulletin.")
        return
    r = next(x for x in rows if x["id"] == lignes[i]["_id"])
    x1, x2, x3 = ui.rangee(3)
    with x1:
        ui.telecharger("Bulletin / PDF", bulletin_pdf(r, s), f"bulletin-{r['month']}-{r['code']}.pdf", ui.MIME_PDF,
                       key=f"bul_{r['id']}", principal=True)
    t = R.payroll_totals(r)
    e = r.get("elements") or {}
    with x2:
        ui.telecharger("Exporter CSV", R.to_csv([
            ["Référence", "Mois", "Matricule", "Employé", "Monnaie", "Base", "Primes", "Indemnités", "HS", "Absences",
             "Avances", "Cotisations", "Impôt", "Autres retenues", "Brut", "Retenues", "Net"]
            + [lbl for _, lbl in R.PAY_V7_EXTRA] + ["Charges employeur", "Coût employeur", "Statut"],
            [r["id"], r["month"], r["code"], r["name"], r["currency"], R.plain(t["base"])]
            + [R.plain(e.get(k, 0)) for k in ("bonus", "allowances", "overtime", "absence", "advance", "social", "tax", "other")]
            + [R.plain(t["gross"]), R.plain(t["deductions"]), R.plain(t["net"])]
            + [R.plain(e.get(k, 0)) for k, _ in R.PAY_V7_EXTRA]
            + [R.plain(t["employer"]), R.plain(t["cost"]), "Préparation non validée"]]),
            f"paie-{r['month']}-{r['code']}.csv", ui.MIME_CSV, key=f"pcsv_{r['id']}")
    if ecrit and x3.button("Modifier", icon=":material/edit:"):
        formulaire(r["person_id"], r["id"])
