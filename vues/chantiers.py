"""Chantiers : budget, avancement, décaissements par monnaie."""
from __future__ import annotations

import streamlit as st

import auth
import db
import gestion_v7 as V
import regles as R
import ui


def decaissements(s: dict, pid: str) -> dict[str, int]:
    """Dépenses + versements fournisseurs non contrepassés (avances incluses), par monnaie."""
    sup = [p for p in s.get("supplier_payments", []) if not R.supplier_reversed(s, p["id"])]
    totals = R.totals_by_currency([e for e in s["expenses"] + sup if e["project"] == pid], lambda e: e["amount"])
    for r in V.records("operation"):
        if r["project"] == pid:
            d = r["data"]
            totals[r["currency"]] += sum(p["amount"] for p in d["payments"] if not p.get("reversed")) - sum(p["amount"] for p in d["returns"])
    return totals


def lignes(s: dict, projets: list[dict]) -> list[dict]:
    out = []
    for p in projets:
        t = decaissements(s, p["id"])
        spent = t[p["currency"]]
        autres = [R.money(v, c) for c, v in t.items() if v and c != p["currency"]]
        b = next((b for b in V.records("budget") if b["project"] == p["id"]), None)
        m = V.metrics(b, V.records("operation")) if b else None
        budget = m["budget"] if m else p["budget"]
        ecart = m["available"] if m else budget - spent
        out.append({"_id": p["id"], "nom": p["name"], "client": R.client_name(s, p["client"]), "statut": p["status"],
                    "echeance": p["deadline"] or "", "avancement": float(p["progress"]),
                    "budget": R.money(budget, p["currency"]),
                    "depense": R.money(spent, p["currency"]) + (" + " + " + ".join(autres) if autres else ""),
                    "reste": ("Dépassement : " if ecart < 0 else "Disponible : ") + R.money(abs(ecart), p["currency"])})
    return out


KINSHASA = (-4.3317, 15.3139)
COULEURS_ETAT = {"En cours": [255, 159, 28], "À démarrer": [61, 90, 254], "Suspendu": [240, 80, 122],
                 "Terminé": [18, 184, 134]}


def lire_gps(texte: str) -> tuple[float | None, float | None]:
    """« -4.3317, 15.3139 » (copié depuis Google Maps) → (latitude, longitude) ; vide → (None, None)."""
    t = (texte or "").strip()
    if not t:
        return None, None
    morceaux = [m for m in t.replace(";", ",").replace(" ", ",").split(",") if m]
    if len(morceaux) != 2:
        raise ValueError("Coordonnées GPS : indiquez la latitude et la longitude, par exemple -4.3317, 15.3139.")
    try:
        lat, lon = float(morceaux[0]), float(morceaux[1])
    except ValueError:
        raise ValueError("Coordonnées GPS : utilisez des nombres avec un point décimal, par exemple -4.3317, 15.3139.")
    if not (-14 <= lat <= 6 and 11 <= lon <= 32):
        raise ValueError("Coordonnées GPS hors de la RDC : vérifiez l’ordre (latitude d’abord, puis longitude).")
    return round(lat, 6), round(lon, 6)


def texte_gps(p: dict) -> str:
    return f"{p['latitude']}, {p['longitude']}" if p.get("latitude") is not None and p.get("longitude") is not None else ""


def carte(s: dict, projets: list[dict], hauteur: int = 430) -> None:
    """Carte des chantiers géolocalisés, couleur selon l’état, avec le compteur des chantiers en cours."""
    import pydeck as pdk
    points = [p for p in projets if p.get("latitude") is not None and p.get("longitude") is not None]
    n_cours = sum(1 for p in projets if p["status"] == "En cours")
    legende = "".join(f'<span class="bg-legende"><i style="background:rgb({c[0]},{c[1]},{c[2]})"></i>{ui._esc(e)}</span>'
                      for e, c in COULEURS_ETAT.items())
    st.html(f'<div class="bg-carte-tete"><div class="g">{legende}</div><span class="bg-compteur"><i></i>'
            f'{n_cours} chantier{"s" if n_cours > 1 else ""} en cours</span></div>')
    if not points:
        st.caption("Aucun chantier n’a encore de coordonnées GPS. Ouvrez un chantier, puis « Modifier ce chantier » "
                   "pour les ajouter.")
    donnees = [{"nom": p["name"], "client": R.client_name(s, p["client"]) or "—", "etat": p["status"],
                "lieu": p.get("location") or "—", "avancement": f"{float(p['progress']):.0f} %",
                "lat": p["latitude"], "lon": p["longitude"], "couleur": COULEURS_ETAT.get(p["status"], [90, 102, 132]),
                "halo": COULEURS_ETAT.get(p["status"], [90, 102, 132]) + [60]} for p in points]
    if points:
        lat = sum(p["latitude"] for p in points) / len(points)
        lon = sum(p["longitude"] for p in points) / len(points)
        ecart = max(max(abs(p["latitude"] - lat), abs(p["longitude"] - lon)) for p in points)
        zoom = 12 if ecart < .03 else 11 if ecart < .1 else 10 if ecart < .25 else 8 if ecart < 1 else 6
    else:
        (lat, lon), zoom = KINSHASA, 10.5
    couches = [
        pdk.Layer("ScatterplotLayer", donnees, get_position="[lon, lat]", get_fill_color="halo", get_radius=420,
                  radius_min_pixels=14, radius_max_pixels=30, pickable=False),
        pdk.Layer("ScatterplotLayer", donnees, get_position="[lon, lat]", get_fill_color="couleur", get_radius=160,
                  radius_min_pixels=7, radius_max_pixels=14, stroked=True, get_line_color=[255, 255, 255],
                  line_width_min_pixels=2, pickable=True),
    ]
    st.pydeck_chart(pdk.Deck(layers=couches, initial_view_state=pdk.ViewState(latitude=lat, longitude=lon, zoom=zoom),
                             map_style="light",
                             tooltip={"html": "<b>{nom}</b><br/>{client}<br/>{lieu}<br/>État : {etat} · {avancement}",
                                      "style": {"backgroundColor": "#0f1a6e", "color": "white", "fontSize": "13px",
                                                "borderRadius": "8px"}}),
                    height=hauteur, key=f"carte_{hauteur}_{len(points)}")


COLONNES = {
    "nom": "Chantier", "client": "Client", "statut": "État", "echeance": "Échéance",
    "avancement": st.column_config.ProgressColumn("Avancement", min_value=0, max_value=100, format="%.0f %%"),
    "budget": "Budget", "depense": "Décaissements (avances incluses)", "reste": "Disponible à engager V7 ou solde historique",
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
    gps = a.text_input("Coordonnées GPS (facultatif)", value=texte_gps(p), placeholder="-4.3317, 15.3139",
                       help="Dans Google Maps, faites un appui long sur le chantier : les deux nombres affichés "
                            "(latitude, longitude) se copient ici. Ils placent le chantier sur la carte.")
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
            latitude, longitude = lire_gps(gps)
            rec = {"name": nom.strip(), "client": cli or "", "location": lieu.strip(), "deadline": echeance,
                   "latitude": latitude, "longitude": longitude,
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
    s = R.charger("projects", "clients", "expenses", "supplier_payments", "supplier_reversals", "invoices",
                  "personnel")
    n = sum(1 for p in s["projects"] if p["status"] == "En cours")
    ui.en_tete("Chantiers", "Budgets, avancement et dépenses par chantier.",
               badge=f"{n} chantier{'s' if n > 1 else ''} en cours")
    ecrit = auth.modifie("chantiers")
    if ecrit and st.button("Nouveau chantier", type="primary", icon=":material/add:"):
        formulaire()
    if ecrit:
        from vues import imports as IMP
        IMP.encart(["chantiers"], "Importer des chantiers depuis Excel")
    if not s["projects"]:
        st.info("Organisez vos travaux : ajoutez un premier chantier, son client et son budget.")
        return
    filtre = st.pills("État", R.STATUSES, selection_mode="multi", default=None, key="ch_filtre")
    projets = [p for p in s["projects"] if not filtre or p["status"] in filtre]
    st.subheader("Carte des chantiers")
    carte(s, projets)
    rows = lignes(s, projets)
    i = ui.tableau(rows, COLONNES, key="tab_chantiers", selection=True)
    if i is None:
        st.caption("Sélectionnez un chantier dans le tableau pour l'ouvrir ou le modifier.")
        return
    p = next(x for x in s["projects"] if x["id"] == rows[i]["_id"])
    st.subheader(p["name"])
    ui.pieces_jointes("chantiers", p["id"], peut_ajouter=ecrit)
    if ecrit and st.button("Modifier ce chantier", icon=":material/edit:"):
        formulaire(p["id"])
    a, b, c = st.columns(3)
    a.markdown(f"**Client :** {R.client_name(s, p['client'])}  \n**Lieu :** {p['location'] or '—'}  \n"
               f"**Échéance :** {p['deadline'] or 'Non précisée'}  \n**État :** {p['status']}  \n"
               f"**GPS :** {texte_gps(p) or 'non renseigné'}")
    managed = next((x for x in V.records("budget") if x["project"] == p["id"]), None)
    if managed:
        st.info("Budget DQE et engagements disponibles dans Circuit financier V7. Le budget historique ci-dessous reste une référence antérieure.")
    b.markdown(f"**Budget historique :** {R.money(p['budget'], p['currency'])}  \n**Décaissements :** "
               f"{ui.montants_texte(decaissements(s, p['id']), True, consolide_aussi=True)}")
    if auth.voit("commercial"):
        fac = [x for x in s["invoices"] if x["project"] == p["id"]]
        c.markdown("**Facturé :** " + ui.montants_texte(R.totals_by_currency(fac, R.total), True, consolide_aussi=True) + "  \n**Reste à "
                   "encaisser :** " + ui.montants_texte(R.totals_by_currency(fac, lambda x: R.total(x) - x["paid"]), True, consolide_aussi=True))
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
