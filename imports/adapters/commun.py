"""Outils communs aux adaptateurs."""
from __future__ import annotations

import db


def lignes(ds, feuille):
    return ds["feuilles"].get(feuille) or []


def ok(row, *champs):
    """Vrai si les champs ont pu être normalisés (une erreur de format est déjà signalée)."""
    return all(row.get(c) is not None for c in champs)


def correspondance(t, ctx, entite, ref, id_interne, effet):
    """Enregistre la table de correspondance (référence externe → identifiant interne) pour ce lot."""
    m = db.TABLES["import_mappings"]
    existe = t.cx.execute(m.select().where(m.c.entite == entite, m.c.reference_externe == ref)).first()
    if existe:
        if existe._mapping["id_interne"] != id_interne:
            raise ValueError(f"Correspondance {entite} « {ref} » déjà utilisée par un autre lot.")
        return
    t.inserer("import_mappings", {"id": db.nouvel_id(), "lot_id": ctx["lot_id"], "entite": entite,
                                  "reference_externe": ref, "id_interne": id_interne, "effet": effet},
              resume=f"Correspondance {entite} {ref}")


def verifier_chantier_contexte(ctx, res, feuille, row, rep, champ="chantier_ref"):
    """Si l'import est limité à un chantier, toute référence de chantier doit le désigner."""
    if not ctx.get("chantier") or not row.get(champ):
        return True
    r = res.chantier(row[champ])
    if r and r.get("source") == "base" and r["id"] == ctx["chantier"]:
        return True
    rep.erreur(feuille, row["__line"], champ, "Le lot est limité au chantier choisi à l’écran.")
    return False


def provenance(ctx):
    return {"import_lot": ctx.get("lot_id", ""), "import_lot_ref": ctx.get("lot_ref", ""),
            "import_source": ctx.get("source_systeme", ""), "import_mode": ctx["mode"]}


def ref_v7(ctx, nature, ref):
    """Référence V7 lisible et unique par lot (un lot corrigé ne réutilise pas les références du lot remplacé)."""
    return f"{ctx['lot_ref']}/{ctx['lot_id'][:6]}:{nature}:{ref}"[:200]
