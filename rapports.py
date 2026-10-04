"""Rapports et alertes : échéances à surveiller et prévision de trésorerie par monnaie."""
from __future__ import annotations

import streamlit as st

import auth
import regles as R
import ui


def page() -> None:
    auth.exiger("rapports")
    ui.en_tete("Rapports et alertes", "Échéances à surveiller et prévisions par monnaie.")
    s = R.charger()
    auj = R.today()
    alertes = R.erp_alerts(s, auj, avec_rh=auth.voit("personnel"))
    st.subheader(f"Échéances et alertes ({len(alertes)})")
    if alertes:
        ui.tableau([{"a": a["reason"], "t": a["kind"], "r": a["label"], "d": a["date"]} for a in alertes],
                   {"a": "Alerte", "t": "Type", "r": "Référence", "d": "Échéance"}, key="tab_alertes")
    else:
        st.success("Aucune alerte dans les données enregistrées.")
    st.subheader("Prévision de trésorerie à partir des factures")
    st.caption(f"Situation au {auj}. Soldes actuels des factures enregistrées, y compris les brouillons. Les échéances "
               "passées et les dates manquantes sont présentées séparément. Les paies, taxes et commandes ne sont pas "
               "encore intégrées.")
    prev = R.erp_forecast(s, auj)
    for c in R.CURRENCIES:
        r = prev[c]
        if not any([r["balance"], r["overdueIn"], r["overdueOut"], r["undatedIn"]] +
                   [h["incoming"] or h["outgoing"] for h in r["horizons"].values()]):
            continue
        st.markdown(f"#### {c}")
        st.markdown(f"Trésorerie enregistrée : **{R.money(r['balance'], c)}**  \nCréances échues : "
                    f"{R.money(r['overdueIn'], c)} · Dettes échues : {R.money(r['overdueOut'], c)}  \n"
                    f"Créances sans échéance : {R.money(r['undatedIn'], c)}")
        ui.tableau([{"h": f"{d} jours", "e": R.money(h["incoming"], c), "p": R.money(h["outgoing"], c),
                     "s": R.money(r["balance"] + h["incoming"] - h["outgoing"], c)} for d, h in r["horizons"].items()],
                   {"h": "Horizon cumulé", "e": "À encaisser", "p": "À payer", "s": "Solde indicatif"}, key=f"prev_{c}")
    st.caption("Le solde indicatif suppose le règlement à l’échéance des factures futures. Les impayés antérieurs sont "
               "exclus de cette projection. Les mouvements sans compte précisé sont exclus. Aucune conversion de devises.")
