"""Mon tableau de bord : chaque utilisateur choisit ses indicateurs, graphiques et listes, et leur ordre."""
from __future__ import annotations

import datetime as dt
from typing import Callable

import altair as alt
import pandas as pd
import streamlit as st

import auth
import db
import erp
import regles as R
import ui

COUL_DEVISES = {"USD": "#1a27b5", "CDF": "#ff9f1c", "EUR": "#12b886"}


def legende(couleurs: dict[str, str]) -> None:
    """Légende en HTML sous le graphique (la légende Vega en haut écrase le graphique dans Streamlit)."""
    st.html('<div style="display:flex;gap:14px;flex-wrap:wrap;font-size:.82rem;color:#5a6684">' + "".join(
        f'<span><i style="display:inline-block;width:10px;height:10px;border-radius:3px;background:{c};margin-right:5px">'
        f'</i>{ui._esc(k)}</span>' for k, c in couleurs.items()) + "</div>")


AXE = alt.Axis(labelColor="#5a6684", titleColor="#5a6684", gridColor="#eef1f7", domain=False, ticks=False)


class Donnees:
    """Chargement paresseux : chaque collection n'est lue qu'une fois par affichage."""

    def __init__(self) -> None:
        self._c: dict = {}

    def __getitem__(self, nom: str):
        if nom not in self._c:
            self._c[nom] = db.tout(nom)
        return self._c[nom]

    @property
    def s(self) -> dict:
        return {"clients": self["clients"], "projects": self["projects"]}


def _mois(d: str) -> str:
    return str(d or "")[:7]


def _ce_mois() -> str:
    return dt.date.today().isoformat()[:7]


# ------------------------------------------------------------------ indicateurs
def k_chantiers(d: Donnees) -> None:
    enc = [p for p in d["projects"] if p["status"] == "En cours"]
    ret = [p for p in enc if p["deadline"] and p["deadline"] < R.today()]
    ui.carte("Chantiers en cours", str(len(enc)), f"{len(ret)} en retard de livraison", accent=True)


def k_avancement(d: Donnees) -> None:
    enc = [p for p in d["projects"] if p["status"] == "En cours"]
    moy = sum(float(p["progress"] or 0) for p in enc) / len(enc) if enc else 0
    ui.carte("Avancement moyen", f"{moy:.0f} %", "des chantiers en cours")


def k_creances(d: Donnees) -> None:
    t = R.totals_by_currency(d["invoices"], lambda x: R.total(x) - x["paid"])
    ui.carte("Reste à encaisser", ui.montants_texte(t, True), f"{sum(1 for x in d['invoices'] if R.total(x) > x['paid'])}"
             " facture(s) non soldée(s)")


def k_facture_mois(d: Donnees) -> None:
    f = [x for x in d["invoices"] if _mois(x["date"]) == _ce_mois()]
    ui.carte("Facturé ce mois", ui.montants_texte(R.totals_by_currency(f, R.total), True), f"{len(f)} facture(s)")


def k_pipeline(d: Donnees) -> None:
    ouv = [p for p in d["crm_pistes"] if p["etape"] not in ("Gagné", erp.PERDU)]
    t: dict[str, int] = {}
    for p in ouv:
        t[p["devise"]] = t.get(p["devise"], 0) + erp.montant_pondere(p)
    ui.carte("Pipeline CRM pondéré", ui.montants_texte(t, True), f"{len(ouv)} piste(s) ouverte(s)")


def k_depenses_mois(d: Donnees) -> None:
    e = [x for x in d["expenses"] if _mois(x["date"]) == _ce_mois()]
    ui.carte("Dépenses du mois", ui.montants_texte(R.totals_by_currency(e, lambda x: x["amount"]), True),
             f"{len(e)} dépense(s)")


def k_personnel(d: Donnees) -> None:
    act = [p for p in d["personnel"] if p["active"]]
    ch = sum(1 for p in act if p["location"] == "Chantier")
    ui.carte("Personnel actif", str(len(act)), f"dont {ch} sur chantier")


def k_activites(d: Donnees) -> None:
    n = erp.rappels(auth.utilisateur()["id"])
    ui.carte("Mes activités", f"{n['En retard']} en retard", f"{n['Aujourd’hui']} pour aujourd’hui")


# ------------------------------------------------------------------ graphiques
def g_depenses(d: Donnees) -> None:
    debut = (dt.date.today().replace(day=1) - dt.timedelta(days=150)).isoformat()[:7]
    rows: dict[tuple[str, str], int] = {}
    for x in d["expenses"]:
        if _mois(x["date"]) >= debut:
            k = (_mois(x["date"]), x["currency"])
            rows[k] = rows.get(k, 0) + x["amount"]
    if not rows:
        st.caption("Aucune dépense sur les 6 derniers mois.")
        return
    df = pd.DataFrame([{"Mois": m, "Monnaie": c, "Montant": v / 100} for (m, c), v in sorted(rows.items())])
    st.altair_chart(alt.Chart(df).mark_bar(cornerRadiusTopLeft=5, cornerRadiusTopRight=5).encode(
        x=alt.X("Mois:N", axis=AXE, title=None), xOffset="Monnaie:N",
        y=alt.Y("Montant:Q", axis=AXE, title=None),
        color=alt.Color("Monnaie:N", scale=alt.Scale(domain=R.CURRENCIES, range=list(COUL_DEVISES.values())),
                        legend=None),
        tooltip=["Mois", "Monnaie", alt.Tooltip("Montant:Q", format=",.2f")]).properties(height=230), width="stretch")
    legende({c: COUL_DEVISES[c] for c in sorted({c for _, c in rows})})


def g_pipeline(d: Donnees) -> None:
    ordre = erp.ETAPES_CRM + [erp.PERDU]
    rows = [{"Étape": e, "Pistes": sum(1 for p in d["crm_pistes"] if p["etape"] == e)} for e in ordre]
    if not any(r["Pistes"] for r in rows):
        st.caption("Aucune piste dans le CRM.")
        return
    st.altair_chart(alt.Chart(pd.DataFrame(rows)).mark_bar(cornerRadiusTopRight=5, cornerRadiusBottomRight=5).encode(
        y=alt.Y("Étape:N", sort=ordre, axis=AXE, title=None),
        x=alt.X("Pistes:Q", axis=alt.Axis(labelColor="#5a6684", gridColor="#eef1f7", domain=False, ticks=False,
                                          format="d", tickMinStep=1), title=None),
        color=alt.Color("Étape:N", sort=ordre, legend=None, scale=alt.Scale(
            domain=ordre, range=["#3d5afe", "#22b8cf", "#ff9f1c", "#7048e8", "#12b886", "#adb5bd"])),
        tooltip=["Étape", "Pistes"]).properties(height=220), width="stretch")


def g_avancement(d: Donnees) -> None:
    enc = [p for p in d["projects"] if p["status"] in ("En cours", "Suspendu")]
    if not enc:
        st.caption("Aucun chantier en cours.")
        return
    df = pd.DataFrame([{"Chantier": p["name"], "Avancement": float(p["progress"] or 0), "État": p["status"]} for p in enc])
    st.altair_chart(alt.Chart(df).mark_bar(cornerRadiusTopRight=5, cornerRadiusBottomRight=5).encode(
        y=alt.Y("Chantier:N", sort="-x", axis=AXE, title=None),
        x=alt.X("Avancement:Q", scale=alt.Scale(domain=[0, 100]), axis=AXE, title="%"),
        color=alt.Color("État:N", scale=alt.Scale(domain=["En cours", "Suspendu"], range=["#ff9f1c", "#f0507a"]),
                        legend=None),
        tooltip=["Chantier", "État", alt.Tooltip("Avancement:Q", format=".0f")]).properties(
        height=max(140, 30 * len(df))), width="stretch")
    legende({"En cours": "#ff9f1c", "Suspendu": "#f0507a"})


# ------------------------------------------------------------------ listes
def l_activites(d: Donnees) -> None:
    acts = erp.activites(auth.utilisateur()["id"])[:8]
    if not acts:
        st.caption("Aucune activité à venir.")
        return
    ui.tableau([{"e": a["echeance"], "t": f"{a['type']} · {a['resume']}", "f": a["libelle"] or "—",
                 "s": erp.echeance_etat(a["echeance"])} for a in acts],
               {"e": "Échéance", "t": "Activité", "f": "Fiche", "s": "État"}, key="tdb_act")


def l_impayees(d: Donnees) -> None:
    f = sorted([x for x in d["invoices"] if R.total(x) > x["paid"]], key=lambda x: x["due"] or x["date"])[:8]
    if not f:
        st.caption("Toutes les factures sont réglées.")
        return
    cl = {c["id"]: c["name"] for c in d["clients"]}
    ui.tableau([{"n": x["number"], "c": cl.get(x["client"], ""), "e": x["due"] or "—",
                 "r": R.money(R.total(x) - x["paid"], x["currency"])} for x in f],
               {"n": "Facture", "c": "Client", "e": "Échéance", "r": "Reste"}, key="tdb_imp")


def l_retard(d: Donnees) -> None:
    r = [p for p in d["projects"] if p["deadline"] and p["deadline"] < R.today() and p["status"] != "Terminé"]
    if not r:
        st.caption("Aucun chantier en retard.")
        return
    ui.tableau([{"n": p["name"], "e": p["deadline"], "a": f"{float(p['progress']):.0f} %", "s": p["status"]} for p in r],
               {"n": "Chantier", "e": "Livraison prévue", "a": "Avancement", "s": "État"}, key="tdb_ret")


def l_devis(d: Donnees) -> None:
    q = [x for x in d["quotes"] if x["status"] == "Envoyé"]
    if not q:
        st.caption("Aucun devis en attente de réponse.")
        return
    cl = {c["id"]: c["name"] for c in d["clients"]}
    ui.tableau([{"n": x["number"], "c": cl.get(x["client"], ""), "d": x["date"], "t": R.money(R.total(x), x["currency"])}
                for x in sorted(q, key=lambda x: x["date"])], {"n": "Devis", "c": "Client", "d": "Envoyé le", "t": "Total"},
               key="tdb_dev")


# id : (titre, module requis, genre, fonction)
WIDGETS: dict[str, tuple[str, str, str, Callable[[Donnees], None]]] = {
    "k_chantiers": ("Chantiers en cours", "chantiers", "kpi", k_chantiers),
    "k_avancement": ("Avancement moyen", "chantiers", "kpi", k_avancement),
    "k_creances": ("Reste à encaisser", "commercial", "kpi", k_creances),
    "k_facture_mois": ("Facturé ce mois", "commercial", "kpi", k_facture_mois),
    "k_pipeline": ("Pipeline CRM pondéré", "commercial", "kpi", k_pipeline),
    "k_depenses_mois": ("Dépenses du mois", "depenses", "kpi", k_depenses_mois),
    "k_personnel": ("Personnel actif", "personnel", "kpi", k_personnel),
    "k_activites": ("Mes activités (rappels)", "accueil", "kpi", k_activites),
    "g_avancement": ("Graphique : avancement des chantiers", "chantiers", "bloc", g_avancement),
    "g_pipeline": ("Graphique : pipeline CRM par étape", "commercial", "bloc", g_pipeline),
    "g_depenses": ("Graphique : dépenses des 6 derniers mois", "depenses", "bloc", g_depenses),
    "l_activites": ("Liste : mes prochaines activités", "accueil", "bloc", l_activites),
    "l_impayees": ("Liste : factures non réglées", "commercial", "bloc", l_impayees),
    "l_retard": ("Liste : chantiers en retard", "chantiers", "bloc", l_retard),
    "l_devis": ("Liste : devis en attente", "commercial", "bloc", l_devis),
}
DEFAUT = ["k_chantiers", "k_creances", "k_depenses_mois", "k_activites", "g_avancement", "g_pipeline", "l_activites",
          "l_impayees"]


def disponibles() -> list[str]:
    return [k for k, (_, m, _, _) in WIDGETS.items() if auth.voit(m)]


def choix_utilisateur(uid: int) -> tuple[list[str], int]:
    dispo = disponibles()
    p = erp.prefs_tableau(uid) or {}
    liste = [w for w in (p.get("widgets") or DEFAUT) if w in dispo]
    return liste, int(p.get("colonnes") or 2)


def page() -> None:
    auth.exiger("accueil")
    u = auth.utilisateur()
    widgets, colonnes = choix_utilisateur(u["id"])
    ui.en_tete("Mon tableau de bord", "Vos indicateurs, graphiques et listes, dans l’ordre que vous choisissez.",
               badge=dt.date.today().strftime("%d/%m/%Y"))
    with st.expander("Personnaliser mon tableau de bord", icon=":material/tune:"):
        dispo = disponibles()
        with st.form("tdb_prefs"):
            choix = st.multiselect("Éléments affichés (dans l’ordre de sélection)", dispo, default=widgets,
                                   format_func=lambda k: WIDGETS[k][0])
            cols = st.radio("Colonnes pour les graphiques et listes", [1, 2, 3], index=[1, 2, 3].index(colonnes),
                            horizontal=True)
            a, b = st.columns(2)
            ok = a.form_submit_button("Enregistrer", type="primary", icon=":material/save:")
            raz = b.form_submit_button("Rétablir le tableau par défaut", icon=":material/restart_alt:")
        if ok:
            erp.enregistrer_prefs_tableau(u["id"], choix, cols)
            ui.succes("Tableau de bord enregistré.")
        if raz:
            erp.enregistrer_prefs_tableau(u["id"], [w for w in DEFAUT if w in dispo], 2)
            ui.succes("Tableau de bord par défaut rétabli.")
    if not widgets:
        st.info("Votre tableau de bord est vide : ouvrez « Personnaliser » et choisissez des éléments.")
        return
    d = Donnees()
    kpis = [w for w in widgets if WIDGETS[w][2] == "kpi"]
    blocs = [w for w in widgets if WIDGETS[w][2] == "bloc"]
    for debut in range(0, len(kpis), 4):
        cols = st.columns(4)
        for col, w in zip(cols, kpis[debut:debut + 4]):
            with col:
                _rendre(w, d)
    for debut in range(0, len(blocs), colonnes):
        cols = st.columns(colonnes, gap="medium")
        for col, w in zip(cols, blocs[debut:debut + colonnes]):
            with col, st.container(border=True):
                t = WIDGETS[w][0].split(" : ", 1)[-1]
                st.markdown(f"**{t[:1].upper() + t[1:]}**")
                _rendre(w, d)


def _rendre(w: str, d: Donnees) -> None:
    try:
        WIDGETS[w][3](d)
    except Exception as e:  # noqa: BLE001  (un élément en panne ne doit pas masquer les autres)
        st.caption(f"Élément indisponible ({type(e).__name__}).")
