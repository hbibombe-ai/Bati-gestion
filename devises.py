"""Taux du jour et affichage consolidé multi-devises.

Les écritures restent tenues dans leur devise (USD, CDF, EUR), sans conversion : rien n'est modifié en base par ce
module. Il ajoute :
- la saisie quotidienne des taux par la finance (registre des taux historiques V7, type « rate ») ;
- la recherche du dernier taux connu à une date (taux direct, inverse ou via une devise pivot) ;
- un total consolidé, affiché à côté des totaux par devise, avec le taux et sa date.

Convention d'un taux : « 1 unité de la devise d'origine vaut <taux> unités de la devise cible »
(ex. USD → CDF : 2 850 ; EUR → USD : 1,08).
"""
from __future__ import annotations

import datetime as dt
import time
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import sqlalchemy as sa

import db
import gestion_v7 as V
import regles as R

PAIRES_SAISIE = (("USD", "CDF"), ("EUR", "USD"))   # paires proposées à la saisie quotidienne
ANCIENNETE_DEFAUT = 3                                # jours au-delà desquels un taux est signalé ancien
_CACHE: dict = {"t": 0.0, "rows": None}
_TTL = 15.0


# ------------------------------------------------------------------ réglages
def reglages(tx=None) -> dict:
    if tx is not None:
        v = tx.cx.execute(sa.select(db.settings.c.valeur).where(db.settings.c.cle == "devises_consolidation")).scalar()
    else:
        v = db.parametre("devises_consolidation")
    v = v if isinstance(v, dict) else {}
    devise = v.get("devise") if v.get("devise") in R.CURRENCIES else (R.company().get("defaultCurrency") or "USD")
    try:
        anciennete = max(0, int(v.get("anciennete_jours", ANCIENNETE_DEFAUT)))
    except (TypeError, ValueError):
        anciennete = ANCIENNETE_DEFAUT
    return {"devise": devise if devise in R.CURRENCIES else "USD", "anciennete_jours": anciennete}


def configurer(devise: str, anciennete_jours: int) -> None:
    u = V.actor(["admin", "finance"])
    if not (V.peut(u, "tresorerie") or V.peut(u, "comptabilite")):
        raise ValueError("Réglage réservé à la trésorerie ou à la comptabilité.")
    if devise not in R.CURRENCIES:
        raise ValueError("Devise de présentation invalide.")
    if not 0 <= int(anciennete_jours) <= 365:
        raise ValueError("Ancienneté maximale entre 0 et 365 jours.")
    with db.transaction("Réglages de l’affichage consolidé") as t:
        t.parametre("devises_consolidation", {"devise": devise, "anciennete_jours": int(anciennete_jours)})
    vider_cache()


# ------------------------------------------------------------------ registre des taux
def vider_cache() -> None:
    _CACHE.update(t=0.0, rows=None)


def _taux_enregistres() -> list[dict]:
    if _CACHE["rows"] is None or time.monotonic() - _CACHE["t"] > _TTL:
        _CACHE.update(rows=V.records("rate"), t=time.monotonic())
    return _CACHE["rows"]


def _decimal(valeur) -> Decimal:
    try:
        d = Decimal(str(valeur).replace(" ", "").replace(" ", "").replace(",", ".").strip())
    except (InvalidOperation, ValueError):
        raise ValueError("Taux invalide : nombre positif attendu.") from None
    if not d.is_finite() or d <= 0 or d > Decimal("1e9"):
        raise ValueError("Taux invalide : nombre positif attendu.")
    return d


def ref_taux(source: str, cible: str, date_: str) -> str:
    return f"TAUX-{source}{cible}-{date_}"


def saisir_taux(source: str, cible: str, valeur, date_: str, note: str = "") -> str:
    """Taux du jour d'une paire. Une seconde saisie le même jour corrige le taux (modification tracée à l'audit)."""
    u = V.actor(["admin", "finance"])
    if not (V.peut(u, "tresorerie") or V.peut(u, "comptabilite")):
        raise ValueError("Saisie des taux réservée à la trésorerie ou à la comptabilité.")
    V.date(date_)
    if date_ > R.today():
        raise ValueError("Un taux ne se saisit pas pour une date future.")
    if source not in R.CURRENCIES or cible not in R.CURRENCIES or source == cible:
        raise ValueError("Paire de devises invalide.")
    v = _decimal(valeur)
    ref = ref_taux(source, cible, date_)
    with db.transaction(f"Taux du jour {source}/{cible}") as t:
        existant = next((r for r in V.records("rate", t) if r["ref"] == ref), None)
        if existant:
            d = dict(existant["data"])
            ancien = d.get("rate")
            d.update(rate=str(v), note=note.strip()[:300], saisi_par=u["id"], saisi_nom=u["nom"],
                     corrige=(d.get("corrige") or []) + [{"ancien": ancien, "par": u["nom"],
                                                          "le": db.maintenant().isoformat()}])
            V.save(t, existant, d)
            id_ = existant["id"]
        else:
            id_ = V.insert(t, "rate", ref, "", source, dict(target=cible, rate=str(v), date=date_, note=note.strip()[:300],
                                                            saisi_par=u["id"], saisi_nom=u["nom"]))
    vider_cache()
    return id_


def _direct(source: str, cible: str, date_: str, rows: list[dict]):
    """Dernier taux enregistré source → cible à la date, ou son inverse ; (Decimal, date, libellé) ou None."""
    candidats = []
    for r in rows:
        d = r["data"]
        if d.get("date", "") > date_:
            continue
        if r["currency"] == source and d.get("target") == cible:
            candidats.append((d["date"], r["ref"], Decimal(d["rate"]), f"1 {source} = {_fmt(d['rate'])} {cible}"))
        elif r["currency"] == cible and d.get("target") == source:
            inverse = (Decimal(1) / Decimal(d["rate"])).quantize(Decimal("1e-12"), ROUND_HALF_UP)
            candidats.append((d["date"], r["ref"], inverse, f"1 {cible} = {_fmt(d['rate'])} {source}"))
    if not candidats:
        return None
    date_t, _, taux, libelle = max(candidats, key=lambda c: (c[0], c[1]))
    return taux, date_t, libelle


def taux(source: str, cible: str, date_: str | None = None, rows: list[dict] | None = None) -> dict | None:
    """Taux applicable à une date : direct, inverse ou via une devise pivot. None si aucun taux connu."""
    date_ = date_ or R.today()
    if source == cible:
        return {"taux": Decimal(1), "date": date_, "libelle": "", "pivot": ""}
    rows = _taux_enregistres() if rows is None else rows
    if (d := _direct(source, cible, date_, rows)):
        return {"taux": d[0], "date": d[1], "libelle": d[2], "pivot": ""}
    for pivot in R.CURRENCIES:
        if pivot in (source, cible):
            continue
        a, b = _direct(source, pivot, date_, rows), _direct(pivot, cible, date_, rows)
        if a and b:
            return {"taux": a[0] * b[0], "date": min(a[1], b[1]), "libelle": f"{a[2]} ; {b[2]}", "pivot": pivot}
    return None


def convertir(montant: int, source: str, cible: str, date_: str | None = None, rows=None) -> int | None:
    t = taux(source, cible, date_, rows)
    if t is None:
        return None
    return int((Decimal(montant) * t["taux"]).quantize(Decimal("1"), ROUND_HALF_UP))


# ------------------------------------------------------------------ consolidation (affichage seulement)
def consolider(totaux: dict[str, int], cible: str | None = None, date_: str | None = None) -> dict:
    """Total converti dans la devise de présentation, avec les taux utilisés.
    Les devises sans taux sont listées dans « manquantes » et exclues du total (jamais converties à 1)."""
    reg = reglages()
    cible = cible or reg["devise"]
    date_ = date_ or R.today()
    rows = _taux_enregistres()
    lignes, manquantes, anciens, total = [], [], [], 0
    limite = (dt.date.fromisoformat(date_) - dt.timedelta(days=reg["anciennete_jours"])).isoformat()
    for devise in R.CURRENCIES:
        montant = int((totaux or {}).get(devise) or 0)
        if not montant:
            continue
        t = taux(devise, cible, date_, rows)
        if t is None:
            manquantes.append(devise)
            continue
        converti = int((Decimal(montant) * t["taux"]).quantize(Decimal("1"), ROUND_HALF_UP))
        total += converti
        if devise != cible and t["date"] < limite:
            anciens.append(devise)
        lignes.append({"devise": devise, "montant": montant, "taux": t["taux"], "date_taux": t["date"],
                       "libelle": t["libelle"], "converti": converti})
    return {"devise": cible, "date": date_, "total": total, "lignes": lignes, "manquantes": manquantes,
            "anciens": anciens,
            "multi": len(lignes) + len(manquantes) > 1 or any(l["devise"] != cible for l in lignes) or bool(manquantes)}


def _fmt(taux_txt) -> str:
    d = Decimal(str(taux_txt)).normalize()
    entier, _, dec = f"{d:f}".partition(".")
    entier = f"{int(entier):,}".replace(",", " ")
    return entier + ("," + dec if dec else "")


def _date_fr(d: str) -> str:
    return f"{d[8:10]}/{d[5:7]}/{d[:4]}" if R.is_date(d) else d


def texte_consolide(totaux: dict[str, int], cible: str | None = None, date_: str | None = None) -> str:
    """« ≈ 12 345,00 USD (1 USD = 2 850 CDF, taux du 16/10/2026) » ; chaîne vide si une seule devise, déjà la bonne."""
    c = consolider(totaux, cible, date_)
    if not c["multi"]:
        return ""
    if not c["lignes"] and c["manquantes"]:
        return f"Total consolidé indisponible : aucun taux {', '.join(c['manquantes'])} → {c['devise']}."
    taux_txt = "; ".join(sorted({f"{l['libelle']}, taux du {_date_fr(l['date_taux'])}" for l in c["lignes"]
                                 if l["devise"] != c["devise"]}))
    out = f"≈ {R.money(c['total'], c['devise'])}" + (f" ({taux_txt})" if taux_txt else "")
    if c["manquantes"]:
        out += f" — hors {', '.join(c['manquantes'])} (aucun taux saisi)"
    if c["anciens"]:
        out += f" — taux {', '.join(c['anciens'])} à mettre à jour"
    return out


def etat_du_jour(date_: str | None = None) -> list[dict]:
    """Pour chaque paire de saisie : dernier taux, sa date, et s'il est ancien (alerte d'accueil)."""
    date_ = date_ or R.today()
    reg = reglages()
    limite = (dt.date.fromisoformat(date_) - dt.timedelta(days=reg["anciennete_jours"])).isoformat()
    out = []
    for s, c in PAIRES_SAISIE:
        d = _direct(s, c, date_, _taux_enregistres())
        out.append({"paire": f"{s}/{c}", "source": s, "cible": c, "taux": d[0] if d else None,
                    "date": d[1] if d else "", "libelle": d[2] if d else "", "ancien": not d or d[1] < limite,
                    "du_jour": bool(d) and d[1] == date_})
    return out
