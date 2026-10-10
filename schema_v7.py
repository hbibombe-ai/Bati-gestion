"""Tables additives du circuit V7, sans transformation des données historiques."""
import sqlalchemy as sa

def ajouter(meta):
    sa.Table('v7_records', meta,
        sa.Column('id', sa.String(80), primary_key=True),
        sa.Column('kind', sa.String(30), nullable=False),
        sa.Column('ref', sa.String(200), nullable=False),
        sa.Column('project', sa.String(80), nullable=False, default=''),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('data', sa.JSON, nullable=False),
        sa.Column('version', sa.Integer, nullable=False, default=1),
        sa.UniqueConstraint('kind', 'ref', name='v7_reference_unique'))
