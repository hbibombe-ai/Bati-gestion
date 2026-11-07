"""Devis et factures clients : prestations, impression PDF, conversion devis → facture, règlements,
téléchargement des factures (un PDF, ou un ZIP pour plusieurs)."""
from __future__ import annotations

import io
import re
import zipfile

import pandas as pd
import streamlit as st

import auth
import composants as C
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
    # identifiant du document : celui du dossier existant, ou un identifiant réservé pour une création
    cible = did or st.session_state.setdefault(f"df_id_{k}", db.nouvel_id())
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
    ui.pieces_jointes(kind, cible, peut_ajouter=True, titre="Pièces jointes (facture, bon de commande, PV…)")
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
                    t.inserer(kind, {"id": cible, **rec})
        except ValueError as e:
            st.error(str(e))
        else:
            st.session_state.pop(f"df_id_{k}", None)  # la prochaine création recevra un nouvel identifiant
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


ETAPES_PAIEMENT = ["À régler", "Partiellement réglée", "Réglée"]


def page(kind: str) -> None:
    auth.exiger("commercial")
    titre = NOMS[kind][0]
    s = R.charger("clients", "projects", "quotes", "invoices")
    cle = f"doc_{kind}"
    sel = C.fiche_ouverte(cle)
    d = next((x for x in s[kind] if x["id"] == sel), None) if sel else None
    if d:
        _fiche(kind, s, d, cle)
        return
    ui.en_tete(titre, "Préparez et imprimez vos propositions." if kind == "quotes"
               else "Suivez les montants facturés et les règlements.")
    if kind != "invoices":
        _gestion(kind, s)
        return
    onglet_factures, onglet_telecharger = st.tabs(["Factures", "Télécharger"])
    with onglet_factures:
        _gestion(kind, s)
    with onglet_telecharger:
        _telecharger(s)


def _carte(kind: str):
    teintes = {"Brouillon": ("#edf0f7", "#5a6684"), "Envoyé": ("#e9eeff", "#1a27b5"), "Accepté": ("#e3f7ef", "#0b7a56"),
               "Refusé": ("#fde7ee", "#b0234d"), "Réglée": ("#e3f7ef", "#0b7a56"), "À régler": ("#fff1dc", "#b35c00"),
               "Partiellement réglée": ("#e9eeff", "#1a27b5"), "En retard": ("#fdeeec", "#a62d25")}
    bord = {"Accepté": "#12b886", "Réglée": "#12b886", "Refusé": "#f0507a", "En retard": "#f0507a", "Envoyé": "#3d5afe",
            "À régler": "#ff9f1c", "Partiellement réglée": "#3d5afe"}

    def carte(r: dict) -> dict:
        etat = r["_etat"]
        tags = [(etat, *teintes.get(etat, ("#eef1fd", "#1a27b5")))]
        if r.get("_retard"):
            tags.append(("En retard", *teintes["En retard"]))
        if r.get("_facture"):
            tags.append(("Facturé", "#e3f7ef", "#0b7a56"))
        lignes = [r["chantier"] if r["chantier"] != "—" else "", f"Date : {r['date']}",
                  f"Reste : {r['reste']}" if kind == "invoices" and r["reste"] != "Réglée" else ""]
        return {"titre": f"{r['num']} · {r['total']}", "sous_titre": r["client"], "initiales": C.initiales(r["client"]),
                "couleur": bord.get("En retard" if r.get("_retard") else etat, "#c8d0e4"), "lignes": lignes,
                "etiquettes": tags}
    return carte


def _gestion(kind: str, s: dict) -> None:
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
    aujourd_hui = R.today()
    for d in docs:
        row = {"_id": d["id"], "num": d["number"], "date": d["date"], "client": R.client_name(s, d["client"]),
               "chantier": R.project_name(s, d["project"]) if d["project"] else "—",
               "total": R.money(R.total(d), d["currency"])}
        if kind == "invoices":
            reste = R.total(d) - d["paid"]
            row.update(recu=R.money(d["paid"], d["currency"]), reste="Réglée" if reste == 0 else R.money(reste, d["currency"]),
                       echeance=d["due"] or "—", _etat=_etat_paiement(d),
                       _retard=bool(d["due"]) and d["due"] < aujourd_hui and reste > 0)
        else:
            facture = any(i["quote_id"] == d["id"] for i in s["invoices"])
            row.update(etat=d["status"] + (" · facturé" if facture else ""), _etat=d["status"], _facture=facture)
        rows.append(row)
    cols = {"num": "Document", "date": "Date", "client": "Client", "chantier": "Chantier", "total": "Total"}
    cols.update({"recu": "Reçu", "reste": "Reste à payer", "echeance": "Échéance"} if kind == "invoices"
                else {"etat": "État"})
    if kind == "invoices":
        filtres = [(e, "Paiement", (lambda e: lambda r: r["_etat"] == e)(e)) for e in ETAPES_PAIEMENT]
        filtres.append(("En retard", "Alerte", lambda r: r["_retard"]))
        groupes = {"Paiement": ("_etat", ETAPES_PAIEMENT), "Client": ("client", None), "Chantier": ("chantier", None)}
    else:
        filtres = [(e, "État", (lambda e: lambda r: r["_etat"] == e)(e)) for e in R.QUOTE_STATUSES]
        filtres.append(("Non facturés", "Facturation", lambda r: not r["_facture"]))
        groupes = {"État": ("_etat", R.QUOTE_STATUSES), "Client": ("client", None), "Chantier": ("chantier", None)}
    C.vue_liste(f"doc_{kind}", rows, cols, recherche=("num", "client", "chantier", "date"), filtres=filtres,
                regroupements=groupes, regroupement_defaut="État" if kind == "quotes" else None,
                carte=_carte(kind), vue_defaut="Kanban" if kind == "quotes" else "Liste",
                nom=NOMS[kind][1], nom_pluriel="devis" if kind == "quotes" else "factures")


def _etat_paiement(d: dict) -> str:
    reste = R.total(d) - d["paid"]
    return "Réglée" if reste <= 0 else "Partiellement réglée" if d["paid"] > 0 else "À régler"


def _fiche(kind: str, s: dict, d: dict, cle: str) -> None:
    ecrit = auth.modifie("commercial")
    C.fil_ariane(NOMS[kind][0], f"{NOMS[kind][2].capitalize()} {d['number']}", cle)
    if kind == "quotes":
        nouvel = C.barre_etapes(R.QUOTE_STATUSES, d["status"], cle=f"q_{d['id']}", modifiable=ecrit)
        if nouvel:
            with db.transaction(f"Devis {d['number']} : état « {nouvel} »") as t:
                t.maj("quotes", d["id"], {"status": nouvel})
            ui.succes(f"Devis {d['number']} : {nouvel}.")
    else:
        C.barre_etapes(ETAPES_PAIEMENT, _etat_paiement(d), cle=f"f_{d['id']}")
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
    gauche, droite = st.columns([1.75, 1], gap="medium")
    with gauche:
        with st.container(key="bg_feuille"):
            st.markdown(f"**Client :** {R.client_name(s, d['client'])}  \n**Chantier :** "
                        f"{R.project_name(s, d['project']) if d['project'] else '—'}  \n**Date :** {d['date']}"
                        + (f"  \n**Échéance :** {d['due'] or '—'}  \n**Reçu :** {R.money(d['paid'], d['currency'])}"
                           if kind == "invoices" else ""))
            st.dataframe(pd.DataFrame([{"Prestation": l["description"], "Quantité": l["qty"],
                                        "Prix unitaire": R.money(l["price"], d["currency"]),
                                        "Montant": R.money(R.js_round(float(l["qty"]) * l["price"]), d["currency"])}
                                       for l in d["lines"]]), hide_index=True, width="stretch")
            st.markdown(f"**Total : {R.money(R.total(d), d['currency'])}**")
    with droite:
        C.fil_activite(kind, d["id"])


def _nom_fichier(texte: str) -> str:
    return re.sub(r"[^\w.-]+", "_", texte).strip("_") or "facture"


def _fichier(factures: list[dict], s: dict) -> tuple[str, bytes, str]:
    """Un PDF pour une facture ; un ZIP de PDF pour plusieurs. Les noms en double reçoivent un suffixe."""
    if len(factures) == 1:
        d = factures[0]
        return f"{_nom_fichier(d['number'])}.pdf", document_pdf("invoices", d, s), ui.MIME_PDF
    buf = io.BytesIO()
    vus: set[str] = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for d in factures:
            base = _nom_fichier(d["number"])
            nom, n = f"{base}.pdf", 2
            while nom in vus:
                nom = f"{base}_{n}.pdf"
                n += 1
            vus.add(nom)
            z.writestr(nom, document_pdf("invoices", d, s))
    return f"factures_{R.today()}.zip", buf.getvalue(), "application/zip"


def _telecharger(s: dict) -> None:
    st.caption("Choisissez une facture (PDF) ou plusieurs (un fichier ZIP de PDF).")
    factures = sorted(s["invoices"], key=lambda d: (d["date"], d["number"]), reverse=True)
    if not factures:
        st.info("Aucune facture à télécharger pour le moment.")
        return
    libelles = {d["id"]: f"{d['number']} · {R.client_name(s, d['client'])} · {d['date']} · "
                         f"{R.money(R.total(d), d['currency'])}" for d in factures}
    if st.checkbox("Toutes les factures", key="dl_tout"):
        ids = list(libelles)
        st.caption(f"{len(ids)} facture(s) seront téléchargées.")
    else:
        ids = st.multiselect("Factures à télécharger", list(libelles), format_func=libelles.get, key="dl_choix")
    if not ids:
        st.caption("Sélectionnez au moins une facture.")
        return
    if len(ids) > 200:
        st.warning("Maximum 200 factures par téléchargement : affinez la sélection.")
        return
    cle = tuple(sorted(ids))
    if st.button("Préparer le PDF" if len(ids) == 1 else "Préparer le fichier ZIP", type="primary",
                 icon=":material/download:", key="dl_prep"):
        choisies = [d for d in factures if d["id"] in ids]
        st.session_state["dl_pret"] = (cle, _fichier(choisies, s))
    pret = st.session_state.get("dl_pret")
    if pret and pret[0] == cle:  # le fichier préparé ne s'affiche que pour la sélection courante
        nom, data, mime = pret[1]
        ui.telecharger("Télécharger", data, nom, mime, key=f"dl_fichier_{hash(cle)}", principal=True)
    else:
        st.caption("Cliquez sur « Préparer » pour générer le fichier de la sélection.")
