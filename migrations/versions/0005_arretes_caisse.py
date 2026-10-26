"""Arrêtés de caisse (mémo V8, § 9.1) : procès-verbal de comptage, écart, validation par une autre personne.

Revision ID: 0005_arretes_caisse
Revises: 0004_socle_comptable
Create Date: 2026-10-24
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_arretes_caisse"
down_revision = "0004_socle_comptable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('caisse_arretes',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('caisse', sa.String(length=120), nullable=False),
    sa.Column('libelle_caisse', sa.String(length=300), nullable=False),
    sa.Column('devise', sa.String(length=3), nullable=False),
    sa.Column('date', sa.String(length=10), nullable=False),
    sa.Column('solde_theorique', sa.BigInteger(), nullable=False),
    sa.Column('billetage', sa.JSON(), nullable=False),
    sa.Column('autres', sa.BigInteger(), nullable=False),
    sa.Column('montant_compte', sa.BigInteger(), nullable=False),
    sa.Column('ecart', sa.BigInteger(), nullable=False),
    sa.Column('explication', sa.String(length=1000), nullable=False),
    sa.Column('statut', sa.String(length=20), nullable=False),
    sa.Column('saisi_par', sa.Integer(), nullable=False),
    sa.Column('saisi_le', sa.DateTime(), nullable=False),
    sa.Column('decide_par', sa.Integer(), nullable=True),
    sa.Column('decide_le', sa.DateTime(), nullable=True),
    sa.Column('motif_decision', sa.String(length=1000), nullable=True),
    sa.Column('mouvement_ecart', sa.String(length=80), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_caisse_arrete_caisse_date', 'caisse_arretes', ['caisse', 'date'], unique=False)


def downgrade() -> None:
    op.drop_table('caisse_arretes')
