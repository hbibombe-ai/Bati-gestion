"""Pipeline CRM : pistes commerciales en kanban par étape, montants pondérés, conversion en client."""
from __future__ import annotations

import datetime as dt

import streamlit as st

import auth
import composants as C
import db
import erp
import nav
import regles as R
import ui

TEINTES = {"Nouveau": "#3d5afe", "Qualifié": "#22b8cf", "Proposition": "#ff9f1c", "Négociation": "#7048e8",
           "Gagné": "#12b886", "Perdu": "#868e96"}
ETIQ = {"Nouveau": ("#e9eeff", "#1a27b5"), "Qualifié": ("#e3f8fb", "#0b7285"), "Proposition": ("#fff1dc", "#b35c00"),
        "Négociation": ("#efe9ff", "#5f3dc4"), "Gagné": ("#e3f7ef", "#0b7a56"), "Perdu": ("#edf0f7", "#5a6684")}


def _etoiles(n: int) -> str:
    return "★" * int(n or 0) + "☆" * (3 - int(n or 0))


@st.dialog("Piste commerciale", width="large")
def formulaire(pid: str | None = None) -> None:
    s = R.charger("clients")
    p = db.un("crm_pistes", pid) if pid else {}
    p = p or {}
    users = erp.utilisateurs_actifs()
    titre = st.text_input("Titre de l’opportunité *", value=p.get("titre", ""), max_chars=500,
                          placeholder="Ex. Construction d’un entrepôt à Kingabwa")
    a, b = st.columns(2)
    client = ui.choix("Client existant", ui.options_clients(s, p.get("client", "")), f"crm_cli_{pid}", p.get("client", ""),
                      vide="Nouveau prospect (pas encore client)")
    with b:
        contact = st.text_input("Nom du prospect / de l’interlocuteur", value=p.get("contact", ""), max_chars=300)
    c, d = st.columns(2)
    tel = c.text_input("Téléphone", value=p.get("telephone", ""), max_chars=100)
    mail = d.text_input("E-mail", value=p.get("email", ""), max_chars=300)
    e, f, g = st.columns(3)
    with e:
        devise = ui.devise("Monnaie", f"crm_dev_{pid}", p.get("devise") or R.company().get("defaultCurrency", "USD"))
    with f:
        montant = ui.montant("Montant estimé", f"crm_mt_{pid}", p.get("montant", 0))
    etape = g.selectbox("Étape", erp.ETAPES_CRM + [erp.PERDU],
                        index=(erp.ETAPES_CRM + [erp.PERDU]).index(p.get("etape", "Nouveau")))
    h, i, j = st.columns(3)
    proba = h.slider("Probabilité (%)", 0, 100, int(p.get("probabilite", erp.PROBA_ETAPE.get(etape, 10))), step=5)
    prio = i.select_slider("Priorité", options=[0, 1, 2, 3], value=int(p.get("priorite", 0)), format_func=_etoiles)
    with j:
        cloture = ui.date_txt("Clôture prévue", f"crm_cl_{pid}", p.get("cloture_prevue") or "", vide_ok=True)
    k, l_ = st.columns(2)
    sources = [""] + erp.SOURCES_CRM
    source = k.selectbox("Source", sources, index=sources.index(p.get("source", "")) if p.get("source", "") in sources else 0,
                         format_func=lambda x: x or "Non précisée")
    ids = list(users)
    moi = auth.utilisateur()["id"]
    resp = l_.selectbox("Responsable", ids, format_func=users.get,
                        index=ids.index(p.get("responsable") or moi) if (p.get("responsable") or moi) in ids else 0)
    notes = st.text_area("Notes", value=p.get("notes", ""), height=90)
    if st.button("Enregistrer", type="primary"):
        try:
            erp.enregistrer_piste({"titre": titre, "client": client or "", "contact": contact, "telephone": tel,
                                   "email": mail, "source": source, "montant": R.cents(montant, "Montant estimé"),
                                   "devise": devise, "probabilite": proba, "etape": etape, "responsable": resp,
                                   "cloture_prevue": cloture, "priorite": prio, "notes": notes,
                                   "motif_perte": p.get("motif_perte", "")}, pid)
        except ValueError as e:
            st.error(str(e))
        else:
            ui.succes("Piste enregistrée.")


def _lignes(s: dict, pistes: list[dict], users: dict) -> list[dict]:
    aujourd_hui = R.today()
    rows = []
    for p in pistes:
        nom_client = R.client_name(s, p["client"]) if p["client"] else ""
        rows.append({"_id": p["id"], "titre": p["titre"], "client": nom_client or p["contact"] or "—",
                     "etape": p["etape"], "montant": R.money(p["montant"], p["devise"]), "_montant": p["montant"],
                     "_devise": p["devise"], "pondere": R.money(erp.montant_pondere(p), p["devise"]),
                     "proba": f"{p['probabilite']} %", "_proba": p["probabilite"], "prio": _etoiles(p["priorite"]),
                     "_prio": p["priorite"], "resp": users.get(p["responsable"], "—"), "_resp": p["responsable"],
                     "source": p["source"] or "Non précisée", "cloture": p["cloture_prevue"] or "",
                     "_retard": bool(p["cloture_prevue"]) and p["cloture_prevue"] < aujourd_hui
                     and p["etape"] not in ("Gagné", erp.PERDU), "tel": p["telephone"], "mail": p["email"]})
    return rows


def _carte(r: dict) -> dict:
    fond, txt = ETIQ.get(r["etape"], ("#eef1fd", "#1a27b5"))
    tags = [(r["prio"], "#fff8e1", "#b38600")] if r["_prio"] else []
    if r["_retard"]:
        tags.append(("Clôture dépassée", "#fdeeec", "#a62d25"))
    tags.append((r["etape"], fond, txt))
    return {"titre": r["titre"], "sous_titre": r["client"], "initiales": C.initiales(r["resp"]),
            "couleur_avatar": C.couleur_nom(r["resp"]), "couleur": TEINTES.get(r["etape"], "#c8d0e4"),
            "lignes": [f"{r['montant']} · {r['proba']}", f"Clôture prévue : {r['cloture']}" if r["cloture"] else "",
                       f"Responsable : {r['resp']}"], "etiquettes": tags}


def _total(rs: list[dict]) -> str:
    par: dict[str, int] = {}
    for r in rs:
        par[r["_devise"]] = par.get(r["_devise"], 0) + r["_montant"]
    return " · ".join(R.money(v, k) for k, v in par.items() if v)


def page() -> None:
    auth.exiger("commercial")
    ecrit = auth.modifie("commercial")
    s = R.charger("clients")
    pistes = db.tout("crm_pistes")
    users = erp.utilisateurs_actifs()
    sel = C.fiche_ouverte("crm")
    p = next((x for x in pistes if x["id"] == sel), None) if sel else None
    if p:
        fiche(s, p, ecrit, users)
        return
    ouvertes = [x for x in pistes if x["etape"] not in ("Gagné", erp.PERDU)]
    pond: dict[str, int] = {}
    for x in ouvertes:
        pond[x["devise"]] = pond.get(x["devise"], 0) + erp.montant_pondere(x)
    ui.en_tete("Pipeline CRM", "Prospects et opportunités, de la première prise de contact à la signature.",
               badge=f"{len(ouvertes)} piste{'s' if len(ouvertes) > 1 else ''} ouverte{'s' if len(ouvertes) > 1 else ''}")
    if ecrit and st.button("Nouvelle piste", type="primary", icon=":material/add:"):
        formulaire()
    if not pistes:
        st.info("Ajoutez une première piste : un prospect, un appel d’offres, un client qui demande un prix…")
        return
    gagnees = [x for x in pistes if x["etape"] == "Gagné"]
    perdues = [x for x in pistes if x["etape"] == erp.PERDU]
    taux = f"{100 * len(gagnees) / (len(gagnees) + len(perdues)):.0f} %" if gagnees or perdues else "—"
    k = st.columns(3)
    with k[0]:
        ui.carte("Montant pondéré des pistes ouvertes", " · ".join(R.money(v, c) for c, v in pond.items()) or "0",
                 "montant × probabilité", accent=True)
    with k[1]:
        ui.carte("Pistes gagnées", str(len(gagnees)), _total(_lignes(s, gagnees, users)) or "—")
    with k[2]:
        ui.carte("Taux de réussite", taux, f"{len(gagnees)} gagnée(s) / {len(perdues)} perdue(s)")
    moi = auth.utilisateur()["id"]
    filtres = [("Mes pistes", "Qui", lambda r: r["_resp"] == moi),
               ("Ouvertes", "État", lambda r: r["etape"] not in ("Gagné", erp.PERDU)),
               ("Gagnées", "État", lambda r: r["etape"] == "Gagné"), ("Perdues", "État", lambda r: r["etape"] == erp.PERDU),
               ("Priorité haute", "Priorité", lambda r: r["_prio"] >= 2),
               ("Clôture dépassée", "Alerte", lambda r: r["_retard"])]
    C.vue_liste("crm", _lignes(s, pistes, users),
                {"titre": "Opportunité", "client": "Client / prospect", "etape": "Étape", "montant": "Montant",
                 "proba": "Probabilité", "pondere": "Pondéré", "cloture": "Clôture prévue", "resp": "Responsable",
                 "prio": "Priorité"},
                recherche=("titre", "client", "resp", "source", "tel", "mail"), filtres=filtres,
                regroupements={"Étape": ("etape", erp.ETAPES_CRM + [erp.PERDU]), "Responsable": ("resp", None),
                               "Source": ("source", None), "Client": ("client", None)},
                regroupement_defaut="Étape", carte=_carte, vue_defaut="Kanban", nom="piste",
                couleurs_groupes=TEINTES, total_groupe=_total)


def fiche(s: dict, p: dict, ecrit: bool, users: dict) -> None:
    C.fil_ariane("Pipeline CRM", p["titre"], "crm")
    with st.container(horizontal=True, gap="small", vertical_alignment="center", horizontal_alignment="distribute"):
        with st.container(horizontal=True, gap="small", width="content"):
            if ecrit and st.button("Modifier", icon=":material/edit:", type="primary", key="crm_mod"):
                formulaire(p["id"])
            if ecrit and not p["client"] and st.button("Créer le client", icon=":material/person_add:", key="crm_cli"):
                erp.creer_client(p["id"])
                ui.succes("Client créé dans « Clients et fournisseurs » et rattaché à la piste.")
            if ecrit and p["etape"] != erp.PERDU:
                with st.popover("Marquer perdue", icon=":material/thumb_down:"):
                    motif = st.text_input("Motif de la perte", key="crm_motif", placeholder="Prix, délai, concurrent…")
                    if st.button("Confirmer", key="crm_perdu"):
                        try:
                            erp.changer_etape(p["id"], erp.PERDU, motif)
                        except ValueError as e:
                            st.error(str(e))
                        else:
                            ui.succes("Piste marquée perdue.")
            if p["etape"] == "Gagné" and "devis" in nav.PAGES and st.button("Aller aux devis", icon=":material/request_quote:"):
                nav.aller("devis")
        if p["etape"] == erp.PERDU:
            st.html('<div class="bg-etapes"><span class="on" style="background:#868e96">Perdue</span></div>')
            nouvelle = None
            if ecrit and st.button("Réouvrir", icon=":material/undo:", key="crm_rouvrir"):
                nouvelle = "Nouveau"
        else:
            nouvelle = C.barre_etapes(erp.ETAPES_CRM, p["etape"], cle=f"crm_{p['id']}", modifiable=ecrit)
    if nouvelle:
        erp.changer_etape(p["id"], nouvelle)
        ui.succes(f"Étape : {nouvelle}." + (" Félicitations !" if nouvelle == "Gagné" else ""))
    gauche, droite = st.columns([1.75, 1], gap="medium")
    with gauche:
        with st.container(key="bg_feuille"):
            st.subheader(p["titre"])
            a, b = st.columns(2)
            a.markdown(f"**Client :** {R.client_name(s, p['client']) if p['client'] else '— (prospect)'}  \n"
                       f"**Interlocuteur :** {p['contact'] or '—'}  \n**Téléphone :** {p['telephone'] or '—'}  \n"
                       f"**E-mail :** {p['email'] or '—'}")
            b.markdown(f"**Montant estimé :** {R.money(p['montant'], p['devise'])}  \n**Probabilité :** "
                       f"{p['probabilite']} %  \n**Montant pondéré :** {R.money(erp.montant_pondere(p), p['devise'])}  \n"
                       f"**Clôture prévue :** {p['cloture_prevue'] or '—'}")
            st.markdown(f"**Responsable :** {users.get(p['responsable'], '—')} · **Source :** {p['source'] or '—'} · "
                        f"**Priorité :** {_etoiles(p['priorite'])}")
            if p["etape"] == erp.PERDU and p["motif_perte"]:
                st.warning(f"Motif de la perte : {p['motif_perte']}")
            if p["notes"]:
                st.markdown("**Notes**")
                st.write(p["notes"])
    with droite:
        C.fil_activite("crm_pistes", p["id"], peut_noter=ecrit, libelle=p["titre"])
