"""Planning des chantiers : diagramme de Gantt (début → livraison), avancement et ligne « aujourd'hui »."""
from __future__ import annotations

import datetime as dt

import altair as alt
import pandas as pd
import streamlit as st

import auth
import composants as C
import erp
import nav
import regles as R
import ui
from vues.chantiers import ETAT_TEINTES

PERIODES = {"Tout": None, "3 mois": 91, "6 mois": 183, "12 mois": 365}


def _donnees(s: dict) -> tuple[list[dict], list[dict]]:
    """Chantiers datés (barres) et chantiers à compléter (sans début ou sans livraison)."""
    dates, incomplets = [], []
    aujourd_hui = dt.date.today()
    for p in s["projects"]:
        debut, fin = erp.periode_chantier(p)
        if not debut or not fin or fin < debut:
            incomplets.append(p)
            continue
        av = max(0.0, min(100.0, float(p["progress"] or 0)))
        avance = debut + dt.timedelta(days=round((fin - debut).days * av / 100))
        retard = fin < aujourd_hui and p["status"] != "Terminé"
        dates.append({"_id": p["id"], "chantier": p["name"], "client": R.client_name(s, p["client"]) or "—",
                      "etat": p["status"], "debut": debut, "fin": fin, "avance": avance, "avancement": f"{av:.0f} %",
                      "duree": f"{(fin - debut).days + 1} jours", "retard": "Oui" if retard else "Non",
                      "lieu": p.get("location") or ""})
    return dates, incomplets


def gantt(rows: list[dict], hauteur_ligne: int = 34):
    df = pd.DataFrame(rows)
    ordre = list(df.sort_values(["debut", "fin"])["chantier"])
    aujourd_hui = pd.Timestamp(dt.date.today())
    couleurs = alt.Scale(domain=list(ETAT_TEINTES), range=list(ETAT_TEINTES.values()))
    infos = [alt.Tooltip("chantier:N", title="Chantier"), alt.Tooltip("client:N", title="Client"),
             alt.Tooltip("etat:N", title="État"), alt.Tooltip("debut:T", title="Début", format="%d/%m/%Y"),
             alt.Tooltip("fin:T", title="Livraison", format="%d/%m/%Y"), alt.Tooltip("duree:N", title="Durée"),
             alt.Tooltip("avancement:N", title="Avancement"), alt.Tooltip("retard:N", title="En retard")]
    base = alt.Chart(df).encode(y=alt.Y("chantier:N", sort=ordre, title=None,
                                        axis=alt.Axis(labelLimit=240, labelFontSize=12, labelColor="#0f1a6e",
                                                      domain=False, ticks=False)))
    fond = base.mark_bar(cornerRadius=7, height={"band": 0.62}, opacity=0.28).encode(
        x=alt.X("debut:T", title=None, axis=alt.Axis(format="%b %Y", grid=True, gridColor="#eef1f7", labelColor="#5a6684")),
        x2="fin:T", color=alt.Color("etat:N", scale=couleurs, legend=None), tooltip=infos)
    fait = base.mark_bar(cornerRadius=7, height={"band": 0.62}).encode(
        x="debut:T", x2="avance:T", color=alt.Color("etat:N", scale=couleurs, legend=None), tooltip=infos)
    retard = base.transform_filter(alt.datum.retard == "Oui").mark_text(
        text="⚠ en retard", align="left", dx=6, color="#c92a2a", fontWeight="bold", fontSize=11).encode(x="fin:T")
    regle = alt.Chart(pd.DataFrame({"j": [aujourd_hui], "t": ["Aujourd’hui"]})).mark_rule(
        color="#e03131", strokeDash=[5, 4], size=2).encode(x="j:T")
    etiq = alt.Chart(pd.DataFrame({"j": [aujourd_hui], "t": ["Aujourd’hui"]})).mark_text(
        align="left", dx=4, dy=-6, color="#e03131", fontWeight="bold", fontSize=11).encode(
        x="j:T", y=alt.value(0), text="t:N")
    return (fond + fait + retard + regle + etiq).properties(height=max(140, hauteur_ligne * len(df) + 40)).configure_view(
        strokeWidth=0).configure_axis(labelFont="Inter, sans-serif")


def page() -> None:
    auth.exiger("chantiers")
    ecrit = auth.modifie("chantiers")
    s = R.charger("projects", "clients")
    ui.en_tete("Planning des chantiers", "Diagramme de Gantt : de la date de début à la livraison prévue, avec "
                                          "l’avancement réel en couleur pleine.")
    if not s["projects"]:
        st.info("Ajoutez des chantiers avec une date de début et une date de livraison pour voir le planning.")
        return
    rows, incomplets = _donnees(s)
    with st.container(horizontal=True, key="bg_cp_planning", gap="small", vertical_alignment="center"):
        etats = st.pills("États", list(ETAT_TEINTES), selection_mode="multi", default=["À démarrer", "En cours", "Suspendu"],
                         key="pl_etats", label_visibility="collapsed")
        periode = st.segmented_control("Période", list(PERIODES), default="Tout", key="pl_periode",
                                       label_visibility="collapsed") or "Tout"
        q = st.text_input("Rechercher", placeholder="Rechercher un chantier ou un client…", key="pl_q",
                          label_visibility="collapsed", width=280, icon=":material/search:")
    vus = C.filtrer(rows, q, ("chantier", "client", "lieu"), [], [])
    if etats:
        vus = [r for r in vus if r["etat"] in etats]
    if PERIODES[periode]:
        j = dt.date.today()
        fin_fenetre = j + dt.timedelta(days=PERIODES[periode])
        vus = [r for r in vus if r["fin"] >= j - dt.timedelta(days=30) and r["debut"] <= fin_fenetre]
    n_retard = sum(1 for r in vus if r["retard"] == "Oui")
    k = st.columns(3)
    with k[0]:
        ui.carte("Chantiers planifiés", str(len(vus)), f"sur {len(s['projects'])} chantier(s)", accent=True)
    with k[1]:
        ui.carte("En retard", str(n_retard), "livraison dépassée, non terminés")
    with k[2]:
        prochaine = min((r for r in vus if r["fin"] >= dt.date.today() and r["etat"] != "Terminé"),
                        key=lambda r: r["fin"], default=None)
        ui.carte("Prochaine livraison", prochaine["fin"].strftime("%d/%m/%Y") if prochaine else "—",
                 prochaine["chantier"] if prochaine else "")
    if vus:
        st.html('<div style="display:flex;gap:14px;flex-wrap:wrap;font-size:.85rem;color:#5a6684;margin:6px 0">' + "".join(
            f'<span><i style="display:inline-block;width:12px;height:12px;border-radius:3px;background:{c};margin-right:5px">'
            f'</i>{e}</span>' for e, c in ETAT_TEINTES.items()) + '<span>· barre pâle : durée prévue · barre pleine : '
            'avancement réel</span></div>')
        st.altair_chart(gantt(vus), width="stretch")
        def _ouvrir():
            if st.session_state.get("pl_ouvrir"):
                st.session_state["bg_fiche_ch"] = st.session_state["pl_ouvrir"]
                st.session_state["pl_go"] = True
            st.session_state["pl_ouvrir"] = ""
        st.selectbox("Ouvrir la fiche d’un chantier", [""] + [r["_id"] for r in vus], key="pl_ouvrir", on_change=_ouvrir,
                     format_func=lambda i: "Choisir un chantier…" if not i else next(
                         r["chantier"] for r in vus if r["_id"] == i))
        if st.session_state.pop("pl_go", None) and "chantiers" in nav.PAGES:
            nav.aller("chantiers")
    else:
        st.info("Aucun chantier daté ne correspond à ces critères.")
    if incomplets or ecrit:
        titre = (f"Compléter les dates ({len(incomplets)} chantier(s) sans dates complètes)" if incomplets
                 else "Modifier les dates des chantiers")
        with st.expander(titre, icon=":material/edit_calendar:", expanded=bool(incomplets) and not rows):
            if not ecrit:
                st.caption("Chantiers sans date de début ou de livraison : " + ", ".join(p["name"] for p in incomplets))
            else:
                cibles = sorted(s["projects"], key=lambda p: (bool(erp.periode_chantier(p)[0]), p["name"].lower()))
                df = pd.DataFrame([{"id": p["id"], "Chantier": p["name"], "Début": erp.periode_chantier(p)[0],
                                    "Livraison prévue": erp.periode_chantier(p)[1]} for p in cibles])
                ed = st.data_editor(df, key="pl_dates", hide_index=True, width="stretch", disabled=["id", "Chantier"],
                                    column_order=["Chantier", "Début", "Livraison prévue"], column_config={
                                        "Début": st.column_config.DateColumn("Début", format="DD/MM/YYYY"),
                                        "Livraison prévue": st.column_config.DateColumn("Livraison prévue",
                                                                                         format="DD/MM/YYYY")})
                if st.button("Enregistrer les dates", type="primary", icon=":material/save:"):
                    def iso(v):
                        return "" if v is None or pd.isna(v) else pd.Timestamp(v).date().isoformat()
                    try:
                        n = erp.enregistrer_dates({r["id"]: (iso(r["Début"]), iso(r["Livraison prévue"]))
                                                   for r in ed.to_dict("records")})
                    except ValueError as e:
                        st.error(str(e))
                    else:
                        ui.succes(f"{n} chantier(s) mis à jour." if n else "Aucune date modifiée.")
