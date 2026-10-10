"""Centre de reprise et d'import Excel ; composant réutilisable dans les pages métier.

Parcours : modèle téléchargeable → contrôle (aperçu conservé côté serveur) → confirmation → lot.
En reprise, le lot reste « Préparé » jusqu'à la validation Finance puis l'activation DG.
"""
from __future__ import annotations

import datetime as dt

import streamlit as st

import auth
import db
import gestion_v7 as V
import regles as R
import ui
from imports import excel as X
from imports import reconciliation as RC
from imports import schema as S
from imports import service as SV
from imports import validation as VA

ACTIONS_LIB = {"Création": "Créations", "Correspondance": "Correspondances", "Reliquat à activer": "Reliquats à activer",
               "Budget à approuver": "Budgets à approuver", "Brouillon N0": "Demandes N0 en brouillon",
               "Archive": "Archives", "Ignoré (identique)": "Ignorés (identiques)", "Pièce jointe": "Pièces"}


def _role() -> str:
    return (auth.utilisateur() or {}).get("role", "")


def fonctions_permises(role: str, parmi: list[str] | None = None) -> list[str]:
    out = []
    for cle, f in S.FONCTIONS.items():
        if parmi and cle not in parmi:
            continue
        if any(VA.autorise(role, S.FEUILLES[n]) for n in f.feuilles):
            out.append(cle)
    return out


def _modes(cle: str, role: str) -> list[str]:
    f = S.fonction(cle)
    modes = set()
    for n in f.feuilles:
        fe = S.FEUILLES[n]
        if VA.autorise(role, fe):
            modes |= set(fe.modes)
    return [m for m in S.MODES if m in modes]


def _montant(c: int, devise: str) -> str:
    return R.money(c, devise)


def afficher_rapport(rapport: dict, key: str) -> None:
    n_err, n_al = len(rapport["errors"]), len(rapport["warnings"])
    cols = st.columns(4)
    cols[0].metric("Erreurs bloquantes", n_err)
    cols[1].metric("Alertes", n_al, help="Une alerte marquée « décision » exige votre accord explicite.")
    cols[2].metric("Actions prévues", len(rapport["plan"]))
    cols[3].metric("Décisions requises", len(rapport["decisions"]))
    if rapport["confidentiel_refuse"]:
        st.error("Import refusé : ce fichier contient des données réservées (RH / rémunérations) ou des feuilles hors de "
                 "vos droits. Son contenu n’est pas affiché.")
    if rapport["errors"]:
        st.markdown("**Erreurs bloquantes** — aucune donnée ne sera enregistrée tant qu’elles subsistent.")
        ui.tableau(rapport["errors"][:500], {"sheet": "Feuille", "line": "Ligne", "field": "Champ", "message": "Anomalie"},
                   key=f"{key}_err")
    if rapport["warnings"]:
        st.markdown("**Alertes**")
        ui.tableau([{**w, "decision": "Oui" if w["decision"] else ""} for w in rapport["warnings"][:500]],
                   {"sheet": "Feuille", "line": "Ligne", "field": "Champ", "message": "Alerte", "decision": "Décision requise"},
                   key=f"{key}_warn")
    if rapport["confidentiel_refuse"]:
        return
    if rapport["comptes"]:
        st.markdown("**Effets proposés** : " + " · ".join(f"{ACTIONS_LIB.get(k, k)} {v}" for k, v in rapport["comptes"].items()))
    if rapport["totaux"]:
        st.markdown("**Totaux par devise** (jamais additionnés entre USD, CDF et EUR)")
        ui.tableau([{"r": t["rubrique"], "d": t["devise"], "c": t["compte"], "m": _montant(t["montant"], t["devise"])}
                    for t in rapport["totaux"]], {"r": "Rubrique", "d": "Devise", "c": "Compte", "m": "Montant"},
                   key=f"{key}_tot")
    with st.expander(f"Détail des {len(rapport['plan'])} actions (créations, correspondances, doublons, effets)"):
        ui.tableau([{k: a[k] for k in ("ordre", "sheet", "line", "action", "ref", "detail")} for a in rapport["plan"][:2000]],
                   {"ordre": "Ordre", "sheet": "Feuille", "line": "Ligne", "action": "Action", "ref": "Référence",
                    "detail": "Détail"}, key=f"{key}_plan")


def bloc_import(parmi: list[str] | None = None, cle: str = "centre") -> None:
    """Composant d'import : utilisé dans le centre de reprise et dans les pages métier."""
    role = _role()
    permises = fonctions_permises(role, parmi)
    if not permises:
        st.caption("Votre rôle ne permet pas d’importer ces données.")
        return
    a, b = st.columns(2)
    fonction = a.selectbox("Fonction", permises, format_func=lambda k: S.FONCTIONS[k].libelle, key=f"{cle}_fn")
    modes = _modes(fonction, role)
    mode = b.radio("Mode", modes, format_func=S.MODES.get, horizontal=True, key=f"{cle}_mode")
    st.info(S.EFFETS_MODE[mode])
    c1, c2, c3 = st.columns(3)
    with c1:
        date_b = ui.date_txt("Date de bascule", f"{cle}_d", "2026-11-01") if mode == "reprise" else ""
    ref_lot = c2.text_input("Référence du lot (pré-remplie dans le modèle)", value=f"LOT-{fonction.upper()}-{dt.date.today():%Y%m%d}", key=f"{cle}_ref",
                            help="Unique. Un lot préparé peut être remplacé par un fichier corrigé portant la même référence.")
    projets = db.tout("projects")
    chantier = c3.selectbox("Limiter à un chantier (facultatif)", [""] + [p["id"] for p in projets], key=f"{cle}_ch",
                            format_func=lambda i: "Tous" if not i else R.name_of(projets, i, "Chantier"))
    st.caption(f"Feuilles : {', '.join(S.fonction(fonction).feuilles)} · {S.fonction(fonction).description}")
    ui.telecharger("Télécharger le modèle Excel", X.modele(fonction, mode, date_b, ref_lot),
                   f"MY-DESTINY-import-{fonction}-{S.VERSION_MODELE}.xlsx", ui.MIME_XLSX, key=f"{cle}_mod", principal=True)
    fichier = st.file_uploader("Classeur rempli (.xlsx, sans macros ni formules)", type=["xlsx"], key=f"{cle}_file")
    pieces = {}
    if "Documents" in S.fonction(fonction).feuilles:
        envois = st.file_uploader("Pièces originales citées dans la feuille Documents (PDF, JPEG, PNG)",
                                  type=["pdf", "jpg", "jpeg", "png"], accept_multiple_files=True, key=f"{cle}_pieces")
        pieces = {f.name: f.getvalue() for f in envois or []}
    etat_key = f"{cle}_apercu"
    if fichier is not None and st.button("Contrôler le fichier", type="primary", key=f"{cle}_ctrl"):
        try:
            contenu = fichier.getvalue()
            ds = SV.parse_file(contenu, fonction)
            ctx = SV.contexte(mode, date_b, chantier, pieces)
            st.session_state[etat_key] = {**SV.preview_import(ds, ctx, contenu, fichier.name), "nom": fichier.name,
                                          "fonction": fonction, "mode": mode}
        except ValueError as e:
            st.session_state.pop(etat_key, None)
            st.error(str(e))
    ap = st.session_state.get(etat_key)
    if not ap or ap.get("fonction") != fonction or ap.get("mode") != mode:
        return
    with st.container(border=True):
        st.markdown(f"**Contrôle de {ap['nom']}** — {S.FONCTIONS[fonction].libelle} · {S.MODES[mode]}")
        afficher_rapport(ap["rapport"], f"{cle}_r")
        ui.telecharger("Télécharger le rapport de contrôle", X.rapport(ap["rapport"]), "rapport-controle-import.xlsx",
                       ui.MIME_XLSX, key=f"{cle}_rap")
        if ap["rapport"]["errors"] or not ap["preview_id"]:
            return
        accepte = True
        if ap["rapport"]["decisions"]:
            accepte = st.checkbox("J’ai examiné les alertes marquées « décision requise » et j’accepte leurs effets sur la "
                                  "reprise.", key=f"{cle}_acc")
        remplacer = False
        if any(w["field"] == "reference_lot" for w in ap["rapport"]["decisions"]):
            remplacer = st.checkbox("Rejeter et remplacer le lot préparé portant cette référence.", key=f"{cle}_rempl")
        if st.button("Confirmer l’import", type="primary", disabled=not accepte, key=f"{cle}_go"):
            try:
                r = SV.commit_import(ap["preview_id"], {"accepter_alertes": accepte, "remplacer": remplacer}, pieces)
            except SV.ImportBloque as e:
                st.error(str(e))
                afficher_rapport(e.rapport, f"{cle}_rb")
            except ValueError as e:
                st.error(str(e))
            else:
                st.session_state.pop(etat_key, None)
                l = r["lot"]
                if r["existant"]:
                    ui.succes(f"Ce fichier a déjà été importé : lot {l['reference_lot']} ({l['statut']}). Aucun nouvel effet.")
                else:
                    suite = (" Le lot attend la validation Finance puis l’activation DG." if l["statut"] == "Préparé" else "")
                    ui.succes(f"Lot {l['reference_lot']} enregistré : {l['statut']}.{suite}")


def encart(parmi: list[str], titre: str = "Importer depuis Excel") -> None:
    """Encart repliable pour les pages métier (mêmes contrôles et mêmes droits que le centre de reprise)."""
    if not fonctions_permises(_role(), parmi):
        return
    with st.expander(titre, icon=":material/upload_file:"):
        bloc_import(parmi, cle="enc_" + "_".join(parmi))


# ------------------------------------------------------------------ lots
def _lots_tab() -> None:
    lots = SV.lots()
    if not lots:
        st.caption("Aucun lot d’import.")
        return
    users = {u["id"]: u["nom"] for u in db.tout("users", sans=("mdp_hash",))}
    rows = [{"_id": l["id"], "ref": l["reference_lot"], "fn": S.FONCTIONS.get(l["fonction"], S.FONCTIONS["globale"]).libelle,
             "mode": S.MODES.get(l["mode"], l["mode"]), "d": l["date_bascule"], "st": l["statut"], "f": l["fichier"],
             "par": users.get(l["cree_par"], ""), "le": l["cree_le"]} for l in lots]
    i = ui.tableau(rows, {"ref": "Lot", "fn": "Fonction", "mode": "Mode", "d": "Bascule", "st": "Statut", "f": "Fichier",
                          "par": "Importé par", "le": st.column_config.DatetimeColumn("Le", format="DD/MM/YYYY HH:mm")},
                   key="imp_lots", selection=True)
    if i is None:
        st.caption("Sélectionnez un lot pour le consulter, le valider, l’activer ou le rejeter.")
        return
    l = SV.lot(rows[i]["_id"])
    st.subheader(f"Lot {l['reference_lot']} — {l['statut']}")
    st.caption(f"Empreinte SHA-256 du fichier : {l['empreinte']} · modèle {l['version_modele']} · source "
               f"{l['source_systeme'] or 'non précisée'}")
    for h in l.get("historique") or []:
        st.write(f"• {h['at'][:16].replace('T', ' ')} — {h['action']} par {h['nom']}" + (f" : {h['motif']}" if h.get("motif") else ""))
    a, b = ui.rangee(2)
    with a:
        src = SV.contenu_lot(l["id"])
        if src:
            ui.telecharger("Fichier source", src, l["fichier"] or "source.xlsx", ui.MIME_XLSX, key=f"src_{l['id']}")
    with b:
        ui.telecharger("Rapport de contrôle", X.rapport({**(l.get("rapport") or {}), "totaux": (l.get("resume") or {}).get("totaux", [])}),
                       f"controle-{l['reference_lot']}.xlsx", ui.MIME_XLSX, key=f"rap_{l['id']}")
    rap = l.get("rapprochement") or {}
    ecarts = rap.get("ecarts_activation") or rap.get("ecarts_import") or []
    if ecarts:
        st.markdown("**Rapprochement avant / après** (par devise et par compte)")
        ui.tableau([{**e, "avant": _montant(e["avant"], e["devise"] or "USD"), "apres": _montant(e["apres"], e["devise"] or "USD"),
                     "ecart": _montant(e["ecart"], e["devise"] or "USD")} for e in ecarts],
                   {"rubrique": "Rubrique", "objet": "Objet", "devise": "Devise", "avant": "Avant", "apres": "Après",
                    "ecart": "Écart"}, key=f"ec_{l['id']}")
    rel = RC.reliquats_lot(l["id"])
    if rel:
        st.markdown("**Reliquats du lot**")
        ui.tableau([{**r, "montant": _montant(r["montant"], r["devise"]), "reste": _montant(r["reste"], r["devise"])} for r in rel],
                   {"ref": "Référence", "type": "Nature", "devise": "Devise", "montant": "Montant repris", "reste": "Reste",
                    "statut": "Statut"}, key=f"rel_{l['id']}")
    lignes = SV.lignes_lot(l["id"], _role())
    if lignes:
        feuilles = [n for n, v in lignes.items() if v]
        if feuilles:
            fe = st.pills("Lignes conservées", feuilles, default=feuilles[0], key=f"pl_{l['id']}") or feuilles[0]
            ui.tableau([{k: v for k, v in r.items()} for r in lignes[fe][:2000]],
                       {k: k for k in (["__line"] + S.FEUILLES[fe].colonnes)}, key=f"li_{l['id']}_{fe}")
    role, uid = _role(), (auth.utilisateur() or {}).get("id")
    if l["statut"] not in SV.STATUTS_PREPARES or role not in ("finance", "admin"):
        return
    motif = st.text_input("Motif / référence du rapprochement", key=f"motif_{l['id']}")
    c = ui.rangee(3)
    if l["statut"] == "Préparé" and role in ("finance", "admin") and uid != l["cree_par"]:
        if c[0].button("Valider (Finance)", key=f"vf_{l['id']}", type="primary"):
            _executer(SV.valider_finance, l["id"], motif, ok="Lot validé par Finance.")
    if l["statut"] == "Validé Finance" and role == "admin":
        if c[1].button("Activer (DG)", key=f"act_{l['id']}", type="primary"):
            _executer(SV.activer, l["id"], motif, ok="Lot activé : budgets, soldes et reliquats sont désormais effectifs.")
    if l["statut"] in SV.STATUTS_PREPARES and role in ("finance", "admin"):
        if c[2].button("Rejeter le lot", key=f"rej_{l['id']}"):
            _executer(SV.rejeter, l["id"], motif, ok="Lot rejeté : aucune donnée exécutée n’a été supprimée.")


def _executer(fn, *args, ok="Enregistré."):
    try:
        fn(*args)
    except ValueError as e:
        st.error(str(e))
    else:
        ui.succes(ok)


# ------------------------------------------------------------------ reliquats repris (Finance)
def _reliquats_tab() -> None:
    rows = [c for c in V.records("carryover") if c["data"]["type"] in ("debt", "advance", "commitment")
            and c["data"]["status"] == "Approuvée"]
    if not rows:
        st.caption("Aucun reliquat activé en attente.")
        return
    parties = db.tout("clients")
    tableau = []
    for c in rows:
        d = c["data"]
        reste = (d["amount"] - V._carry_paid(d)) if d["type"] == "debt" else V.carry_effects(c)["advance" if d["type"] == "advance" else "open"]
        tableau.append({"_id": c["id"], "ref": c["ref"], "n": V.CARRY_LABELS[d["type"]],
                        "t": R.name_of(parties, d.get("party", ""), "—"), "dev": c["currency"],
                        "rep": _montant(d["amount"], c["currency"]), "reste": _montant(reste, c["currency"]),
                        "ech": d.get("due", "")})
    i = ui.tableau(tableau, {"ref": "Référence", "n": "Nature", "t": "Tiers", "dev": "Devise", "rep": "Repris",
                             "reste": "Reste", "ech": "Échéance"}, key="imp_rel", selection=True)
    if i is None or not auth.modifie("tresorerie") and not auth.modifie("depenses"):
        return
    c = next(x for x in rows if x["id"] == tableau[i]["_id"])
    d = c["data"]
    st.caption("Archive : " + ", ".join(f"{k} = {v}" for k, v in (d.get("archive") or {}).items() if k != "paiements"))
    comptes = [a for a in V.records("account") if a["currency"] == c["currency"]]
    if d["type"] == "debt" and auth.modifie("tresorerie"):
        with st.form(f"pay_{c['id']}"):
            a = st.selectbox("Compte", [x["id"] for x in comptes], format_func=lambda k: next(x["ref"] for x in comptes if x["id"] == k))
            v = st.text_input("Montant", R.plain(d["amount"] - V._carry_paid(d)))
            dt_ = st.text_input("Date (AAAA-MM-JJ, à partir de la bascule)", R.today())
            ref = st.text_input("Référence du règlement")
            if st.form_submit_button("Régler le reliquat"):
                _executer(lambda: V.pay_carryover(c["id"], a, R.cents(v), dt_, ref), ok="Reliquat réglé.")
    if d["type"] == "advance":
        with st.form(f"piece_{c['id']}", clear_on_submit=True):
            f = st.file_uploader("Justificatif (PDF, JPEG, PNG)", type=["pdf", "jpg", "jpeg", "png"])
            v = st.text_input("Montant justifié", "0.00")
            dt_ = st.text_input("Date du document", R.today())
            if st.form_submit_button("Déposer"):
                _executer(lambda: V.upload_carryover_piece(c["id"], f.name if f else "", f.getvalue() if f else b"", dt_,
                                                           R.cents(v)), ok="Pièce déposée, à contrôler par une autre personne.")
        for j in [x for x in d["justifications"] if x["status"] == "Soumise"]:
            x, y = st.columns([3, 1])
            x.write(f"Pièce {j['piece'][:8]} · {R.money(j['amount'], c['currency'])}")
            if y.button("Accepter", key=f"ok_{j['piece']}"):
                _executer(V.validate_carryover_justification, c["id"], j["piece"], True, "Pièce contrôlée", ok="Justificatif accepté.")
        if auth.modifie("tresorerie") and comptes:
            with st.form(f"ret_{c['id']}"):
                a = st.selectbox("Compte de restitution", [x["id"] for x in comptes],
                                 format_func=lambda k: next(x["ref"] for x in comptes if x["id"] == k))
                v = st.text_input("Montant restitué", "0.00")
                dt_ = st.text_input("Date", R.today())
                ref = st.text_input("Référence")
                if st.form_submit_button("Enregistrer la restitution"):
                    _executer(lambda: V.return_carryover_advance(c["id"], a, R.cents(v), dt_, ref), ok="Restitution enregistrée.")
    if d["type"] == "commitment":
        motif = st.text_input("Motif (ex. remplacé par la demande N0 …)", key=f"cm_{c['id']}")
        if st.button("Solder l’engagement repris", key=f"cmb_{c['id']}"):
            _executer(V.close_commitment, c["id"], motif, ok="Engagement soldé : il n’est plus compté.")


def page() -> None:
    auth.exiger("imports")
    ui.en_tete("Centre de reprise et d’import", "Modèles Excel, contrôle préalable, confirmation et lots traçables.")
    onglets = st.tabs(["Nouvel import", "Lots", "Reliquats repris", "Aide"])
    with onglets[0]:
        if auth.modifie("imports"):
            bloc_import()
        else:
            ui.lecture_seule()
    with onglets[1]:
        _lots_tab()
    with onglets[2]:
        _reliquats_tab()
    with onglets[3]:
        for m, lib in S.MODES.items():
            st.markdown(f"**{lib}** — {S.EFFETS_MODE[m]}")
        st.markdown("Règles communes : fichiers .xlsx de "
                    f"{X.limites()['taille_fichier'] // (1024 * 1024)} Mo et {X.limites()['lignes']} lignes utiles au plus ; "
                    "pas de formules, de macros ni de cellules fusionnées ; dates AAAA-MM-JJ ; montants en Decimal puis "
                    "centimes ; aucune conversion entre devises. Un second chargement du même fichier restitue le lot "
                    "existant. Un lot activé ne se supprime pas : correction ou contre-passation contrôlée.")
        st.markdown("Couverture : " + " · ".join(f"{f.libelle} ({'actif' if any(S.FEUILLES[n].statut == 'réalisé' and len(S.FEUILLES[n].modes) > 1 for n in f.feuilles) else 'archives'})"
                                                  for k, f in S.FONCTIONS.items() if k != "globale"))
