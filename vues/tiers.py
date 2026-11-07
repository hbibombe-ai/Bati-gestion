"""Tiers : clients, fournisseurs et sous-traitants dans un carnet unique (une fiche peut cumuler les rôles)."""
from __future__ import annotations

import streamlit as st

import auth
import composants as C
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


ROLE_ETIQUETTES = {"client": ("#e9eeff", "#1a27b5"), "supplier": ("#fff1dc", "#b35c00"),
                   "subcontractor": ("#efe9ff", "#5f3dc4")}


def carte_kanban(r: dict) -> dict:
    """Carte de contact : avatar, rôles, téléphone, e-mail, adresse."""
    tags = [(R.PARTY_ROLES.get(x, x), *ROLE_ETIQUETTES.get(x, ("#eef1fd", "#1a27b5"))) for x in r["_roles"]]
    if r["etat"] == "Archivé":
        tags.append(("Archivé", "#edf0f7", "#5a6684"))
    return {"titre": r["nom"], "sous_titre": r["code"], "initiales": C.initiales(r["nom"]),
            "couleur": "#d6336c" if "client" in r["_roles"] else "#ff9f1c",
            "lignes": [r["tel"], r["mail"], r["adr"]], "etiquettes": tags}


def page() -> None:
    auth.exiger("tiers")
    s = R.charger("clients", "projects", "invoices", "expenses")
    ecrit = auth.modifie("tiers")
    sel = C.fiche_ouverte("tiers")
    p = next((x for x in s["clients"] if x["id"] == sel), None) if sel else None
    if p:
        fiche(s, p, ecrit)
        return
    ui.en_tete("Clients et fournisseurs", "Clients, fournisseurs et sous-traitants dans un carnet unique.")
    if ecrit and st.button("Nouveau tiers", type="primary", icon=":material/person_add:"):
        formulaire()
    if ecrit:
        from vues import imports as IMP
        IMP.encart(["tiers"], "Importer des tiers depuis Excel")
    if not s["clients"]:
        st.info("Enregistrez un client pour établir un devis ou une facture, ou un fournisseur pour vos dépenses.")
        return
    liste = sorted(s["clients"], key=lambda p: p["name"].lower())
    rows = [{"_id": p["id"], "nom": p["name"], "code": p.get("code", ""), "roles": roles_txt(p), "tel": p["phone"] or "",
             "mail": p["email"] or "", "adr": p["address"] or "", "etat": "Archivé" if p.get("archived") else "Actif",
             "rccm": p.get("registration") or "", "_roles": R.party_roles(p),
             "role1": R.PARTY_ROLES.get((R.party_roles(p) or [""])[0], "")} for p in liste]
    filtres = [(R.PARTY_ROLES[k], "Rôle", (lambda k: lambda r: k in r["_roles"])(k)) for k in R.PARTY_ROLES]
    filtres += [("Actifs", "État", lambda r: r["etat"] == "Actif"), ("Archivés", "État", lambda r: r["etat"] == "Archivé")]
    C.vue_liste("tiers", rows, {"nom": "Tiers", "code": "Code", "roles": "Rôles", "tel": "Téléphone", "mail": "E-mail",
                                "adr": "Adresse", "etat": "État"},
                recherche=("nom", "code", "tel", "mail", "rccm", "adr"), filtres=filtres,
                regroupements={"Rôle principal": ("role1", list(R.PARTY_ROLES.values())), "État": ("etat", ["Actif", "Archivé"])},
                carte=carte_kanban, vue_defaut="Kanban", nom="tiers", nom_pluriel="tiers")


def fiche(s: dict, p: dict, ecrit: bool) -> None:
    """Fiche tiers : coordonnées, chiffres clés, documents et fil d'activité."""
    C.fil_ariane("Clients et fournisseurs", p["name"], "tiers")
    cols = ui.rangee(3)
    if ecrit and cols[0].button("Modifier", icon=":material/edit:", type="primary"):
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
    gauche, droite = st.columns([1.75, 1], gap="medium")
    with gauche:
        with st.container(key="bg_feuille"):
            tags = "".join(f'<span class="bg-tag">{ui._esc(R.PARTY_ROLES.get(x, x))}</span>' for x in R.party_roles(p))
            st.html(f'<div style="display:flex;gap:14px;align-items:center"><span class="bg-avatar" style="width:56px;'
                    f'height:56px;font-size:1.2rem;border-radius:14px;background:{C.couleur_nom(p["name"])}">'
                    f'{ui._esc(C.initiales(p["name"]))}</span><div><div style="font-size:1.4rem;font-weight:800;'
                    f'color:var(--bg-navy)">{ui._esc(p["name"])}</div><div>{tags}'
                    + ('<span class="bg-tag alerte">Archivé</span>' if p.get("archived") else "") + "</div></div></div>")
            a, b = st.columns(2)
            a.markdown(f"**Code :** {p.get('code') or '—'}  \n**Téléphone :** {p['phone'] or '—'}  \n"
                       f"**E-mail :** {p['email'] or '—'}")
            b.markdown(f"**Adresse :** {p['address'] or '—'}  \n**RCCM / identifiant fiscal :** {p.get('registration') or '—'}")
            if auth.voit("commercial"):
                st.markdown("**Créances sur factures :** " + ui.montants_texte(
                    R.totals_by_currency(factures, lambda x: R.total(x) - x["paid"]), True, consolide_aussi=True))
            st.markdown("**Chantiers liés :** " + (", ".join(projets) if projets else "aucun"))
            if auth.voit("depenses"):
                st.markdown(f"**Dépenses rattachées :** {len(depenses)} · "
                            + ui.montants_texte(R.totals_by_currency(depenses, lambda e: e["amount"]), True,
                                                consolide_aussi=True))
            ui.pieces_jointes("tiers", p["id"], peut_ajouter=ecrit)
    with droite:
        C.fil_activite("clients", p["id"], peut_noter=auth.voit("tiers"))
