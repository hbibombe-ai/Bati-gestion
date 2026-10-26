"""Lot 0 V8 : index (kind, project) sur v7_records ; l'unicité (kind, ref) reste portée par v7_reference_unique.

Revision ID: 0002_lot0
Revises: 0001_base
Create Date: 2026-10-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_lot0"
down_revision = "0001_base"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "ix_v7_records_kind_project" not in {i["name"] for i in insp.get_indexes("v7_records")}:
        op.create_index("ix_v7_records_kind_project", "v7_records", ["kind", "project"])


def downgrade() -> None:
    op.drop_index("ix_v7_records_kind_project", table_name="v7_records")
