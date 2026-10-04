"""Chantiers : budget, avancement, décaissements par monnaie."""
from __future__ import annotations

import streamlit as st

import auth
import db
import regles as R
import ui


def decaissements(s: dict, pid: str) -> dict[str, int]:
    """Dépenses + versements fournisseurs non contrepassés (avances incluses), par monnaie."""
    sup = [p for p in s.get("supplier_payments", []) if not R.supplier_reversed(s, p["id"])]
    return R.totals_by_currency([e for e in s["expenses"] + sup if e["project"] == pid], lambda e: e["amount"])


def lignes(s: dict, projets: list[dict]) -> list[dict]:
    out = []
    for p in projets:
        t = decaissements(s, p["id"])
        spent = t[p["currency"]]
        autres = [R.money(v, c) for c, v in t.items() if v and c != p["currency"]]
        ecart = p["budget"] - spent
        out.append({"_id": p["id"], "nom": p["name"], "client": R.client_name(s, p["client"]), "statut": p["status"],
                    "echeance": p["deadline"] or "", "avancement": float(p["progress"]),
                    "budget": R.money(p["budget"], p["currency"]),
                    "depense": R.money(spent, p["currency"]) + (" + " + " + ".join(autres) if autres else ""),
                    "reste": ("Dépassement : " if ecart < 0 else "Disponible : ") + R.money(abs(ecart), p["currency"])})
    return out


COLONNES = {
    "nom": "Chantier", "client": "Client", "statut": "État", "echeance": "Échéance",
    "avancement": st.column_config.ProgressColumn("Avancement", min_value=0, max_value=100, format="%.0f %%"),
    "budget": "Budget", "depense": "Décaissements (avances incluses)", "reste": "Budget restant",
}


@st.dialog("Chantier", width="large")
def formulaire(pid: str | None = None) -> None:
    s = R.charger("projects", "clients", "expenses", "supplier_payments", "supplier_reversals")
    p = next((x for x in s["projects"] if x["id"] == pid), None) or {}
    a, b = st.columns(2)
    nom = a.text_input("Nom du chantier *", value=p.get("name", ""), max_chars=500)
    cli = ui.choix("Client", ui.options_clients(s, p.get("client", "")), f"ch_client_{pid}", p.get("client", ""),
                   vide="Choisir un client (facultatif)")
    lieu = a.text_input("Lieu", value=p.get("location", ""), max_chars=500)
    with b:
        echeance = ui.date_txt("Date de livraison prévue", f"ch_deadline_{pid}", p.get("deadline"), vide_ok=True)
    monnaie = ui.devise("Monnaie", f"ch_cur_{pid}", p.get("currency"))
    taux = None
    if p and monnaie != p["currency"]:
        taux = st.number_input(f"Taux : 1 {p['currency']} = combien de {monnaie} ?", min_value=0.0, value=None,
                               format="%.6f", help="Le budget saisi ci-dessous sera converti avec ce taux.")
    budget = ui.montant(f"Budget des dépenses ({p.get('currency', monnaie) if p else monnaie})", f"ch_budget_{pid}",
                        p.get("budget", 0))
    c1, c2 = st.columns(2)
    statut = c1.selectbox("État", R.STATUSES, index=R.STATUSES.index(p.get("status", "À démarrer")))
    avancement = c2.slider("Avancement (%)", 0, 100, int(p.get("progress", 0)))
    if st.button("Enregistrer", type="primary"):
        try:
            if not nom.strip():
                raise ValueError("Le nom est obligatoire.")
            rec = {"name": nom.strip(), "client": cli or "", "location": lieu.strip(), "deadline": echeance,
                   "status": statut, "progress": float(avancement), "currency": monnaie,
                   "budget": R.cents(budget, "Budget")}
            if p:
                rec = R.convert_currency("projects", {**rec, "id": p["id"]}, p, taux)
                rec.pop("id")
                with db.transaction(f"Modification du chantier {rec['name']}") as t:
                    t.maj("projects", p["id"], rec)
            else:
                with db.transaction(f"Création du chantier {rec['name']}") as t:
                    t.inserer("projects", {"id": db.nouvel_id(), **rec})
        except ValueError as e:
            st.error(str(e))
        else:
            ui.succes("Chantier enregistré.")


def page() -> None:
    auth.exiger("chantiers")
    ui.en_tete("Chantiers", "Budgets, avancement et dépenses par chantier.")
    s = R.charger("projects", "clients", "expenses", "supplier_payments", "supplier_reversals", "invoices",
                  "personnel")
    ecrit = auth.modifie("chantiers")
    if ecrit and st.button("Nouveau chantier", type="primary", icon=":material/add:"):
        formulaire()
    if not s["projects"]:
        st.info("Organisez vos travaux : ajoutez un premier chantier, son client et son budget.")
        return
    filtre = st.pills("État", R.STATUSES, selection_mode="multi", default=None, key="ch_filtre")
    projets = [p for p in s["projects"] if not filtre or p["status"] in filtre]
    rows = lignes(s, projets)
    i = ui.tableau(rows, COLONNES, key="tab_chantiers", selection=True)
    if i is None:
        st.caption("Sélectionnez un chantier dans le tableau pour l'ouvrir ou le modifier.")
        return
    p = next(x for x in s["projects"] if x["id"] == rows[i]["_id"])
    st.subheader(p["name"])
    if ecrit and st.button("Modifier ce chantier", icon=":material/edit:"):
        formulaire(p["id"])
    a, b, c = st.columns(3)
    a.markdown(f"**Client :** {R.client_name(s, p['client'])}  \n**Lieu :** {p['location'] or '—'}  \n"
               f"**Échéance :** {p['deadline'] or 'Non précisée'}  \n**État :** {p['status']}")
    b.markdown(f"**Budget :** {R.money(p['budget'], p['currency'])}  \n**Décaissements :** "
               f"{ui.montants_texte(decaissements(s, p['id']), True)}")
    if auth.voit("commercial"):
        fac = [x for x in s["invoices"] if x["project"] == p["id"]]
        c.markdown("**Facturé :** " + ui.montants_texte(R.totals_by_currency(fac, R.total), True) + "  \n**Reste à "
                   "encaisser :** " + ui.montants_texte(R.totals_by_currency(fac, lambda x: R.total(x) - x["paid"]), True))
    if auth.voit("depenses"):
        dep = sorted([e for e in s["expenses"] if e["project"] == p["id"]], key=lambda e: e["date"], reverse=True)
        st.markdown("**Dépenses du chantier**")
        if dep:
            ui.tableau([{"date": e["date"], "libelle": e["label"], "cat": e["category"],
                         "montant": R.money(e["amount"], e["currency"])} for e in dep],
                       {"date": "Date", "libelle": "Libellé", "cat": "Catégorie", "montant": "Montant"},
                       key="tab_dep_ch")
        else:
            st.caption("Aucune dépense enregistrée sur ce chantier.")
    equipe = [x["name"] for x in s["personnel"] if x["active"] and x["location"] == "Chantier" and x["project"] == p["id"]]
    if equipe:
        st.markdown("**Personnel affecté :** " + ", ".join(equipe))
