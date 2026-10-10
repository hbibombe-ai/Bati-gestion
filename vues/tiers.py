"""Tiers : clients, fournisseurs et sous-traitants dans un carnet unique (une fiche peut cumuler les rôles)."""
from __future__ import annotations

import streamlit as st

import auth
import db
import nav
import regles as R
import ui


def roles_txt(p: dict) -> str:
    return ", ".join(R.PARTY_ROLES.get(r, r) for r in R.party_roles(p))


@st.dialog("Fiche tiers", width="large")
def formulaire(tid: str | None = None) -> None:
    s = R.charger("clients", "projects", "quotes", "invoices", "expenses", "supplier_invoices", "supplier_payments")
    old = next((c for c in s["clients"] if c["id"] == tid), None) or {}
    k = tid or "new"
    a, b = st.columns(2)
    code = a.text_input("Code tiers *", value=old.get("code") or R.next_party_code(s["clients"]), key=f"t_code_{k}")
    nom = b.text_input("Raison sociale / nom *", value=old.get("name", ""), key=f"t_nom_{k}", max_chars=500)
    tel = a.text_input("Téléphone", value=old.get("phone", ""), key=f"t_tel_{k}")
    mail = b.text_input("E-mail", value=old.get("email", ""), key=f"t_mail_{k}")
    adr = a.text_input("Adresse", value=old.get("address", ""), key=f"t_adr_{k}")
    rccm = b.text_input("RCCM / identifiant fiscal", value=old.get("registration", ""), key=f"t_rccm_{k}")
    roles = st.multiselect("Rôles de ce tiers *", list(R.PARTY_ROLES), default=R.party_roles(old) if old else ["client"],
                           format_func=lambda r: R.PARTY_ROLES[r], key=f"t_roles_{k}",
                           help="Cochez plusieurs rôles si nécessaire. Archiver une fiche conserve ses opérations.")
    if st.button("Enregistrer", type="primary"):
        try:
            if not roles:
                raise ValueError("Choisissez au moins un rôle.")
            rec = {"code": code.strip(), "name": nom.strip(), "phone": tel.strip(), "email": mail.strip(),
                   "address": adr.strip(), "registration": rccm.strip(), "roles": roles,
                   "archived": bool(old.get("archived", False))}
            if not rec["name"] or not rec["code"]:
                raise ValueError("Le nom et le code sont obligatoires.")
            norm = lambda x: str(x or "").strip().lower()  # noqa: E731
            if any(c["id"] != tid and norm(c["code"]) == norm(rec["code"]) for c in s["clients"]):
                raise ValueError("Ce code existe déjà. Utilisez un autre code.")
            if (not tid or norm(old.get("name")) != norm(rec["name"])) and \
                    any(c["id"] != tid and norm(c["name"]) == norm(rec["name"]) for c in s["clients"]):
                raise ValueError("Ce nom existe déjà. Ajoutez les rôles à sa fiche existante plutôt que de créer un doublon.")
            if tid and "client" not in roles and any(r["client"] == tid for r in s["projects"] + s["quotes"] + s["invoices"]):
                raise ValueError("Conservez le rôle Client : cette fiche est liée à des chantiers ou documents.")
            if tid and not set(roles) & {"supplier", "subcontractor"} and (
                    any(e["supplier_id"] == tid for e in s["expenses"])
                    or any(i["party_id"] == tid for i in s["supplier_invoices"] + s["supplier_payments"])):
                raise ValueError("Conservez le rôle Fournisseur ou Sous-traitant : des opérations utilisent cette fiche.")
            with db.transaction(f"Fiche tiers {rec['name']}") as t:
                if tid:
                    t.maj("clients", tid, rec)
                else:
                    t.inserer("clients", {"id": db.nouvel_id(), **rec})
        except ValueError as e:
            st.error(str(e))
        else:
            ui.succes("Fiche tiers enregistrée.")


def page() -> None:
    auth.exiger("tiers")
    ui.en_tete("Clients et fournisseurs", "Clients, fournisseurs et sous-traitants dans un carnet unique.")
    s = R.charger("clients", "projects", "invoices", "expenses")
    ecrit = auth.modifie("tiers")
    if ecrit and st.button("Nouveau tiers", type="primary", icon=":material/person_add:"):
        formulaire()
    a, b, c = st.columns([2, 1, 1])
    q = a.text_input("Rechercher un tiers", placeholder="Nom, code, téléphone…", key="t_q")
    role = b.selectbox("Rôle", [""] + list(R.PARTY_ROLES), format_func=lambda r: R.PARTY_ROLES.get(r, "Tous les rôles"))
    archives = c.toggle("Inclure les tiers archivés", key="t_arch")
    ql = q.strip().lower()
    liste = [p for p in s["clients"] if (archives or not p.get("archived")) and (not role or role in R.party_roles(p))
             and any(ql in str(p.get(f) or "").lower() for f in ("name", "code", "phone", "email", "registration"))]
    liste.sort(key=lambda p: p["name"].lower())
    if not liste:
        st.info("Aucun tiers ne correspond à ces critères." if s["clients"] else
                "Enregistrez un client pour établir un devis ou une facture, ou un fournisseur pour vos dépenses.")
        return
    rows = [{"_id": p["id"], "nom": p["name"], "code": p.get("code", ""), "roles": roles_txt(p), "tel": p["phone"],
             "mail": p["email"], "adr": p["address"], "etat": "Archivé" if p.get("archived") else "Actif"} for p in liste]
    i = ui.tableau(rows, {"nom": "Tiers", "code": "Code", "roles": "Rôles", "tel": "Téléphone", "mail": "E-mail",
                          "adr": "Adresse", "etat": "État"}, key="tab_tiers", selection=True)
    st.caption("Une seule fiche peut cumuler plusieurs rôles. Sélectionnez un tiers pour le consulter.")
    if i is None:
        return
    p = next(x for x in s["clients"] if x["id"] == rows[i]["_id"])
    st.subheader(p["name"])
    cols = ui.rangee(4)
    if ecrit and cols[0].button("Modifier", icon=":material/edit:"):
        formulaire(p["id"])
    if ecrit and cols[1].button("Réactiver" if p.get("archived") else "Archiver", icon=":material/archive:"):
        with db.transaction(("Réactivation" if p.get("archived") else "Archivage") + f" du tiers {p['name']}") as t:
            t.maj("clients", p["id"], {"archived": not p.get("archived")})
        ui.succes("Tiers réactivé." if p.get("archived") else "Tiers archivé. Ses liens et opérations sont conservés.")
    if "comptes-tiers" in nav.PAGES and cols[2].button("Ouvrir son compte", icon=":material/account_balance_wallet:"):
        st.session_state["ct_filtres"] = {"party": p["id"], "project": "", "currency": "", "from": "", "to": ""}
        nav.aller("comptes-tiers")
    factures = [d for d in s["invoices"] if d["client"] == p["id"]]
    depenses = [e for e in s["expenses"] if e["supplier_id"] == p["id"]]
    projets = [r["name"] for r in s["projects"] if r["client"] == p["id"]
               or any(f["project"] == r["id"] for f in factures) or any(e["project"] == r["id"] for e in depenses)]
    st.markdown(f"{p.get('code', '')} · {roles_txt(p)}  \n{p['phone'] or ''} {p['email'] or ''}  \n{p['address'] or ''}"
                f"  \n{p.get('registration') or ''}")
    if auth.voit("commercial"):
        st.markdown("**Créances sur factures :** " + ui.montants_texte(
            R.totals_by_currency(factures, lambda x: R.total(x) - x["paid"]), True))
    st.markdown("**Chantiers liés :** " + (", ".join(projets) if projets else "aucun"))
    if auth.voit("depenses"):
        st.markdown(f"**Dépenses rattachées :** {len(depenses)} · "
                    + ui.montants_texte(R.totals_by_currency(depenses, lambda e: e["amount"]), True))
