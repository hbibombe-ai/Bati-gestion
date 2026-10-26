"""Schéma de base : tables du paquet BatiGestion V8 tel que reçu (V7 + import généralisé).

Révision de reprise : chaque table n'est créée que si elle n'existe pas encore. Une base déjà en service,
créée jusqu'ici par meta.create_all au démarrage, est donc reprise telle quelle par Alembic sans perte.

Revision ID: 0001_base
Revises:
Create Date: 2026-10-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_base"
down_revision = None
branch_labels = None
depends_on = None


def _creer(nom, *elements, **kw):
    if not sa.inspect(op.get_bind()).has_table(nom):
        op.create_table(nom, *elements, **kw)


def upgrade() -> None:

    _creer('attendance',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('person_id', sa.String(length=80), nullable=False),
    sa.Column('date', sa.String(length=10), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('hours', sa.Float(), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('location', sa.String(length=20), nullable=True),
    sa.Column('project', sa.String(length=80), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('person_id', 'date', name='un_pointage_par_jour')
    )
    _creer('audit',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('quand', sa.DateTime(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('user_nom', sa.String(length=200), nullable=True),
    sa.Column('action', sa.String(length=40), nullable=False),
    sa.Column('objet', sa.String(length=60), nullable=True),
    sa.Column('objet_id', sa.String(length=80), nullable=True),
    sa.Column('resume', sa.Text(), nullable=True),
    sa.Column('avant', sa.JSON(), nullable=True),
    sa.Column('apres', sa.JSON(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    _creer('clients',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('code', sa.String(length=60), nullable=False),
    sa.Column('name', sa.String(length=500), nullable=False),
    sa.Column('phone', sa.String(length=500), nullable=True),
    sa.Column('email', sa.String(length=500), nullable=True),
    sa.Column('address', sa.Text(), nullable=True),
    sa.Column('registration', sa.String(length=500), nullable=True),
    sa.Column('roles', sa.JSON(), nullable=False),
    sa.Column('archived', sa.Boolean(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code')
    )
    _creer('company_history',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('before', sa.JSON(), nullable=False),
    sa.Column('after', sa.JSON(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('user_nom', sa.String(length=200), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    _creer('erp_dossiers',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('type', sa.String(length=40), nullable=False),
    sa.Column('ref', sa.String(length=100), nullable=False),
    sa.Column('date', sa.String(length=10), nullable=False),
    sa.Column('project', sa.String(length=80), nullable=True),
    sa.Column('centre', sa.String(length=80), nullable=True),
    sa.Column('party', sa.String(length=80), nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('values', sa.JSON(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('company_snapshot', sa.JSON(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('type', 'ref', name='ref_unique_par_type')
    )
    _creer('expenses',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('label', sa.String(length=500), nullable=False),
    sa.Column('project', sa.String(length=80), nullable=False),
    sa.Column('category', sa.String(length=80), nullable=False),
    sa.Column('date', sa.String(length=10), nullable=False),
    sa.Column('amount', sa.BigInteger(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('supplier_id', sa.String(length=80), nullable=True),
    sa.Column('responsible', sa.String(length=200), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    _creer('history_batches',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('project_ref', sa.String(length=200), nullable=False),
    sa.Column('project', sa.JSON(), nullable=False),
    sa.Column('rows', sa.JSON(), nullable=False),
    sa.Column('source', sa.String(length=300), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_ref')
    )
    _creer('import_lots',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('cle', sa.String(length=200), nullable=False),
    sa.Column('reference_lot', sa.String(length=200), nullable=False),
    sa.Column('fonction', sa.String(length=40), nullable=False),
    sa.Column('version_modele', sa.String(length=40), nullable=False),
    sa.Column('mode', sa.String(length=20), nullable=False),
    sa.Column('date_bascule', sa.String(length=10), nullable=True),
    sa.Column('source_systeme', sa.String(length=300), nullable=True),
    sa.Column('empreinte', sa.String(length=64), nullable=False),
    sa.Column('fichier', sa.String(length=300), nullable=True),
    sa.Column('contenu', sa.LargeBinary(), nullable=True),
    sa.Column('statut', sa.String(length=30), nullable=False),
    sa.Column('cree_par', sa.Integer(), nullable=True),
    sa.Column('cree_le', sa.DateTime(), nullable=False),
    sa.Column('resume', sa.JSON(), nullable=True),
    sa.Column('lignes', sa.JSON(), nullable=True),
    sa.Column('rapport', sa.JSON(), nullable=True),
    sa.Column('rapprochement', sa.JSON(), nullable=True),
    sa.Column('historique', sa.JSON(), nullable=True),
    sa.Column('remplace', sa.String(length=80), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('cle'),
    sa.UniqueConstraint('reference_lot')
    )
    _creer('import_mappings',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('lot_id', sa.String(length=80), nullable=False),
    sa.Column('entite', sa.String(length=40), nullable=False),
    sa.Column('reference_externe', sa.String(length=200), nullable=False),
    sa.Column('id_interne', sa.String(length=80), nullable=False),
    sa.Column('effet', sa.String(length=30), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('entite', 'reference_externe', name='correspondance_unique')
    )
    _creer('import_previews',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('cree_le', sa.DateTime(), nullable=False),
    sa.Column('fonction', sa.String(length=40), nullable=False),
    sa.Column('contexte', sa.JSON(), nullable=False),
    sa.Column('donnees', sa.JSON(), nullable=False),
    sa.Column('condensat', sa.String(length=64), nullable=False),
    sa.Column('empreinte', sa.String(length=64), nullable=False),
    sa.Column('fichier', sa.String(length=300), nullable=True),
    sa.Column('contenu', sa.LargeBinary(), nullable=True),
    sa.Column('statut', sa.String(length=20), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    _creer('invoices',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('number', sa.String(length=100), nullable=False),
    sa.Column('client', sa.String(length=80), nullable=False),
    sa.Column('project', sa.String(length=80), nullable=True),
    sa.Column('date', sa.String(length=10), nullable=False),
    sa.Column('due', sa.String(length=10), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('lines', sa.JSON(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('company_snapshot', sa.JSON(), nullable=True),
    sa.Column('paid', sa.BigInteger(), nullable=False),
    sa.Column('quote_id', sa.String(length=80), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('number')
    )
    _creer('kobo_pointages',
    sa.Column('id', sa.String(length=200), nullable=False),
    sa.Column('fiche', sa.String(length=80), nullable=False),
    sa.Column('soumis_le', sa.String(length=40), nullable=True),
    sa.Column('date', sa.String(length=10), nullable=True),
    sa.Column('person_id', sa.String(length=80), nullable=True),
    sa.Column('agent', sa.String(length=200), nullable=True),
    sa.Column('statut', sa.String(length=20), nullable=True),
    sa.Column('heures', sa.Float(), nullable=True),
    sa.Column('lieu', sa.String(length=120), nullable=True),
    sa.Column('pointeur', sa.String(length=300), nullable=True),
    sa.Column('resultat', sa.String(length=30), nullable=False),
    sa.Column('attendance_id', sa.Integer(), nullable=True),
    sa.Column('donnees', sa.JSON(), nullable=True),
    sa.Column('traite_le', sa.DateTime(), nullable=True),
    sa.Column('traite_par', sa.String(length=200), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    _creer('movements',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('date', sa.String(length=10), nullable=True),
    sa.Column('account', sa.String(length=20), nullable=False),
    sa.Column('label', sa.Text(), nullable=False),
    sa.Column('direction', sa.String(length=3), nullable=False),
    sa.Column('amount', sa.BigInteger(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('project', sa.String(length=80), nullable=True),
    sa.Column('invoice_id', sa.String(length=80), nullable=True),
    sa.Column('invoice_amount', sa.BigInteger(), nullable=True),
    sa.Column('expense_id', sa.String(length=80), nullable=True),
    sa.Column('supplier_payment_id', sa.String(length=80), nullable=True),
    sa.Column('supplier_reversal_id', sa.String(length=80), nullable=True),
    sa.Column('journal', sa.JSON(), nullable=True),
    sa.Column('cree_le', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    _creer('payroll',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('person_id', sa.String(length=80), nullable=False),
    sa.Column('month', sa.String(length=7), nullable=False),
    sa.Column('name', sa.String(length=500), nullable=True),
    sa.Column('code', sa.String(length=100), nullable=True),
    sa.Column('job', sa.String(length=500), nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('period', sa.String(length=10), nullable=False),
    sa.Column('quantity', sa.Float(), nullable=False),
    sa.Column('rate', sa.BigInteger(), nullable=False),
    sa.Column('elements', sa.JSON(), nullable=False),
    sa.Column('method', sa.String(length=10), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('location', sa.String(length=20), nullable=False),
    sa.Column('project', sa.String(length=80), nullable=True),
    sa.Column('prepared', sa.String(length=10), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('rules', sa.JSON(), nullable=True),
    sa.Column('employee_snapshot', sa.JSON(), nullable=True),
    sa.Column('company_snapshot', sa.JSON(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('person_id', 'month', name='une_paie_par_mois')
    )
    _creer('personnel',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('code', sa.String(length=100), nullable=False),
    sa.Column('name', sa.String(length=500), nullable=False),
    sa.Column('job', sa.String(length=500), nullable=True),
    sa.Column('service', sa.String(length=500), nullable=True),
    sa.Column('phone', sa.String(length=500), nullable=True),
    sa.Column('start', sa.String(length=10), nullable=False),
    sa.Column('location', sa.String(length=20), nullable=False),
    sa.Column('project', sa.String(length=80), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=True),
    sa.Column('details', sa.JSON(), nullable=True),
    sa.Column('v7', sa.JSON(), nullable=True),
    sa.Column('salary', sa.JSON(), nullable=True),
    sa.Column('assignments', sa.JSON(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code')
    )
    _creer('pieces',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('expense_id', sa.String(length=200), nullable=True),
    sa.Column('batch_id', sa.String(length=80), nullable=True),
    sa.Column('name', sa.String(length=300), nullable=False),
    sa.Column('mime', sa.String(length=40), nullable=False),
    sa.Column('content', sa.LargeBinary(), nullable=False),
    sa.Column('size', sa.Integer(), nullable=False),
    sa.Column('hash', sa.String(length=64), nullable=False),
    sa.Column('type', sa.String(length=60), nullable=False),
    sa.Column('beneficiary', sa.String(length=500), nullable=True),
    sa.Column('document_date', sa.String(length=10), nullable=False),
    sa.Column('amount', sa.BigInteger(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('uploaded_at', sa.DateTime(), nullable=False),
    sa.Column('uploaded_by', sa.Integer(), nullable=True),
    sa.Column('validated_by', sa.Integer(), nullable=True),
    sa.Column('validated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('hash')
    )
    _creer('pieces_jointes',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('entite', sa.String(length=40), nullable=False),
    sa.Column('entite_id', sa.String(length=80), nullable=False),
    sa.Column('libelle', sa.String(length=200), nullable=True),
    sa.Column('nom', sa.String(length=300), nullable=False),
    sa.Column('mime', sa.String(length=40), nullable=False),
    sa.Column('taille', sa.Integer(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('contenu', sa.LargeBinary(), nullable=False),
    sa.Column('ajoute_par', sa.Integer(), nullable=True),
    sa.Column('ajoute_le', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    _creer('projects',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('name', sa.String(length=500), nullable=False),
    sa.Column('client', sa.String(length=80), nullable=True),
    sa.Column('location', sa.String(length=500), nullable=True),
    sa.Column('deadline', sa.String(length=10), nullable=True),
    sa.Column('budget', sa.BigInteger(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('progress', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    _creer('quotes',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('number', sa.String(length=100), nullable=False),
    sa.Column('client', sa.String(length=80), nullable=False),
    sa.Column('project', sa.String(length=80), nullable=True),
    sa.Column('date', sa.String(length=10), nullable=False),
    sa.Column('due', sa.String(length=10), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('lines', sa.JSON(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('company_snapshot', sa.JSON(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('number')
    )
    _creer('settings',
    sa.Column('cle', sa.String(length=80), nullable=False),
    sa.Column('valeur', sa.JSON(), nullable=True),
    sa.PrimaryKeyConstraint('cle')
    )
    _creer('supplier_allocations',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('payment_id', sa.String(length=80), nullable=False),
    sa.Column('invoice_id', sa.String(length=80), nullable=False),
    sa.Column('amount', sa.BigInteger(), nullable=False),
    sa.Column('date', sa.String(length=10), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    _creer('supplier_invoices',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('party_id', sa.String(length=80), nullable=False),
    sa.Column('project', sa.String(length=80), nullable=False),
    sa.Column('reference', sa.String(length=500), nullable=False),
    sa.Column('date', sa.String(length=10), nullable=False),
    sa.Column('due', sa.String(length=10), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('amount', sa.BigInteger(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    _creer('supplier_payments',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('party_id', sa.String(length=80), nullable=False),
    sa.Column('project', sa.String(length=80), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('amount', sa.BigInteger(), nullable=False),
    sa.Column('date', sa.String(length=10), nullable=False),
    sa.Column('account', sa.String(length=20), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    _creer('supplier_reversals',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('payment_id', sa.String(length=80), nullable=False),
    sa.Column('date', sa.String(length=10), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('payment_id')
    )
    _creer('users',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('identifiant', sa.String(length=60), nullable=False),
    sa.Column('nom', sa.String(length=200), nullable=False),
    sa.Column('telephone', sa.String(length=60), nullable=True),
    sa.Column('role', sa.String(length=30), nullable=False),
    sa.Column('mdp_hash', sa.String(length=300), nullable=False),
    sa.Column('doit_changer_mdp', sa.Boolean(), nullable=True),
    sa.Column('actif', sa.Boolean(), nullable=True),
    sa.Column('echecs', sa.Integer(), nullable=True),
    sa.Column('bloque_jusqua', sa.DateTime(), nullable=True),
    sa.Column('derniere_connexion', sa.DateTime(), nullable=True),
    sa.Column('version_session', sa.Integer(), nullable=True),
    sa.Column('cree_le', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('identifiant')
    )
    _creer('v7_records',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('kind', sa.String(length=30), nullable=False),
    sa.Column('ref', sa.String(length=200), nullable=False),
    sa.Column('project', sa.String(length=80), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('data', sa.JSON(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('kind', 'ref', name='v7_reference_unique')
    )


def downgrade() -> None:
    raise RuntimeError("Retour en arrière non prévu : restaurer la sauvegarde prise avant la migration.")
