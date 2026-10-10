"""Pièces et documents : la feuille Documents sert de manifeste ; les fichiers originaux sont chargés à part.

Chaque fichier est vérifié (type réel PDF/JPEG/PNG, 5 Mo au plus, empreinte SHA-256, absence de doublon) puis
conservé comme pièce « Préparée », rattachée au lot. Sa validation suit le contrôle habituel des justificatifs.
"""
from __future__ import annotations

import hashlib

import db
import regles as R
from imports.adapters.commun import correspondance, lignes, ok

MAX_FICHIERS = 200


def _mime(contenu: bytes):
    if contenu[:4] == b"%PDF":
        return "application/pdf"
    if contenu[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if contenu[:4] == b"\x89PNG":
        return "image/png"
    return None


def _cible(etat, res, entite, ref, ds):
    if entite == "lot":
        return True
    if entite == "tiers":
        return bool(res.tiers(ref))
    if entite == "chantier":
        return bool(res.chantier(ref))
    if entite == "personnel":
        return bool(res.personne(ref))
    if entite == "compte_tresorerie":
        return bool(res.compte(ref))
    feuille = {"facture_fournisseur": "Factures_Fournisseurs", "avance": "Avances", "besoin": "Besoins",
               "budget": "Budgets", "ecriture": "Ecritures"}[entite]
    return any(l.get("reference_externe") == ref for l in lignes(ds, feuille)) or bool(etat.mapping(entite, ref))


def verifier(ds, ctx, etat, res, rep):
    fichiers = ctx.get("fichiers") or {}
    manifeste = lignes(ds, "Documents")
    if not manifeste:
        return
    if len(fichiers) > MAX_FICHIERS:
        rep.erreur("Documents", 0, "", f"{MAX_FICHIERS} fichiers au plus par lot.")
        return
    hashes = {p["hash"] for p in etat.pieces}
    noms_vus = set()
    for l in manifeste:
        if not ok(l, "reference_externe", "entite_cible", "reference_cible", "nom_fichier", "type", "date"):
            continue
        line, nom = l["__line"], l["nom_fichier"]
        if nom in noms_vus:
            rep.erreur("Documents", line, "nom_fichier", "Fichier cité deux fois dans le manifeste.")
            continue
        noms_vus.add(nom)
        if not _cible(etat, res, l["entite_cible"], l["reference_cible"], ds):
            rep.erreur("Documents", line, "reference_cible", "Référence métier introuvable (fichier ou base).")
            continue
        contenu = fichiers.get(nom)
        if contenu is None:
            rep.erreur("Documents", line, "nom_fichier", "Fichier non chargé : joignez le fichier original portant ce nom.")
            continue
        mime = _mime(contenu)
        if not mime or len(contenu) > R.PIECE_MAX:
            rep.erreur("Documents", line, "nom_fichier", "Le contenu doit être un PDF, un JPEG ou un PNG de 5 Mo au plus.")
            continue
        h = hashlib.sha256(contenu).hexdigest()
        if l.get("empreinte_sha256") and l["empreinte_sha256"] != h:
            rep.erreur("Documents", line, "empreinte_sha256", "Empreinte différente : fichier modifié ou mauvais fichier.")
            continue
        if h in hashes:
            rep.erreur("Documents", line, "nom_fichier", "Ce fichier est déjà enregistré dans l’application.")
            continue
        hashes.add(h)
        rep.action("Documents", line, "Pièce jointe", l["reference_externe"], f"{l['type']} · {nom} → {l['entite_cible']} "
                   f"{l['reference_cible']} · statut Préparée (à valider)", "document",
                   {"nom": nom, "mime": mime, "hash": h, "type": l["type"], "date": l["date"],
                    "cible": f"{l['entite_cible']}:{l['reference_cible']}"}, adaptateur="documents")
    for nom in fichiers:
        if nom not in noms_vus:
            rep.alerte("Documents", 0, "nom_fichier", f"Fichier « {nom} » absent du manifeste : il ne sera pas importé.")


def executer(t, ctx, a, res):
    p = a["payload"]
    contenu = (ctx.get("fichiers") or {})[p["nom"]]
    if hashlib.sha256(contenu).hexdigest() != p["hash"]:
        raise ValueError(f"Le fichier {p['nom']} a changé depuis l’aperçu : relancez le contrôle.")
    id_ = db.nouvel_id()
    t.inserer("pieces", {"id": id_, "expense_id": "", "batch_id": ctx["lot_id"], "name": p["nom"], "mime": p["mime"],
                         "content": contenu, "size": len(contenu), "hash": p["hash"], "type": p["type"],
                         "beneficiary": p["cible"][:500], "document_date": p["date"], "amount": 0, "currency": "",
                         "status": "Préparée", "reason": "", "uploaded_at": db.maintenant(),
                         "uploaded_by": ctx["user"]["id"]}, resume=f"Import pièce {a['ref']}")
    correspondance(t, ctx, "document", a["ref"], id_, "Pièce jointe")
    return id_


DOCUMENTS = {"verifier": verifier, "executer": executer}
