"""Comptes tiers : créances clients (balance âgée), dettes et avances fournisseurs, contre-passations."""
from __future__ import annotations

import datetime as dt
import hashlib
import re

import streamlit as st

import auth
import db
import gestion_v7 as V
import lecture_facture as LF
import regles as R
import ui
from vues import devis_factures


def _filtres() -> dict:
    return st.session_state.setdefault("ct_filtres", {"party": "", "project": "", "currency": "", "from": "", "to": ""})


def _lire_facture(s: dict) -> None:
    """Dès qu'une facture est jointe : lit le document et pré-remplit la saisie, que l'usager vérifie ensuite."""
    st.session_state.pop("sf_lecture", None)
    st.session_state.pop("sf_erreur", None)
    f = st.session_state.get("sf_fichier")
    if f is None:
        st.session_state.pop("sf_contenu", None)
        return
    contenu = f.getvalue()
    mime = ui.mime_fichier(contenu)
    if not contenu or len(contenu) > R.PIECE_MAX or not mime:
        st.session_state.pop("sf_contenu", None)
        st.session_state["sf_erreur"] = "Fichier refusé : PDF, JPEG ou PNG de 5 Mo au plus."
        return
    st.session_state.update({"sf_contenu": contenu, "sf_nom": f.name, "sf_mime": mime})
    texte = LF.texte_pdf(contenu) if mime == "application/pdf" else ""
    fournisseurs = [(c["id"], c["name"]) for c in s["clients"] if set(R.party_roles(c)) & {"supplier", "subcontractor"}]
    res = LF.extraire(texte, fournisseurs)
    if res.get("party_id"):
        st.session_state["sf_t"] = res["party_id"]
    if res.get("reference"):
        st.session_state["sf_ref"] = res["reference"]
    if res.get("date"):
        st.session_state["sf_d"] = dt.date.fromisoformat(res["date"])
    if res.get("due"):
        st.session_state["sf_due"] = dt.date.fromisoformat(res["due"])
    if res.get("amount"):
        st.session_state["sf_mt"] = res["amount"] / 100
    if res.get("currency"):
        st.session_state["sf_cur"] = res["currency"]
    trouves, manquants = LF.bilan(res)
    if trouves:
        message = "Champs proposés à partir de la facture : " + ", ".join(trouves) + "."
        if manquants:
            message += " À saisir : " + ", ".join(manquants) + "."
    else:
        message = "Aucun champ lisible dans ce document : saisissez les informations de la facture."
    st.session_state["sf_lecture"] = message


@st.dialog("Facture fournisseur", width="large")
def facture_fournisseur() -> None:
    s = R.charger("clients", "projects", "supplier_invoices", "supplier_allocations", "supplier_reversals")
    st.caption("Cette saisie crée une dette, sans sortie de caisse et sans dépense payée.")
    st.file_uploader("Facture * (PDF, JPEG ou PNG, 5 Mo au plus)", type=["pdf", "jpg", "jpeg", "png"],
                     key="sf_fichier", on_change=_lire_facture, args=(s,))
    if st.session_state.get("sf_erreur"):
        st.error(st.session_state["sf_erreur"])
    elif st.session_state.get("sf_lecture"):
        st.info(st.session_state["sf_lecture"])
    a, b = st.columns(2)
    with a:
        tiers = ui.choix("Fournisseur *", ui.options_fournisseurs(s), "sf_t", "", vide="Choisir")
        ref = st.text_input("Référence de la facture *", key="sf_ref")
        date = ui.date_txt("Date de facture *", "sf_d")
        monnaie = ui.devise("Monnaie", "sf_cur")
    with b:
        projet = ui.choix("Chantier *", ui.options_chantiers(s), "sf_p", "", vide="Choisir")
        montant = ui.montant("Montant total *", "sf_mt", 0)
        due = ui.date_txt("Échéance *", "sf_due")
    # Contrôle en direct : la facture est-elle déjà saisie pour ce fournisseur, et a-t-elle été réglée ?
    try:
        montant_apercu = R.cents(montant, "Montant", positif=True)
    except ValueError:
        montant_apercu = None
    contenu = st.session_state.get("sf_contenu")
    empreinte = hashlib.sha256(contenu).hexdigest() if contenu else None
    deja = db.requete("select entite_id from pieces_jointes where entite = 'supplier_invoice' and sha256 = :h",
                      h=empreinte) if empreinte else []
    if deja:
        fac = next((i for i in s["supplier_invoices"] if i["id"] == deja[0]["entite_id"]), None)
        if fac:
            etat = R.statut_facture_fournisseur(s, fac["party_id"], fac["reference"])
            st.error(f"Ce fichier est déjà joint à la facture « {fac['reference']} » ({etat['statut']}, "
                     f"{R.money(etat['paye'], fac['currency'])} réglés). Ne le saisissez pas une seconde fois.")
    ex = R.statut_facture_fournisseur(s, tiers, ref, montant_apercu)
    if ex:
        inv = ex["facture"]
        detail = (f"Facture « {inv['reference']} » du {inv['date']}, {R.money(inv['amount'], inv['currency'])} : "
                  f"{ex['statut']} ({R.money(ex['paye'], inv['currency'])} réglés, "
                  f"reste {R.money(ex['reste'], inv['currency'])}).")
        if not ex["montant_identique"]:
            detail += " Le montant saisi est différent de celui de la facture existante."
        if ex["statut"] == "réglée":
            st.error(detail + " Cette facture est déjà payée : ne la saisissez pas une seconde fois.")
        else:
            st.warning(detail + " Vérifiez qu’il ne s’agit pas d’un doublon avant d’enregistrer.")
    elif tiers and ref.strip():
        st.caption("Aucune facture de ce fournisseur avec cette référence : pas de doublon détecté.")
    # Identifiant réservé : les documents joints sont liés à la facture dès leur ajout
    cible = st.session_state.setdefault("sf_id_new", db.nouvel_id())
    ui.pieces_jointes("supplier_invoice", cible, peut_ajouter=True,
                      titre="Autres documents (bon de commande, bordereau… facultatif)")
    if st.button("Enregistrer", type="primary"):
        try:
            mt = R.cents(montant, "Montant", positif=True)
            if not contenu:
                raise ValueError("Joignez la facture (PDF, JPEG ou PNG) avant d’enregistrer.")
            if not tiers or not projet or not ref.strip() or due < date:
                raise ValueError("Renseignez le tiers, le chantier, la référence, le montant et une échéance après la "
                                 "date de facture.")
            if deja:
                raise ValueError("Ce fichier est déjà joint à une facture enregistrée.")
            ex = R.statut_facture_fournisseur(s, tiers, ref, mt)
            if ex:
                raise ValueError(f"Cette facture existe déjà pour ce fournisseur ({ex['statut']}, "
                                 f"{R.money(ex['paye'], ex['facture']['currency'])} réglés).")
            V.guard_legacy(projet)
            nom = re.sub(r'[\\/:*?"<>|]+', "_", st.session_state.get("sf_nom", "facture"))[:280] or "facture"
            with db.transaction(f"Facture fournisseur {ref.strip()}") as t:
                t.inserer("supplier_invoices", {"id": cible, "party_id": tiers, "project": projet,
                                                "reference": ref.strip(), "date": date, "due": due, "currency": monnaie,
                                                "amount": mt})
                t.inserer("pieces_jointes", {"id": db.nouvel_id(), "entite": "supplier_invoice", "entite_id": cible,
                                             "libelle": "Facture fournisseur", "nom": nom,
                                             "mime": st.session_state["sf_mime"], "taille": len(contenu),
                                             "sha256": empreinte, "contenu": contenu,
                                             "ajoute_par": (auth.utilisateur() or {}).get("id"),
                                             "ajoute_le": db.maintenant()})
        except ValueError as e:
            st.error(str(e))
        else:
            for cle in ("sf_id_new", "sf_contenu", "sf_nom", "sf_mime", "sf_lecture"):
                st.session_state.pop(cle, None)
            ui.succes("Facture fournisseur enregistrée, avec son justificatif, sans mouvement de trésorerie.")


@st.dialog("Modifier la facture fournisseur", width="large")
def modifier_facture(facture_id: str) -> None:
    if not auth.est_admin():
        st.error("La modification d’une facture fournisseur est réservée à l’administrateur.")
        return
    s = R.charger("clients", "projects", "supplier_invoices", "supplier_allocations", "supplier_reversals")
    i = next((x for x in s["supplier_invoices"] if x["id"] == facture_id), None)
    if i is None:
        st.error("Facture introuvable.")
        return
    k = facture_id
    paye = R.supplier_paid(s, k)
    if paye:
        st.info(f"Déjà réglé : {R.money(paye, i['currency'])}. Le fournisseur, le chantier, la monnaie et la date sont "
                "figés ; le montant ne peut pas descendre sous ce total.")
    else:
        st.caption("Aucun règlement enregistré : tous les champs sont modifiables.")
    a, b = st.columns(2)
    with a:
        tiers = ui.choix("Fournisseur *", ui.options_fournisseurs(s, i["party_id"]), f"mf_t_{k}", i["party_id"],
                         vide="Choisir", disabled=bool(paye))
        ref = st.text_input("Référence de la facture *", value=i["reference"], key=f"mf_ref_{k}")
        if paye:
            date = i["date"]
            st.text_input("Date de facture", value=date, disabled=True, key=f"mf_d_{k}")
        else:
            date = ui.date_txt("Date de facture *", f"mf_d_{k}", i["date"])
        monnaie = ui.devise("Monnaie", f"mf_cur_{k}", i["currency"], disabled=bool(paye))
    with b:
        projet = ui.choix("Chantier *", ui.options_chantiers(s), f"mf_p_{k}", i["project"], vide="Choisir",
                          disabled=bool(paye))
        montant = ui.montant("Montant total *", f"mf_mt_{k}", i["amount"])
        due = ui.date_txt("Échéance *", f"mf_due_{k}", i["due"])
    if st.button("Enregistrer les modifications", type="primary"):
        try:
            if not tiers or not projet:
                raise ValueError("Renseignez le fournisseur et le chantier.")
            nouvelles = {"party_id": tiers, "project": projet, "currency": monnaie, "reference": ref.strip(),
                         "date": date, "due": due, "amount": R.cents(montant, "Montant", positif=True)}
            R.valider_modif_facture_fournisseur(s, k, nouvelles)
            V.guard_legacy(projet)
            with db.transaction(f"Modification facture fournisseur {nouvelles['reference']}") as t:
                t.get("supplier_invoices", k, verrou=True)
                s2 = {**s, "supplier_allocations": t.lire("select * from supplier_allocations"),
                      "supplier_reversals": t.lire("select * from supplier_reversals")}
                R.valider_modif_facture_fournisseur(s2, k, nouvelles)
                t.maj("supplier_invoices", k, nouvelles)
        except ValueError as e:
            st.error(str(e))
        else:
            ui.succes("Facture fournisseur modifiée. Les règlements existants sont conservés.")


@st.dialog("Versement fournisseur", width="large")
def versement(facture_id: str | None = None) -> None:
    s = R.charger("clients", "projects", "supplier_invoices", "supplier_payments", "supplier_allocations",
                  "supplier_reversals")
    i = next((x for x in s["supplier_invoices"] if x["id"] == facture_id), None)
    st.caption("Enregistrez uniquement un versement déjà effectué et absent du journal. Une seule sortie sera créée. "
               "Un excédent par rapport à la facture reste une avance non affectée.")
    if i:
        reste = i["amount"] - R.supplier_paid(s, i["id"])
        st.markdown(f"**{i['reference']}** · {R.client_name(s, i['party_id'])} · reste {R.money(reste, i['currency'])}")
        tiers, projet, monnaie = i["party_id"], i["project"], i["currency"]
    else:
        reste = 0
        a, b = st.columns(2)
        with a:
            tiers = ui.choix("Fournisseur *", ui.options_fournisseurs(s), "sv_t", "", vide="Choisir")
            monnaie = ui.devise("Monnaie", "sv_cur")
        with b:
            projet = ui.choix("Chantier *", ui.options_chantiers(s), "sv_p", "", vide="Choisir")
    a, b, c = st.columns(3)
    with a:
        montant = ui.montant("Montant versé *", f"sv_mt_{facture_id}", reste)
    with b:
        date = ui.date_txt("Date du versement *", f"sv_d_{facture_id}")
    with c:
        compte = ui.choix("Payé depuis *", R.CASH_ACCOUNTS, f"sv_c_{facture_id}", "bank")
    if st.button("Enregistrer le versement", type="primary"):
        try:
            mt = R.cents(montant, "Montant", positif=True)
            if not tiers or not projet:
                raise ValueError("Renseignez le fournisseur, le chantier, la date et le montant.")
            pid = db.nouvel_id()
            V.guard_legacy(projet)
            with db.transaction(("Règlement" if i else "Avance") + " fournisseur") as t:
                t.inserer("supplier_payments", {"id": pid, "party_id": tiers, "project": projet, "currency": monnaie,
                                                "amount": mt, "date": date, "account": compte})
                t.inserer("movements", {"id": db.nouvel_id(), "kind": "manual", "date": date, "account": compte,
                                        "label": ("Règlement fournisseur" if i else "Avance fournisseur") + " · "
                                                 + R.client_name(s, tiers),
                                        "direction": "out", "amount": mt, "currency": monnaie, "project": projet,
                                        "invoice_id": "", "invoice_amount": None, "expense_id": "",
                                        "supplier_payment_id": pid, "supplier_reversal_id": "", "cree_le": db.maintenant()})
                if i:
                    t.get("supplier_invoices", i["id"], verrou=True)
                    deja = sum(a["amount"] for a in t.lire(
                        "select a.amount from supplier_allocations a where a.invoice_id = :i and a.payment_id not in "
                        "(select payment_id from supplier_reversals)", i=i["id"]))
                    alloc = min(mt, i["amount"] - deja)
                    if alloc <= 0:
                        raise ValueError("Cette facture est déjà réglée. Enregistrez une avance si nécessaire.")
                    t.inserer("supplier_allocations", {"id": db.nouvel_id(), "payment_id": pid, "invoice_id": i["id"],
                                                       "amount": alloc, "date": date})
        except ValueError as e:
            st.error(str(e))
        else:
            ui.succes("Versement et journal enregistrés une seule fois.")


@st.dialog("Affecter une avance")
def affecter(pid: str) -> None:
    s = R.charger("clients", "supplier_invoices", "supplier_payments", "supplier_allocations", "supplier_reversals")
    p = next(x for x in s["supplier_payments"] if x["id"] == pid)
    dispo = R.supplier_advance(s, pid)
    choix = {i["id"]: f"{i['reference']} (reste {R.money(i['amount'] - R.supplier_paid(s, i['id']), i['currency'])})"
             for i in s["supplier_invoices"] if i["party_id"] == p["party_id"] and i["project"] == p["project"]
             and i["currency"] == p["currency"] and R.supplier_paid(s, i["id"]) < i["amount"]}
    if not choix:
        st.info("Aucune facture à payer pour ce tiers, ce chantier et cette monnaie.")
        return
    st.caption(f"Disponible : {R.money(dispo, p['currency'])}. Cette affectation ne crée aucune nouvelle sortie de caisse.")
    fid = ui.choix("Facture", choix, f"af_f_{pid}")
    montant = ui.montant("Montant à affecter", f"af_m_{pid}", 0)
    date = ui.date_txt("Date d’affectation", f"af_d_{pid}")
    if st.button("Affecter", type="primary"):
        try:
            mt = R.cents(montant, "Montant", positif=True)
            if date < p["date"]:
                raise ValueError("La date d’affectation ne peut précéder le paiement.")
            with db.transaction("Affectation d'une avance fournisseur") as t:
                t.get("supplier_payments", pid, verrou=True)
                i = t.get("supplier_invoices", fid, verrou=True)
                s2 = {**s, "supplier_allocations": t.lire("select * from supplier_allocations"),
                      "supplier_reversals": t.lire("select * from supplier_reversals")}
                if mt > R.supplier_advance(s2, pid) or mt > i["amount"] - R.supplier_paid(s2, fid):
                    raise ValueError("Le montant dépasse l’avance disponible ou le reste de la facture.")
                t.inserer("supplier_allocations", {"id": db.nouvel_id(), "payment_id": pid, "invoice_id": fid,
                                                   "amount": mt, "date": date})
        except ValueError as e:
            st.error(str(e))
        else:
            ui.succes("Avance affectée, sans nouveau paiement.")


@st.dialog("Corriger une saisie de paiement")
def contrepasser(pid: str) -> None:
    s = R.charger("clients", "supplier_payments", "supplier_allocations", "supplier_reversals")
    p = next(x for x in s["supplier_payments"] if x["id"] == pid)
    st.markdown(f"Versement enregistré : **{R.money(p['amount'], p['currency'])}** · {R.client_name(s, p['party_id'])}")
    st.warning("Pour corriger un paiement saisi par erreur uniquement. Cette écriture rétablit le solde du compte et les "
               "factures à payer ; elle ne récupère aucun argent auprès du fournisseur. L’original et ses affectations "
               "restent conservés.")
    date = ui.date_txt("Date de contre-passation", f"cp_d_{pid}")
    motif = st.text_area("Motif obligatoire", max_chars=2000)
    if st.button("Contre-passer", type="primary", disabled=not motif.strip()):
        try:
            if R.supplier_reversed(s, pid):
                raise ValueError("Paiement déjà contrepassé.")
            if date < p["date"]:
                raise ValueError("La date doit être au moins égale à celle du paiement.")
            if any(a["payment_id"] == pid and a["date"] > date for a in s["supplier_allocations"]):
                raise ValueError("La contre-passation ne peut précéder une affectation de cette avance.")
            rid = db.nouvel_id()
            with db.transaction("Contre-passation d'un paiement fournisseur") as t:
                t.get("supplier_payments", pid, verrou=True)
                if t.lire("select id from supplier_reversals where payment_id = :p", p=pid):
                    raise ValueError("Paiement déjà contrepassé.")
                t.inserer("supplier_reversals", {"id": rid, "payment_id": pid, "date": date, "reason": motif.strip(),
                                                 "created_at": db.maintenant().isoformat()})
                t.inserer("movements", {"id": db.nouvel_id(), "kind": "manual", "date": date, "account": p["account"],
                                        "label": f"Contre-passation fournisseur · {R.client_name(s, p['party_id'])} · "
                                                 f"{motif.strip()}",
                                        "direction": "in", "amount": p["amount"], "currency": p["currency"],
                                        "project": p["project"], "invoice_id": "", "invoice_amount": None,
                                        "expense_id": "", "supplier_payment_id": "", "supplier_reversal_id": rid,
                                        "cree_le": db.maintenant()})
        except ValueError as e:
            st.error(str(e))
        else:
            ui.succes("Contre-passation enregistrée. Le paiement original est conservé.")


def page() -> None:
    auth.exiger("comptes")
    ui.en_tete("Comptes tiers", "Soldes clients, factures fournisseurs, avances et règlements par chantier.")
    s = R.charger("clients", "projects", "invoices", "expenses", "supplier_invoices", "supplier_payments",
                  "supplier_allocations", "supplier_reversals")
    ecrit = auth.modifie("comptes")
    f = _filtres()
    a, b, c, d, e = st.columns([1.4, 1.4, 1, 1, 1])
    with a:
        f["party"] = ui.choix("Partenaire", {p["id"]: p["name"] for p in s["clients"]}, "ct_party", f["party"],
                              vide="Tous les tiers")
    with b:
        f["project"] = ui.choix("Chantier", ui.options_chantiers(s), "ct_proj", f["project"], vide="Tous les chantiers")
    with c:
        f["currency"] = ui.choix("Monnaie", R.CURRENCY_LABELS, "ct_cur", f["currency"], vide="Toutes")
    with d:
        f["from"] = ui.date_txt("Émises à partir du", "ct_from", f["from"] or None, vide_ok=True)
    with e:
        f["to"] = ui.date_txt("Émises jusqu’au", "ct_to", f["to"] or None, vide_ok=True)
    st.caption("Soldes actuels des factures sélectionnées, avec tous leurs règlements. La période filtre la date "
               "d’émission ; elle ne reconstitue pas un solde historique.")
    try:
        rep = R.client_account_report(s, f, R.today())
    except ValueError as err:
        st.error(str(err))
        return

    tab1, tab2, tab3 = st.tabs(["Clients", "Fournisseurs et avances", "Anciennes dépenses rattachées"])
    with tab1:
        cs = st.columns(3)
        for col, (lbl, key, acc) in zip(cs, [("Facturé aux clients", "amount", False), ("Règlements reçus", "paid", False),
                                             ("Reste à encaisser", "remaining", True)]):
            with col:
                ui.carte(lbl, ui.montants_html({c_: rep["totals"][c_][key] for c_ in R.CURRENCIES}), accent=acc)
        st.markdown(f"**Créances échues au {R.today()} :** "
                    + ui.montants_texte({c_: rep["totals"][c_]["overdue"] for c_ in R.CURRENCIES})
                    + f"  \nSans échéance renseignée : "
                    + ui.montants_texte({c_: rep["totals"][c_]["undated"] for c_ in R.CURRENCIES}))
        lignes = [{"_id": r["id"], "f": r["number"], "t": R.client_name(s, r["party"]), "ch": R.project_name(s, r["project"]),
                   "em": r["date"], "ech": r["due"] or "Non renseignée", "fac": R.money(r["amount"], r["currency"]),
                   "rec": R.money(r["paid"], r["currency"]), "reste": R.money(r["remaining"], r["currency"]),
                   "ret": r["bucket"] if r["remaining"] else "Réglée"} for r in rep["rows"]]
        export = [["Entreprise", s["company"].get("name", "")], ["Relevé", "Soldes clients actuels ; règlements cumulés"],
                  ["Édité le", R.today()], ["Émission du", f["from"], "au", f["to"]],
                  ["Facture", "Tiers", "Chantier", "Émission", "Échéance", "Monnaie", "Facturé", "Reçu", "Reste", "Retard"]]
        export += [[r["number"], R.client_name(s, r["party"]), R.project_name(s, r["project"]), r["date"], r["due"],
                    r["currency"], R.plain(r["amount"]), R.plain(r["paid"]), R.plain(r["remaining"]),
                    r["bucket"] if r["remaining"] else "Réglée"] for r in rep["rows"]]
        export += [[], ["Totaux par monnaie", "Facturé", "Reçu", "Reste", "Échu"]] + [
            [c_] + [R.plain(rep["totals"][c_][k]) for k in ("amount", "paid", "remaining", "overdue")] for c_ in R.CURRENCIES]
        ui.telecharger("Exporter le relevé CSV", R.to_csv(export), f"releve-clients-{R.today()}.csv", ui.MIME_CSV,
                       key="ct_csv")
        if lignes:
            i = ui.tableau(lignes, {"f": "Facture", "t": "Tiers", "ch": "Chantier", "em": "Émission", "ech": "Échéance",
                                    "fac": "Facturé", "rec": "Reçu", "reste": "Reste", "ret": "Retard"},
                           key="tab_ct_cli", selection=ecrit and auth.modifie("commercial"))
            if i is not None:
                r = rep["rows"][i]
                if r["remaining"] > 0 and st.button(f"Enregistrer un règlement sur {r['number']}", type="primary"):
                    devis_factures.reglement(r["id"])
        else:
            st.caption("Aucune facture client pour ces critères.")

    with tab2:
        def match(x):
            return ((not f["party"] or x["party_id"] == f["party"]) and (not f["project"] or x["project"] == f["project"])
                    and (not f["currency"] or x["currency"] == f["currency"]) and (not f["from"] or x["date"] >= f["from"])
                    and (not f["to"] or x["date"] <= f["to"]))
        factures = [x for x in s["supplier_invoices"] if match(x)]
        paiements = [x for x in s["supplier_payments"] if match(x)]
        if ecrit:
            b1, b2 = ui.rangee(2)
            if b1.button("Nouvelle facture fournisseur", icon=":material/add:", type="primary"):
                if not s["projects"] or not ui.options_fournisseurs(s):
                    st.warning("Ajoutez d’abord un chantier et un tiers Fournisseur ou Sous-traitant.")
                else:
                    facture_fournisseur()
            if b2.button("Enregistrer une avance versée", icon=":material/payments:"):
                if not s["projects"] or not ui.options_fournisseurs(s):
                    st.warning("Ajoutez d’abord un chantier et un tiers Fournisseur ou Sous-traitant.")
                else:
                    versement()
        st.markdown("**Reste à payer :** " + ui.montants_texte(R.totals_by_currency(
            factures, lambda x: x["amount"] - R.supplier_paid(s, x["id"]))) + "  \n**Avances non affectées :** "
            + ui.montants_texte(R.totals_by_currency(paiements, lambda p: R.supplier_advance(s, p["id"]))))
        st.caption("Enregistrement des paiements déjà effectués. Ne ressaisissez pas un paiement déjà présent dans "
                   "Dépenses ou le journal. Les avances restent séparées des dettes jusqu’à leur affectation.")
        st.markdown("##### Factures fournisseurs à payer")
        if factures:
            lf = []
            for x in sorted(factures, key=lambda x: x["due"]):
                paye = R.supplier_paid(s, x["id"])
                reste = x["amount"] - paye
                lf.append({"_id": x["id"], "f": x["reference"], "t": R.client_name(s, x["party_id"]),
                           "ch": R.project_name(s, x["project"]), "ech": x["due"] + (" · échue" if reste and x["due"] < R.today() else ""),
                           "fac": R.money(x["amount"], x["currency"]), "reg": R.money(paye, x["currency"]),
                           "reste": R.money(reste, x["currency"]) if reste else "Réglée"})
            i = ui.tableau(lf, {"f": "Facture", "t": "Fournisseur", "ch": "Chantier", "ech": "Échéance",
                                "fac": "Facturé", "reg": "Réglé", "reste": "Reste"}, key="tab_ct_four", selection=ecrit)
            if i is not None:
                x = next(y for y in factures if y["id"] == lf[i]["_id"])
                b_mod, b_pay = ui.rangee(2)
                if auth.est_admin() and b_mod.button(f"Modifier {x['reference']}", icon=":material/edit:"):
                    modifier_facture(x["id"])
                if x["amount"] - R.supplier_paid(s, x["id"]) > 0 and b_pay.button(
                        f"Règlement effectué sur {x['reference']}", type="primary"):
                    versement(x["id"])
                ui.pieces_jointes("supplier_invoice", x["id"], peut_ajouter=ecrit,
                                  titre=f"Pièces jointes à {x['reference']}")
        else:
            st.caption("Aucune facture fournisseur saisie pour ces critères.")
        st.markdown("##### Avances et paiements enregistrés")
        if paiements:
            lp = [{"_id": p["id"], "d": p["date"], "t": R.client_name(s, p["party_id"]), "ch": R.project_name(s, p["project"]),
                   "v": R.money(p["amount"], p["currency"]),
                   "na": "Contrepassé" if R.supplier_reversed(s, p["id"]) else R.money(R.supplier_advance(s, p["id"]), p["currency"])}
                  for p in sorted(paiements, key=lambda p: p["date"], reverse=True)]
            i = ui.tableau(lp, {"d": "Date", "t": "Fournisseur", "ch": "Chantier", "v": "Versé", "na": "Non affecté"},
                           key="tab_ct_pay", selection=ecrit)
            if i is not None:
                p = next(y for y in paiements if y["id"] == lp[i]["_id"])
                if R.supplier_reversed(s, p["id"]):
                    st.caption("Ce paiement a été contrepassé.")
                else:
                    c1, c2 = ui.rangee(2)
                    if R.supplier_advance(s, p["id"]) and c1.button("Affecter à une facture", type="primary"):
                        affecter(p["id"])
                    if c2.button("Corriger par contre-passation"):
                        contrepasser(p["id"])
        else:
            st.caption("Aucun paiement fournisseur saisi ici.")
        rev = [r for r in s["supplier_reversals"] if any(p["id"] == r["payment_id"] for p in paiements)]
        if rev:
            st.markdown("##### Historique des contre-passations")
            ui.tableau([{"d": r["date"], "p": r["payment_id"][:8], "m": r["reason"]} for r in rev],
                       {"d": "Date", "p": "Paiement d’origine", "m": "Motif"}, key="tab_ct_rev")

    with tab3:
        dep = [x for x in s["expenses"] if x["supplier_id"] and (not f["party"] or x["supplier_id"] == f["party"])
               and (not f["project"] or x["project"] == f["project"]) and (not f["currency"] or x["currency"] == f["currency"])
               and (not f["from"] or x["date"] >= f["from"]) and (not f["to"] or x["date"] <= f["to"])]
        st.markdown("Dépenses payées et rattachées : " + ui.montants_texte(R.totals_by_currency(dep, lambda x: x["amount"])))
        if dep:
            ui.tableau([{"d": x["date"], "t": R.client_name(s, x["supplier_id"]), "ch": R.project_name(s, x["project"]),
                         "l": x["label"], "m": R.money(x["amount"], x["currency"])} for x in dep],
                       {"d": "Date", "t": "Partenaire", "ch": "Chantier", "l": "Dépense", "m": "Payé"}, key="tab_ct_dep")
        st.caption("Ces dépenses sont déjà payées. Ne les ressaisissez pas comme un nouveau règlement fournisseur.")
