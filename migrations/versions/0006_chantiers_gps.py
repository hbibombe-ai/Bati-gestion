"""Chantiers : coordonnées GPS facultatives (latitude, longitude) pour la carte des chantiers.

Revision ID: 0006_chantiers_gps
Revises: 0005_arretes_caisse
Create Date: 2026-11-06
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_chantiers_gps"
down_revision = "0005_arretes_caisse"
branch_labels = None
depends_on = None


def _colonnes() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("projects")}


def upgrade() -> None:
    existantes = _colonnes()          # base reprise : les colonnes peuvent déjà exister
    for nom in ("latitude", "longitude"):
        if nom not in existantes:
            op.add_column("projects", sa.Column(nom, sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("projects") as b:
        b.drop_column("longitude")
        b.drop_column("latitude")
