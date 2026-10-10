"""Factures fournisseurs, paiements et avances : archives des montants initiaux et reprise des seuls reliquats.

Exemple de la spécification : facture de 1 000 USD payée 600 USD avant la bascule → le montant initial et le
paiement restent en archives ; seul le reliquat de 400 USD devient une dette reprise, sans redébiter la caisse.
Avance de 500 USD dont 350 USD déclarés justifiés → reliquat de 150 USD à justifier ou restituer ; la
justification déclarée reste à prouver par les pièces.
"""
from __future__ import annotations

import gestion_v7 as V
import regles as R
from imports.adapters.commun import correspondance, lignes, ok, provenance, ref_v7, verifier_chantier_contexte
from imports.validation import norm


def _poste(etat, res, chantier, code, rep, feuille, line):
    if not code:
        return True
    from imports.adapters.budgets import _budget_pour
    b = _budget_pour(etat, res, chantier)
    if not b or code not in {x["code"] for x in b["lines"]}:
        rep.erreur(feuille, line, "code_dqe", "Poste DQE absent du budget du chantier.")
        return False
    return True


def verifier(ds, ctx, etat, res, rep):
    D = ctx["date_bascule"]
    factures = {l["reference_externe"]: l for l in lignes(ds, "Factures_Fournisseurs") if l.get("reference_externe")}
    avances = {l["reference_externe"]: l for l in lignes(ds, "Avances") if l.get("reference_externe")}
    payes = {("f", k): [] for k in factures} | {("a", k): [] for k in avances}
    for p in lignes(ds, "Paiements"):
        if not ok(p, "reference_externe", "date", "devise", "montant"):
            continue
        line = p["__line"]
        cibles = [x for x in (("f", p.get("facture_ref")), ("a", p.get("avance_ref"))) if x[1]]
        if len(cibles) != 1:
            rep.erreur("Paiements", line, "facture_ref", "Relier chaque paiement à une seule facture OU une seule avance "
                                                         "(une ligne par affectation).")
            continue
        cible = cibles[0]
        if cible not in payes:
            rep.erreur("Paiements", line, "facture_ref" if cible[0] == "f" else "avance_ref",
                       "Facture ou avance absente du fichier.")
            continue
        origine = (factures if cible[0] == "f" else avances)[cible[1]]
        if origine.get("devise") and p["devise"] != origine["devise"]:
            rep.erreur("Paiements", line, "devise", "Devise différente de la pièce réglée : aucune conversion implicite.")
            continue
        if ctx["mode"] == "reprise" and p["date"] >= D:
            rep.erreur("Paiements", line, "date", "Paiement à partir de la date de bascule : à enregistrer dans le "
                                                  "circuit (il n’est pas repris par import).")
            continue
        payes[cible].append(p)
        rep.action("Paiements", line, "Archive", p["reference_externe"], f"Paiement antérieur conservé ({p['montant'] / 100:.2f} "
                   f"{p['devise']}) · aucun nouveau décaissement", "paiement", {}, adaptateur="fournisseurs",
                   effet={"rubrique": "Paiements antérieurs (archives)", "devise": p["devise"], "montant": p["montant"]})

    deja = {(norm(x["data"].get("party", "")), norm((x["data"].get("archive") or {}).get("numero", "")))
            for x in etat.v7_kind("carryover") if x["data"]["type"] == "debt" and x["data"]["status"] != "Rejetée"}
    deja |= {tuple(norm(v) for v in x["ref"].split(":", 1)) for x in etat.v7_kind("invoice") if ":" in x["ref"]}
    for l in lignes(ds, "Factures_Fournisseurs"):
        if not ok(l, "reference_externe", "numero_facture", "tiers_ref", "chantier_ref", "date_facture", "date_echeance",
                  "devise", "montant"):
            continue
        ref, line = l["reference_externe"], l["__line"]
        if not verifier_chantier_contexte(ctx, res, "Factures_Fournisseurs", l, rep):
            continue
        t_ = res.tiers(l["tiers_ref"])
        c = res.chantier(l["chantier_ref"])
        if not t_ or not c:
            rep.erreur("Factures_Fournisseurs", line, "tiers_ref" if not t_ else "chantier_ref", "Tiers ou chantier introuvable.")
            continue
        roles = t_["row"].get("roles", []) if t_["source"] == "fichier" else R.party_roles(t_["fiche"])
        if not set(roles) & {"supplier", "subcontractor"}:
            rep.erreur("Factures_Fournisseurs", line, "tiers_ref", "Ce tiers n’a pas le rôle Fournisseur ou Sous-traitant.")
            continue
        if ctx["mode"] == "reprise" and l["date_facture"] >= ctx["date_bascule"]:
            rep.erreur("Factures_Fournisseurs", line, "date_facture", "Facture à partir de la bascule : à enregistrer dans "
                                                                      "le circuit V7.")
            continue
        if not _poste(etat, res, {**c, "ref": l["chantier_ref"]}, l.get("code_dqe"), rep, "Factures_Fournisseurs", line):
            continue
        if etat.mapping("facture_fournisseur", ref) or (t_.get("id") and (norm(t_["id"]), norm(l["numero_facture"])) in deja):
            rep.erreur("Factures_Fournisseurs", line, "numero_facture", "Facture déjà reprise ou enregistrée pour ce tiers.")
            continue
        paye = sum(p["montant"] for p in payes[("f", ref)])
        if paye > l["montant"]:
            rep.erreur("Factures_Fournisseurs", line, "montant", "Paiements antérieurs supérieurs au montant de la facture.")
            continue
        reliquat = l["montant"] - paye
        archive = {"numero": l["numero_facture"], "date_facture": l["date_facture"], "montant_initial": l["montant"],
                   "paye_avant_bascule": paye, "paiements": [{k: p[k] for k in ("reference_externe", "date", "montant", "compte")}
                                                              for p in payes[("f", ref)]]}
        rep.action("Factures_Fournisseurs", line, "Archive", ref, f"Facture {l['numero_facture']} : initial "
                   f"{l['montant'] / 100:.2f}, payé avant bascule {paye / 100:.2f} {l['devise']}", "facture_fournisseur", {},
                   adaptateur="fournisseurs",
                   effet={"rubrique": "Factures fournisseurs — montant initial (archives)", "devise": l["devise"],
                          "montant": l["montant"]})
        if ctx["mode"] == "reprise" and reliquat > 0:
            rep.action("Factures_Fournisseurs", line, "Reliquat à activer", ref, f"Dette reprise {reliquat / 100:.2f} "
                       f"{l['devise']} · échéance {l['date_echeance']}", "facture_fournisseur",
                       {"type": "debt", "amount": reliquat, "chantier_ref": l["chantier_ref"], "party_ref": l["tiers_ref"],
                        "post": l.get("code_dqe") or "", "due": l["date_echeance"], "currency": l["devise"],
                        "label": f"Reliquat facture {l['numero_facture']}", "archive": archive},
                       effet={"rubrique": "Dettes fournisseurs reprises (reliquat)", "devise": l["devise"], "montant": reliquat},
                       adaptateur="fournisseurs")
        elif ctx["mode"] == "reprise":
            rep.alerte("Factures_Fournisseurs", line, "montant", "Facture soldée avant la bascule : conservée en archives seulement.")

    for l in lignes(ds, "Avances"):
        if not ok(l, "reference_externe", "beneficiaire_ref", "chantier_ref", "objet", "date_versement", "devise",
                  "montant_verse", "montant_justifie_declare", "montant_restitue"):
            continue
        ref, line = l["reference_externe"], l["__line"]
        if not verifier_chantier_contexte(ctx, res, "Avances", l, rep):
            continue
        t_ = res.tiers(l["beneficiaire_ref"])
        c = res.chantier(l["chantier_ref"])
        if not t_ or not c:
            rep.erreur("Avances", line, "beneficiaire_ref" if not t_ else "chantier_ref", "Bénéficiaire ou chantier introuvable.")
            continue
        if ctx["mode"] == "reprise" and l["date_versement"] >= ctx["date_bascule"]:
            rep.erreur("Avances", line, "date_versement", "Avance versée à partir de la bascule : à saisir dans le circuit V7.")
            continue
        if not _poste(etat, res, {**c, "ref": l["chantier_ref"]}, l.get("code_dqe"), rep, "Avances", line):
            continue
        utilise = l["montant_justifie_declare"] + l["montant_restitue"]
        if utilise > l["montant_verse"]:
            rep.erreur("Avances", line, "montant_justifie_declare", "Justifié + restitué supérieur au montant versé.")
            continue
        versements = payes[("a", ref)]
        if versements and sum(p["montant"] for p in versements) != l["montant_verse"]:
            rep.erreur("Avances", line, "montant_verse", "Les paiements liés à cette avance ne correspondent pas au montant versé.")
            continue
        if etat.mapping("avance", ref):
            rep.erreur("Avances", line, "reference_externe", "Avance déjà reprise par un autre lot.")
            continue
        compte = l.get("compte_charge") or "605"
        if compte not in V.CHART or not compte.startswith(("6", "2", "3")):
            rep.erreur("Avances", line, "compte_charge", "Compte de charge du plan proposé requis.")
            continue
        reliquat = l["montant_verse"] - utilise
        archive = {"date_versement": l["date_versement"], "montant_verse": l["montant_verse"],
                   "justifie_declare": l["montant_justifie_declare"], "restitue": l["montant_restitue"],
                   "justification": "déclarée dans l’ancien système, à prouver par les pièces"}
        rep.action("Avances", line, "Archive", ref, f"Avance versée {l['montant_verse'] / 100:.2f}, justifiée (déclarée) "
                   f"{l['montant_justifie_declare'] / 100:.2f}, restituée {l['montant_restitue'] / 100:.2f} {l['devise']}",
                   "avance", {}, adaptateur="fournisseurs",
                   effet={"rubrique": "Avances versées (archives)", "devise": l["devise"], "montant": l["montant_verse"]})
        if l["montant_justifie_declare"] > 0:
            rep.alerte("Avances", line, "montant_justifie_declare", "La justification déclarée n’est pas une preuve : "
                       "joignez les pièces (feuille Documents). Elle reste en archives et n’est pas comptée comme charge "
                       "V7 ; les coûts déjà justifiés relèvent des cumuls du chantier.", decision=True)
        if ctx["mode"] == "reprise" and reliquat > 0:
            rep.action("Avances", line, "Reliquat à activer", ref, f"Reste à justifier ou restituer {reliquat / 100:.2f} "
                       f"{l['devise']} · aucun nouveau versement", "avance",
                       {"type": "advance", "amount": reliquat, "chantier_ref": l["chantier_ref"],
                        "party_ref": l["beneficiaire_ref"], "post": l.get("code_dqe") or "", "currency": l["devise"],
                        "label": l["objet"], "expense_account": compte, "archive": archive, "due": ""},
                       effet={"rubrique": "Avances restant à justifier (reliquat)", "devise": l["devise"], "montant": reliquat},
                       adaptateur="fournisseurs")


def executer(t, ctx, a, res):
    if a["action"] == "Archive":
        return ""
    p = a["payload"]
    projet = res.id("chantier", p["chantier_ref"])
    party = res.id("tiers", p["party_ref"])
    prefixe = "DETTE" if p["type"] == "debt" else "AVANCE"
    data = {"type": p["type"], "amount": p["amount"], "post": p["post"], "party": party, "label": p["label"],
            "due": p["due"], "cutover": ctx["date_bascule"], "archive": p["archive"], "lot_ref": ctx["lot_ref"],
            **({"expense_account": p["expense_account"]} if p.get("expense_account") else {}), **provenance(ctx)}
    id_ = V._carryover_tx(t, ctx["user"], ref_v7(ctx, prefixe, a["ref"]), projet, p["currency"], data)
    correspondance(t, ctx, a["entite"], a["ref"], id_, "Reliquat")
    return id_


FOURNISSEURS = {"verifier": verifier, "executer": executer}
