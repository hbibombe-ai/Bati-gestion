"""Taux du jour (USD/CDF, EUR/USD), convertisseur et trésorerie consolidée.

Les montants restent enregistrés dans leur devise ; la conversion sert à l'affichage des totaux consolidés."""
from __future__ import annotations

import datetime as dt

import streamlit as st

import auth
import devises as DV
import gestion_v7 as V
import regles as R
import ui


def _peut_saisir() -> bool:
    return auth.modifie("tresorerie") or auth.modifie("comptabilite")


def _etat() -> None:
    cols = st.columns(len(DV.PAIRES_SAISIE))
    for col, e in zip(cols, DV.etat_du_jour()):
        with col:
            if e["taux"] is None:
                ui.carte(f"Taux {e['paire']}", "—", "Aucun taux saisi", accent=True)
            else:
                note = f"Taux du {DV._date_fr(e['date'])}" + ("" if e["du_jour"] else
                                                              " — à mettre à jour" if e["ancien"] else " — pas encore saisi aujourd’hui")
                ui.carte(f"Taux {e['paire']}", ui._esc(e["libelle"]), note, accent=e["ancien"])


def _saisie() -> None:
    st.markdown("**Saisir les taux du jour**")
    st.caption("Taux BCC ou taux effectivement pratiqué. Une nouvelle saisie le même jour corrige le taux ; la "
               "correction reste tracée.")
    with st.form("taux_du_jour"):
        date_ = st.date_input("Date", value=dt.date.today(), max_value=dt.date.today(), format="DD/MM/YYYY")
        cols = st.columns(len(DV.PAIRES_SAISIE))
        valeurs = {}
        for col, (s, c) in zip(cols, DV.PAIRES_SAISIE):
            valeurs[(s, c)] = col.text_input(f"1 {s} = … {c}", placeholder="ex. 2850" if c == "CDF" else "ex. 1,08")
        note = st.text_input("Source ou remarque", placeholder="ex. BCC, cours indicatif du jour")
        ok = st.form_submit_button("Enregistrer", type="primary")
    if ok:
        saisis, erreurs = [], []
        for (s, c), v in valeurs.items():
            if not (v or "").strip():
                continue
            try:
                DV.saisir_taux(s, c, v, date_.isoformat(), note)
                saisis.append(f"{s}/{c}")
            except ValueError as e:
                erreurs.append(f"{s}/{c} : {e}")
        if erreurs:
            st.error(" ; ".join(erreurs))
        elif not saisis:
            st.warning("Aucun taux saisi.")
        else:
            ui.succes(f"Taux enregistré(s) : {', '.join(saisis)}.")


def _convertisseur() -> None:
    st.markdown("**Convertisseur**")
    a, b, c, d = st.columns(4)
    montant = a.text_input("Montant", "100", key="cv_m")
    source = b.selectbox("De", R.CURRENCIES, key="cv_s")
    cible = c.selectbox("Vers", R.CURRENCIES, index=1, key="cv_c")
    with d:
        date_ = ui.date_txt("Au taux du", "cv_d")
    try:
        cents = R.cents(montant)
    except ValueError as e:
        st.error(str(e))
        return
    t = DV.taux(source, cible, date_)
    if t is None:
        st.warning(f"Aucun taux {source} → {cible} connu à cette date.")
    else:
        st.markdown(f"**{R.money(cents, source)} ≈ {R.money(DV.convertir(cents, source, cible, date_), cible)}**")
        st.caption((t["libelle"] or "Même devise") + (f" · taux du {DV._date_fr(t['date'])}" if t["libelle"] else "")
                   + (f" · via {t['pivot']}" if t["pivot"] else ""))


def _tresorerie() -> None:
    comptes = V.records("account")
    if not comptes:
        return
    st.markdown("**Trésorerie du circuit V7, consolidée au dernier taux**")
    totaux: dict[str, int] = {}
    lignes = []
    for a in comptes:
        solde = V.balance(a)
        totaux[a["currency"]] = totaux.get(a["currency"], 0) + solde
        lignes.append({"Compte": a["ref"], "Libellé": a["data"].get("label", ""), "Solde": R.money(solde, a["currency"])})
    st.dataframe(lignes, hide_index=True, width="stretch")
    st.markdown(ui.montants_texte(totaux, True, consolide_aussi=True))
    st.caption("Indicatif : aucun mouvement n’est converti en base. Pour un état daté et justifié, utilisez la "
               "consolidation à taux explicites du circuit V7.")


def _historique() -> None:
    rows = sorted(V.records("rate"), key=lambda r: (r["data"].get("date", ""), r["ref"]), reverse=True)[:120]
    if not rows:
        st.info("Aucun taux enregistré.")
        return
    st.dataframe([{"Date": DV._date_fr(r["data"].get("date", "")), "Paire": f"{r['currency']}/{r['data'].get('target')}",
                   "Taux": DV._fmt(r["data"]["rate"]), "Saisi par": r["data"].get("saisi_nom", ""),
                   "Corrections": len(r["data"].get("corrige") or []), "Source": r["data"].get("note", ""),
                   "Référence": r["ref"]} for r in rows], hide_index=True, width="stretch")


def _reglages() -> None:
    reg = DV.reglages()
    with st.form("taux_reglages"):
        a, b = st.columns(2)
        devise = a.selectbox("Devise des totaux consolidés", R.CURRENCIES, index=R.CURRENCIES.index(reg["devise"]),
                             format_func=lambda c: R.CURRENCY_LABELS[c])
        anciennete = b.number_input("Signaler un taux plus ancien que (jours)", min_value=0, max_value=365,
                                    value=reg["anciennete_jours"], step=1)
        ok = st.form_submit_button("Enregistrer les réglages")
    if ok:
        try:
            DV.configurer(devise, int(anciennete))
        except ValueError as e:
            st.error(str(e))
        else:
            ui.succes("Réglages enregistrés.")


def page() -> None:
    if not (auth.voit("tresorerie") or auth.voit("comptabilite")):
        st.error("Votre rôle ne donne pas accès à cette rubrique.")
        st.stop()
    ui.en_tete("Taux de change", "Taux du jour et totaux consolidés. Les écritures restent tenues dans leur devise.")
    _etat()
    if _peut_saisir():
        with st.container(border=True):
            _saisie()
    with st.container(border=True):
        _convertisseur()
    _tresorerie()
    with st.expander("Historique des taux", icon=":material/history:"):
        _historique()
    if _peut_saisir():
        with st.expander("Réglages", icon=":material/settings:"):
            _reglages()
