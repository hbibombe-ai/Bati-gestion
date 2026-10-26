"""Achats et stock V8 : besoins et demandes à lignes d'articles, validations N1 → DG, commandes, réceptions,
factures et paiements, stock permanent, référentiel et paramètres (mémo V8, § 4 et § 5).

L'écran n'exécute aucun calcul métier : il appelle les services achats.py, stocks.py, comptabilisation.py."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import streamlit as st

import achats as A
import auth
import db
import derogations as DR
import gestion_v7 as V
import regles as R
import stocks as S
import ui
from vues import imports as centre_imports

MODULES = ["demandes_achat", "chiffrage_achats", "factures_achat", "magasin", "achats", "approbation_n1",
           "approbation_n2", "approbation_n3", "approbation_dg"]


def _ok(fn, *args, msg="Enregistré.", **kw):
    try:
        r = fn(*args, **kw)
    except (ValueError, ArithmeticError) as e:
        st.error(str(e))
        return None
    ui.succes(msg)
    return r


def _q(v) -> str:
    return f"{Decimal(str(v)).normalize():f}" if v not in (None, "") else ""


def _ref() -> dict:
    s = R.charger("clients", "projects")
    s["articles"] = {a["id"]: a for a in S.articles()}
    s["magasins"] = {m["id"]: m for m in S.magasins()}
    return s


def _lib_article(s, i) -> str:
    a = s["articles"].get(i)
    return f"{a['code']} — {a['libelle']} ({a['unite_stock']})" if a else "—"


# ------------------------------------------------------------------ besoins et demandes
def _besoins(s: dict) -> None:
    u = V.actor()
    if auth.modifie("demandes_achat"):
        budgets = {b["project"]: b for b in V.active_budgets(V.records("budget")) if b["data"]["status"] == "Approuvé"
                   and auth.sur_chantier(u, b["project"])}
        arts = {k: _lib_article(s, k) for k, a in s["articles"].items() if a["actif"]}
        mags = {k: f"{m['code']} — {m['libelle']}" for k, m in s["magasins"].items() if m["actif"]}
        with st.expander("Exprimer un besoin du chantier", icon=":material/add_shopping_cart:", expanded=False):
            if not budgets or not arts or not mags:
                st.info("Il faut un chantier de votre périmètre avec budget DQE approuvé, des articles et des magasins "
                        "(onglet Référentiel).")
            else:
                pid = st.selectbox("Chantier", list(budgets), format_func=lambda p: R.project_name(s, p), key="bes_ch")
                defaut = S.magasin_du_chantier(pid)
                mag = st.selectbox("Magasin de livraison", list(mags), format_func=mags.get, key="bes_mag",
                                   index=list(mags).index(defaut["id"]) if defaut and defaut["id"] in mags else 0)
                postes = [x["code"] for x in budgets[pid]["data"]["lines"]]
                noms = {v: k for k, v in arts.items()}
                with st.form("besoin"):
                    date_ = ui.date_txt("Date souhaitée", "bes_d", (dt.date.today() + dt.timedelta(days=7)).isoformat())
                    lignes = st.data_editor([{"article": "", "poste": postes[0], "quantite": None, "prix": "",
                                              "motif": ""}], num_rows="dynamic", key="bes_lignes", hide_index=True,
                                            width="stretch", column_config={
                        "article": st.column_config.SelectboxColumn("Article", options=list(noms), required=True),
                        "poste": st.column_config.SelectboxColumn("Poste DQE", options=postes, required=True),
                        "quantite": st.column_config.NumberColumn("Quantité (unité de stock)", min_value=0.0),
                        "prix": st.column_config.TextColumn("Prix unitaire estimé"),
                        "motif": st.column_config.TextColumn("Motif d’achat malgré le stock")})
                    just = st.text_area("Justification")
                    ok = st.form_submit_button("Servir le disponible et demander le manque", type="primary")
                if ok:
                    try:
                        propres = [dict(article=noms[x["article"]], poste=x["poste"], quantite=x["quantite"],
                                        prix_estime=R.cents(x["prix"] or "0", "Prix estimé"),
                                        motif_hors_stock=x["motif"] or None) for x in lignes if x.get("article")]
                        r = A.besoin_chantier(pid, mag, date_, propres, just)
                    except (ValueError, ArithmeticError) as e:
                        st.error(str(e))
                    else:
                        ui.succes(("Bon de sortie créé pour le disponible. " if r["bon_sortie"] else "")
                                  + ("Demande d’achat créée en brouillon pour le manque." if r["demande"] else ""))
        centre_imports.encart(["demandes_achat"], "Importer des demandes depuis Excel")
    rows = A.demandes(u)
    if not rows:
        st.info("Aucune demande d’achat.")
        return
    tab = [{"_id": d["id"], "num": d["numero"], "ch": R.project_name(s, d["projet"]), "date": d["date_souhaitee"],
            "st": A.statut_demande(d), "niv": f"{d['niveau']}/{len(V.policy()['levels'])}" if d["statut"] == "Soumise" else "",
            "est": R.money(A.montant_estime(None, d["id"]), d["devise"]), "orig": d["origine"]}
           for d in sorted(rows, key=lambda x: x["numero"], reverse=True)]
    i = ui.tableau(tab, {"num": "Numéro", "ch": "Chantier", "date": "Date souhaitée", "st": "Statut", "niv": "Validations",
                         "est": "Estimation", "orig": "Origine"}, key="tab_da", selection=True)
    if i is None:
        return
    d = next(x for x in rows if x["id"] == tab[i]["_id"])
    with st.container(border=True):
        st.subheader(d["numero"])
        st.dataframe([{"N°": l["numero"], "Article": _lib_article(s, l["article"]), "Poste": l["poste"],
                       "Quantité": _q(l["quantite"]), "Prix estimé": R.money(l["prix_estime"], d["devise"]),
                       "Statut": A.statut_ligne(d, l), "Clôture": l["motif_cloture"] or ""}
                      for l in A.lignes_demande(None, d["id"])], hide_index=True, width="stretch")
        ch = A.chaine(d["id"])
        if any(ch.values()):
            st.caption("Chaîne : " + " · ".join(
                [f"BC {c['numero']}" for c in ch["commandes"]] + [f"BR {r['numero']}" for r in ch["receptions"]]
                + [f"Facture {f['reference']} ({f['statut']})" for f in ch["factures"]]))
        if d["demandeur"] == u["id"] and d["statut"] == "Brouillon":
            c1, c2 = st.columns(2)
            alertes = c1.checkbox("J’ai vu les alertes budgétaires et je confirme", key=f"al_{d['id']}")
            if c1.button("Soumettre (N0)", type="primary", key=f"sou_{d['id']}"):
                _ok(A.soumettre, d["id"], accepter_alertes=alertes, msg="Demande soumise au circuit de validation.")
            with c2.popover("Annuler"):
                m = st.text_input("Motif", key=f"anm_{d['id']}")
                if st.button("Confirmer", key=f"an_{d['id']}"):
                    _ok(A.annuler_demande, d["id"], m, msg="Demande annulée.")
        if d["statut"] == "Approuvée" and (auth.modifie("chiffrage_achats") or auth.droit("approbation_dg") == "w"):
            with st.popover("Clôturer une ligne (libère l’engagement restant)"):
                n = st.selectbox("Ligne", [l["id"] for l in A.lignes_demande(None, d["id"]) if not l["cloturee"]],
                                 format_func=lambda x: next(f"{l['numero']} · {_lib_article(s, l['article'])}"
                                                            for l in A.lignes_demande(None, d["id"]) if l["id"] == x),
                                 key=f"cl_{d['id']}")
                m = st.text_input("Motif", key=f"clm_{d['id']}")
                if n and st.button("Clôturer", key=f"clb_{d['id']}"):
                    _ok(A.cloturer_ligne, n, m, msg="Ligne clôturée.")
        with st.expander("Historique"):
            st.dataframe([{"Date": h["at"][:16].replace("T", " "), "Par": h["name"], "Action": h["action"],
                           "Note": h.get("note", "")} for h in d["historique"]], hide_index=True, width="stretch")


def _validations(s: dict) -> None:
    u = V.actor()
    rows = A.a_valider(u)
    if not rows:
        st.info("Aucune demande n’attend votre validation.")
        return
    niveaux = V.policy()["levels"]
    for d in rows:
        with st.container(border=True):
            st.markdown(f"**{d['numero']}** · {R.project_name(s, d['projet'])} · "
                        f"{R.money(A.montant_estime(None, d['id']), d['devise'])} · niveau {niveaux[d['niveau']]}")
            st.dataframe([{"Article": _lib_article(s, l["article"]), "Poste": l["poste"], "Quantité": _q(l["quantite"]),
                           "Prix estimé": R.money(l["prix_estime"], d["devise"])}
                          for l in A.lignes_demande(None, d["id"])], hide_index=True, width="stretch")
            with st.form(f"val_{d['id']}"):
                note = st.text_input("Commentaire de contrôle *")
                derog = st.checkbox("Dérogation DG au dépassement du budget") if niveaux[d["niveau"]] == niveaux[-1] else False
                a, b = st.columns(2)
                ok = a.form_submit_button("Approuver", type="primary")
                ko = b.form_submit_button("Rejeter")
            if ok or ko:
                _ok(A.approuver, d["id"], note, rejeter=ko, derogation=derog,
                    msg="Demande rejetée (retour en brouillon)." if ko else "Validation enregistrée.")


def _commandes(s: dict) -> None:
    if auth.modifie("chiffrage_achats"):
        dispo = A.lignes_a_commander()
        fourn = ui.options_fournisseurs(s)
        if not dispo:
            st.info("Aucune ligne approuvée à commander.")
        elif fourn:
            with st.expander("Nouveau bon de commande (plusieurs demandes, un fournisseur)", icon=":material/receipt:"):
                a, b, c = st.columns(3)
                f = a.selectbox("Fournisseur", list(fourn), format_func=fourn.get, key="bc_f")
                devise = b.selectbox("Devise", R.CURRENCIES, key="bc_dev")
                with c:
                    date_ = ui.date_txt("Date", "bc_d")
                lib = {x["id"]: f"{x['demande_numero']} · {_lib_article(s, x['article'])} · reste {_q(x['reste'])}"
                       for x in dispo}
                with st.form("bc"):
                    ed = st.data_editor([{"ligne": lib[x["id"]], "quantite": float(x["reste"]), "prix": "",
                                          "inclure": False} for x in dispo], hide_index=True, width="stretch",
                                        disabled=["ligne"], key="bc_ed", column_config={
                        "ligne": "Ligne de demande", "quantite": st.column_config.NumberColumn("Quantité", min_value=0.0),
                        "prix": st.column_config.TextColumn("Prix unitaire"), "inclure": "Commander"})
                    devis = st.data_editor([{"fournisseur": "", "reference": "", "montant": ""}], num_rows="dynamic",
                                           hide_index=True, key="bc_devis", width="stretch")
                    cond = st.text_input("Conditions (délai, livraison, paiement)")
                    ok = st.form_submit_button("Émettre le bon de commande", type="primary")
                if ok:
                    inv = {v: k for k, v in lib.items()}
                    try:
                        lignes = [dict(demande_ligne=inv[x["ligne"]], quantite=x["quantite"],
                                       prix_unitaire=R.cents(x["prix"], "Prix unitaire")) for x in ed if x["inclure"]]
                    except ValueError as e:
                        st.error(str(e))
                    else:
                        _ok(A.commander, f, devise, date_, lignes, devis, cond, msg="Bon de commande émis.")
    cmds = sorted(db.tout("ach_commandes"), key=lambda c: c["numero"], reverse=True)
    if cmds:
        st.dataframe([{"Numéro": c["numero"], "Fournisseur": R.name_of(s["clients"], c["fournisseur"], ""),
                       "Date": c["date"], "Devise": c["devise"], "Statut": c["statut"],
                       "Montant": R.money(sum(S.cents(S.D(l["quantite"]) * l["prix_unitaire"])
                                              for l in A.lignes_commande(None, c["id"])), c["devise"])}
                      for c in cmds], hide_index=True, width="stretch")


def _receptions(s: dict) -> None:
    if not auth.modifie("magasin"):
        ui.lecture_seule()
        return
    cmds = [c for c in db.tout("ach_commandes") if c["statut"] == "Émise"]
    if not cmds:
        st.info("Aucune commande à réceptionner.")
        return
    c = st.selectbox("Commande", [x["id"] for x in cmds], key="br_c",
                     format_func=lambda i: next(f"{x['numero']} · {R.name_of(s['clients'], x['fournisseur'], '')}"
                                                for x in cmds if x["id"] == i))
    lignes = A.lignes_a_recevoir(c)
    with st.form("br"):
        bl = st.text_input("Bon de livraison ou attestation de service fait *")
        date_ = ui.date_txt("Date de réception", "br_d", max_aujourdhui=True)
        ed = st.data_editor([{"id": l["id"], "article": _lib_article(s, A._get(None, "ach_demande_lignes",
                                                                                l["demande_ligne"])["article"]),
                              "commande": _q(l["quantite"]), "deja": _q(l["recu"]), "acceptee": 0.0, "rejetee": 0.0,
                              "motif": ""} for l in lignes], hide_index=True, width="stretch", key="br_ed",
                            disabled=["id", "article", "commande", "deja"], column_config={
            "id": None, "article": "Article", "commande": "Commandé", "deja": "Déjà reçu",
            "acceptee": st.column_config.NumberColumn("Accepté", min_value=0.0),
            "rejetee": st.column_config.NumberColumn("Rejeté", min_value=0.0), "motif": "Motif du rejet"})
        ok = st.form_submit_button("Valider la réception", type="primary")
    if ok:
        _ok(A.receptionner, c, date_, bl, [dict(commande_ligne=x["id"], qte_acceptee=x["acceptee"],
                                                qte_rejetee=x["rejetee"], motif=x["motif"]) for x in ed],
            msg="Réception enregistrée : stock et écritures mis à jour.")


def _factures(s: dict) -> None:
    fourn = ui.options_fournisseurs(s)
    if auth.modifie("factures_achat") and fourn:
        with st.expander("Saisir une facture fournisseur (rapprochement à 3 voies)", icon=":material/request_quote:"):
            a, b = st.columns(2)
            f = a.selectbox("Fournisseur", list(fourn), format_func=fourn.get, key="fa_f")
            lignes = A.lignes_a_facturer(f)
            if not lignes:
                st.info("Aucune quantité reçue à facturer pour ce fournisseur.")
            else:
                with st.form("fa"):
                    a, b, c = st.columns(3)
                    ref = a.text_input("Référence de la facture *")
                    with b:
                        date_ = ui.date_txt("Date", "fa_d")
                    with c:
                        ech = ui.date_txt("Échéance", "fa_e")
                    devise = lignes[0]["devise"]
                    ed = st.data_editor([{"id": l["id"], "commande": l["commande_numero"], "a_facturer": _q(l["a_facturer"]),
                                          "quantite": float(l["a_facturer"]), "prix": R.plain(l["prix_unitaire"])}
                                         for l in lignes], hide_index=True, width="stretch", key="fa_ed",
                                        disabled=["id", "commande", "a_facturer"], column_config={
                        "id": None, "commande": "Commande", "a_facturer": "Reçu non facturé",
                        "quantite": st.column_config.NumberColumn("Quantité facturée", min_value=0.0),
                        "prix": "Prix facturé"})
                    tva = st.text_input("TVA portée sur la facture (montant)", "0")
                    ok = st.form_submit_button("Enregistrer la facture", type="primary")
                if ok:
                    try:
                        propres = [dict(commande_ligne=x["id"], quantite=x["quantite"],
                                        prix_unitaire=R.cents(x["prix"], "Prix")) for x in ed if x["quantite"]]
                        ht = sum(S.cents(S.D(x["quantite"]) * x["prix_unitaire"]) for x in propres)
                        _ok(A.enregistrer_facture, f, ref, date_, ech, devise, ht, R.cents(tva, "TVA"), propres,
                            msg="Facture enregistrée : à valider par une autre personne.")
                    except ValueError as e:
                        st.error(str(e))
    facs = sorted(db.tout("ach_factures"), key=lambda x: x["date"], reverse=True)
    if not facs:
        return
    tab = [{"_id": x["id"], "ref": x["reference"], "f": R.name_of(s["clients"], x["fournisseur"], ""), "d": x["date"],
            "m": R.money(x["montant_ht"] + x["tva"], x["devise"]), "st": x["statut"],
            "p": R.money(sum(p["montant"] for p in x["paiements"]), x["devise"])} for x in facs]
    i = ui.tableau(tab, {"ref": "Facture", "f": "Fournisseur", "d": "Date", "m": "TTC", "st": "Statut", "p": "Payé"},
                   key="tab_fa", selection=True)
    if i is None:
        return
    x = next(f for f in facs if f["id"] == tab[i]["_id"])
    if x["statut"] == "Enregistrée" and auth.modifie("factures_achat"):
        with st.form(f"vf_{x['id']}"):
            note = st.text_input("Commentaire de contrôle *")
            a, b = st.columns(2)
            ok, ko = a.form_submit_button("Valider", type="primary"), b.form_submit_button("Rejeter")
        if ok or ko:
            _ok(A.valider_facture, x["id"], note, rejeter=ko, msg="Facture traitée.")
    if x["statut"] == "Validée" and auth.modifie("tresorerie"):
        comptes = [a for a in V.records("account") if a["currency"] == x["devise"]]
        if comptes:
            with st.form(f"pf_{x['id']}"):
                c = st.selectbox("Compte de trésorerie", [a["id"] for a in comptes],
                                 format_func=lambda i: next(a["ref"] for a in comptes if a["id"] == i))
                m = st.text_input("Montant", R.plain(x["montant_ht"] + x["tva"] - sum(p["montant"] for p in x["paiements"])))
                ref = st.text_input("Référence du règlement *")
                with st.container():
                    d = ui.date_txt("Date", f"pf_d_{x['id']}")
                ok = st.form_submit_button("Payer", type="primary")
            if ok:
                try:
                    _ok(A.payer, x["id"], c, R.cents(m, "Montant", positif=True), d, ref, msg="Paiement enregistré.")
                except ValueError as e:
                    st.error(str(e))


def _stock(s: dict) -> None:
    etat = S.etat_valorise()
    tenue = (S.tenue() or {}).get("devise", "")
    if etat:
        st.dataframe([{"Article": e["article"], "Libellé": e["libelle"], "Magasin": e["magasin"], "Quantité": _q(e["quantite"]),
                       "Réservé": _q(e["reserve"]), "Unité": e["unite"], "CMUP": R.money(S.cents(e["cmup"]), tenue),
                       "Valeur": R.money(e["valeur"], tenue)} for e in etat], hide_index=True, width="stretch")
        import comptabilisation as CPT
        c = CPT.controle_stock_comptes()
        (st.success if not c["ecart"] else st.error)(
            f"Contrôle permanent : stock {R.money(c['stock'], tenue)} · comptes de stock {R.money(c['comptes'], tenue)}"
            + ("" if not c["ecart"] else f" · écart {R.money(c['ecart'], tenue)}"))
    else:
        st.info("Aucun stock.")
    for a in S.alertes_seuils():
        st.warning(f"{a['code']} sous le seuil minimum : {_q(a['disponible'])} disponible pour {_q(a['seuil_min'])}.")
    bons = [b for b in db.tout("stk_bons_sortie") if b["statut"] == "À servir"]
    if bons:
        st.markdown("**Bons de sortie à servir**")
        for b in bons:
            c1, c2 = st.columns([4, 1])
            c1.write(f"{b['numero']} · {R.project_name(s, b['projet'])} · magasin "
                     f"{s['magasins'].get(b['magasin'], {}).get('code', '')} · "
                     + ", ".join(f"{_lib_article(s, l['article'])} × {_q(l['quantite'])}"
                                 for l in db.tout("stk_bon_sortie_lignes") if l["bon"] == b["id"]))
            if auth.modifie("magasin") and c2.button("Servir", key=f"srv_{b['id']}"):
                _ok(S.servir_bon, b["id"], msg="Sortie enregistrée : coût imputé au chantier.")
    with st.expander("Mouvements de stock"):
        mv = sorted(db.tout("stk_mouvements"), key=lambda m: m["numero"], reverse=True)[:200]
        st.dataframe([{"N°": m["numero"], "Date": m["date"], "Type": m["type"], "Article": _lib_article(s, m["article"]),
                       "Quantité": _q(m["quantite"]), "Valeur": R.money(m["valeur"], m["devise_tenue"]),
                       "Chantier": R.project_name(s, m["projet"]) if m["projet"] else "", "Poste": m["poste"] or ""}
                      for m in mv], hide_index=True, width="stretch")
        if auth.modifie("magasin") and mv:
            with st.form("cp_mvt"):
                m = st.selectbox("Mouvement à contre-passer", [x["id"] for x in mv if x["type"] != "ecart_prix"],
                                 format_func=lambda i: next(x["numero"] for x in mv if x["id"] == i))
                motif = st.text_input("Motif")
                ok = st.form_submit_button("Contre-passer")
            if ok:
                _ok(S.contre_passer, m, motif, msg="Mouvement contre-passé (écriture inverse générée).")


def _referentiel(s: dict) -> None:
    if auth.modifie("comptabilite"):
        with st.expander("Familles d’articles (comptes)", icon=":material/category:"):
            st.dataframe(S.familles(), hide_index=True, width="stretch",
                         column_order=["code", "libelle", "compte_stock", "compte_variation", "compte_charge", "actif"])
            with st.form("fam"):
                a, b, c, d, e = st.columns(5)
                code, lib = a.text_input("Code"), b.text_input("Libellé")
                cs, cv, cc = c.text_input("Compte de stock"), d.text_input("Compte de variation"), e.text_input("Compte de charge")
                ok = st.form_submit_button("Enregistrer la famille")
            if ok:
                _ok(S.enregistrer_famille, code, lib, cc, cs, cv, msg="Famille enregistrée.")
    st.markdown("**Articles**")
    st.dataframe([{"Code": a["code"], "Libellé": a["libelle"], "Famille": a["famille"], "Nature": S.NATURES[a["nature"]],
                   "Unité": a["unite_stock"], "Seuil min.": _q(a["seuil_min"]), "Actif": a["actif"],
                   "À qualifier": a["a_qualifier"]} for a in S.articles()], hide_index=True, width="stretch")
    if auth.modifie("achats"):
        fams = [f["code"] for f in S.familles(True)]
        with st.form("art"):
            a, b, c, d = st.columns(4)
            code, lib = a.text_input("Code article"), b.text_input("Libellé")
            fam = c.selectbox("Famille", fams) if fams else None
            nat = d.selectbox("Nature", list(S.NATURES), format_func=S.NATURES.get)
            a, b, c, d = st.columns(4)
            us, ua = a.text_input("Unité de stock"), b.text_input("Unité d’achat")
            coef, smin = c.text_input("Coefficient", "1"), d.text_input("Seuil minimum")
            existant = st.selectbox("Modifier l’article existant (facultatif)", [""] + [x["id"] for x in S.articles()],
                                    format_func=lambda i: "Nouvel article" if not i else _lib_article(s, i))
            ok = st.form_submit_button("Enregistrer l’article")
        if ok:
            _ok(S.enregistrer_article, code, lib, fam, nat, us, ua, coef, smin or None, id_=existant or None,
                msg="Article enregistré.")
        st.markdown("**Magasins**")
        st.dataframe([{"Code": m["code"], "Libellé": m["libelle"], "Type": S.TYPES_MAGASIN[m["type"]],
                       "Chantier": R.project_name(s, m["projet"]) if m["projet"] else "", "Actif": m["actif"]}
                      for m in S.magasins()], hide_index=True, width="stretch")
        with st.form("mag"):
            a, b, c, d = st.columns(4)
            code, lib = a.text_input("Code magasin"), b.text_input("Libellé du magasin")
            typ = c.selectbox("Type", list(S.TYPES_MAGASIN), format_func=S.TYPES_MAGASIN.get)
            pr = d.selectbox("Chantier", [""] + [p["id"] for p in s["projects"]],
                             format_func=lambda p: "—" if not p else R.project_name(s, p))
            ok = st.form_submit_button("Créer le magasin")
        if ok:
            _ok(S.enregistrer_magasin, code, lib, typ, pr or None, msg="Magasin créé.")
    centre_imports.encart(["referentiel_stock"], "Importer familles, articles et magasins depuis Excel")


def _parametres() -> None:
    t_ = S.tenue()
    st.markdown("**Monnaie de tenue** " + (f": {t_['devise']} (décision {t_['reference']}, {t_['decide_nom']})"
                                           if t_ else ": non fixée — la valorisation du stock est bloquée")
                + (f" · comptabilisation des opérations existantes depuis le {t_['debut']}" if t_ and t_.get("debut")
                   else ""))
    p = A.parametres()
    st.markdown("**Tolérances et mise en concurrence** " + (
        f": quantité {p['tolerance_qte_pct']} %, prix {p['tolerance_prix_pct']} %, {p['nb_devis']} devis au-delà de "
        + ", ".join(R.money(v, c) for c, v in (p.get("seuil_devis") or {}).items() if v is not None) + f" ({p['reference']})"
        if p else ": non fixées — commandes, réceptions et factures bloquées"))
    if auth.droit("approbation_dg") != "w":
        return
    with st.form("tenue"):
        a, b, c, d = st.columns(4)
        dev = a.selectbox("Monnaie de tenue", R.CURRENCIES, index=R.CURRENCIES.index(t_["devise"]) if t_ else 0)
        ref, mot = b.text_input("Référence de la décision"), c.text_input("Motif")
        debut = d.text_input("Démarrage comptable (AAAA-MM-JJ)", (t_ or {}).get("debut") or "",
                             help="Les opérations existantes (V7, caisse, dépenses, tiers) sont comptabilisées à partir "
                                  "de cette date. Vide = pas encore.")
        if st.form_submit_button("Enregistrer la monnaie de tenue"):
            _ok(S.fixer_tenue, dev, ref, mot, debut.strip() or None)
    with st.form("tol"):
        a, b, c = st.columns(3)
        tq, tp = a.text_input("Tolérance quantité (%)", p.get("tolerance_qte_pct", "")), b.text_input(
            "Tolérance prix (%)", p.get("tolerance_prix_pct", ""))
        nb = c.number_input("Nombre de devis exigé", min_value=1, max_value=10, value=int(p.get("nb_devis") or 1))
        cols = st.columns(len(R.CURRENCIES))
        seuils = {cu: col.text_input(f"Seuil de mise en concurrence {cu} (vide = aucun)",
                                     R.plain((p.get("seuil_devis") or {}).get(cu)) if (p.get("seuil_devis") or {}).get(cu) is not None else "")
                  for col, cu in zip(cols, R.CURRENCIES)}
        a, b = st.columns(2)
        ref, mot = a.text_input("Référence (note DG)"), b.text_input("Motif ")
        ok = st.form_submit_button("Enregistrer les paramètres d’achat")
    if ok:
        try:
            _ok(A.configurer, tq, tp, {k: (R.cents(v) if v.strip() else None) for k, v in seuils.items()}, nb, ref, mot)
        except ValueError as e:
            st.error(str(e))
    with st.expander("Dérogations à la séparation des fonctions", icon=":material/gpp_maybe:"):
        us = [u for u in db.tout("users", sans=("mdp_hash",)) if u["actif"]]
        with st.form("derog"):
            a, b = st.columns(2)
            uid = a.selectbox("Personne", [u["id"] for u in us], format_func=lambda i: next(u["nom"] for u in us if u["id"] == i))
            regle = b.selectbox("Règle", list(DR.REGLES), format_func=DR.REGLES.get)
            a, b, c = st.columns(3)
            with a:
                deb = ui.date_txt("Du", "der_d")
            with b:
                fin = ui.date_txt("Au", "der_f")
            mot = c.text_input("Motif *")
            ok = st.form_submit_button("Accorder")
        if ok:
            _ok(DR.accorder, uid, regle, deb, fin, mot, msg="Dérogation accordée et inscrite au journal d’audit.")
        st.dataframe([{"Personne": d["nom"], "Règle": DR.REGLES[d["regle"]], "Du": d["debut"], "Au": d["fin"],
                       "Motif": d["motif"], "Accordée par": d["accordee_nom"], "Révoquée": d.get("revoquee", False)}
                      for d in DR.etat()], hide_index=True, width="stretch")
    apercu = A.reprendre_transitoires()
    if apercu:
        with st.expander(f"Reprise des {len(apercu)} demande(s) du circuit transitoire", icon=":material/history:"):
            st.dataframe(apercu, hide_index=True, width="stretch")
            if st.button("Reprendre en brouillon dans le circuit V8"):
                _ok(lambda: A.reprendre_transitoires(execute=True), msg="Demandes reprises en brouillon.")


def page() -> None:
    if not any(auth.voit(m) for m in MODULES):
        st.error("Votre rôle ne donne pas accès à cette rubrique.")
        st.stop()
    ui.en_tete("Achats et stock", "Besoin du chantier → demande → N1 … DG → commande → réception → facture → paiement → "
                                  "sortie vers le chantier. Stock au CMUP, écritures STK, ACH et BQ automatiques.")
    s = _ref()
    noms = ["Besoins et demandes", "Validations", "Commandes", "Réceptions", "Factures et paiements", "Stock",
            "Référentiel", "Paramètres"]
    onglets = st.tabs(noms)
    for onglet, fn in zip(onglets, (_besoins, _validations, _commandes, _receptions, _factures, _stock, _referentiel)):
        with onglet:
            fn(s)
    with onglets[-1]:
        _parametres()
