"""Comptabilité générale V8 (socle) : balance, grand livre, pièces par journal, plan de comptes, règles comptables
(Finance propose, DG active) et périodes. Les pièces sont produites par comptabilisation.py, jamais saisies ici."""
from __future__ import annotations

import csv
import io

import pandas as pd
import streamlit as st

import auth
import comptabilisation as CPT
import db
import regles as R
import stocks as S
import ui


def _ok(fn, *a, msg="Enregistré.", **k):
    try:
        fn(*a, **k)
    except (ValueError, ArithmeticError) as e:
        st.error(str(e))
    else:
        ui.succes(msg)


def _devise() -> str:
    return (S.tenue() or {}).get("devise", "")


def _balance() -> None:
    exercices = sorted({p["exercice"] for p in db.tout("cpt_pieces")}, reverse=True)
    if not exercices:
        st.info("Aucune écriture : les pièces naissent des opérations (stock, factures d’achat, paiements).")
        return
    ex = st.selectbox("Exercice", exercices, key="bal_ex")
    dev = _devise()
    bal = CPT.balance(ex)
    st.dataframe([{"Compte": b["compte"], "Libellé": b["libelle"], "Débit": R.money(b["debit"], dev),
                   "Crédit": R.money(b["credit"], dev), "Solde débiteur": R.money(b["solde_debiteur"], dev),
                   "Solde créditeur": R.money(b["solde_crediteur"], dev)} for b in bal], hide_index=True, width="stretch")
    d, c = sum(b["debit"] for b in bal), sum(b["credit"] for b in bal)
    (st.success if d == c else st.error)(f"Total débit {R.money(d, dev)} · total crédit {R.money(c, dev)}")
    ui.telecharger("Exporter la balance (Excel)", _xlsx(pd.DataFrame(bal)), f"balance-{ex}.xlsx", ui.MIME_XLSX, key="bal_x")


def _xlsx(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


def _grand_livre() -> None:
    comptes = sorted({l["compte"] for l in db.tout("cpt_lignes")})
    if not comptes:
        st.info("Aucune écriture.")
        return
    c = st.selectbox("Compte", comptes, key="gl_c")
    dev = _devise()
    st.dataframe([{"Date": l["date"], "Journal": l["journal"], "Pièce": l["piece_numero"], "Libellé": l["libelle"],
                   "Tiers": l["tiers"] or "", "Chantier": l["projet"] or l["centre"] or "", "Poste": l["poste"] or "",
                   "Débit": R.money(l["debit"], dev), "Crédit": R.money(l["credit"], dev), "Solde": R.money(l["solde"], dev),
                   "Devise d’origine": f"{R.money(l['montant_devise'], l['devise'])} au taux {l['taux']}"}
                  for l in CPT.grand_livre(c)], hide_index=True, width="stretch")


def _pieces() -> None:
    pieces = sorted(db.tout("cpt_pieces"), key=lambda p: (p["exercice"], p["journal"], p["numero"]), reverse=True)
    if not pieces:
        st.info("Aucune pièce.")
        return
    j = st.selectbox("Journal", [""] + sorted({p["journal"] for p in pieces}), format_func=lambda x: x or "Tous", key="pc_j")
    pieces = [p for p in pieces if not j or p["journal"] == j][:300]
    tab = [{"_id": p["id"], "n": f"{p['journal']}-{p['exercice']}-{p['numero']:05d}", "d": p["date"], "l": p["libelle"],
            "e": p["evenement"], "s": f"{p['source_type']} {p['source_id'][:8]}", "cp": "oui" if p["contre_passe"] else ""}
           for p in pieces]
    i = ui.tableau(tab, {"n": "Pièce", "d": "Date", "l": "Libellé", "e": "Événement", "s": "Source", "cp": "Contre-passation"},
                   key="tab_pc", selection=True)
    if i is not None:
        dev = _devise()
        st.dataframe([{"Compte": l["compte"], "Tiers": l["tiers"] or "", "Analytique": l["projet"] or l["centre"] or "",
                       "Poste": l["poste"] or "", "Débit": R.money(l["debit"], dev), "Crédit": R.money(l["credit"], dev),
                       "Origine": f"{R.money(l['montant_devise'], l['devise'])} × {l['taux']}"}
                      for l in sorted(db.tout("cpt_lignes"), key=lambda l: l["numero"]) if l["piece"] == tab[i]["_id"]],
                     hide_index=True, width="stretch")


def _plan() -> None:
    st.dataframe([{"Compte": c["numero"], "Libellé": c["libelle"], "Classe": c["classe"], "Collectif": c["collectif"],
                   "Actif": c["actif"], "Origine": c["origine"]} for c in sorted(db.tout("cpt_comptes"), key=lambda c: c["numero"])],
                 hide_index=True, width="stretch")
    if not auth.modifie("comptabilite"):
        return
    st.caption("Plan SYSCOHADA révisé validé par l’expert-comptable : fichier CSV ou Excel avec les colonnes numero, libelle, "
               "collectif (oui / non). Un compte se désactive, il ne se supprime pas.")
    f = st.file_uploader("Plan de comptes", type=["csv", "xlsx"], key="plan_f")
    motif = st.text_input("Référence du plan validé", key="plan_m")
    if f is not None and st.button("Importer le plan", type="primary"):
        try:
            if f.name.endswith(".csv"):
                rows = list(csv.DictReader(io.StringIO(f.getvalue().decode("utf-8-sig")), delimiter=";"))
            else:
                rows = pd.read_excel(io.BytesIO(f.getvalue()), dtype=str).fillna("").to_dict("records")
            lignes = [dict(numero=str(r.get("numero", "")).strip(), libelle=str(r.get("libelle", "")).strip(),
                           collectif=str(r.get("collectif", "")).strip().lower() in ("oui", "1", "true", "x"))
                      for r in rows if str(r.get("numero", "")).strip()]
        except Exception:  # noqa: BLE001
            st.error("Fichier illisible : colonnes numero, libelle, collectif attendues.")
        else:
            _ok(CPT.importer_plan, lignes, motif, msg=f"{len(lignes)} compte(s) importé(s).")


def _regles() -> None:
    regles = sorted(db.tout("regles_comptables"), key=lambda r: (r["evenement"], -r["version"]))
    if not regles:
        st.info("Les règles par défaut du mémo V8 sont créées à la première écriture.")
    for r in regles:
        with st.expander(f"{r['evenement']} · version {r['version']} · {r['statut']} · journal {r['journal']}"):
            st.caption(r["motif"])
            st.dataframe(r["schema"]["postes"], hide_index=True, width="stretch")
            if r["statut"] == "Proposée" and auth.droit("approbation_dg") == "w":
                a, b = st.columns(2)
                if a.button("Activer", key=f"ra_{r['id']}", type="primary"):
                    _ok(CPT.activer_regle, r["id"], msg="Règle activée : elle s’applique aux prochaines écritures.")
                if b.button("Rejeter", key=f"rr_{r['id']}"):
                    _ok(CPT.activer_regle, r["id"], False, msg="Règle rejetée.")
    if auth.modifie("comptabilite") and regles:
        with st.expander("Proposer une nouvelle version de règle", icon=":material/edit_note:"):
            evs = sorted({r["evenement"] for r in regles})
            ev = st.selectbox("Événement", evs, key="rp_ev")
            active = next((r for r in regles if r["evenement"] == ev and r["statut"] == "Active"), regles[0])
            with st.form("rp"):
                postes = st.data_editor(active["schema"]["postes"], num_rows="dynamic", hide_index=True, key="rp_ed",
                                        width="stretch", column_config={
                    "sens": st.column_config.SelectboxColumn("Sens", options=["D", "C"]),
                    "par": st.column_config.SelectboxColumn("Par", options=["document", "ligne"])})
                a, b, c = st.columns(3)
                journal = a.text_input("Journal", active["journal"])
                with b:
                    effet = ui.date_txt("Date d’effet", "rp_d")
                motif = c.text_input("Motif *")
                ok = st.form_submit_button("Proposer à la DG")
            if ok:
                _ok(CPT.proposer_regle, ev, journal, postes, effet, motif, msg="Règle proposée : activation par la DG.")


def _periodes() -> None:
    ps = sorted(db.tout("cpt_periodes"), key=lambda p: p["id"], reverse=True)
    if not ps:
        st.info("L’exercice s’ouvre à la première écriture.")
        return
    st.dataframe([{"Période": p["id"], "Statut": p["statut"]} for p in ps], hide_index=True, width="stretch")
    import caisses as CA
    mois = st.selectbox("Liste de clôture : caisses arrêtées du mois", [p["id"] for p in ps], key="cl_mois")
    etat = CA.etat_cloture(mois)
    if etat:
        st.dataframe([{"Caisse": e["caisse"], "Devise": e["devise"], "Solde fin de mois": R.money(e["solde"], e["devise"]),
                       "Arrêtée": "Oui" if e["arretee"] else "Non", "Date de l’arrêté": e["arrete"],
                       "Écart régularisé": R.money(e["ecart"], e["devise"]) if e["arretee"] else ""} for e in etat],
                     hide_index=True, width="stretch")
        if not all(e["arretee"] for e in etat):
            st.warning("Caisses non arrêtées pour ce mois : faites valider leur arrêté (Journal de caisse) avant la "
                       "clôture.")
    with st.form("per"):
        a, b, c = st.columns(3)
        pid = a.selectbox("Période", [p["id"] for p in ps])
        statut = b.selectbox("Nouveau statut", list(CPT.STATUTS_PERIODE))
        motif = c.text_input("Motif *")
        ok = st.form_submit_button("Appliquer")
    if ok:
        _ok(CPT.changer_periode, pid, statut, motif, msg="Période mise à jour.")


def _parametres_comptables() -> None:
    p = CPT.parametres()
    t_ = S.tenue() or {}
    st.markdown("**Démarrage de la comptabilisation des opérations existantes** (circuit V7, caisse, dépenses, tiers) : "
                + (t_.get("debut") or "non fixé — à fixer par la DG dans Achats et stock › Paramètres"))
    ctrl = CPT.controle_tresorerie()
    if ctrl:
        st.markdown("**Contrôle permanent : trésorerie de l’application = comptes de trésorerie**")
        st.dataframe([{"Journal": c["journal"], "Compte": c["compte"], "Devise": c["devise"],
                       "Application": R.money(c["application"], c["devise"]),
                       "Comptabilité": R.money(c["comptabilite"], c["devise"]),
                       "Écart": R.money(c["ecart"], c["devise"])} for c in ctrl], hide_index=True, width="stretch")
        if any(c["ecart"] for c in ctrl):
            st.warning("Écart entre la trésorerie de l’application et les comptes : à analyser avant clôture.")
    peut = auth.droit("comptabilite") == "w"
    cats = R.expense_categories()
    with st.form("param_cpt"):
        st.markdown("**Comptes des catégories de dépense** (obligatoires : une dépense sans compte est refusée)")
        cols = st.columns(3)
        dep = {c: cols[i % 3].text_input(c, (p["comptes_depenses"] or {}).get(c, ""), key=f"dep_{i}")
               for i, c in enumerate(cats)}
        st.markdown("**Journal de caisse historique**")
        a, b, c = st.columns(3)
        th = p["tresorerie_historique"]
        tres = {"cash": a.text_input("Compte caisse", th.get("cash", "")),
                "bank": b.text_input("Compte banque", th.get("bank", "")),
                "mobile": c.text_input("Compte mobile money", th.get("mobile", ""))}
        a, b, c = st.columns(3)
        attente = a.text_input("Compte d’attente (mouvements non imputés)", p["compte_attente"])
        ouverture = b.text_input("Compte de contrepartie des soldes d’ouverture", p["compte_ouverture"])
        fact = c.text_input("Compte de charge des factures fournisseurs historiques", p["compte_factures_historiques"])
        motif = st.text_input("Motif *")
        ok = st.form_submit_button("Enregistrer", disabled=not peut)
    if ok:
        _ok(CPT.configurer, {"comptes_depenses": {k: v.strip() for k, v in dep.items() if v.strip()},
                             "tresorerie_historique": {k: v.strip() for k, v in tres.items()},
                             "compte_attente": attente.strip(), "compte_ouverture": ouverture.strip(),
                             "compte_factures_historiques": fact.strip()}, motif, msg="Paramètres comptables enregistrés.")


def page() -> None:
    auth.exiger("comptabilite")
    ui.en_tete("Comptabilité générale", f"Monnaie de tenue : {_devise() or 'non fixée'} · pièces générées par les "
                                        "opérations, numérotées sans trou par journal et par exercice.")
    onglets = st.tabs(["Balance", "Grand livre", "Pièces", "Plan de comptes", "Règles comptables", "Périodes",
                       "Paramètres"])
    for o, fn in zip(onglets, (_balance, _grand_livre, _pieces, _plan, _regles, _periodes, _parametres_comptables)):
        with o:
            fn()
