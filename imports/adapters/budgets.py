"""DQE et budgets V7, cumuls à la date de bascule, besoins de dépense (demandes N0)."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

import gestion_v7 as V
from imports.adapters.commun import correspondance, lignes, ok, provenance, ref_v7, verifier_chantier_contexte
from imports.validation import norm


def _budget_existant(etat, projet_id):
    return next((b for b in etat.budgets_actifs() if b["project"] == projet_id), None)


# ------------------------------------------------------------------ budgets et lignes
def verifier_budgets(ds, ctx, etat, res, rep):
    lignes_par_budget = {}
    for l in lignes(ds, "Lignes_Budget"):
        lignes_par_budget.setdefault(l.get("budget_ref"), []).append(l)
    codes_v7 = {norm(b["ref"]) for b in etat.v7_kind("budget")}
    for l in lignes(ds, "Budgets"):
        if not ok(l, "reference_externe", "chantier_ref", "devise", "montant_contrat", "cout_estime_terminaison"):
            continue
        ref, line = l["reference_externe"], l["__line"]
        if not verifier_chantier_contexte(ctx, res, "Budgets", l, rep):
            continue
        c = res.chantier(l["chantier_ref"])
        if not c:
            rep.erreur("Budgets", line, "chantier_ref", "Chantier introuvable.")
            continue
        devise_chantier = c["row"]["currency"] if c["source"] == "fichier" else c["fiche"]["currency"]
        if l["devise"] != devise_chantier:
            rep.erreur("Budgets", line, "devise", f"Le chantier est tenu en {devise_chantier} : aucune conversion implicite.")
            continue
        if c.get("id") and _budget_existant(etat, c["id"]):
            rep.erreur("Budgets", line, "chantier_ref", "Ce chantier possède déjà un budget V7.")
            continue
        if norm(ref) in codes_v7:
            rep.erreur("Budgets", line, "reference_externe", "Code budget déjà utilisé.")
            continue
        enfants = lignes_par_budget.get(ref, [])
        if not enfants:
            rep.erreur("Budgets", line, "", "Aucune ligne dans Lignes_Budget pour ce budget.")
            continue
        vus, out, ko = set(), [], False
        for x in sorted(enfants, key=lambda x: x.get("numero_ligne") or 0):
            if not ok(x, "code_dqe", "libelle", "budget_initial"):
                ko = True
                continue
            if x["code_dqe"] in vus:
                rep.erreur("Lignes_Budget", x["__line"], "code_dqe", "Poste DQE en double dans ce budget.")
                ko = True
                continue
            vus.add(x["code_dqe"])
            if x.get("quantite") is not None and x.get("prix_unitaire") is not None:
                calc = int((Decimal(str(x["quantite"])) * x["prix_unitaire"]).quantize(Decimal("1"), ROUND_HALF_UP))
                if calc != x["budget_initial"]:
                    rep.alerte("Lignes_Budget", x["__line"], "budget_initial",
                               "Quantité × prix unitaire différent du budget initial : vérifier le DQE.", decision=True)
            budget = x["budget_revise"] if x.get("budget_revise") is not None else x["budget_initial"]
            if x.get("budget_revise") is not None and x["budget_revise"] != x["budget_initial"]:
                rep.alerte("Lignes_Budget", x["__line"], "budget_revise", "Budget révisé repris : la DG l’approuve "
                           "avec le budget ; l’historique des révisions reste dans les archives du lot.")
            out.append({"code": x["code_dqe"], "label": x["libelle"], "budget": budget,
                        "forecast": x["prevision"] if x.get("prevision") is not None else budget,
                        "initial": x["budget_initial"], "unit": x.get("unite") or "", "qty": x.get("quantite"),
                        "unit_price": x.get("prix_unitaire")})
        if ko:
            continue
        res.declarer("budget", ref, {"project_ref": l["chantier_ref"], "lines": out, "currency": l["devise"],
                                     "approved": False}, "Budgets")
        payload = {"chantier_ref": l["chantier_ref"], "code": ref, "lines": out, "contract": l["montant_contrat"],
                   "forecast": l["cout_estime_terminaison"], "revenue": l.get("chiffre_affaires_final")}
        rep.action("Budgets", line, "Budget à approuver", ref, f"{len(out)} poste(s) DQE · approbation DG requise",
                   "budget", payload, effet={"rubrique": "Budget DQE à approuver", "devise": l["devise"],
                                             "montant": sum(x["budget"] for x in out)}, adaptateur="budgets")


def executer_budgets(t, ctx, a, res):
    p = a["payload"]
    projet = res.id("chantier", p["chantier_ref"])
    id_ = V._create_budget_tx(t, ctx["user"], projet, p["code"], p["lines"], p["contract"], p["forecast"], p["revenue"],
                              extra=provenance(ctx))
    correspondance(t, ctx, "budget", a["ref"], id_, "Budget à approuver")
    return id_


# ------------------------------------------------------------------ cumuls à la date de bascule
def _budget_pour(etat, res, chantier):
    """Budget utilisable par un cumul : budget du fichier, ou budget existant non rejeté."""
    for (ent, ref), f in res.fichier.items():
        if ent == "budget" and f["row"].get("project_ref") == chantier["ref"]:
            return {"lines": f["row"]["lines"], "currency": f["row"]["currency"], "approved": False, "source": "fichier"}
    if chantier.get("id"):
        b = _budget_existant(etat, chantier["id"])
        if b:
            return {"lines": b["data"]["lines"], "currency": b["currency"], "approved": b["data"]["status"] == "Approuvé",
                    "source": "base", "id": b["id"]}
    return None


def verifier_cumuls(ds, ctx, etat, res, rep):
    vus = set()
    for l in lignes(ds, "Cumuls_Budget"):
        if not ok(l, "reference_externe", "chantier_ref", "code_dqe", "devise", "couts_executes", "engagements_ouverts",
                  "date_arrete"):
            continue
        ref, line = l["reference_externe"], l["__line"]
        if not verifier_chantier_contexte(ctx, res, "Cumuls_Budget", l, rep):
            continue
        if l["date_arrete"] > ctx["date_bascule"]:
            rep.erreur("Cumuls_Budget", line, "date_arrete", "Arrêté postérieur à la date de bascule.")
            continue
        c = res.chantier(l["chantier_ref"])
        if not c:
            rep.erreur("Cumuls_Budget", line, "chantier_ref", "Chantier introuvable.")
            continue
        b = _budget_pour(etat, res, {**c, "ref": l["chantier_ref"]})
        if not b:
            rep.erreur("Cumuls_Budget", line, "chantier_ref", "Aucun budget V7 pour ce chantier (dans le fichier ou la base).")
            continue
        if b["currency"] != l["devise"]:
            rep.erreur("Cumuls_Budget", line, "devise", "Devise différente du budget : aucune conversion implicite.")
            continue
        poste = next((x for x in b["lines"] if x["code"] == l["code_dqe"]), None)
        if not poste:
            rep.erreur("Cumuls_Budget", line, "code_dqe", "Poste DQE absent du budget.")
            continue
        cle = (l["chantier_ref"], l["code_dqe"])
        if cle in vus:
            rep.erreur("Cumuls_Budget", line, "code_dqe", "Un seul cumul par chantier et poste DQE.")
            continue
        vus.add(cle)
        if etat.mapping("cumul", ref):
            rep.erreur("Cumuls_Budget", line, "reference_externe", "Cumul déjà repris par un autre lot.")
            continue
        if c.get("id") and any(x["project"] == c["id"] and x["data"]["type"] in ("cost", "commitment")
                               and x["data"].get("post") == l["code_dqe"] and x["data"]["status"] in ("À approuver", "Approuvée", "Soldée")
                               for x in etat.v7_kind("carryover")):
            rep.erreur("Cumuls_Budget", line, "code_dqe", "Des cumuls existent déjà pour ce poste : pas de double reprise.")
            continue
        if c.get("id") and any(o["project"] == c["id"] and o["data"]["post"] == l["code_dqe"] and o["data"]["status"] != "Annulée"
                               for o in etat.v7_kind("operation")):
            rep.alerte("Cumuls_Budget", line, "code_dqe", "Des opérations V7 existent déjà sur ce poste : vérifiez que les "
                       "cumuls n’incluent pas ces montants (sinon double comptage).", decision=True)
        if c.get("id") and any(e["project"] == c["id"] for e in etat.expenses):
            rep.alerte("Cumuls_Budget", line, "chantier_ref", "Des dépenses historiques existent dans l’application pour ce "
                       "chantier : elles restent des archives et ne sont pas additionnées aux cumuls.")
        reste = poste["budget"] - l["couts_executes"] - l["engagements_ouverts"]
        if reste < 0:
            rep.alerte("Cumuls_Budget", line, "engagements_ouverts", "Cumuls supérieurs au budget du poste : "
                       "dépassement à justifier lors de l’activation.", decision=True)
        base = {"chantier_ref": l["chantier_ref"], "post": l["code_dqe"], "currency": l["devise"], "date": l["date_arrete"],
                "ref": ref}
        for typ, champ, lib in (("cost", "couts_executes", "Coûts exécutés repris"),
                                ("commitment", "engagements_ouverts", "Engagement ouvert repris")):
            if l[champ] > 0:
                rep.action("Cumuls_Budget", line, "Reliquat à activer", f"{ref}:{typ}",
                           f"{lib} · poste {l['code_dqe']} · disponible après reprise {reste / 100:.2f} {l['devise']}",
                           "cumul", {**base, "type": typ, "amount": l[champ]},
                           effet={"rubrique": lib, "devise": l["devise"], "montant": l[champ]}, adaptateur="cumuls")


def executer_cumuls(t, ctx, a, res):
    p = a["payload"]
    projet = res.id("chantier", p["chantier_ref"])
    id_ = V._carryover_tx(t, ctx["user"], ref_v7(ctx, "CUMUL", a["ref"]), projet, p["currency"],
                          {"type": p["type"], "amount": p["amount"], "post": p["post"], "label": V.CARRY_LABELS[p["type"]],
                           "cutover": ctx["date_bascule"], "archive": {"date_arrete": p["date"], "reference": p["ref"]},
                           "lot_ref": ctx["lot_ref"], **provenance(ctx)})
    correspondance(t, ctx, "cumul", a["ref"], id_, "Reliquat")
    return id_


# ------------------------------------------------------------------ besoins (demandes N0)
def verifier_besoins(ds, ctx, etat, res, rep):
    refs_v7 = {norm(o["ref"]) for o in etat.v7_kind("operation")}
    for l in lignes(ds, "Besoins"):
        if not ok(l, "reference_externe", "chantier_ref", "code_dqe", "objet", "beneficiaire_ref", "nature", "devise",
                  "echeance"):
            continue
        ref, line = l["reference_externe"], l["__line"]
        if not verifier_chantier_contexte(ctx, res, "Besoins", l, rep):
            continue
        if norm(ref) in refs_v7 or etat.mapping("besoin", ref):
            rep.erreur("Besoins", line, "reference_externe", "Référence de demande déjà utilisée.")
            continue
        c = res.chantier(l["chantier_ref"])
        if not c or not c.get("id"):
            rep.erreur("Besoins", line, "chantier_ref", "Chantier existant avec budget approuvé requis.")
            continue
        b = _budget_existant(etat, c["id"])
        if not b or b["data"]["status"] != "Approuvé":
            rep.erreur("Besoins", line, "chantier_ref", "Budget DQE approuvé requis avant d’importer des besoins.")
            continue
        if l["devise"] != b["currency"]:
            rep.erreur("Besoins", line, "devise", f"Le budget est en {b['currency']} : convertissez explicitement avant import.")
            continue
        if l["code_dqe"] not in {x["code"] for x in b["data"]["lines"]}:
            rep.erreur("Besoins", line, "code_dqe", "Poste DQE absent du budget.")
            continue
        t_ = res.tiers(l["beneficiaire_ref"])
        if not t_:
            rep.erreur("Besoins", line, "beneficiaire_ref", "Bénéficiaire introuvable.")
            continue
        montant = l.get("montant")
        if l.get("quantite") is not None and l.get("prix_unitaire") is not None:
            calc = int((Decimal(str(l["quantite"])) * l["prix_unitaire"]).quantize(Decimal("1"), ROUND_HALF_UP))
            if montant is not None and montant != calc:
                rep.erreur("Besoins", line, "montant", "Montant différent de quantité × prix unitaire.")
                continue
            montant = calc
        if not montant:
            rep.erreur("Besoins", line, "montant", "Montant positif requis (ou quantité et prix unitaire).")
            continue
        compte = l.get("compte") or "605"
        if compte not in V.CHART or not compte.startswith(("6", "2", "3")):
            rep.erreur("Besoins", line, "compte", "Compte de coût ou d’actif du plan proposé requis.")
            continue
        rep.action("Besoins", line, "Brouillon N0", ref, f"{l['objet']} · {l['nature']} · à soumettre au circuit N1→DG",
                   "besoin", {"chantier_ref": l["chantier_ref"], "post": l["code_dqe"], "party_ref": l["beneficiaire_ref"],
                              "label": l["objet"], "nature": l["nature"], "amount": montant, "due": l["echeance"],
                              "account": compte, "currency": l["devise"]},
                   effet={"rubrique": "Demandes N0 en brouillon", "devise": l["devise"], "montant": montant},
                   adaptateur="besoins")


def executer_besoins(t, ctx, a, res):
    p = a["payload"]
    id_ = V._create_operation_tx(t, ctx["user"], a["ref"], res.id("chantier", p["chantier_ref"]), p["post"],
                                 res.id("tiers", p["party_ref"]), p["label"], p["nature"], p["amount"], p["due"],
                                 p["account"], p["currency"], extra=provenance(ctx))
    correspondance(t, ctx, "besoin", a["ref"], id_, "Brouillon N0")
    return id_


BUDGETS = {"verifier": verifier_budgets, "executer": executer_budgets}
CUMULS = {"verifier": verifier_cumuls, "executer": executer_cumuls}
BESOINS = {"verifier": verifier_besoins, "executer": executer_besoins}
