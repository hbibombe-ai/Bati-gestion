"""Dossiers préparatoires (référentiel V7) : achats, stocks, matériel, chantier, RH, comptabilité, registres.

Ces dossiers ne réservent pas de budget et ne modifient ni stock, ni trésorerie, ni comptabilité.
"""
from __future__ import annotations

import streamlit as st

import auth
import db
import pdf
import regles as R
import ui


def module_de(type_: str) -> str:
    return R.DOSSIER_MODULE[R.ERP_DOSSIERS[type_]["group"]]


@st.dialog("Dossier", width="large")
def formulaire(type_: str, did: str | None = None) -> None:
    s = R.charger("projects", "clients", "personnel", "erp_dossiers")
    spec = R.ERP_DOSSIERS[type_]
    r = next((d for d in s["erp_dossiers"] if d["id"] == did), None) or {}
    vals = r.get("values") or {}
    k = did or f"new_{type_}"
    st.markdown(f"#### {spec['label']}")
    a, b, c = st.columns(3)
    ref = a.text_input("Référence unique *", value=r.get("ref") or R.dossier_next_ref(s["erp_dossiers"], type_),
                       key=f"do_ref_{k}")
    with b:
        date = ui.date_txt("Date *", f"do_date_{k}", r.get("date"))
    with c:
        cur = ui.devise("Monnaie des montants", f"do_cur_{k}", r.get("currency"))
    a, b, c = st.columns(3)
    with a:
        projet = ui.choix("Chantier", ui.options_chantiers(s), f"do_proj_{k}", r.get("project", ""), vide="Non renseigné")
    with b:
        centres = {d["id"]: R.link_label(d) for d in s["erp_dossiers"] if d["type"] == "centres"}
        centre = ui.choix("Centre de coût (si hors chantier)", centres, f"do_cen_{k}", r.get("centre", ""),
                          vide="Non renseigné")
    with c:
        tiers = ui.choix("Tiers", {p["id"]: p["name"] for p in s["clients"]}, f"do_tiers_{k}", r.get("party", ""),
                         vide="Non renseigné")
    valeurs = {}
    cols = st.columns(2)
    for n, f in enumerate(spec["fields"]):
        cle, label, kind, requis, options = R.field_spec(f)
        lbl = label + (" *" if requis else "")
        v = vals.get(cle)
        with cols[n % 2]:
            if kind == "select":
                valeurs[cle] = ui.choix(lbl, {o: o for o in options}, f"do_{cle}_{k}", v or "", vide="Choisir") or None
            elif kind == "link":
                liens = {d["id"]: R.link_label(d) for d in R.dossier_links(s, options)}
                valeurs[cle] = ui.choix(lbl, liens, f"do_{cle}_{k}", v or "", vide="Choisir") or None
            elif kind == "date":
                valeurs[cle] = ui.date_txt(lbl, f"do_{cle}_{k}", v, vide_ok=True) or None
            elif kind == "money":
                x = st.number_input(f"{lbl} ({cur})", min_value=0.0, value=(v / 100) if v is not None else None,
                                    format="%.2f", key=f"do_{cle}_{k}")
                valeurs[cle] = x
            elif kind == "quantity":
                valeurs[cle] = st.number_input(lbl, min_value=0.0, value=float(v) if v is not None else None,
                                               format="%.2f", key=f"do_{cle}_{k}")
            else:
                valeurs[cle] = st.text_input(lbl, value=v or "", key=f"do_{cle}_{k}", max_chars=500).strip() or None
    notes = st.text_input("Observations / références des pièces", value=r.get("notes", ""), key=f"do_notes_{k}",
                          max_chars=2000)
    st.caption(("Un chantier ou un centre de coût est obligatoire. " if spec.get("analytical") else "")
               + "Les liens proposent les dossiers déjà saisis. État : brouillon uniquement.")
    if st.button("Enregistrer", type="primary"):
        try:
            for f in spec["fields"]:
                cle, label, kind, _, _ = R.field_spec(f)
                if kind == "money" and valeurs[cle] is not None:
                    valeurs[cle] = R.cents(valeurs[cle], label)
                if kind == "quantity" and valeurs[cle] is not None:
                    valeurs[cle] = float(valeurs[cle])
            rec = {"id": did or db.nouvel_id(), "type": type_, "ref": ref.strip(), "date": date,
                   "project": projet or "", "centre": centre or "", "party": tiers or "", "currency": cur,
                   "status": "Brouillon", "values": valeurs, "notes": notes.strip()}
            R.validate_dossier(rec, s)
            with db.transaction(f"Dossier {spec['label']} {rec['ref']}") as t:
                if r:
                    rec.pop("id")
                    t.maj("erp_dossiers", did, rec)
                else:
                    rec["company_snapshot"] = R.company_snapshot()
                    t.inserer("erp_dossiers", rec)
        except ValueError as e:
            st.error(str(e))
        else:
            ui.succes("Dossier préparatoire enregistré.")


def page_espace(cle: str) -> None:
    titre, types = R.V7_SPACES[cle]
    module = module_de(types[0])
    auth.exiger(module)
    ui.en_tete(titre, "Saisie préparatoire : ces dossiers ne modifient ni stock, ni trésorerie, ni comptabilité.")
    s = R.charger("projects", "clients", "personnel", "erp_dossiers")
    compte = {t: sum(1 for d in s["erp_dossiers"] if d["type"] == t) for t in types}
    type_ = st.pills("Type de dossier", types, default=st.session_state.get(f"esp_{cle}", types[0]),
                     format_func=lambda t: f"{R.ERP_DOSSIERS[t]['label']} ({compte[t]})", key=f"pill_{cle}") or types[0]
    st.session_state[f"esp_{cle}"] = type_
    spec = R.ERP_DOSSIERS[type_]
    ecrit = auth.modifie(module)
    rows = sorted([d for d in s["erp_dossiers"] if d["type"] == type_], key=lambda d: d["ref"])
    a, b = ui.rangee(2)
    if ecrit and a.button("Ajouter un dossier", type="primary", icon=":material/add:", key=f"add_{cle}"):
        formulaire(type_)
    entete = ["Référence", "Date", "Projet", "Centre de coût", "Tiers", "Monnaie"] + [R.field_spec(f)[1] for f in
                                                                                     spec["fields"]] + ["Observations", "Statut"]
    with b:
        ui.telecharger("Exporter la liste CSV", R.to_csv([entete] + [[v for _, v in R.dossier_rows(s, d)] for d in rows]),
                       f"dossiers-{type_}.csv", ui.MIME_CSV, key=f"csv_{cle}_{type_}")
    if not rows:
        st.info("Aucun dossier saisi. Ajoutez une première fiche.")
        return
    premier = next((R.field_spec(f)[0] for f in spec["fields"] if R.field_spec(f)[2] in ("text", "link")), None)
    lignes = [{"_id": d["id"], "ref": d["ref"], "date": d["date"],
               "obj": R.dossier_value(s, d, next(f for f in spec["fields"] if f[0] == premier)) if premier else "",
               "ch": R.project_name(s, d["project"]) if d["project"] else
               next((c["ref"] for c in s["erp_dossiers"] if c["id"] == d["centre"]), "—"),
               "st": "Brouillon"} for d in rows]
    i = ui.tableau(lignes, {"ref": "Référence", "date": "Date", "obj": next((R.field_spec(f)[1] for f in spec["fields"]
                                                                          if f[0] == premier), "Objet"),
                            "ch": "Chantier / centre", "st": "Statut"}, key=f"tab_{cle}_{type_}", selection=True)
    if i is None:
        st.caption("Sélectionnez un dossier pour l’ouvrir, le modifier ou l’exporter.")
        return
    d = next(x for x in rows if x["id"] == lignes[i]["_id"])
    st.subheader(f"{spec['label']} · {d['ref']}")
    c1, c2, c3 = ui.rangee(3)
    if ecrit and c1.button("Modifier", icon=":material/edit:", key=f"mod_{d['id']}"):
        formulaire(type_, d["id"])
    with c2:
        ui.telecharger("Fiche / PDF", pdf.document(spec["label"], d.get("company_snapshot") or R.company_snapshot(),
                                                   [("mention", "BROUILLON — NON VALIDÉ"), ("kv", R.dossier_rows(s, d)),
                                                    ("petit", "Aucun impact automatique sur les stocks, les comptes ou la "
                                                              "trésorerie.")], auteur=auth.utilisateur()["nom"]),
                       f"dossier-{d['ref']}.pdf", ui.MIME_PDF, key=f"pdf_{d['id']}")
    with c3:
        ui.telecharger("Exporter CSV", R.to_csv([list(x) for x in R.dossier_rows(s, d)]), f"dossier-{d['ref']}.csv",
                       ui.MIME_CSV, key=f"dcsv_{d['id']}")
    ui.tableau([{"k": k_, "v": v_} for k_, v_ in R.dossier_rows(s, d)], {"k": "Information", "v": "Valeur"},
               key=f"det_{d['id']}")
