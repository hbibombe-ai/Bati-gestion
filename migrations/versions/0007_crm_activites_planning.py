"""Extension ERP : pistes commerciales (CRM), activités planifiées (rappels) et date de début des chantiers (Gantt).

Revision ID: 0007_crm_activites_planning
Revises: 0006_chantiers_gps
Create Date: 2026-11-07
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_crm_activites_planning"
down_revision = "0006_chantiers_gps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    if "debut" not in {c["name"] for c in insp.get_columns("projects")}:
        op.add_column("projects", sa.Column("debut", sa.String(10), nullable=True))
    if "crm_pistes" not in tables:
        op.create_table("crm_pistes",
                        sa.Column("id", sa.String(80), nullable=False),
                        sa.Column("titre", sa.String(500), nullable=False),
                        sa.Column("client", sa.String(80), nullable=False),
                        sa.Column("contact", sa.String(300), nullable=False),
                        sa.Column("telephone", sa.String(100), nullable=False),
                        sa.Column("email", sa.String(300), nullable=False),
                        sa.Column("source", sa.String(60), nullable=False),
                        sa.Column("montant", sa.BigInteger(), nullable=False),
                        sa.Column("devise", sa.String(3), nullable=False),
                        sa.Column("probabilite", sa.Integer(), nullable=False),
                        sa.Column("etape", sa.String(30), nullable=False),
                        sa.Column("responsable", sa.Integer(), nullable=True),
                        sa.Column("cloture_prevue", sa.String(10), nullable=False),
                        sa.Column("priorite", sa.Integer(), nullable=False),
                        sa.Column("notes", sa.Text(), nullable=False),
                        sa.Column("motif_perte", sa.String(500), nullable=False),
                        sa.Column("cree_le", sa.DateTime(), nullable=False),
                        sa.Column("archive", sa.Boolean(), nullable=False),
                        sa.PrimaryKeyConstraint("id"))
    if "activites" not in tables:
        op.create_table("activites",
                        sa.Column("id", sa.String(80), nullable=False),
                        sa.Column("objet", sa.String(60), nullable=False),
                        sa.Column("objet_id", sa.String(80), nullable=False),
                        sa.Column("libelle", sa.String(500), nullable=False),
                        sa.Column("type", sa.String(40), nullable=False),
                        sa.Column("resume", sa.String(500), nullable=False),
                        sa.Column("echeance", sa.String(10), nullable=False),
                        sa.Column("assigne_a", sa.Integer(), nullable=True),
                        sa.Column("cree_par", sa.Integer(), nullable=True),
                        sa.Column("cree_le", sa.DateTime(), nullable=False),
                        sa.Column("fait", sa.Boolean(), nullable=False),
                        sa.Column("fait_le", sa.DateTime(), nullable=True),
                        sa.Column("compte_rendu", sa.Text(), nullable=False),
                        sa.PrimaryKeyConstraint("id"))
        op.create_index("ix_activites_objet", "activites", ["objet", "objet_id"])
        op.create_index("ix_activites_assigne", "activites", ["assigne_a", "fait"])


def downgrade() -> None:
    op.drop_index("ix_activites_assigne", table_name="activites")
    op.drop_index("ix_activites_objet", table_name="activites")
    op.drop_table("activites")
    op.drop_table("crm_pistes")
    with op.batch_alter_table("projects") as b:
        b.drop_column("debut")
