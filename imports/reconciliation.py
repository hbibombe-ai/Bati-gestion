"""Rapprochements : totaux avant / après par devise et par compte, cumuls budgétaires, reliquats d'un lot.

Les totaux restent séparés par devise (USD, CDF, EUR) : aucune somme multi-devises.
"""
from __future__ import annotations

from collections import defaultdict

import sqlalchemy as sa

import db
import gestion_v7 as V


class _Tx:
    """Adaptateur minimal pour réutiliser les calculs V7 avec une connexion donnée."""

    def __init__(self, cx):
        self.cx = cx


def instantane(cx, projets: set | None = None) -> dict:
    tx = _Tx(cx)
    v7 = [dict(r._mapping) for r in cx.execute(sa.select(db.TABLES["v7_records"]))]
    moves = [dict(r._mapping) for r in cx.execute(sa.select(db.TABLES["movements"]))]
    comptes = {}
    for a in [r for r in v7 if r["kind"] == "account"]:
        solde = sum(m["amount"] * (1 if m["direction"] == "in" else -1) for m in moves
                    if (m.get("journal") or {}).get("v7_account") == a["id"])
        comptes[a["ref"]] = {"devise": a["currency"], "solde": solde}
    gl = defaultdict(lambda: {"debit": 0, "credit": 0})
    for e in [r for r in v7 if r["kind"] == "entry"]:
        for l in e["data"]["lines"]:
            gl[e["currency"]]["debit"] += l["debit"]
            gl[e["currency"]]["credit"] += l["credit"]
    budgets = {}
    ops = [r for r in v7 if r["kind"] == "operation"]
    carry = [r for r in v7 if r["kind"] == "carryover"]
    for b in V.active_budgets([r for r in v7 if r["kind"] == "budget"]):
        if projets is not None and b["project"] not in projets:
            continue
        m = V.metrics(b, ops, carry, tx)
        budgets[b["ref"]] = {"devise": b["currency"], "statut": b["data"]["status"], "budget": m["budget"],
                             "cout": m["cost"], "engage": m["open"], "avances": m["advance"], "disponible": m["available"]}
    reliquats = defaultdict(int)
    for c in carry:
        if c["data"]["status"] in ("Approuvée",):
            eff = V.carry_effects(c)
            d = c["data"]
            if d["type"] == "debt":
                reliquats[("Dettes reprises restant dues", c["currency"])] += d["amount"] - V._carry_paid(d)
            elif d["type"] == "advance":
                reliquats[("Avances reprises à régulariser", c["currency"])] += eff["advance"]
    return {"tresorerie": comptes, "grand_livre": dict(gl), "budgets": budgets,
            "reliquats": [{"rubrique": k[0], "devise": k[1], "montant": v} for k, v in sorted(reliquats.items())]}


def ecarts(avant: dict, apres: dict) -> list[dict]:
    """Écarts lisibles entre deux instantanés (trésorerie par compte, grand livre et disponibles par devise)."""
    out = []
    for ref in sorted(set(avant["tresorerie"]) | set(apres["tresorerie"])):
        a = avant["tresorerie"].get(ref, {}).get("solde", 0)
        b = apres["tresorerie"].get(ref, {}).get("solde", 0)
        if a != b or ref not in avant["tresorerie"]:
            out.append({"rubrique": "Trésorerie", "objet": ref, "devise": apres["tresorerie"].get(ref, avant["tresorerie"].get(ref, {})).get("devise", ""),
                        "avant": a, "apres": b, "ecart": b - a})
    for dev in sorted(set(avant["grand_livre"]) | set(apres["grand_livre"])):
        a = avant["grand_livre"].get(dev, {"debit": 0, "credit": 0})
        b = apres["grand_livre"].get(dev, {"debit": 0, "credit": 0})
        if a != b:
            out.append({"rubrique": "Grand livre (débit)", "objet": dev, "devise": dev, "avant": a["debit"], "apres": b["debit"],
                        "ecart": b["debit"] - a["debit"]})
            out.append({"rubrique": "Grand livre (crédit)", "objet": dev, "devise": dev, "avant": a["credit"], "apres": b["credit"],
                        "ecart": b["credit"] - a["credit"]})
    for ref in sorted(set(avant["budgets"]) | set(apres["budgets"])):
        a = avant["budgets"].get(ref)
        b = apres["budgets"].get(ref)
        if a != b:
            for k, lib in (("cout", "Coûts"), ("engage", "Engagements ouverts"), ("disponible", "Disponible")):
                out.append({"rubrique": f"Budget {lib}", "objet": ref, "devise": (b or a)["devise"],
                            "avant": (a or {}).get(k, 0), "apres": (b or {}).get(k, 0),
                            "ecart": (b or {}).get(k, 0) - (a or {}).get(k, 0)})
    return out


def reliquats_lot(lot_id: str) -> list[dict]:
    rows = []
    for c in V.records("carryover"):
        d = c["data"]
        if d.get("import_lot") != lot_id:
            continue
        eff = V.carry_effects(c)
        reste = {"debt": d.get("amount", 0) - V._carry_paid(d), "advance": eff["advance"],
                 "commitment": eff["open"]}.get(d["type"], 0)
        rows.append({"id": c["id"], "ref": c["ref"], "type": V.CARRY_LABELS[d["type"]], "devise": c["currency"],
                     "montant": d.get("amount", 0), "reste": reste if d["status"] in ("Approuvée", "Soldée") else d.get("amount", 0),
                     "statut": d["status"], "archive": d.get("archive") or {}})
    return rows
