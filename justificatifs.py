"""Justificatifs des dépenses : dépôt des pièces, contrôle et validation par la finance ou la direction.

Une pièce ne compte comme justification qu'une fois validée, par une autre personne que celle qui l'a déposée.
"""
from __future__ import annotations

import hashlib
import io
import re

import openpyxl
import streamlit as st

import auth
import db
import pdf
import regles as R
import ui


def mime_de(contenu: bytes) -> str | None:
    if contenu[:4] == b"%PDF":
        return "application/pdf"
    if contenu[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if contenu[:4] == b"\x89PNG":
        return "image/png"
    return None


def nom_sur(nom: str, mime: str) -> str:
    base = re.sub(r"\.[^.]*$", "", re.sub(r'[\\/:<>|?*"]', "_", nom))[:220]
    return base + {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png"}[mime]


def depenses_a_justifier(s: dict) -> list[dict]:
    """Dépenses du journal, versements fournisseurs et dépenses historiques des lots de reprise."""
    rows = [{"id": e["id"], "ref": e["id"][:8], "label": e["label"], "project": e["project"],
             "projectName": R.project_name(s, e["project"]), "responsible": e.get("responsible") or "Non renseigné",
             "currency": e["currency"], "amount": e["amount"], "date": e["date"], "origine": "Dépense"}
            for e in s["expenses"]]
    rows += [{"id": "supplierPayment:" + p["id"], "ref": p["id"][:8],
              "label": "Versement fournisseur · " + R.client_name(s, p["party_id"]), "project": p["project"],
              "projectName": R.project_name(s, p["project"]), "responsible": "Non renseigné",
              "currency": p["currency"], "amount": p["amount"], "date": p["date"], "origine": "Versement fournisseur"}
             for p in s["supplier_payments"] if not R.supplier_reversed(s, p["id"])]
    for b in db.tout("history_batches"):
        for r in b["rows"]:
            if r["sheet"] == "Depenses":
                v = r["values"]
                rows.append({"id": f"{b['id']}:{v['reference']}", "ref": v["reference"], "label": v["description"],
                             "project": b["id"], "projectName": b["project"]["nom"] + " (historique)",
                             "responsible": v.get("responsable_ref") or "Non renseigné", "currency": v["monnaie"],
                             "amount": R.js_round(float(v["montant"]) * 100), "date": v["date"],
                             "origine": "Historique (lot de reprise)"})
    return rows


def etat(pcs: list[dict], montant: int) -> tuple[int, str]:
    valide = min(montant, sum(p["amount"] for p in pcs if p["status"] == "Validée"))
    if valide >= montant and montant > 0:
        return valide, "Justifiée"
    if any(p["status"] == "Préparée" for p in pcs):
        return valide, "Pièces à contrôler"
    return valide, "Partiellement justifiée" if valide else "Non justifiée"


@st.dialog("Refuser la pièce")
def rejeter(pid: str) -> None:
    motif = st.text_area("Motif du refus *", max_chars=1000)
    if st.button("Refuser", type="primary", disabled=not motif.strip()):
        with db.transaction("Refus d'un justificatif") as t:
            t.maj("pieces", pid, {"status": "Rejetée", "reason": motif.strip(), "validated_by": auth.utilisateur()["id"],
                                  "validated_at": db.maintenant()})
        ui.succes("Pièce refusée : la personne qui l'a déposée verra le motif.")


def bloc_depense(e: dict, pcs: list[dict], users: dict) -> None:
    moi = auth.utilisateur()["id"]
    peut_deposer = auth.modifie("justificatifs")
    peut_valider = auth.modifie("validation_pieces")
    valide, statut = etat(pcs, e["amount"])
    st.markdown(f"**{e['label']}** · {e['projectName']} · {e['date']}  \nMontant : **{R.money(e['amount'], e['currency'])}**"
                f" · justifié (validé) : **{R.money(valide, e['currency'])}** · reste : "
                f"**{R.money(e['amount'] - valide, e['currency'])}** · {statut}")
    for p in sorted(pcs, key=lambda x: x["uploaded_at"]):
        with st.container(border=True):
            a, b = st.columns([3, 2])
            a.markdown(f"**{p['type']}** — {p['name']}  \nBénéficiaire : {p['beneficiary']} · pièce du {p['document_date']}"
                       f"  \nMontant couvert : {R.money(p['amount'], p['currency']) if p['currency'] else '—'}"
                       f"  \nDéposée le {p['uploaded_at']:%d/%m/%Y %H:%M} par {users.get(p['uploaded_by'], '?')}")
            tag = {"Validée": "ok", "Rejetée": "alerte"}.get(p["status"], "")
            b.html(f'<span class="bg-tag {tag}">{p["status"]}</span>' + (
                f'<br><small>par {ui._esc(users.get(p["validated_by"], "?"))} le {p["validated_at"]:%d/%m/%Y}</small>'
                if p["validated_at"] else "") + (f'<br><small>Motif : {ui._esc(p["reason"])}</small>' if p["reason"] else ""))
            c = b.columns(3)
            contenu = db.requete("select content from pieces where id = :i", i=p["id"])[0]["content"]
            with c[0]:
                ui.telecharger("Ouvrir", bytes(contenu), p["name"], p["mime"], key=f"dl_{p['id']}")
            if p["status"] == "Préparée" and peut_valider:
                if p["uploaded_by"] == moi:
                    b.caption("Vous avez déposé cette pièce : une autre personne habilitée doit la valider.")
                else:
                    if c[1].button("Valider", key=f"val_{p['id']}", icon=":material/check:"):
                        with db.transaction("Validation d'un justificatif") as t:
                            t.maj("pieces", p["id"], {"status": "Validée", "reason": "", "validated_by": moi,
                                                      "validated_at": db.maintenant()})
                        ui.succes("Pièce validée.")
                    if c[2].button("Refuser", key=f"rej_{p['id']}", icon=":material/close:"):
                        rejeter(p["id"])
            if p["status"] != "Validée" and peut_deposer and (p["uploaded_by"] == moi or peut_valider):
                if b.button("Retirer la pièce", key=f"del_{p['id']}"):
                    with db.transaction("Retrait d'un justificatif") as t:
                        t.supprimer("pieces", p["id"])
                    ui.succes("Pièce retirée.")
    if not peut_deposer:
        return
    with st.form(f"depot_{e['id']}", clear_on_submit=True):
        st.markdown("**Joindre une pièce** — PDF, JPEG ou PNG, 5 Mo au plus")
        a, b = st.columns(2)
        type_ = a.selectbox("Type de pièce", R.PIECE_TYPES)
        date = b.date_input("Date de la pièce", format="DD/MM/YYYY")
        benef = a.text_input("Bénéficiaire / fournisseur *")
        montant = b.number_input(f"Montant couvert ({e['currency']})", min_value=0.01, max_value=e["amount"] / 100,
                                 value=e["amount"] / 100, step=1.0, format="%.2f")
        fichier = st.file_uploader("Fichier *", type=["pdf", "jpg", "jpeg", "png"])
        ok = st.form_submit_button("Conserver la pièce", type="primary")
    if ok:
        try:
            if fichier is None:
                raise ValueError("Choisissez un fichier.")
            contenu = fichier.getvalue()
            if not contenu or len(contenu) > R.PIECE_MAX:
                raise ValueError("Choisissez un fichier non vide de 5 Mo maximum.")
            mime = mime_de(contenu)
            if not mime:
                raise ValueError("Le contenu doit être un PDF, une photo JPEG ou une image PNG.")
            if not benef.strip():
                raise ValueError("Indiquez le bénéficiaire.")
            mt = R.cents(montant, "Montant couvert", positif=True)
            if mt > e["amount"]:
                raise ValueError("Le montant couvert ne peut dépasser la dépense.")
            h = hashlib.sha256(contenu).hexdigest()
            if db.requete("select id from pieces where hash = :h", h=h):
                raise ValueError("Ce fichier est déjà enregistré. Il ne peut pas être compté deux fois.")
            with db.transaction(f"Dépôt d'un justificatif pour {e['label']}") as t:
                t.inserer("pieces", {"id": db.nouvel_id(), "expense_id": e["id"],
                                     "batch_id": e["project"] if e["origine"].startswith("Historique") else "",
                                     "name": nom_sur(fichier.name, mime), "mime": mime, "content": contenu,
                                     "size": len(contenu), "hash": h, "type": type_, "beneficiary": benef.strip(),
                                     "document_date": date.isoformat(), "amount": mt, "currency": e["currency"],
                                     "status": "Préparée", "reason": "", "uploaded_at": db.maintenant(),
                                     "uploaded_by": auth.utilisateur()["id"]})
        except ValueError as err:
            st.error(str(err))
        else:
            ui.succes("Pièce enregistrée. Elle compte comme justification une fois validée par la finance ou la direction.")


def rapport_excel(rows: list[dict], pcs: dict) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Justificatifs"
    ws.append([f"{R.company().get('name', 'MY DESTINY')} — Suivi des justificatifs"])
    ws.append(["Édité le", R.today()])
    ws.append(["Référence", "Chantier", "Date", "Responsable", "Monnaie", "Montant", "Justifié (validé)", "Reste",
               "Statut", "Pièces", "Origine"])
    tot = {c: [0, 0] for c in R.CURRENCIES}
    for e in rows:
        v, st_ = etat(pcs.get(e["id"], []), e["amount"])
        ws.append([e["ref"], e["projectName"], e["date"], e["responsible"], e["currency"], e["amount"] / 100, v / 100,
                   (e["amount"] - v) / 100, st_, len(pcs.get(e["id"], [])), e["origine"]])
        tot[e["currency"]][0] += e["amount"]
        tot[e["currency"]][1] += v
    for col in "ABCDEFGHIJK":
        ws.column_dimensions[col].width = 22
    t = wb.create_sheet("Totaux")
    t.append(["Monnaie", "Dépenses", "Justifié", "Reste", "Taux de justification"])
    for c, (m, v) in tot.items():
        t.append([c, m / 100, v / 100, (m - v) / 100, (v / m) if m else "Sans dépense"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def page() -> None:
    auth.exiger("justificatifs")
    ui.en_tete("Justificatifs", "Joignez les pièces de chaque dépense ; la finance ou la direction les valide.")
    s = R.charger("projects", "clients", "expenses", "supplier_payments", "supplier_reversals")
    toutes = depenses_a_justifier(s)
    pcs: dict[str, list] = {}
    for p in db.tout("pieces", sans=("content",)):
        if p["expense_id"]:
            pcs.setdefault(p["expense_id"], []).append(p)
    users = {u["id"]: u["nom"] for u in db.requete("select id, nom from users")}
    projets = {}
    for e in toutes:
        projets.setdefault(e["project"], e["projectName"])
    a, b = st.columns([2, 1])
    with a:
        f = ui.choix("Chantier", projets, "j_f_proj", "", vide="Tous les chantiers")
    vue = b.selectbox("Afficher", ["Toutes les dépenses", "À justifier", "Pièces à contrôler", "Justifiées"])
    rows = [e for e in toutes if not f or e["project"] == f]
    infos = {e["id"]: etat(pcs.get(e["id"], []), e["amount"]) for e in rows}
    reste = R.totals_by_currency(rows, lambda e: e["amount"] - infos[e["id"]][0])
    a_controler = sum(1 for e in rows for p in pcs.get(e["id"], []) if p["status"] == "Préparée")
    c1, c2, c3 = st.columns(3)
    with c1:
        ui.carte("Reste à justifier", ui.montants_html(reste), "Un paiement ne vaut pas justificatif.", accent=True)
    with c2:
        ui.carte("Pièces à contrôler", str(a_controler), "En attente de validation par la finance ou la direction")
    with c3:
        tot = R.totals_by_currency(rows, lambda e: e["amount"])
        val = R.totals_by_currency(rows, lambda e: infos[e["id"]][0])
        ui.carte("Justification validée", "<br>".join(
            f"{c} : {round(100 * val[c] / tot[c])} %" for c in R.CURRENCIES if tot[c]) or "—", "Par monnaie")
    filtre = {"À justifier": lambda e: infos[e["id"]][1] != "Justifiée",
              "Pièces à contrôler": lambda e: infos[e["id"]][1] == "Pièces à contrôler",
              "Justifiées": lambda e: infos[e["id"]][1] == "Justifiée"}.get(vue, lambda e: True)
    rows = sorted([e for e in rows if filtre(e)], key=lambda e: e["date"], reverse=True)
    x1, x2 = ui.rangee(2)
    with x1:
        ui.telecharger("Exporter Excel", rapport_excel(rows, pcs), f"justificatifs-{R.today()}.xlsx", ui.MIME_XLSX,
                       key="j_xlsx")
    with x2:
        ui.telecharger("Imprimer / PDF", pdf.document(
            "Suivi des justificatifs", R.company_snapshot(),
            [("p", f"Édité le {R.today()} · {len(rows)} dépense(s)" + (f" · {projets.get(f)}" if f else "")),
             ("table", ["Dépense / chantier", "Date", "Montant", "Justifié", "Reste", "Statut"],
              [[f"{e['label']} — {e['projectName']}", e["date"], R.money(e["amount"], e["currency"]),
                R.money(infos[e["id"]][0], e["currency"]), R.money(e["amount"] - infos[e["id"]][0], e["currency"]),
                infos[e["id"]][1]] for e in rows], {2, 3, 4})],
            paysage=True, auteur=auth.utilisateur()["nom"]), f"justificatifs-{R.today()}.pdf", ui.MIME_PDF, key="j_pdf")
    if not rows:
        st.info("Aucune dépense pour ces critères.")
        return
    tab = [{"_id": e["id"], "lib": e["label"], "ch": e["projectName"], "date": e["date"],
            "mt": R.money(e["amount"], e["currency"]), "just": R.money(infos[e["id"]][0], e["currency"]),
            "reste": R.money(e["amount"] - infos[e["id"]][0], e["currency"]), "st": infos[e["id"]][1],
            "np": len(pcs.get(e["id"], [])), "orig": e["origine"]} for e in rows]
    i = ui.tableau(tab, {"lib": "Dépense", "ch": "Chantier", "date": "Date", "mt": "Montant", "just": "Justifié",
                         "reste": "Reste", "st": "Statut", "np": st.column_config.NumberColumn("Pièces", format="%d"),
                         "orig": "Origine"}, key="tab_just", selection=True)
    if i is not None:
        st.session_state["just_sel"] = rows[i]["id"]
    eid = st.session_state.get("just_sel")
    e = next((x for x in toutes if x["id"] == eid), None)
    if not e:
        st.caption("Sélectionnez une dépense pour voir ses pièces ou en joindre une.")
        return
    st.divider()
    bloc_depense(e, pcs.get(e["id"], []), users)
