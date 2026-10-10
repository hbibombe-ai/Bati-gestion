"""Personnel : fiches, contrats, affectations datées et pointage quotidien.

Les salaires ne sont visibles et modifiables que par la direction et les RH (module « paie »).
"""
from __future__ import annotations

import streamlit as st

import auth
import db
import nav
import pdf
import regles as R
import ui


def fiche_lignes(p: dict, s: dict, avec_salaire: bool) -> list[tuple[str, str]]:
    d = p.get("details") or {}
    v = p.get("v7") or {}
    w = p.get("salary")
    rows = [("Matricule", p["code"])] + [(lbl, v.get(k, "")) for k, lbl in R.HR_V7_FIELDS] + [
        ("Nombre d’enfants", "Non renseigné" if v.get("children") is None else str(v["children"])),
        ("Mode de paiement habituel", R.account_name(v.get("paymentMethod")) if v.get("paymentMethod") else "À préciser"),
        ("Nom complet", p["name"]), ("Fonction", p["job"]), ("Service", p["service"]), ("Téléphone", p["phone"]),
        ("Adresse", d.get("address", "")), ("E-mail", d.get("email", "")),
        ("Contact d’urgence", d.get("emergencyName", "")), ("Téléphone du contact", d.get("emergencyPhone", "")),
        ("Date d’engagement", p["start"]), ("Affectation actuelle", R.hr_place_label(p, s)),
        ("Statut", "Actif" if p["active"] else "Inactif"), ("Type de contrat", d.get("contractType", "")),
        ("Référence du contrat", d.get("contractReference", "")), ("Fin prévue du contrat", d.get("contractEnd", ""))]
    if avec_salaire:
        rows += [("Salaire de base brut", f"{R.money(w['amount'], w['currency'])} / {w['period'].lower()}" if w
                  else "Non renseigné"), ("Salaire applicable à partir du", (w or {}).get("effective", ""))]
    rows.append(("Observations", d.get("notes", "")))
    return rows


@st.dialog("Fiche du personnel", width="large")
def formulaire(pid: str | None = None) -> None:
    s = R.charger("personnel", "projects", "attendance")
    p = next((x for x in s["personnel"] if x["id"] == pid), None) or {}
    d = p.get("details") or {}
    v = p.get("v7") or {}
    w = p.get("salary") or {}
    avec_salaire = auth.modifie("paie")
    k = pid or "new"
    a, b, c = st.columns(3)
    code = a.text_input("Matricule unique *", value=p.get("code", ""), key=f"pe_code_{k}")
    nom = b.text_input("Nom complet *", value=p.get("name", ""), key=f"pe_nom_{k}")
    fonction = c.text_input("Fonction *", value=p.get("job", ""), key=f"pe_job_{k}")
    service = a.text_input("Service", value=p.get("service", ""), key=f"pe_srv_{k}")
    tel = b.text_input("Téléphone", value=p.get("phone", ""), key=f"pe_tel_{k}")
    with c:
        debut = ui.date_txt("Date d’engagement *", f"pe_deb_{k}", p.get("start"))
    lieu, projet = p.get("location", "Bureau"), p.get("project", "")
    if not p:
        lieu = a.selectbox("Affectation initiale", ["Bureau", "Chantier"], key=f"pe_lieu_{k}")
        with b:
            projet = ui.choix("Chantier (si affecté au chantier)", ui.options_chantiers(s), f"pe_proj_{k}", "",
                              vide="Aucun")
    actif = c.toggle("Actif", value=p.get("active", True), key=f"pe_act_{k}")
    st.markdown("**Informations salarié**")
    cols = st.columns(3)
    v7 = {}
    for n, (cle, lbl) in enumerate(R.HR_V7_FIELDS):
        v7[cle] = cols[n % 3].text_input(lbl, value=v.get(cle, ""), key=f"pe_{cle}_{k}")
    enfants = cols[0].number_input("Nombre d’enfants", min_value=0, max_value=100, step=1,
                                   value=v.get("children"), key=f"pe_enf_{k}")
    with cols[1]:
        paiement = ui.choix("Mode de paiement habituel", R.CASH_ACCOUNTS, f"pe_pm_{k}", v.get("paymentMethod", ""),
                            vide="À préciser")
    st.markdown("**Coordonnées et contact d’urgence**")
    a, b = st.columns(2)
    adr = a.text_input("Adresse", value=d.get("address", ""), key=f"pe_adr_{k}")
    mail = b.text_input("E-mail", value=d.get("email", ""), key=f"pe_mail_{k}")
    urg = a.text_input("Personne à prévenir", value=d.get("emergencyName", ""), key=f"pe_urg_{k}")
    urg_tel = b.text_input("Téléphone du contact", value=d.get("emergencyPhone", ""), key=f"pe_urgt_{k}")
    st.markdown("**Contrat**")
    a, b, c = st.columns(3)
    contrat = a.selectbox("Type de contrat / engagement", R.HR_CONTRACTS,
                          index=R.HR_CONTRACTS.index(d.get("contractType", "À préciser")), key=f"pe_ct_{k}")
    ref = b.text_input("Référence du contrat", value=d.get("contractReference", ""), key=f"pe_cref_{k}")
    with c:
        fin = ui.date_txt("Date de fin (si prévue)", f"pe_fin_{k}", d.get("contractEnd"), vide_ok=True)
    salaire = None
    if avec_salaire:
        st.markdown("**Rémunération convenue** (confidentiel : direction et RH)")
        a, b, c, e = st.columns(4)
        montant = a.number_input("Salaire de base brut", min_value=0.0, value=(w["amount"] / 100) if w else None,
                                 format="%.2f", key=f"pe_sal_{k}", help="Laisser vide si inconnu.")
        with b:
            sal_cur = ui.devise("Monnaie du salaire", f"pe_salc_{k}", w.get("currency"))
        periode = c.selectbox("Base de rémunération", R.HR_PAY_PERIODS,
                              index=R.HR_PAY_PERIODS.index(w.get("period", "Mois")), key=f"pe_salp_{k}")
        with e:
            effet = ui.date_txt("Applicable à partir du", f"pe_sale_{k}", w.get("effective") or p.get("start"))
        st.caption("Montant brut convenu, avant primes, retenues et cotisations. Changer la monnaie ne convertit pas le montant.")
    notes = st.text_area("Observations", value=d.get("notes", ""), key=f"pe_notes_{k}")
    if p:
        st.caption("Pour un changement de chantier, utilisez « Affectations » : chaque nouvelle affectation conserve "
                   "les précédentes.")
    if st.button("Enregistrer", type="primary"):
        try:
            rec = {"code": code.strip(), "name": nom.strip(), "job": fonction.strip(), "service": service.strip(),
                   "phone": tel.strip(), "start": debut, "active": bool(actif)}
            if not rec["code"] or not rec["name"] or not rec["job"] or not R.is_date(debut):
                raise ValueError("Renseignez le matricule, le nom, la fonction et la date d’engagement.")
            if any(x["id"] != pid and x["code"].lower() == rec["code"].lower() for x in s["personnel"]):
                raise ValueError("Ce matricule existe déjà.")
            if not p:
                if lieu == "Chantier" and not projet:
                    raise ValueError("Choisissez le chantier d’affectation.")
                rec.update(location=lieu, project=projet if lieu == "Chantier" else "",
                           assignments=[{"date": debut, "location": lieu, "project": projet if lieu == "Chantier" else ""}])
            else:
                if any(a_["person_id"] == pid and a_["date"] < debut for a_ in s["attendance"]):
                    raise ValueError("La date d’engagement ne peut pas être postérieure aux pointages existants.")
                if any(a_["date"] < debut for a_ in p.get("assignments") or []):
                    raise ValueError("La date d’engagement doit précéder les affectations enregistrées.")
            if fin and fin < debut:
                raise ValueError("La fin du contrat ne peut précéder l’engagement.")
            if not avec_salaire and p.get("salary") and p["salary"].get("effective", "") < debut:
                raise ValueError("Le salaire enregistré prend effet avant cette date d’engagement : demandez aux RH de "
                                 "mettre la fiche à jour.")
            rec["v7"] = {**v7, "children": int(enfants) if enfants is not None else None, "paymentMethod": paiement or ""}
            rec["details"] = {"address": adr.strip(), "email": mail.strip(), "emergencyName": urg.strip(),
                              "emergencyPhone": urg_tel.strip(), "contractType": contrat, "contractReference": ref.strip(),
                              "contractEnd": fin, "notes": notes.strip()}
            if avec_salaire:
                if montant is None:
                    salaire = None
                else:
                    if not R.is_date(effet) or effet < debut:
                        raise ValueError("Le salaire doit prendre effet après l’engagement.")
                    salaire = {"amount": R.cents(montant, "Salaire"), "currency": sal_cur, "period": periode,
                               "effective": effet}
                rec["salary"] = salaire
            with db.transaction(f"Fiche du personnel {rec['name']}") as t:
                if p:
                    t.maj("personnel", pid, rec)
                else:
                    t.inserer("personnel", {"id": db.nouvel_id(), **rec, **({} if avec_salaire else {"salary": None})})
        except ValueError as e:
            st.error(str(e))
        else:
            ui.succes("Fiche personnel enregistrée.")


@st.dialog("Affectations", width="large")
def affectations(pid: str) -> None:
    s = R.charger("personnel", "projects", "attendance")
    p = next(x for x in s["personnel"] if x["id"] == pid)
    st.markdown(f"**{p['name']}**")
    rows = p.get("assignments") or []
    if rows:
        ui.tableau([{"d": a["date"], "l": R.hr_place_label(a, s)} for a in rows], {"d": "À partir du", "l": "Affectation"},
                   key=f"aff_{pid}")
    else:
        st.caption(f"Aucun historique daté. Affectation connue sur la fiche : {R.hr_place_label(p, s)}.")
    st.caption("Une affectation reste valable jusqu’à la suivante. Les changements doivent suivre les pointages déjà "
               "enregistrés.")
    if not p["active"] or not auth.modifie("personnel"):
        return
    st.markdown("**Nouvelle affectation**")
    a, b, c = st.columns(3)
    with a:
        date = ui.date_txt("À partir du", f"aff_d_{pid}", max_aujourdhui=True)
    lieu = b.selectbox("Affectation", ["Bureau", "Chantier"], index=["Bureau", "Chantier"].index(p["location"]))
    with c:
        projet = ui.choix("Chantier", ui.options_chantiers(s), f"aff_p_{pid}", p["project"], vide="Aucun")
    if st.button("Enregistrer l’affectation", type="primary"):
        try:
            if not R.is_date(date) or date < p["start"] or date > R.today():
                raise ValueError("La date doit être comprise entre l’engagement et aujourd’hui.")
            if any(x["date"] >= date for x in rows):
                raise ValueError("La nouvelle affectation doit suivre la dernière affectation enregistrée.")
            if any(x["person_id"] == pid and x["date"] >= date for x in s["attendance"]):
                raise ValueError("Des pointages existent à partir de cette date. Choisissez une date après le dernier pointage.")
            if lieu == "Chantier" and not projet:
                raise ValueError("Sélectionnez le bureau ou un chantier existant.")
            row = {"date": date, "location": lieu, "project": projet if lieu == "Chantier" else ""}
            with db.transaction(f"Affectation de {p['name']}") as t:
                actuel = t.get("personnel", pid, verrou=True)["assignments"] or []
                if any(x["date"] >= date for x in actuel):
                    raise ValueError("La nouvelle affectation doit suivre la dernière affectation enregistrée.")
                t.maj("personnel", pid, {"assignments": actuel + [row], "location": row["location"],
                                         "project": row["project"]})
        except ValueError as e:
            st.error(str(e))
        else:
            ui.succes("Affectation enregistrée.")


@st.dialog("Pointage")
def pointage(pid: str) -> None:
    s = R.charger("personnel", "projects", "attendance")
    p = next(x for x in s["personnel"] if x["id"] == pid)
    st.markdown(f"**{p['name']}** · {p['code']}")
    date = ui.date_txt("Date", f"pt_d_{pid}", max_aujourdhui=True)
    statut = st.selectbox("Présence", R.ATTENDANCE_STATUSES, key=f"pt_s_{pid}")
    lieux = {"": "Selon l’historique des affectations", "bureau": "Bureau",
             **{f"project:{x['id']}": x["name"] for x in s["projects"]}}
    lieu = st.selectbox("Lieu du pointage", list(lieux), format_func=lieux.get, key=f"pt_l_{pid}")
    heures = st.number_input("Heures réellement travaillées", min_value=0.0, max_value=24.0, step=0.25,
                             value=0.0 if statut in R.ZERO_HOUR_STATUSES else 8.0, key=f"pt_h_{pid}_{statut}")
    note = st.text_input("Observation", key=f"pt_n_{pid}")
    existe = next((a for a in s["attendance"] if a["person_id"] == pid and a["date"] == date), None)
    remplacer = True
    if existe:
        remplacer = st.checkbox(f"Remplacer le pointage existant du {date} ({existe['status']}, {existe['hours']:g} h)")
    if st.button("Enregistrer le pointage", type="primary", disabled=not remplacer):
        try:
            if not R.is_date(date) or date < p["start"] or date > R.today():
                raise ValueError("La date doit être comprise entre l’engagement et aujourd’hui.")
            if statut in R.ZERO_HOUR_STATUSES and heures != 0:
                raise ValueError("Pour ce statut, les heures travaillées doivent être nulles.")
            aff = ({"location": "Bureau", "project": ""} if lieu == "bureau" else
                   {"location": "Chantier", "project": lieu[8:]} if lieu.startswith("project:") else R.hr_assignment_at(p, date))
            if not aff:
                raise ValueError("Aucune affectation connue pour cette date : choisissez le lieu du pointage.")
            row = {"person_id": pid, "date": date, "status": statut, "hours": float(heures), "note": note.strip(),
                   "location": aff["location"], "project": aff.get("project", "")}
            with db.transaction(f"Pointage de {p['name']} le {date}") as t:
                if existe:
                    t.maj("attendance", existe["id"], row)
                else:
                    t.inserer("attendance", row)
        except ValueError as e:
            st.error(str(e))
        else:
            ui.succes("Pointage enregistré.")


def page() -> None:
    if not (auth.voit("personnel") or auth.voit("pointage")):
        auth.exiger("personnel")
    ui.en_tete("Personnel et pointage", "Personnel, affectation actuelle et présence quotidienne.")
    from vues import imports as IMP
    IMP.encart(["personnel", "presences"], "Importer du personnel, des affectations ou des présences depuis Excel")
    s = R.charger("personnel", "projects", "attendance")
    salaires = auth.voit("paie")
    staff = sorted(s["personnel"], key=lambda p: (not p["active"], p["name"].lower()))
    ecrit = auth.modifie("personnel")
    b = ui.rangee(3)
    if ecrit and b[0].button("Ajouter une personne", type="primary", icon=":material/person_add:"):
        formulaire()
    entete = (["Matricule", "Nom", "Fonction", "Service", "Téléphone", "Engagement", "Statut", "Affectation", "Contrat",
               "Fin du contrat"] + (["Salaire brut", "Monnaie", "Base", "Applicable à partir du"] if salaires else [])
              + [lbl for _, lbl in R.HR_V7_FIELDS] + ["Nombre d’enfants", "Mode de paiement habituel"])
    data = [entete] + [[p["code"], p["name"], p["job"], p["service"], p["phone"], p["start"],
                        "Actif" if p["active"] else "Inactif", R.hr_place_label(p, s),
                        (p.get("details") or {}).get("contractType", ""), (p.get("details") or {}).get("contractEnd", "")]
                       + ([R.plain(p["salary"]["amount"]) if p.get("salary") else "", (p.get("salary") or {}).get("currency", ""),
                           (p.get("salary") or {}).get("period", ""), (p.get("salary") or {}).get("effective", "")]
                          if salaires else [])
                       + [(p.get("v7") or {}).get(k_, "") for k_, _ in R.HR_V7_FIELDS]
                       + [(p.get("v7") or {}).get("children", ""),
                          R.account_name((p.get("v7") or {}).get("paymentMethod")) if (p.get("v7") or {}).get("paymentMethod") else ""]
                       for p in staff]
    with b[1]:
        ui.telecharger("Exporter le personnel", R.to_csv(data), f"personnel-{R.today()}.csv", ui.MIME_CSV, key="pe_csv")
    noms = {p["id"]: p for p in s["personnel"]}
    pts = [["Matricule", "Employé", "Date", "Lieu", "Statut", "Heures", "Observation"]] + [
        [noms[a["person_id"]]["code"], noms[a["person_id"]]["name"], a["date"], R.hr_place_label(a, s), a["status"],
         a["hours"], a["note"]] for a in s["attendance"] if a["person_id"] in noms]
    with b[2]:
        ui.telecharger("Exporter les pointages", R.to_csv(pts), f"pointages-{R.today()}.csv", ui.MIME_CSV, key="pt_csv")

    st.subheader(f"Personnel ({sum(1 for p in staff if p['active'])} actif(s))")
    if not staff:
        st.info("Ajoutez votre personnel de bureau et de chantier.")
        return
    rows = [{"_id": p["id"], "nom": p["name"], "mat": p["code"], "fct": p["job"], "srv": p["service"],
             "aff": R.hr_place_label(p, s), "deb": p["start"], "st": "Actif" if p["active"] else "Inactif"} for p in staff]
    i = ui.tableau(rows, {"nom": "Nom", "mat": "Matricule", "fct": "Fonction", "srv": "Service",
                          "aff": "Affectation actuelle", "deb": "Entrée", "st": "Statut"}, key="tab_pers", selection=True)
    if i is not None:
        p = next(x for x in staff if x["id"] == rows[i]["_id"])
        st.subheader(p["name"])
        c = ui.rangee(5)
        if ecrit and c[0].button("Modifier", icon=":material/edit:"):
            formulaire(p["id"])
        if c[1].button("Affectations", icon=":material/swap_horiz:"):
            affectations(p["id"])
        if p["active"] and auth.modifie("pointage") and c[2].button("Pointer", icon=":material/how_to_reg:", type="primary"):
            pointage(p["id"])
        with c[3]:
            ui.telecharger("Fiche / PDF", pdf.document("Fiche employé", R.company_snapshot(),
                                                       [("kv", fiche_lignes(p, s, salaires))],
                                                       auteur=auth.utilisateur()["nom"]),
                           f"fiche-{p['code']}.pdf", ui.MIME_PDF, key=f"fiche_{p['id']}")
        if p["active"] and auth.modifie("paie") and "paie" in nav.PAGES and c[4].button("Préparer la paie",
                                                                                        icon=":material/payments:"):
            st.session_state["paie_personne"] = p["id"]
            nav.aller("paie")
        with st.expander("Fiche employé", expanded=False):
            ui.tableau([{"k": k_, "v": v_ or "Non renseigné"} for k_, v_ in fiche_lignes(p, s, salaires)],
                       {"k": "Information", "v": "Valeur"}, key=f"fiche_tab_{p['id']}")
    else:
        st.caption("Sélectionnez une personne pour la pointer, voir sa fiche ou ses affectations.")

    st.subheader("Derniers pointages")
    nav.lien("presence-kobo", "Pointage par téléphone avec KoboCollect : présence du jour et import des fiches",
             ":material/phone_android:")
    derniers = sorted([a for a in s["attendance"] if a["person_id"] in noms], key=lambda a: a["date"], reverse=True)[:100]
    if derniers:
        ui.tableau([{"d": a["date"], "p": noms[a["person_id"]]["name"], "l": R.hr_place_label(a, s), "s": a["status"],
                     "h": a["hours"], "n": a["note"]} for a in derniers],
                   {"d": "Date", "p": "Personnel", "l": "Bureau / chantier", "s": "Présence",
                    "h": st.column_config.NumberColumn("Heures constatées", format="%.2f"), "n": "Observation"},
                   key="tab_pts")
        st.caption("Une ligne par personne et par jour. Les 100 dernières lignes sont affichées ; toutes sont "
                   "conservées et exportables.")
    else:
        st.caption("Aucun pointage enregistré.")
