"""Socle comptable V8 (mémo § 2 et § 3) : plan de comptes, journaux, périodes, pièces, lignes, règles comptables.
Les comptes, journaux et règles par défaut sont créés à la première comptabilisation (comptabilisation.assurer_socle).

Revision ID: 0004_socle_comptable
Revises: 0003_achats_stocks
Create Date: 2026-10-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_socle_comptable"
down_revision = "0003_achats_stocks"
branch_labels = None
depends_on = None

TABLES = ['cpt_comptes', 'cpt_periodes', 'regles_comptables', 'cpt_journaux', 'cpt_pieces', 'cpt_lignes']


def upgrade() -> None:

    op.create_table('cpt_comptes',
    sa.Column('numero', sa.String(length=20), nullable=False),
    sa.Column('libelle', sa.String(length=300), nullable=False),
    sa.Column('classe', sa.Integer(), nullable=False),
    sa.Column('collectif', sa.Boolean(), nullable=False),
    sa.Column('actif', sa.Boolean(), nullable=False),
    sa.Column('origine', sa.String(length=30), nullable=False),
    sa.Column('cree_par', sa.Integer(), nullable=True),
    sa.Column('cree_le', sa.DateTime(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('numero')
    )
    op.create_table('cpt_periodes',
    sa.Column('id', sa.String(length=7), nullable=False),
    sa.Column('exercice', sa.Integer(), nullable=False),
    sa.Column('statut', sa.String(length=30), nullable=False),
    sa.Column('historique', sa.JSON(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('regles_comptables',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('evenement', sa.String(length=40), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('journal', sa.String(length=10), nullable=False),
    sa.Column('schema', sa.JSON(), nullable=False),
    sa.Column('date_effet', sa.String(length=10), nullable=False),
    sa.Column('statut', sa.String(length=20), nullable=False),
    sa.Column('motif', sa.Text(), nullable=False),
    sa.Column('propose_par', sa.Integer(), nullable=True),
    sa.Column('active_par', sa.Integer(), nullable=True),
    sa.Column('active_le', sa.DateTime(), nullable=True),
    sa.Column('cree_le', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('evenement', 'version', name='un_regle_version')
    )
    op.create_table('cpt_journaux',
    sa.Column('code', sa.String(length=10), nullable=False),
    sa.Column('libelle', sa.String(length=200), nullable=False),
    sa.Column('type', sa.String(length=10), nullable=False),
    sa.Column('compte_tresorerie', sa.String(length=20), nullable=True),
    sa.Column('v7_compte', sa.String(length=80), nullable=True),
    sa.Column('actif', sa.Boolean(), nullable=False),
    sa.Column('cree_par', sa.Integer(), nullable=True),
    sa.Column('cree_le', sa.DateTime(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['compte_tresorerie'], ['cpt_comptes.numero'], ),
    sa.PrimaryKeyConstraint('code'),
    sa.UniqueConstraint('v7_compte')
    )
    op.create_table('cpt_pieces',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('journal', sa.String(length=10), nullable=False),
    sa.Column('exercice', sa.Integer(), nullable=False),
    sa.Column('numero', sa.Integer(), nullable=False),
    sa.Column('date', sa.String(length=10), nullable=False),
    sa.Column('libelle', sa.String(length=300), nullable=False),
    sa.Column('source_type', sa.String(length=40), nullable=False),
    sa.Column('source_id', sa.String(length=80), nullable=False),
    sa.Column('evenement', sa.String(length=40), nullable=False),
    sa.Column('regle_version', sa.Integer(), nullable=False),
    sa.Column('devise_tenue', sa.String(length=3), nullable=False),
    sa.Column('statut', sa.String(length=20), nullable=False),
    sa.Column('contre_passe', sa.String(length=80), nullable=True),
    sa.Column('cree_par', sa.Integer(), nullable=True),
    sa.Column('cree_le', sa.DateTime(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['journal'], ['cpt_journaux.code'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('journal', 'exercice', 'numero', name='un_piece_numero')
    )
    op.create_index('ix_cpt_piece_source', 'cpt_pieces', ['source_type', 'source_id'], unique=False)
    op.create_table('cpt_lignes',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('piece', sa.String(length=80), nullable=False),
    sa.Column('numero', sa.Integer(), nullable=False),
    sa.Column('compte', sa.String(length=20), nullable=False),
    sa.Column('tiers', sa.String(length=80), nullable=True),
    sa.Column('projet', sa.String(length=80), nullable=True),
    sa.Column('poste', sa.String(length=80), nullable=True),
    sa.Column('centre', sa.String(length=80), nullable=True),
    sa.Column('libelle', sa.String(length=300), nullable=False),
    sa.Column('debit', sa.BigInteger(), nullable=False),
    sa.Column('credit', sa.BigInteger(), nullable=False),
    sa.Column('devise', sa.String(length=3), nullable=False),
    sa.Column('montant_devise', sa.BigInteger(), nullable=False),
    sa.Column('taux', sa.String(length=40), nullable=False),
    sa.Column('echeance', sa.String(length=10), nullable=True),
    sa.Column('lettrage', sa.String(length=20), nullable=True),
    sa.CheckConstraint('debit >= 0 and credit >= 0 and (debit = 0 or credit = 0)', name='ck_ligne_sens'),
    sa.ForeignKeyConstraint(['compte'], ['cpt_comptes.numero'], ),
    sa.ForeignKeyConstraint(['piece'], ['cpt_pieces.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_cpt_ligne_analytique', 'cpt_lignes', ['projet', 'poste'], unique=False)
    op.create_index('ix_cpt_ligne_compte', 'cpt_lignes', ['compte'], unique=False)


def downgrade() -> None:
    for nom in reversed(TABLES):
        op.drop_table(nom)
