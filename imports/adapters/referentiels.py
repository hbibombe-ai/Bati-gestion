"""Référentiels : tiers, chantiers, personnel, affectations et présences."""
from __future__ import annotations

import re

import db
import regles as R
from imports import schema as S
from imports.adapters.commun import correspondance, lignes, ok, verifier_chantier_contexte
from imports.validation import norm


# ------------------------------------------------------------------ tiers
def _roles(txt):
    roles = []
    for r in re.split(r"[;,]", txt or ""):
        r = norm(r).replace(" ", "")
        if not r:
            continue
        if r not in S.ROLES_TIERS:
            raise ValueError("Rôle inconnu : utiliser client, fournisseur ou sous-traitant.")
        if S.ROLES_TIERS[r] not in roles:
            roles.append(S.ROLES_TIERS[r])
    if not roles:
        raise ValueError("Au moins un rôle est requis.")
    return roles


def verifier_tiers(ds, ctx, etat, res, rep):
    noms_fichier = {}
    for l in lignes(ds, "Tiers"):
        if not ok(l, "reference_externe", "nom", "roles"):
            continue
        ref, line = l["reference_externe"], l["__line"]
        try:
            roles = _roles(l["roles"])
        except ValueError as e:
            rep.erreur("Tiers", line, "roles", str(e))
            continue
        if l.get("email") and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", l["email"]):
            rep.erreur("Tiers", line, "email", "Adresse e-mail invalide.")
        n = norm(l["nom"])
        if n in noms_fichier:
            rep.erreur("Tiers", line, "nom", f"Même nom que la ligne {noms_fichier[n]} : un seul tiers par nom.")
        noms_fichier.setdefault(n, line)
        par_code = next((c for c in etat.clients if norm(c["code"]) == norm(ref)), None)
        par_nom = next((c for c in etat.clients if norm(c["name"]) == n), None)
        payload = {"code": ref, "name": l["nom"], "phone": l.get("telephone") or "", "email": l.get("email") or "",
                   "address": l.get("adresse") or "", "registration": l.get("identification") or "", "roles": roles}
        if par_code:
            if norm(par_code["name"]) != n:
                rep.erreur("Tiers", line, "reference_externe", f"Code déjà attribué au tiers « {par_code['name']} ».")
                continue
            manquants = set(roles) - set(R.party_roles(par_code))
            if manquants:
                rep.alerte("Tiers", line, "roles", "Rôles absents de la fiche existante, non modifiée : "
                           + ", ".join(R.PARTY_ROLES[r] for r in manquants) + ". Complétez la fiche si nécessaire.")
            res.declarer("tiers", ref, {**payload, "roles": R.party_roles(par_code)}, "Tiers")
            res.fixer("tiers", ref, par_code["id"])
            rep.action("Tiers", line, "Correspondance", ref, f"Tiers existant {par_code['name']}", "tiers",
                       {"id": par_code["id"]}, adaptateur="tiers")
        elif par_nom:
            rep.erreur("Tiers", line, "nom", f"Ce nom existe déjà sous le code {par_nom['code']} : utilisez ce code.")
        else:
            res.declarer("tiers", ref, payload, "Tiers")
            rep.action("Tiers", line, "Création", ref, l["nom"] + " · " + ", ".join(R.PARTY_ROLES[r] for r in roles),
                       "tiers", payload, adaptateur="tiers")


def executer_tiers(t, ctx, a, res):
    if a["action"] == "Correspondance":
        correspondance(t, ctx, "tiers", a["ref"], a["payload"]["id"], "Correspondance")
        return a["payload"]["id"]
    id_ = db.nouvel_id()
    t.inserer("clients", {"id": id_, **a["payload"], "archived": False}, resume=f"Import tiers {a['ref']}")
    res.fixer("tiers", a["ref"], id_)
    correspondance(t, ctx, "tiers", a["ref"], id_, "Création")
    return id_


# ------------------------------------------------------------------ chantiers
def verifier_chantiers(ds, ctx, etat, res, rep):
    for l in lignes(ds, "Chantiers"):
        if not ok(l, "reference_externe", "nom", "devise", "etat", "avancement"):
            continue
        ref, line = l["reference_externe"], l["__line"]
        if ctx.get("chantier"):
            rep.erreur("Chantiers", line, "", "Un lot limité à un chantier ne peut pas créer de chantier.")
            continue
        if l["etat"] == "À démarrer" and l["avancement"] != 0:
            rep.erreur("Chantiers", line, "avancement", "Un chantier à démarrer doit avoir un avancement nul.")
        if l["etat"] == "Terminé" and l["avancement"] != 100:
            rep.erreur("Chantiers", line, "avancement", "Un chantier terminé doit être avancé à 100 %.")
        client = ""
        if l.get("client_ref"):
            c = res.tiers(l["client_ref"])
            if not c:
                rep.erreur("Chantiers", line, "client_ref", "Client introuvable (feuille Tiers ou base).")
                continue
            roles = c["row"].get("roles", []) if c["source"] == "fichier" else R.party_roles(c["fiche"])
            if "client" not in roles:
                rep.erreur("Chantiers", line, "client_ref", "Ce tiers n’a pas le rôle Client.")
                continue
            client = c["id"] or ("@tiers:" + l["client_ref"])
        payload = {"name": l["nom"], "client": client, "location": l.get("lieu") or "", "deadline": l.get("date_fin") or "",
                   "budget": l.get("budget_historique") or 0, "currency": l["devise"], "status": l["etat"],
                   "progress": float(l["avancement"])}
        m = etat.mapping("chantier", ref)
        existant = next((p for p in etat.projects if m and p["id"] == m["id_interne"]), None) or \
            next((p for p in etat.projects if norm(p["name"]) == norm(l["nom"])), None)
        if existant:
            if existant["currency"] != l["devise"]:
                rep.erreur("Chantiers", line, "devise", f"Le chantier existant « {existant['name']} » est tenu en "
                                                        f"{existant['currency']} : aucune conversion implicite.")
                continue
            res.declarer("chantier", ref, payload, "Chantiers")
            res.fixer("chantier", ref, existant["id"])
            rep.action("Chantiers", line, "Correspondance", ref, f"Chantier existant {existant['name']} (fiche non modifiée)",
                       "chantier", {"id": existant["id"]}, adaptateur="chantiers")
            if not m:
                rep.alerte("Chantiers", line, "nom", f"Rapprochement par le nom avec le chantier existant « {existant['name']} ».",
                           decision=True)
        else:
            res.declarer("chantier", ref, payload, "Chantiers")
            rep.action("Chantiers", line, "Création", ref, f"{l['nom']} · {l['devise']} · {l['etat']}", "chantier",
                       payload, adaptateur="chantiers")
        if l.get("montant_contrat"):
            rep.alerte("Chantiers", line, "montant_contrat", "Montant du contrat conservé dans le lot ; il est repris "
                       "par la feuille Budgets (montant contractuel V7).")


def executer_chantiers(t, ctx, a, res):
    if a["action"] == "Correspondance":
        correspondance(t, ctx, "chantier", a["ref"], a["payload"]["id"], "Correspondance")
        return a["payload"]["id"]
    p = dict(a["payload"])
    if p["client"].startswith("@tiers:"):
        p["client"] = res.id("tiers", p["client"][7:])
    id_ = db.nouvel_id()
    t.inserer("projects", {"id": id_, **p}, resume=f"Import chantier {a['ref']}")
    res.fixer("chantier", a["ref"], id_)
    correspondance(t, ctx, "chantier", a["ref"], id_, "Création")
    return id_


# ------------------------------------------------------------------ personnel
def verifier_personnel(ds, ctx, etat, res, rep):
    for l in lignes(ds, "Personnel"):
        if not ok(l, "reference_externe", "nom", "fonction", "date_engagement", "lieu", "actif"):
            continue
        ref, line = l["reference_externe"], l["__line"]
        if l["date_engagement"] > R.today():
            rep.erreur("Personnel", line, "date_engagement", "Date d’engagement dans le futur.")
        projet = ""
        if l["lieu"] == "Chantier":
            if not l.get("chantier_ref"):
                rep.erreur("Personnel", line, "chantier_ref", "Chantier d’affectation obligatoire.")
                continue
            c = res.chantier(l["chantier_ref"])
            if not c:
                rep.erreur("Personnel", line, "chantier_ref", "Chantier introuvable.")
                continue
            projet = c["id"] or "@chantier:" + l["chantier_ref"]
        sal = [l.get(k) for k in ("salaire_base", "devise_salaire", "periode_salaire", "salaire_effet")]
        salaire = None
        if any(v not in (None, "") for v in sal):
            if any(v in (None, "") for v in sal):
                rep.erreur("Personnel", line, "salaire_base", "Salaire incomplet : montant, devise, période et date d’effet.")
                continue
            if sal[3] < l["date_engagement"]:
                rep.erreur("Personnel", line, "salaire_effet", "Le salaire doit prendre effet après l’engagement.")
                continue
            salaire = {"amount": sal[0], "currency": sal[1], "period": sal[2], "effective": sal[3]}
        existant = next((p for p in etat.personnel if norm(p["code"]) == norm(ref)), None)
        payload = {"code": ref, "name": l["nom"], "job": l["fonction"], "service": l.get("service") or "",
                   "phone": l.get("telephone") or "", "start": l["date_engagement"], "location": l["lieu"],
                   "project": projet, "active": bool(l["actif"]), "v7": {},
                   "details": {"contractType": l.get("type_contrat") or "À préciser",
                               "contractReference": l.get("reference_contrat") or "",
                               "contractEnd": l.get("fin_contrat") or "", "notes": "Repris par import"},
                   "salary": salaire,
                   "assignments": [{"date": l["date_engagement"], "location": l["lieu"], "project": projet}]}
        if existant:
            if norm(existant["name"]) != norm(l["nom"]):
                rep.erreur("Personnel", line, "reference_externe", "Matricule déjà attribué à une autre personne.")
                continue
            res.declarer("personnel", ref, existant, "Personnel")
            res.fixer("personnel", ref, existant["id"])
            rep.action("Personnel", line, "Correspondance", ref, "Fiche existante non modifiée", "personnel",
                       {"id": existant["id"]}, adaptateur="personnel")
        else:
            res.declarer("personnel", ref, payload, "Personnel")
            rep.action("Personnel", line, "Création", ref, f"{l['fonction']} · {l['lieu']}"
                       + (" · salaire confidentiel" if salaire else ""), "personnel", payload, adaptateur="personnel")


def executer_personnel(t, ctx, a, res):
    if a["action"] == "Correspondance":
        correspondance(t, ctx, "personnel", a["ref"], a["payload"]["id"], "Correspondance")
        return a["payload"]["id"]
    p = dict(a["payload"])
    if p["project"].startswith("@chantier:"):
        p["project"] = res.id("chantier", p["project"][10:])
        p["assignments"] = [{**x, "project": p["project"]} for x in p["assignments"]]
    id_ = db.nouvel_id()
    t.inserer("personnel", {"id": id_, **p}, resume=f"Import fiche personnel {a['ref']}")
    res.fixer("personnel", a["ref"], id_)
    correspondance(t, ctx, "personnel", a["ref"], id_, "Création")
    return id_


def verifier_affectations(ds, ctx, etat, res, rep):
    par_personne = {}
    for l in sorted(lignes(ds, "Affectations"), key=lambda x: (x.get("matricule") or "", x.get("date_debut") or "")):
        if not ok(l, "reference_externe", "matricule", "date_debut", "lieu"):
            continue
        line = l["__line"]
        p = res.personne(l["matricule"])
        if not p:
            rep.erreur("Affectations", line, "matricule", "Matricule introuvable.")
            continue
        fiche = p["row"] if p["source"] == "fichier" else p["fiche"]
        dates = par_personne.setdefault(l["matricule"], [a["date"] for a in fiche.get("assignments") or []])
        if l["date_debut"] < fiche["start"] or any(d >= l["date_debut"] for d in dates):
            rep.erreur("Affectations", line, "date_debut", "Une nouvelle affectation doit suivre l’engagement et les "
                                                           "affectations déjà enregistrées.")
            continue
        projet = ""
        if l["lieu"] == "Chantier":
            c = res.chantier(l.get("chantier_ref") or "")
            if not c:
                rep.erreur("Affectations", line, "chantier_ref", "Chantier introuvable.")
                continue
            projet = c["id"] or "@chantier:" + l["chantier_ref"]
        dates.append(l["date_debut"])
        rep.action("Affectations", line, "Création", l["reference_externe"], f"{l['matricule']} → {l['lieu']} le {l['date_debut']}",
                   "affectation", {"matricule": l["matricule"], "date": l["date_debut"], "location": l["lieu"],
                                   "project": projet}, adaptateur="affectations")


def executer_affectations(t, ctx, a, res):
    p = a["payload"]
    pid = res.id("personnel", p["matricule"])
    projet = res.id("chantier", p["project"][10:]) if p["project"].startswith("@chantier:") else p["project"]
    fiche = t.get("personnel", pid, verrou=True)
    affs = sorted((fiche.get("assignments") or []) + [{"date": p["date"], "location": p["location"], "project": projet}],
                  key=lambda x: x["date"])
    maj = {"assignments": affs}
    if affs[-1]["date"] == p["date"]:
        maj.update(location=p["location"], project=projet)
    t.maj("personnel", pid, maj, resume=f"Import affectation {a['ref']}")
    correspondance(t, ctx, "affectation", a["ref"], pid, "Création")
    return pid


# ------------------------------------------------------------------ présences
def verifier_presences(ds, ctx, etat, res, rep):
    vus = {}
    existants = {(x["person_id"], x["date"]): x for x in etat.attendance}
    for l in lignes(ds, "Presences"):
        if not ok(l, "matricule", "date", "statut", "heures"):
            continue
        line = l["__line"]
        p = res.personne(l["matricule"])
        if not p:
            rep.erreur("Presences", line, "matricule", "Matricule introuvable.")
            continue
        fiche = p["row"] if p["source"] == "fichier" else p["fiche"]
        if l["date"] > R.today() or l["date"] < fiche["start"]:
            rep.erreur("Presences", line, "date", "La date doit être comprise entre l’engagement et aujourd’hui.")
            continue
        if l["statut"] in R.ZERO_HOUR_STATUSES and l["heures"] != 0:
            rep.erreur("Presences", line, "heures", "Heures nulles exigées pour ce statut.")
            continue
        if l["heures"] > 24:
            rep.erreur("Presences", line, "heures", "Plus de 24 heures dans la journée.")
            continue
        cle = (l["matricule"].lower(), l["date"])
        if cle in vus:
            rep.erreur("Presences", line, "date", f"Personne déjà pointée ce jour dans le fichier (ligne {vus[cle]}).")
            continue
        vus[cle] = line
        lieu = (l.get("lieu") or "").strip()
        if lieu.lower() == "bureau":
            aff = {"location": "Bureau", "project": ""}
        elif lieu:
            c = res.chantier(lieu)
            if not c:
                rep.erreur("Presences", line, "lieu", "Lieu inconnu : « bureau » ou référence de chantier.")
                continue
            aff = {"location": "Chantier", "project": c["id"] or "@chantier:" + lieu}
        else:
            aff = R.hr_assignment_at(fiche, l["date"]) if fiche.get("assignments") else None
            if not aff:
                rep.erreur("Presences", line, "lieu", "Aucune affectation connue à cette date : indiquez le lieu.")
                continue
            aff = {"location": aff["location"], "project": aff.get("project", "")}
        row = {"status": l["statut"], "hours": float(l["heures"]), "date": l["date"],
               "note": " – ".join(x for x in ["Import Excel lot " + ctx.get("lot_ref", ""), l.get("observation") or ""] if x)[:1000],
               **aff}
        ex = existants.get((p.get("id"), l["date"])) if p["source"] == "base" else None
        if ex:
            if ex["status"] == row["status"] and abs((ex["hours"] or 0) - row["hours"]) < 0.01:
                rep.action("Presences", line, "Ignoré (identique)", l["matricule"] + " " + l["date"],
                           "Pointage déjà présent (saisie ou KoboCollect)", "", {}, adaptateur="presences")
            else:
                rep.erreur("Presences", line, "date", f"Conflit avec un pointage existant ({ex['status']}, {ex['hours']:g} h) : "
                                                      "corrigez dans « Personnel et pointage » ou retirez la ligne.")
            continue
        rep.action("Presences", line, "Création", l["matricule"] + " " + l["date"], f"{l['statut']} · {l['heures']:g} h",
                   "", {"matricule": l["matricule"], **row}, adaptateur="presences")


def executer_presences(t, ctx, a, res):
    if a["action"].startswith("Ignoré"):
        return ""
    p = dict(a["payload"])
    pid = res.id("personnel", p.pop("matricule"))
    if p["project"].startswith("@chantier:"):
        p["project"] = res.id("chantier", p["project"][10:])
    if t.lire("select id from attendance where person_id = :p and date = :d", p=pid, d=p["date"]):
        raise ValueError(f"Pointage du {p['date']} créé entre-temps : relancez le contrôle.")
    return t.inserer("attendance", {"person_id": pid, **p}, resume=f"Import pointage {a['ref']}")


TIERS = {"verifier": verifier_tiers, "executer": executer_tiers}
CHANTIERS = {"verifier": verifier_chantiers, "executer": executer_chantiers}
PERSONNEL = {"verifier": verifier_personnel, "executer": executer_personnel}
AFFECTATIONS = {"verifier": verifier_affectations, "executer": executer_affectations}
PRESENCES = {"verifier": verifier_presences, "executer": executer_presences}
