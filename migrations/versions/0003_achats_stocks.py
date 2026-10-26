"""Lot achats et stocks V8 : référentiels, mouvements, réservations, bons de sortie, demandes d'achat à lignes,
commandes, réceptions et factures (mémo V8, § 4, § 5 et § 11.1).

Revision ID: 0003_achats_stocks
Revises: 0002_lot0
Create Date: 2026-10-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_achats_stocks"
down_revision = "0002_lot0"
branch_labels = None
depends_on = None

TABLES = ['ach_commandes', 'ach_factures', 'stk_familles', 'stk_magasins', 'ach_demandes', 'ach_receptions', 'stk_articles', 'stk_bons_sortie', 'ach_demande_lignes', 'stk_bon_sortie_lignes', 'stk_mouvements', 'stk_reservations', 'stk_soldes', 'ach_commande_lignes', 'ach_facture_lignes', 'ach_reception_lignes']


def upgrade() -> None:

    op.create_table('ach_commandes',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('numero', sa.String(length=60), nullable=False),
    sa.Column('fournisseur', sa.String(length=80), nullable=False),
    sa.Column('devise', sa.String(length=3), nullable=False),
    sa.Column('date', sa.String(length=10), nullable=False),
    sa.Column('statut', sa.String(length=20), nullable=False),
    sa.Column('devis', sa.JSON(), nullable=False),
    sa.Column('conditions', sa.Text(), nullable=False),
    sa.Column('historique', sa.JSON(), nullable=False),
    sa.Column('cree_par', sa.Integer(), nullable=True),
    sa.Column('cree_le', sa.DateTime(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('numero')
    )
    op.create_table('ach_factures',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('fournisseur', sa.String(length=80), nullable=False),
    sa.Column('reference', sa.String(length=120), nullable=False),
    sa.Column('date', sa.String(length=10), nullable=False),
    sa.Column('echeance', sa.String(length=10), nullable=False),
    sa.Column('devise', sa.String(length=3), nullable=False),
    sa.Column('montant_ht', sa.BigInteger(), nullable=False),
    sa.Column('tva', sa.BigInteger(), nullable=False),
    sa.Column('statut', sa.String(length=20), nullable=False),
    sa.Column('valide_par', sa.Integer(), nullable=True),
    sa.Column('valide_le', sa.DateTime(), nullable=True),
    sa.Column('paiements', sa.JSON(), nullable=False),
    sa.Column('historique', sa.JSON(), nullable=False),
    sa.Column('cree_par', sa.Integer(), nullable=True),
    sa.Column('cree_le', sa.DateTime(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('fournisseur', 'reference', name='un_facture_fournisseur')
    )
    op.create_table('stk_familles',
    sa.Column('code', sa.String(length=30), nullable=False),
    sa.Column('libelle', sa.String(length=200), nullable=False),
    sa.Column('compte_stock', sa.String(length=20), nullable=False),
    sa.Column('compte_charge', sa.String(length=20), nullable=False),
    sa.Column('compte_variation', sa.String(length=20), nullable=False),
    sa.Column('actif', sa.Boolean(), nullable=False),
    sa.Column('cree_par', sa.Integer(), nullable=True),
    sa.Column('cree_le', sa.DateTime(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('code')
    )
    op.create_table('stk_magasins',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('code', sa.String(length=40), nullable=False),
    sa.Column('libelle', sa.String(length=200), nullable=False),
    sa.Column('type', sa.String(length=20), nullable=False),
    sa.Column('projet', sa.String(length=80), nullable=True),
    sa.Column('responsable', sa.Integer(), nullable=True),
    sa.Column('adjoint', sa.Integer(), nullable=True),
    sa.Column('actif', sa.Boolean(), nullable=False),
    sa.Column('cree_par', sa.Integer(), nullable=True),
    sa.Column('cree_le', sa.DateTime(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.CheckConstraint("type in ('central', 'chantier', 'transit')", name='ck_magasin_type'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code')
    )
    op.create_table('ach_demandes',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('numero', sa.String(length=60), nullable=False),
    sa.Column('projet', sa.String(length=80), nullable=False),
    sa.Column('devise', sa.String(length=3), nullable=False),
    sa.Column('demandeur', sa.Integer(), nullable=False),
    sa.Column('date_souhaitee', sa.String(length=10), nullable=False),
    sa.Column('magasin', sa.String(length=80), nullable=True),
    sa.Column('urgence', sa.String(length=20), nullable=False),
    sa.Column('justification', sa.Text(), nullable=False),
    sa.Column('statut', sa.String(length=20), nullable=False),
    sa.Column('niveau', sa.Integer(), nullable=False),
    sa.Column('approbations', sa.JSON(), nullable=False),
    sa.Column('derogation_dg', sa.Boolean(), nullable=False),
    sa.Column('historique', sa.JSON(), nullable=False),
    sa.Column('origine', sa.String(length=120), nullable=False),
    sa.Column('cree_par', sa.Integer(), nullable=True),
    sa.Column('cree_le', sa.DateTime(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['magasin'], ['stk_magasins.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('numero')
    )
    op.create_index('ix_ach_dem_projet', 'ach_demandes', ['projet', 'statut'], unique=False)
    op.create_table('ach_receptions',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('numero', sa.String(length=60), nullable=False),
    sa.Column('commande', sa.String(length=80), nullable=False),
    sa.Column('date', sa.String(length=10), nullable=False),
    sa.Column('bl', sa.String(length=120), nullable=False),
    sa.Column('statut', sa.String(length=20), nullable=False),
    sa.Column('cree_par', sa.Integer(), nullable=True),
    sa.Column('cree_le', sa.DateTime(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['commande'], ['ach_commandes.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('numero')
    )
    op.create_table('stk_articles',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('code', sa.String(length=60), nullable=False),
    sa.Column('libelle', sa.String(length=300), nullable=False),
    sa.Column('famille', sa.String(length=30), nullable=False),
    sa.Column('nature', sa.String(length=20), nullable=False),
    sa.Column('unite_stock', sa.String(length=30), nullable=False),
    sa.Column('unite_achat', sa.String(length=30), nullable=False),
    sa.Column('coefficient', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('seuil_min', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('seuil_max', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('qte_totale', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('valeur_totale', sa.BigInteger(), nullable=False),
    sa.Column('cmup', sa.Numeric(precision=24, scale=6), nullable=False),
    sa.Column('actif', sa.Boolean(), nullable=False),
    sa.Column('a_qualifier', sa.Boolean(), nullable=False),
    sa.Column('cree_par', sa.Integer(), nullable=True),
    sa.Column('cree_le', sa.DateTime(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.CheckConstraint("nature in ('stocke', 'non_stocke', 'prestation')", name='ck_article_nature'),
    sa.CheckConstraint('coefficient > 0', name='ck_article_coefficient'),
    sa.CheckConstraint('qte_totale >= 0', name='ck_article_qte'),
    sa.ForeignKeyConstraint(['famille'], ['stk_familles.code'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code')
    )
    op.create_table('stk_bons_sortie',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('numero', sa.String(length=40), nullable=False),
    sa.Column('magasin', sa.String(length=80), nullable=False),
    sa.Column('projet', sa.String(length=80), nullable=False),
    sa.Column('demandeur', sa.Integer(), nullable=True),
    sa.Column('date_souhaitee', sa.String(length=10), nullable=False),
    sa.Column('statut', sa.String(length=20), nullable=False),
    sa.Column('servi_par', sa.Integer(), nullable=True),
    sa.Column('servi_le', sa.DateTime(), nullable=True),
    sa.Column('motif', sa.Text(), nullable=True),
    sa.Column('cree_par', sa.Integer(), nullable=True),
    sa.Column('cree_le', sa.DateTime(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['magasin'], ['stk_magasins.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('numero')
    )
    op.create_table('ach_demande_lignes',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('demande', sa.String(length=80), nullable=False),
    sa.Column('numero', sa.Integer(), nullable=False),
    sa.Column('article', sa.String(length=80), nullable=False),
    sa.Column('poste', sa.String(length=80), nullable=False),
    sa.Column('quantite', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('prix_estime', sa.BigInteger(), nullable=False),
    sa.Column('fournisseur_suggere', sa.String(length=80), nullable=True),
    sa.Column('motif_hors_stock', sa.Text(), nullable=True),
    sa.Column('cloturee', sa.Boolean(), nullable=False),
    sa.Column('motif_cloture', sa.Text(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.CheckConstraint('prix_estime >= 0', name='ck_dl_prix'),
    sa.CheckConstraint('quantite > 0', name='ck_dl_qte'),
    sa.ForeignKeyConstraint(['article'], ['stk_articles.id'], ),
    sa.ForeignKeyConstraint(['demande'], ['ach_demandes.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('demande', 'numero', name='un_ligne_demande')
    )
    op.create_table('stk_bon_sortie_lignes',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('bon', sa.String(length=80), nullable=False),
    sa.Column('article', sa.String(length=80), nullable=False),
    sa.Column('poste', sa.String(length=80), nullable=False),
    sa.Column('quantite', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('mouvement', sa.String(length=80), nullable=True),
    sa.CheckConstraint('quantite > 0', name='ck_bs_qte'),
    sa.ForeignKeyConstraint(['article'], ['stk_articles.id'], ),
    sa.ForeignKeyConstraint(['bon'], ['stk_bons_sortie.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('stk_mouvements',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('numero', sa.String(length=40), nullable=False),
    sa.Column('type', sa.String(length=30), nullable=False),
    sa.Column('date', sa.String(length=10), nullable=False),
    sa.Column('article', sa.String(length=80), nullable=False),
    sa.Column('magasin', sa.String(length=80), nullable=False),
    sa.Column('quantite', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('valeur', sa.BigInteger(), nullable=False),
    sa.Column('cmup_apres', sa.Numeric(precision=24, scale=6), nullable=False),
    sa.Column('devise_tenue', sa.String(length=3), nullable=False),
    sa.Column('cout_devise', sa.String(length=3), nullable=True),
    sa.Column('cout_origine', sa.BigInteger(), nullable=True),
    sa.Column('taux', sa.String(length=40), nullable=True),
    sa.Column('projet', sa.String(length=80), nullable=True),
    sa.Column('poste', sa.String(length=80), nullable=True),
    sa.Column('source_type', sa.String(length=40), nullable=False),
    sa.Column('source_id', sa.String(length=80), nullable=False),
    sa.Column('contre_passe', sa.String(length=80), nullable=True),
    sa.Column('statut', sa.String(length=20), nullable=False),
    sa.Column('cree_par', sa.Integer(), nullable=True),
    sa.Column('cree_le', sa.DateTime(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['article'], ['stk_articles.id'], ),
    sa.ForeignKeyConstraint(['magasin'], ['stk_magasins.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('numero')
    )
    op.create_index('ix_stk_mvt_article_magasin', 'stk_mouvements', ['article', 'magasin'], unique=False)
    op.create_index('ix_stk_mvt_projet', 'stk_mouvements', ['projet', 'poste'], unique=False)
    op.create_index('ix_stk_mvt_source', 'stk_mouvements', ['source_type', 'source_id'], unique=False)
    op.create_table('stk_reservations',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('article', sa.String(length=80), nullable=False),
    sa.Column('magasin', sa.String(length=80), nullable=False),
    sa.Column('quantite', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('source_type', sa.String(length=40), nullable=False),
    sa.Column('source_id', sa.String(length=80), nullable=False),
    sa.Column('statut', sa.String(length=20), nullable=False),
    sa.Column('cree_par', sa.Integer(), nullable=True),
    sa.Column('cree_le', sa.DateTime(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['article'], ['stk_articles.id'], ),
    sa.ForeignKeyConstraint(['magasin'], ['stk_magasins.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_stk_resa_article_magasin', 'stk_reservations', ['article', 'magasin', 'statut'], unique=False)
    op.create_table('stk_soldes',
    sa.Column('article', sa.String(length=80), nullable=False),
    sa.Column('magasin', sa.String(length=80), nullable=False),
    sa.Column('quantite', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.CheckConstraint('quantite >= 0', name='ck_solde_positif'),
    sa.ForeignKeyConstraint(['article'], ['stk_articles.id'], ),
    sa.ForeignKeyConstraint(['magasin'], ['stk_magasins.id'], ),
    sa.PrimaryKeyConstraint('article', 'magasin')
    )
    op.create_table('ach_commande_lignes',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('commande', sa.String(length=80), nullable=False),
    sa.Column('demande_ligne', sa.String(length=80), nullable=False),
    sa.Column('magasin', sa.String(length=80), nullable=True),
    sa.Column('quantite', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('prix_unitaire', sa.BigInteger(), nullable=False),
    sa.Column('taux_budget', sa.String(length=40), nullable=False),
    sa.Column('montant_budget', sa.BigInteger(), nullable=False),
    sa.CheckConstraint('prix_unitaire >= 0', name='ck_cl_prix'),
    sa.CheckConstraint('quantite > 0', name='ck_cl_qte'),
    sa.ForeignKeyConstraint(['commande'], ['ach_commandes.id'], ),
    sa.ForeignKeyConstraint(['demande_ligne'], ['ach_demande_lignes.id'], ),
    sa.ForeignKeyConstraint(['magasin'], ['stk_magasins.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('ach_facture_lignes',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('facture', sa.String(length=80), nullable=False),
    sa.Column('commande_ligne', sa.String(length=80), nullable=False),
    sa.Column('quantite', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('prix_unitaire', sa.BigInteger(), nullable=False),
    sa.Column('ecart_budget', sa.BigInteger(), nullable=False),
    sa.CheckConstraint('quantite > 0', name='ck_fl_qte'),
    sa.ForeignKeyConstraint(['commande_ligne'], ['ach_commande_lignes.id'], ),
    sa.ForeignKeyConstraint(['facture'], ['ach_factures.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('ach_reception_lignes',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('reception', sa.String(length=80), nullable=False),
    sa.Column('commande_ligne', sa.String(length=80), nullable=False),
    sa.Column('qte_acceptee', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('qte_rejetee', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('motif_rejet', sa.Text(), nullable=True),
    sa.Column('mouvement', sa.String(length=80), nullable=True),
    sa.Column('cout_budget', sa.BigInteger(), nullable=False),
    sa.CheckConstraint('qte_acceptee >= 0 and qte_rejetee >= 0', name='ck_rl_qte'),
    sa.ForeignKeyConstraint(['commande_ligne'], ['ach_commande_lignes.id'], ),
    sa.ForeignKeyConstraint(['reception'], ['ach_receptions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    for nom in reversed(TABLES):
        op.drop_table(nom)
