"""Test de restauration (lot 0 V8, trimestriel) : recharge une sauvegarde dans une base TEMPORAIRE et compare.

    python scripts/test_restauration.py /srv/sauvegardes/bati-20261016-0200.json.gz

La base de production n'est jamais touchée : le script crée une base SQLite jetable, y applique les migrations,
restaure la sauvegarde, puis compare table par table le nombre de lignes et les montants. Il affiche un
procès-verbal et sort avec le code 0 seulement si tout concorde.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import sys
import tempfile
from unittest.mock import patch

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)


def _lire(chemin: str) -> bytes:
    with open(chemin, "rb") as f:
        brut = f.read()
    if os.path.exists(chemin + ".sha256"):
        with open(chemin + ".sha256", encoding="utf-8") as f:
            attendu = f.read().split()[0]
        if hashlib.sha256(brut).hexdigest() != attendu:
            raise ValueError("Empreinte SHA-256 différente de celle enregistrée : fichier altéré.")
    return gzip.decompress(brut) if chemin.endswith(".gz") else brut


def _somme(lignes: list[dict]) -> int:
    return sum(v for r in lignes for k, v in r.items() if k in ("amount", "budget", "paid") and isinstance(v, int))


def tester(chemin: str) -> tuple[bool, list[str]]:
    import sqlalchemy as sa
    import db
    import migration
    contenu = _lire(chemin)
    data = json.loads(contenu.decode("utf-8"))
    tmp = tempfile.mkdtemp(prefix="bati-restauration-")
    moteur = sa.create_engine("sqlite:///" + os.path.join(tmp, "restauration.db"))
    pv, ok = [f"Fichier : {os.path.basename(chemin)} · exportée le {data.get('exported_at', '?')}"], True
    with patch.object(db, "moteur", lambda: moteur):
        db.migrer(moteur)
        migration.import_json(contenu, role="admin")
        for nom in migration.METIER + migration.OPTIONNELLES:
            source = data["tables"].get(nom)
            if source is None:
                continue
            restaure = db.tout(nom)
            egal = len(source) == len(restaure) and _somme(source) == _somme(restaure)
            ok &= egal
            pv.append(f"{'OK ' if egal else 'ÉCART'} {nom} : {len(source)} → {len(restaure)} ligne(s)")
        pv.append(f"Schéma de la base de test : {db.version_schema(moteur)}")
    moteur.dispose()
    pv.append("RESTAURATION CONFORME" if ok else "RESTAURATION NON CONFORME")
    return ok, pv


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    try:
        ok, pv = tester(sys.argv[1])
    except Exception as e:  # noqa: BLE001
        print(f"ÉCHEC du test de restauration : {e}", file=sys.stderr)
        return 1
    print("\n".join(pv))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
