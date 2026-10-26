"""Environnement Alembic de Bâti Gestion.

Appelé par l'application au démarrage (db.migrer, connexion fournie) ou en ligne de commande :
    DATABASE_URL=postgresql://… alembic upgrade head
"""
from __future__ import annotations

import os
import sys

from alembic import context
import sqlalchemy as sa

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db  # noqa: E402

config = context.config
target_metadata = db.meta


def _executer(connexion) -> None:
    context.configure(connection=connexion, target_metadata=target_metadata,
                      render_as_batch=connexion.dialect.name == "sqlite", compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


connexion = config.attributes.get("connection")
if connexion is not None:
    _executer(connexion)
elif context.is_offline_mode():
    context.configure(url=db.url_base(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    moteur = sa.create_engine(db.url_base())
    with moteur.connect() as c:
        _executer(c)
        c.commit()
