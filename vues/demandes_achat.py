"""Demandes d'achat matériel et matériaux : saisie ou import par le chantier, validation du besoin, chiffrage par
les achats, validation du coordonnateur, transmission au circuit financier V7 et commandes groupées."""
from __future__ import annotations

import datetime as dt

import streamlit as st

import achats_circuit as A
import auth
import db
import gestion_v7 as V
import regles as R
import ui
from vues import imports as centre_imports

MODULES = ["demandes_achat", "approbation_chantier", "chiffrage_achats", "approbation_coordonnateur"]


def _executer(fn, *args, ok: str = "Enregistré.", **kwargs):
    try:
        res = fn(*args, **kwargs)
    except (ValueError, ArithmeticError) as e:
        st.error(str(e))
        return None
    ui.succes(ok)
    return res


def _moi() -> dict:
    return auth.utilisateur() or {}


def _prix(v) -> int | None:
    v = "" if v is None else str(v).strip()
    return R.cents(v, "Prix unitaire", positif=True) if v else None


# ------------------------------------------------------------------ détail d'une demande
def _detail(r: dict, s: dict) -> None:
    d = r["data"]
    fournisseurs = {c["id"]: c["name"] for c in s["clients"]}
    a, b, c = st.columns(3)
    a.metric("Statut", d["statut"])
    b.metric("Chantier", R.project_name(s, r["project"]))
    c.metric("Montant chiffré", R.money(A.montant_total(d), r["currency"]) if any(
        l.get("prix") is not None for l in d["lignes"]) else "—")
    st.caption(f"{d['objet']} · besoin le {d['date_besoin']} · livraison : {d.get('lieu') or '—'} · "
               f"demandeur : {d['history'][0]['name'] if d.get('history') else '—'}")
    st.dataframe([{"N°": l["n"], "Poste DQE": l["post"], "Article": l["article"], "Unité": l["unite"],
                   "Quantité": l["quantite"], "Servie par le stock": l.get("qte_stock") or 0,
                   "Prix unitaire": R.money(l["prix"], r["currency"]) if l.get("prix") is not None else "",
                   "Fournisseur": fournisseurs.get(l.get("fournisseur"), ""), "Origine du prix": l.get("source_prix", ""),
                   "Note": l.get("note", "")} for l in d["lignes"]], hide_index=True, width="stretch")
    if ch := (d.get("validations") or {}).get("chiffrage"):
        for al in ch.get("alertes") or []:
            st.warning(al)
    if d.get("operations"):
        ops = [o for o in V.records("operation") if o["id"] in d["operations"]]
        st.markdown("**Opérations du circuit financier V7**")
        st.dataframe([{"Référence": o["ref"], "Fournisseur": fournisseurs.get(o["data"]["party"], ""),
                       "Poste": o["data"]["post"], "Montant": R.money(o["data"]["amount"], o["currency"]),
                       "Statut": o["data"]["status"], "Niveau validé": V.LEVELS[o["data"]["level"] - 1]
                       if o["data"]["level"] else "—", "Bon de commande": (o["data"].get("order") or {}).get("ref", "")}
                      for o in ops], hide_index=True, width="stretch")
    with st.expander("Historique"):
        st.dataframe([{"Date": h["at"][:16].replace("T", " "), "Par": h["name"], "Action": h["action"],
                       "Commentaire": h.get("note", "")} for h in d["history"]], hide_index=True, width="stretch")


def _actions(r: dict, s: dict) -> None:
    d, u, cle = r["data"], _moi(), r["id"]
    acteurs = {d["creator"], *[v["user"] for v in (d.get("validations") or {}).values()]}
    if d["statut"] in ("Brouillon", "Rejetée") and d["creator"] == u.get("id"):
        c1, c2 = st.columns(2)
        if c1.button("Soumettre au chef de chantier", type="primary", key=f"sou_{cle}"):
            _executer(A.soumettre, cle, ok="Demande soumise au chef de chantier / directeur de projet.")
        with c2.popover("Annuler la demande"):
            motif = st.text_input("Motif", key=f"ann_m_{cle}")
            if st.button("Confirmer l’annulation", key=f"ann_{cle}"):
                _executer(A.annuler, cle, motif, ok="Demande annulée.")
    if d["statut"] == "Soumise" and auth.modifie("approbation_chantier") and u.get("id") != d["creator"]:
        with st.form(f"chantier_{cle}"):
            st.markdown("**Validation du besoin (chantier)**")
            note = st.text_input("Commentaire de contrôle *", placeholder="ex. quantités conformes au métré")
            a, b = st.columns(2)
            ok = a.form_submit_button("Valider le besoin", type="primary")
            ko = b.form_submit_button("Rejeter")
        if ok or ko:
            _executer(A.valider_chantier, cle, note, rejeter=ko, ok="Besoin rejeté." if ko else "Besoin validé : "
                      "transmis aux achats.")
    if d["statut"] == "Validée chantier" and auth.modifie("chiffrage_achats") and u.get("id") not in acteurs:
        _chiffrage(r, s)
    if d["statut"] == "À valider coordonnateur" and auth.modifie("approbation_coordonnateur") \
            and u.get("id") not in acteurs:
        with st.form(f"coord_{cle}"):
            st.markdown("**Validation du coordonnateur de projet**")
            note = st.text_input("Commentaire de contrôle *", placeholder="ex. priorité confirmée, budget suivi")
            a, b = st.columns(2)
            ok = a.form_submit_button("Valider et transmettre au circuit V7", type="primary")
            ko = b.form_submit_button("Rejeter")
        if ok or ko:
            _executer(A.valider_coordonnateur, cle, note, rejeter=ko,
                      ok="Demande rejetée." if ko else "Demande transmise : opérations V7 soumises au contrôle N1.")
    if d["statut"] not in ("Transmise au circuit V7", "Servie par stock", "Annulée") and auth.droit("approbation_dg") == "w" \
            and d["creator"] != u.get("id"):
        with st.popover("Annulation par la DG"):
            motif = st.text_input("Motif", key=f"dg_ann_m_{cle}")
            if st.button("Annuler la demande", key=f"dg_ann_{cle}"):
                _executer(A.annuler, cle, motif, ok="Demande annulée.")


def _chiffrage(r: dict, s: dict) -> None:
    d, cle = r["data"], r["id"]
    fournisseurs = ui.options_fournisseurs(s)
    noms = {v: k for k, v in fournisseurs.items()}
    st.markdown("**Chiffrage par les achats** — fournisseur et prix pour chaque ligne ; une ligne entièrement servie "
                "par le stock n’a pas besoin de prix.")
    if not fournisseurs:
        st.info("Enregistrez d’abord des fournisseurs dans « Clients et fournisseurs ».")
        return
    lignes = [{"n": l["n"], "article": l["article"], "quantite": l["quantite"],
               "prix_propose": R.plain(l["prix"]) if l.get("prix") is not None else "",
               "fournisseur": fournisseurs.get(l.get("fournisseur"), ""), "prix": "", "stock": 0.0} for l in d["lignes"]]
    with st.form(f"chiffrage_{cle}"):
        edit = st.data_editor(lignes, key=f"chif_ed_{cle}", hide_index=True, width="stretch", disabled=[
            "n", "article", "quantite", "prix_propose"], column_config={
            "n": "N°", "article": "Article", "quantite": "Quantité", "prix_propose": "Prix proposé",
            "fournisseur": st.column_config.SelectboxColumn("Fournisseur retenu", options=list(noms)),
            "prix": st.column_config.TextColumn("Prix retenu", help="Vide = prix proposé confirmé"),
            "stock": st.column_config.NumberColumn("Servie par le stock", min_value=0.0)})
        note = st.text_input("Commentaire (négociation, délais…)")
        ok = st.form_submit_button("Enregistrer le chiffrage", type="primary")
    if ok:
        try:
            cot = {int(x["n"]): {"fournisseur": noms.get(x["fournisseur"] or "", ""), "prix": _prix(x["prix"]),
                                 "qte_stock": x["stock"] or 0} for x in edit}
        except ValueError as e:
            st.error(str(e))
            return
        try:
            res = A.chiffrer(cle, cot, note)
        except (ValueError, ArithmeticError) as e:
            st.error(str(e))
        else:
            ui.succes(f"Chiffrage enregistré : {R.money(res['montant'], r['currency'])} · {res['statut']}.")


# ------------------------------------------------------------------ onglets
def _a_traiter(s: dict) -> None:
    u = V.actor()
    files = A.a_traiter(u)
    a, b, c, d = st.columns(4)
    a.metric("Besoins à valider", len(files["chantier"]))
    b.metric("À chiffrer", len(files["chiffrage"]))
    c.metric("À valider (coordonnateur)", len(files["coordonnateur"]))
    d.metric("Mes brouillons ou rejets", len(files["mes_brouillons"]))
    rows = files["chantier"] + files["chiffrage"] + files["coordonnateur"] + files["mes_brouillons"]
    if files["mes_brouillons"] and st.button(f"Soumettre mes {len(files['mes_brouillons'])} brouillon(s)",
                                             icon=":material/send:"):
        erreurs = []
        for r in files["mes_brouillons"]:
            try:
                A.soumettre(r["id"])
            except ValueError as e:
                erreurs.append(f"{r['ref']} : {e}")
        if erreurs:
            st.error(" ; ".join(erreurs))
        else:
            ui.succes("Brouillons soumis au chef de chantier / directeur de projet.")
    if not rows:
        st.info("Aucune demande n’attend votre action.")
    else:
        _liste_et_detail(rows, s, "trait")
    if auth.modifie("chiffrage_achats"):
        centre_imports.encart(["chiffrage_achats"], "Chiffrer plusieurs demandes depuis Excel")


def _liste_et_detail(rows: list[dict], s: dict, key: str) -> None:
    ops = V.records("operation")
    tab = [{"_id": r["id"], "ref": r["ref"], "chantier": R.project_name(s, r["project"]), "objet": r["data"]["objet"],
            "besoin": r["data"]["date_besoin"], "lignes": len(r["data"]["lignes"]), "statut": r["data"]["statut"],
            "montant": R.money(A.montant_total(r["data"]), r["currency"]) if any(
                l.get("prix") is not None for l in r["data"]["lignes"]) else "",
            "execution": A.execution(r, ops) if r["data"].get("operations") else ""}
           for r in sorted(rows, key=lambda x: x["ref"], reverse=True)]
    i = ui.tableau(tab, {"ref": "Référence", "chantier": "Chantier", "objet": "Objet", "besoin": "Date de besoin",
                         "lignes": "Lignes", "statut": "Statut", "montant": "Montant chiffré",
                         "execution": "Exécution V7"}, key=f"da_{key}", selection=True)
    if i is None:
        st.caption("Sélectionnez une demande pour la consulter ou agir.")
        return
    r = next(x for x in rows if x["id"] == tab[i]["_id"])
    with st.container(border=True):
        st.subheader(r["ref"])
        _detail(r, s)
        _actions(r, s)


def _nouvelle(s: dict) -> None:
    u = V.actor()
    if not auth.modifie("demandes_achat"):
        ui.lecture_seule()
        return
    budgets = {b["project"]: b for b in V.active_budgets(V.records("budget")) if b["data"]["status"] == "Approuvé"
               and auth.sur_chantier(u, b["project"])}
    if not budgets:
        st.info("Aucun chantier de votre périmètre n’a de budget DQE approuvé : une demande d’achat est imputée à un "
                "poste DQE.")
    else:
        pid = st.selectbox("Chantier", list(budgets), format_func=lambda p: R.project_name(s, p), key="da_ch")
        b = budgets[pid]
        postes = [x["code"] for x in b["data"]["lines"]]
        libelles = {x["code"]: f"{x['code']} — {x['label']}" for x in b["data"]["lines"]}
        fournisseurs = ui.options_fournisseurs(s)
        noms = {v: k for k, v in fournisseurs.items()}
        st.caption("Postes DQE : " + " · ".join(libelles.values()) + f" · devise du budget : {b['currency']}")
        with st.form("da_nouvelle"):
            a, c = st.columns(2)
            objet = a.text_input("Objet *", placeholder="ex. Approvisionnement coulage dalle R+1")
            lieu = c.text_input("Lieu de livraison", placeholder="ex. Chantier, dépôt central")
            with a:
                besoin = ui.date_txt("Date de besoin", "da_date", (dt.date.today() + dt.timedelta(days=7)).isoformat())
            st.markdown("**Lignes** — prix et fournisseur facultatifs : les achats les complètent.")
            lignes = st.data_editor([{"post": postes[0], "article": "", "unite": "", "quantite": None, "prix": "",
                                      "fournisseur": "", "note": ""}], num_rows="dynamic", key="da_lignes",
                                    hide_index=True, width="stretch", column_config={
                "post": st.column_config.SelectboxColumn("Poste DQE", options=postes, required=True),
                "article": st.column_config.TextColumn("Article *", required=True),
                "unite": "Unité", "quantite": st.column_config.NumberColumn("Quantité *", min_value=0.0),
                "prix": st.column_config.TextColumn("Prix proposé"),
                "fournisseur": st.column_config.SelectboxColumn("Fournisseur proposé", options=list(noms)),
                "note": "Note"})
            ok = st.form_submit_button("Enregistrer en brouillon", type="primary")
            ok_sou = st.form_submit_button("Enregistrer et soumettre")
        if ok or ok_sou:
            try:
                propres = [{"post": x["post"], "article": x["article"], "unite": x["unite"], "quantite": x["quantite"],
                            "prix": _prix(x["prix"]), "fournisseur": noms.get(x["fournisseur"] or "", ""),
                            "note": x["note"]} for x in lignes if (x.get("article") or "").strip()]
                i = A.creer(pid, objet, lieu, besoin, propres)
                if ok_sou:
                    A.soumettre(i)
            except (ValueError, ArithmeticError) as e:
                st.error(str(e))
            else:
                ui.succes("Demande " + ("soumise au chef de chantier." if ok_sou else "enregistrée en brouillon."))
    centre_imports.encart(["demandes_achat"], "Importer des demandes depuis Excel")


def _toutes(s: dict) -> None:
    u = V.actor()
    rows = A.demandes(u)
    if not rows:
        st.info("Aucune demande d’achat.")
        return
    a, b = st.columns(2)
    chantiers = sorted({r["project"] for r in rows})
    ch = a.selectbox("Chantier", [""] + chantiers, format_func=lambda p: "Tous" if not p else R.project_name(s, p),
                     key="da_f_ch")
    statuts = b.multiselect("Statuts", list(A.STATUTS), key="da_f_st")
    rows = [r for r in rows if (not ch or r["project"] == ch) and (not statuts or r["data"]["statut"] in statuts)]
    _liste_et_detail(rows, s, "toutes")


def _commandes(s: dict) -> None:
    if not auth.modifie("chiffrage_achats"):
        ui.lecture_seule()
        return
    if auth.utilisateur().get("role") not in ("admin", "finance"):
        st.info("La commande V7 est réservée aux familles de rôle Finance et Direction.")
        return
    ops = [o for o in V.records("operation") if o["data"].get("demande_achat") and o["data"]["status"] == "Approuvée"]
    if not ops:
        st.info("Aucune opération issue d’une demande d’achat n’est approuvée (N1 → N2 → N3 → DG) et en attente de "
                "commande.")
        return
    fournisseurs = {c["id"]: c["name"] for c in s["clients"]}
    par_f: dict[str, list] = {}
    for o in ops:
        par_f.setdefault(o["data"]["party"], []).append(o)
    f = st.selectbox("Fournisseur", list(par_f), format_func=lambda i: f"{fournisseurs.get(i, i)} ({len(par_f[i])})",
                     key="cg_f")
    choix = {o["id"]: o for o in par_f[f]}
    with st.form("commande_groupee"):
        ids = st.multiselect("Opérations à commander ensemble", list(choix), default=list(choix), format_func=lambda i:
                             f"{choix[i]['ref']} · {R.project_name(s, choix[i]['project'])} · "
                             f"{R.money(choix[i]['data']['amount'], choix[i]['currency'])}")
        a, b = st.columns(2)
        ref = a.text_input("Référence du bon de commande *", placeholder="ex. BC-2026-0150")
        with b:
            date_ = ui.date_txt("Date de commande", "cg_date")
        ok = st.form_submit_button("Passer la commande groupée", type="primary")
    total = sum(choix[i]["data"]["amount"] for i in ids) if ids else 0
    devises = {choix[i]["currency"] for i in ids}
    if len(devises) == 1:
        st.caption(f"Total : {R.money(total, devises.pop())}")
    if ok:
        _executer(A.commande_groupee, ids, ref, date_, ok="Commande enregistrée sur les opérations choisies.")


def _reglages() -> None:
    p = A.politique()
    st.caption("Au-delà du seuil de la devise, le coordonnateur valide la demande chiffrée. Seuil 0 : il valide "
               "toutes les demandes. Un dépassement de poste DQE impose toujours sa validation.")
    with st.form("da_politique"):
        cols = st.columns(len(R.CURRENCIES))
        seuils = {}
        for col, c in zip(cols, R.CURRENCIES):
            seuils[c] = col.text_input(f"Seuil coordonnateur ({c})", R.plain(p["seuil_coordonnateur"].get(c, 0)))
        compte = st.selectbox("Compte de coût des opérations créées", [k for k in V.CHART if k.startswith(("6", "2", "3"))],
                              index=[k for k in V.CHART if k.startswith(("6", "2", "3"))].index(p["compte"]),
                              format_func=lambda k: f"{k} — {V.CHART[k]}")
        ok = st.form_submit_button("Enregistrer les seuils", type="primary")
    if ok:
        try:
            propres = {c: R.cents(v, f"Seuil {c}") for c, v in seuils.items()}
        except ValueError as e:
            st.error(str(e))
        else:
            _executer(A.configurer_politique, propres, compte, ok="Seuils enregistrés.")


def page() -> None:
    if not any(auth.voit(m) for m in MODULES):
        st.error("Votre rôle ne donne pas accès à cette rubrique.")
        st.stop()
    ui.en_tete("Demandes d’achat", "Chantier → chef de chantier → achats → coordonnateur → circuit financier V7 "
                                   "(N1 → N2 → N3 → DG) → commande, réception, facture.")
    s = R.charger("clients", "projects")
    noms = ["À traiter", "Nouvelle demande", "Toutes les demandes", "Commandes groupées"]
    if auth.droit("approbation_dg") == "w":
        noms.append("Réglages")
    onglets = st.tabs(noms)
    with onglets[0]:
        _a_traiter(s)
    with onglets[1]:
        _nouvelle(s)
    with onglets[2]:
        _toutes(s)
    with onglets[3]:
        _commandes(s)
    if len(onglets) > 4:
        with onglets[4]:
            _reglages()
