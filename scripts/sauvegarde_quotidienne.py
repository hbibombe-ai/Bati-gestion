"""Sauvegarde quotidienne de Bâti Gestion (lot 0 V8), à lancer par une tâche planifiée (cron) sur l'hébergement.

    DATABASE_URL=postgresql://… python scripts/sauvegarde_quotidienne.py --dossier /srv/sauvegardes --retention 30

Produit, horodatés :
- bati-AAAAMMJJ-HHMM.json.gz : sauvegarde applicative (même format que « Paramètres et sauvegarde »), restaurable
  dans l'application ;
- bati-AAAAMMJJ-HHMM.dump : copie complète PostgreSQL (pg_dump, comptes et paramètres compris) si pg_dump est
  disponible ;
- un fichier .sha256 par sauvegarde.
Les sauvegardes plus anciennes que la rétention (30 jours par défaut) sont supprimées, jamais la dernière.
Code de sortie non nul en cas d'échec, pour que l'hébergeur alerte.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import os
import shutil
import subprocess
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)


def _empreinte(chemin: str) -> None:
    h = hashlib.sha256()
    with open(chemin, "rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    with open(chemin + ".sha256", "w", encoding="utf-8") as f:
        f.write(f"{h.hexdigest()}  {os.path.basename(chemin)}\n")


def sauvegarder(dossier: str, retention: int, maintenant: dt.datetime | None = None) -> list[str]:
    import db
    import migration
    maintenant = maintenant or dt.datetime.now()
    os.makedirs(dossier, exist_ok=True)
    base = os.path.join(dossier, f"bati-{maintenant:%Y%m%d-%H%M}")
    produits = []
    with gzip.open(base + ".json.gz", "wb") as f:
        f.write(migration.export_json(avec_pieces=True))
    produits.append(base + ".json.gz")
    url = db.url_base()
    if url.startswith("postgresql") and shutil.which("pg_dump"):
        url_pg = url.replace("postgresql+psycopg2://", "postgresql://")
        subprocess.run(["pg_dump", "--format=custom", "--no-owner", f"--file={base}.dump", url_pg], check=True)
        produits.append(base + ".dump")
    for p in produits:
        _empreinte(p)
    purger(dossier, retention, maintenant)
    return produits


def purger(dossier: str, retention: int, maintenant: dt.datetime) -> list[str]:
    limite = maintenant - dt.timedelta(days=retention)
    fichiers = sorted(f for f in os.listdir(dossier) if f.startswith("bati-") and not f.endswith(".sha256"))
    supprimes = []
    for f in fichiers[:-2]:          # les deux dernières (JSON et dump) restent toujours
        try:
            date_f = dt.datetime.strptime(f[5:18], "%Y%m%d-%H%M")
        except ValueError:
            continue
        if date_f < limite:
            for c in (f, f + ".sha256"):
                if os.path.exists(os.path.join(dossier, c)):
                    os.remove(os.path.join(dossier, c))
            supprimes.append(f)
    return supprimes


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--dossier", default=os.environ.get("BG_SAUVEGARDES", os.path.join(RACINE, "sauvegardes")))
    p.add_argument("--retention", type=int, default=int(os.environ.get("BG_RETENTION_JOURS", "30")))
    a = p.parse_args()
    if a.retention < 30:
        print("Rétention minimale : 30 jours (mémo V8, § 11.4).", file=sys.stderr)
        return 2
    try:
        for f in sauvegarder(a.dossier, a.retention):
            print("Sauvegarde :", f)
    except Exception as e:  # noqa: BLE001
        print(f"ÉCHEC de la sauvegarde : {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
