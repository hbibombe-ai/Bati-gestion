"""Demandes d'achat matériel et matériaux (brouillons) et chiffrage par les achats, depuis Excel.

Les contrôles reprennent ceux de la saisie à l'écran (achats_circuit.py) : chantier avec budget DQE approuvé, devise du
budget, poste DQE, fournisseur enregistré, chantiers affectés à l'usager, séparation des responsabilités.
"""
from __future__ import annotations

from decimal import Decimal

import achats_circuit as A
import gestion_v7 as V
import regles as R
from imports.adapters.commun import correspondance, lignes, ok, provenance, verifier_chantier_contexte
from imports.validation import norm


def _budget(etat, projet_id):
    return next((b for b in etat.budgets_actifs() if b["project"] == projet_id), None)


def _fournisseur(res, ref):
    """Fournisseur connu (base ou fichier) ayant le rôle fournisseur ou sous-traitant ; None sinon."""
    t_ = res.tiers(ref)
    if not t_:
        return None
    if t_["source"] == "base":
        c = t_["fiche"]
        return t_ if not c.get("archived") and set(R.party_roles(c)) & {"supplier", "subcontractor"} else None
    roles = norm((t_.get("row") or {}).get("roles"))
    return t_ if "fournisseur" in roles or "sous" in roles else None


# ------------------------------------------------------------------ demandes d'achat
def verifier_demandes(ds, ctx, etat, res, rep):
    u = ctx["user"]
    par_demande: dict[str, list] = {}
    for l in lignes(ds, "Lignes_Demande_Achat"):
        par_demande.setdefault(l.get("demande_ref"), []).append(l)
    refs = {norm(r["ref"]) for r in etat.v7_kind(A.KIND)}
    for h in lignes(ds, "Demandes_Achat"):
        if not ok(h, "reference_externe", "chantier_ref", "objet", "date_besoin", "devise"):
            continue
        ref, line = h["reference_externe"], h["__line"]
        if not verifier_chantier_contexte(ctx, res, "Demandes_Achat", h, rep):
            continue
        if norm(ref) in refs or etat.mapping("demande_achat", ref):
            rep.erreur("Demandes_Achat", line, "reference_externe", "Référence de demande déjà utilisée.")
            continue
        c = res.chantier(h["chantier_ref"])
        if not c or not c.get("id"):
            rep.erreur("Demandes_Achat", line, "chantier_ref", "Chantier existant avec budget DQE approuvé requis.")
            continue
        if not etat.sur_chantier(u, c["id"]):
            rep.erreur("Demandes_Achat", line, "chantier_ref", "Chantier hors de votre périmètre (chantiers affectés).")
            continue
        b = _budget(etat, c["id"])
        if not b or b["data"]["status"] != "Approuvé":
            rep.erreur("Demandes_Achat", line, "chantier_ref", "Budget DQE approuvé requis avant une demande d’achat.")
            continue
        if h["devise"] != b["currency"]:
            rep.erreur("Demandes_Achat", line, "devise", f"Le budget est en {b['currency']} : aucune conversion implicite.")
            continue
        enfants = sorted(par_demande.get(ref, []), key=lambda x: x.get("numero_ligne") or 0)
        if not enfants:
            rep.erreur("Demandes_Achat", line, "reference_externe", "Aucune ligne dans la feuille Lignes_Demande_Achat.")
            continue
        if len(enfants) > A.LIGNES_MAX:
            rep.erreur("Demandes_Achat", line, "reference_externe", f"{A.LIGNES_MAX} lignes au plus par demande.")
            continue
        postes = {x["code"] for x in b["data"]["lines"]}
        sorties, valide, total = [], True, 0
        for e in enfants:
            if not ok(e, "numero_ligne", "code_dqe", "article", "quantite"):
                valide = False
                continue
            if e["code_dqe"] not in postes:
                rep.erreur("Lignes_Demande_Achat", e["__line"], "code_dqe", "Poste DQE absent du budget du chantier.")
                valide = False
            if not e["quantite"]:
                rep.erreur("Lignes_Demande_Achat", e["__line"], "quantite", "Quantité positive requise.")
                valide = False
            if e.get("prix_unitaire") is not None and e["prix_unitaire"] <= 0:
                rep.erreur("Lignes_Demande_Achat", e["__line"], "prix_unitaire", "Prix positif requis (ou laisser vide).")
                valide = False
            if e.get("fournisseur_ref") and not _fournisseur(res, e["fournisseur_ref"]):
                rep.erreur("Lignes_Demande_Achat", e["__line"], "fournisseur_ref",
                           "Fournisseur introuvable, archivé ou sans rôle fournisseur.")
                valide = False
            if e.get("prix_unitaire"):
                total += A.montant_ligne(e["quantite"], e["prix_unitaire"])
            sorties.append({"post": e["code_dqe"], "article": e["article"], "unite": e.get("unite") or "",
                            "quantite": e["quantite"], "prix": e.get("prix_unitaire"),
                            "fournisseur_ref": e.get("fournisseur_ref") or "", "note": e.get("note") or ""})
        if not valide:
            continue
        rep.action("Demandes_Achat", line, "Demande d’achat en brouillon", ref,
                   f"{h['objet']} · {len(sorties)} ligne(s) · à soumettre au chef de chantier",
                   "demande_achat", {"chantier_ref": h["chantier_ref"], "objet": h["objet"],
                                     "lieu": h.get("lieu_livraison") or "", "date_besoin": h["date_besoin"],
                                     "lignes": sorties},
                   effet={"rubrique": "Demandes d’achat en brouillon (prix proposés)", "devise": h["devise"],
                          "montant": total},
                   adaptateur="demandes_achat")


def executer_demandes(t, ctx, a, res):
    p = a["payload"]
    lignes_ = [{**{k: v for k, v in l.items() if k != "fournisseur_ref"},
                "fournisseur": res.id("tiers", l["fournisseur_ref"]) if l["fournisseur_ref"] else ""}
               for l in p["lignes"]]
    id_ = A._creer_tx(t, ctx["user"], res.id("chantier", p["chantier_ref"]), p["objet"], p["lieu"], p["date_besoin"],
                      lignes_, ref=a["ref"], extra=provenance(ctx))
    correspondance(t, ctx, "demande_achat", a["ref"], id_, "Demande d’achat en brouillon")
    return id_


# ------------------------------------------------------------------ chiffrage
def verifier_chiffrage(ds, ctx, etat, res, rep):
    u = ctx["user"]
    par_demande: dict[str, list] = {}
    for l in lignes(ds, "Chiffrage_Achats"):
        if ok(l, "demande_ref", "numero_ligne"):
            par_demande.setdefault(norm(l["demande_ref"]), []).append(l)
    if par_demande and not V.peut(u, "chiffrage_achats"):
        return  # refus déjà signalé par le contrôle des droits
    demandes = {norm(r["ref"]): r for r in etat.v7_kind(A.KIND)}
    for ref, rows in par_demande.items():
        premiere = rows[0]["__line"]
        r = demandes.get(ref)
        if not r:
            rep.erreur("Chiffrage_Achats", premiere, "demande_ref", "Demande d’achat introuvable.")
            continue
        d = r["data"]
        if d["statut"] != "Validée chantier":
            rep.erreur("Chiffrage_Achats", premiere, "demande_ref",
                       f"Demande au statut « {d['statut']} » : chiffrage après la validation chantier seulement.")
            continue
        if u["id"] in (d["creator"], (d.get("validations") or {}).get("chantier", {}).get("user")):
            rep.erreur("Chiffrage_Achats", premiere, "demande_ref", "Séparation des responsabilités : le chiffrage est "
                       "fait par une autre personne que le demandeur et le valideur du chantier.")
            continue
        par_n = {l["n"]: l for l in d["lignes"]}
        cotations, valide, vus = {}, True, set()
        for row in rows:
            n, line = row["numero_ligne"], row["__line"]
            if n in vus:
                rep.erreur("Chiffrage_Achats", line, "numero_ligne", "Ligne citée deux fois pour cette demande.")
                valide = False
                continue
            vus.add(n)
            if n not in par_n:
                rep.erreur("Chiffrage_Achats", line, "numero_ligne", "Numéro de ligne absent de la demande.")
                valide = False
                continue
            c = {}
            if row.get("fournisseur_ref"):
                f = _fournisseur(res, row["fournisseur_ref"])
                if not f or f["source"] != "base":
                    rep.erreur("Chiffrage_Achats", line, "fournisseur_ref",
                               "Fournisseur enregistré (rôle fournisseur ou sous-traitant) requis.")
                    valide = False
                    continue
                c["fournisseur"] = f["id"]
            if row.get("prix_unitaire") is not None:
                if row["prix_unitaire"] <= 0:
                    rep.erreur("Chiffrage_Achats", line, "prix_unitaire", "Prix positif requis.")
                    valide = False
                    continue
                c["prix"] = row["prix_unitaire"]
            if row.get("quantite_stock") is not None:
                if Decimal(str(row["quantite_stock"])) > Decimal(str(par_n[n]["quantite"])):
                    rep.erreur("Chiffrage_Achats", line, "quantite_stock", "Quantité servie supérieure à la quantité demandée.")
                    valide = False
                    continue
                c["qte_stock"] = row["quantite_stock"]
            cotations[n] = c
        if not valide:
            continue
        # Simulation : chaque ligne restant à acheter doit avoir un prix et un fournisseur.
        total, manquantes = 0, []
        for n, l in par_n.items():
            c = cotations.get(n, {})
            q = max(0.0, float(l["quantite"]) - float(c.get("qte_stock", l.get("qte_stock") or 0)))
            prix, fournisseur = c.get("prix", l.get("prix")), c.get("fournisseur", l.get("fournisseur"))
            if q and (prix is None or not fournisseur):
                manquantes.append(str(n))
            elif q:
                total += A.montant_ligne(q, prix)
        if manquantes:
            rep.erreur("Chiffrage_Achats", premiere, "demande_ref",
                       f"Prix ou fournisseur manquant pour la ligne {', '.join(manquantes)} de la demande.")
            continue
        rep.action("Chiffrage_Achats", premiere, "Chiffrage", r["ref"],
                   f"{len(cotations)} ligne(s) chiffrée(s) · {R.money(total, r['currency'])} · puis coordonnateur ou V7",
                   "chiffrage_achats", {"demande": r["id"], "cotations": {str(k): v for k, v in cotations.items()}},
                   effet={"rubrique": "Demandes d’achat chiffrées", "devise": r["currency"], "montant": total},
                   adaptateur="chiffrage_achats")


def executer_chiffrage(t, ctx, a, res):
    p = a["payload"]
    A._chiffrer_tx(t, ctx["user"], p["demande"], {int(k): v for k, v in p["cotations"].items()},
                   extra_note=f"import {ctx.get('lot_ref', '')}")
    correspondance(t, ctx, "chiffrage_achats", a["ref"], p["demande"], "Demande chiffrée")
    return p["demande"]


DEMANDES = {"verifier": verifier_demandes, "executer": executer_demandes}
CHIFFRAGE = {"verifier": verifier_chiffrage, "executer": executer_chiffrage}
