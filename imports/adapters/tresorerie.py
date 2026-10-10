"""Trésorerie (comptes V7 et soldes d'ouverture) et comptabilité (balance d'ouverture équilibrée).

Les soldes et écritures repris sont des propositions : elles ne mouvementent la trésorerie et le grand livre
qu'à l'activation par la DG. La trésorerie ne peut pas être reprise deux fois (solde d'ouverture ET lignes
52/57 dans la balance d'ouverture pour la même devise).
"""
from __future__ import annotations

from collections import defaultdict

import gestion_v7 as V
from imports.adapters.commun import correspondance, lignes, ok, provenance, ref_v7


def _ouvertures_tresorerie(etat, devise):
    return any(e["currency"] == devise and e["ref"].startswith("OPENING:") for e in etat.v7_kind("entry")) or any(
        c["currency"] == devise and c["data"]["type"] == "opening" and c["data"]["status"] in ("À approuver", "Approuvée")
        for c in etat.v7_kind("carryover"))


def _balance_avec_tresorerie(etat, devise):
    return any(c["currency"] == devise and c["data"]["type"] == "entry" and c["data"]["status"] in ("À approuver", "Approuvée")
               and any(str(l["account"]).startswith(("52", "57")) for l in c["data"]["lines"])
               for c in etat.v7_kind("carryover"))


def _tresorerie_dans_ecritures(ds):
    devises = set()
    ecr = {e["reference_externe"]: e for e in lignes(ds, "Ecritures") if e.get("reference_externe")}
    for l in lignes(ds, "Lignes_Ecriture"):
        e = ecr.get(l.get("ecriture_ref"))
        if e and e.get("devise") and str(l.get("compte") or "").startswith(("52", "57")):
            devises.add(e["devise"])
    return devises


def verifier_comptes(ds, ctx, etat, res, rep):
    tres_ecr = _tresorerie_dans_ecritures(ds)
    for l in lignes(ds, "Comptes_Tresorerie"):
        if not ok(l, "reference_externe", "libelle", "devise", "compte_comptable", "rattachement", "solde_ouverture",
                  "date_solde", "reference_releve"):
            continue
        ref, line = l["reference_externe"], l["__line"]
        if not l["compte_comptable"].startswith(("52", "57")):
            rep.erreur("Comptes_Tresorerie", line, "compte_comptable", "Subdivision 52 (banque) ou 57 (caisse) attendue.")
            continue
        if l["date_solde"] != ctx["date_bascule"]:
            rep.erreur("Comptes_Tresorerie", line, "date_solde", "Le solde repris doit être celui du début de la date de bascule.")
            continue
        existant = next((a for a in etat.v7_kind("account") if a["ref"] == ref.upper()), None)
        if existant:
            if existant["currency"] != l["devise"] or existant["data"]["ledger"] != l["compte_comptable"]:
                rep.erreur("Comptes_Tresorerie", line, "reference_externe", "Compte existant avec une autre devise ou subdivision.")
                continue
            res.declarer("compte_tresorerie", ref, existant, "Comptes_Tresorerie")
            res.fixer("compte_tresorerie", ref, existant["id"])
            rep.action("Comptes_Tresorerie", line, "Correspondance", ref, f"Compte V7 existant {existant['data']['label']}",
                       "compte_tresorerie", {"id": existant["id"]}, adaptateur="tresorerie")
            if any((m.get("journal") or {}).get("v7_account") == existant["id"] for m in etat.movements):
                if l["solde_ouverture"] > 0:
                    rep.erreur("Comptes_Tresorerie", line, "solde_ouverture", "Compte déjà mouvementé : utilisez un ajustement "
                               "documenté plutôt qu’un solde d’ouverture.")
                continue
        else:
            if any(a["currency"] == l["devise"] and a["data"]["ledger"] == l["compte_comptable"] for a in etat.v7_kind("account")):
                rep.erreur("Comptes_Tresorerie", line, "compte_comptable", "Subdivision déjà utilisée pour cette devise.")
                continue
            res.declarer("compte_tresorerie", ref, {"currency": l["devise"]}, "Comptes_Tresorerie")
            rep.action("Comptes_Tresorerie", line, "Création", ref, f"{l['libelle']} · {l['devise']} · {l['compte_comptable']}",
                       "compte_tresorerie", {"label": l["libelle"], "currency": l["devise"], "ledger": l["compte_comptable"],
                                             "legacy": l["rattachement"]}, adaptateur="tresorerie")
        if l["solde_ouverture"] > 0:
            if l["devise"] in tres_ecr or _balance_avec_tresorerie(etat, l["devise"]):
                rep.erreur("Comptes_Tresorerie", line, "solde_ouverture", "La balance d’ouverture contient déjà la trésorerie "
                           "en " + l["devise"] + " : choisissez une seule méthode (double comptabilisation).")
                continue
            if any(c["data"]["type"] == "opening" and c["data"].get("account_ref") == ref and c["data"]["status"] != "Rejetée"
                   for c in etat.v7_kind("carryover")) or etat.mapping("solde_ouverture", ref):
                rep.erreur("Comptes_Tresorerie", line, "reference_externe", "Solde d’ouverture déjà repris pour ce compte.")
                continue
            rep.action("Comptes_Tresorerie", line, "Reliquat à activer", ref, f"Solde d’ouverture {l['solde_ouverture'] / 100:.2f} "
                       f"{l['devise']} au {l['date_solde']} · relevé {l['reference_releve']}", "solde_ouverture",
                       {"account_ref": ref, "amount": l["solde_ouverture"], "date": l["date_solde"], "currency": l["devise"],
                        "releve": l["reference_releve"]},
                       effet={"rubrique": "Soldes de trésorerie d’ouverture", "devise": l["devise"], "compte": ref,
                              "montant": l["solde_ouverture"]}, adaptateur="tresorerie")


def executer_comptes(t, ctx, a, res):
    p = a["payload"]
    if a["action"] == "Correspondance":
        correspondance(t, ctx, "compte_tresorerie", a["ref"], p["id"], "Correspondance")
        return p["id"]
    if a["action"] == "Création":
        id_ = V._create_account_tx(t, ctx["user"], a["ref"], p["label"], p["currency"], p["ledger"], p["legacy"],
                                   extra=provenance(ctx))
        res.fixer("compte_tresorerie", a["ref"], id_)
        correspondance(t, ctx, "compte_tresorerie", a["ref"], id_, "Création")
        return id_
    compte = res.id("compte_tresorerie", p["account_ref"])
    id_ = V._carryover_tx(t, ctx["user"], ref_v7(ctx, "SOLDE", a["ref"]), "", p["currency"],
                          {"type": "opening", "amount": p["amount"], "account": compte, "account_ref": p["account_ref"],
                           "date": p["date"], "label": f"Solde d’ouverture {a['ref']}", "cutover": ctx["date_bascule"],
                           "archive": {"releve": p["releve"]}, "lot_ref": ctx["lot_ref"], **provenance(ctx)})
    correspondance(t, ctx, "solde_ouverture", a["ref"], id_, "Reliquat")
    return id_


def _compte_valide(c: str) -> bool:
    return c.isdigit() and 2 <= len(c) <= 10 and any(c.startswith(k) for k in V.CHART)


def verifier_ecritures(ds, ctx, etat, res, rep):
    enfants = defaultdict(list)
    for l in lignes(ds, "Lignes_Ecriture"):
        enfants[l.get("ecriture_ref")].append(l)
    totaux = defaultdict(lambda: [0, 0])
    tres_comptes = {l["devise"] for l in lignes(ds, "Comptes_Tresorerie") if l.get("solde_ouverture") and l.get("devise")}
    for e in lignes(ds, "Ecritures"):
        if not ok(e, "reference_externe", "date", "journal", "libelle", "devise"):
            continue
        ref, line = e["reference_externe"], e["__line"]
        if ctx["mode"] == "reprise" and e["date"] != ctx["date_bascule"]:
            rep.erreur("Ecritures", line, "date", "La balance d’ouverture est datée du jour de bascule.")
            continue
        ls = enfants.get(ref, [])
        if len(ls) < 2:
            rep.erreur("Ecritures", line, "", "Au moins deux lignes débit / crédit sont requises.")
            continue
        out, ko = [], False
        for x in ls:
            if not ok(x, "compte", "debit", "credit"):
                ko = True
                continue
            if not _compte_valide(x["compte"]):
                rep.erreur("Lignes_Ecriture", x["__line"], "compte", "Compte absent du plan comptable utilisé.")
                ko = True
            if (x["debit"] > 0) == (x["credit"] > 0):
                rep.erreur("Lignes_Ecriture", x["__line"], "debit", "Chaque ligne porte soit un débit, soit un crédit.")
                ko = True
            out.append({"account": x["compte"], "debit": x["debit"], "credit": x["credit"], "label": x.get("libelle") or ""})
        if ko:
            continue
        d, c = sum(x["debit"] for x in out), sum(x["credit"] for x in out)
        if d != c:
            rep.erreur("Ecritures", line, "", f"Écriture déséquilibrée : débit {d / 100:.2f} ≠ crédit {c / 100:.2f}.")
            continue
        totaux[e["devise"]][0] += d
        totaux[e["devise"]][1] += c
        if ctx["mode"] != "reprise":
            rep.action("Ecritures", line, "Archive", ref, e["libelle"], "ecriture", {}, adaptateur="comptabilite")
            continue
        if etat.mapping("ecriture", ref) or any(x["data"]["type"] == "entry" and x["currency"] == e["devise"]
                                               and x["data"]["date"] == e["date"] and x["data"]["status"] in ("À approuver", "Approuvée")
                                               for x in etat.v7_kind("carryover")):
            rep.erreur("Ecritures", line, "reference_externe", "Balance d’ouverture déjà reprise pour cette devise et cette date.")
            continue
        if any(str(x["account"]).startswith(("52", "57")) for x in out) and (e["devise"] in tres_comptes or _ouvertures_tresorerie(etat, e["devise"])):
            rep.erreur("Ecritures", line, "", "Trésorerie déjà reprise par des soldes d’ouverture pour cette devise : "
                       "retirez les comptes 52/57 de la balance ou les soldes d’ouverture (double comptabilisation).")
            continue
        rep.action("Ecritures", line, "Reliquat à activer", ref, f"{e['journal']} · {e['libelle']} · {len(out)} lignes équilibrées",
                   "ecriture", {"lines": out, "date": e["date"], "label": e["libelle"], "journal": e["journal"],
                                "currency": e["devise"]},
                   effet={"rubrique": "Balance d’ouverture (débit = crédit)", "devise": e["devise"], "montant": d},
                   adaptateur="comptabilite")


def executer_ecritures(t, ctx, a, res):
    if a["action"] == "Archive":
        return ""
    p = a["payload"]
    id_ = V._carryover_tx(t, ctx["user"], ref_v7(ctx, "ECRITURE", a["ref"]), "", p["currency"],
                          {"type": "entry", "amount": 0, "lines": p["lines"], "date": p["date"], "label": p["label"],
                           "journal": p["journal"], "cutover": ctx["date_bascule"], "lot_ref": ctx["lot_ref"],
                           **provenance(ctx)})
    correspondance(t, ctx, "ecriture", a["ref"], id_, "Reliquat")
    return id_


COMPTES = {"verifier": verifier_comptes, "executer": executer_comptes}
ECRITURES = {"verifier": verifier_ecritures, "executer": executer_ecritures}
