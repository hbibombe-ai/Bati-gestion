"""Tables additives de l'import généralisé (création automatique, aucune transformation des tables existantes)."""
import sqlalchemy as sa


def ajouter(meta):
    sa.Table(
        "import_lots", meta,
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("cle", sa.String(200), nullable=False, unique=True),        # idempotence : fichier + contexte
        sa.Column("reference_lot", sa.String(200), nullable=False, unique=True),
        sa.Column("fonction", sa.String(40), nullable=False),
        sa.Column("version_modele", sa.String(40), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("date_bascule", sa.String(10), default=""),
        sa.Column("source_systeme", sa.String(300), default=""),
        sa.Column("empreinte", sa.String(64), nullable=False),
        sa.Column("fichier", sa.String(300), default=""),
        sa.Column("contenu", sa.LargeBinary, nullable=True),                  # fichier source conservé avec le lot
        sa.Column("statut", sa.String(30), nullable=False),
        sa.Column("cree_par", sa.Integer, nullable=True),
        sa.Column("cree_le", sa.DateTime, nullable=False),
        sa.Column("resume", sa.JSON, nullable=True),        # comptes, créations, correspondances
        sa.Column("lignes", sa.JSON, nullable=True),        # lignes normalisées (consultation des archives)
        sa.Column("rapport", sa.JSON, nullable=True),       # erreurs, alertes acceptées, effets
        sa.Column("rapprochement", sa.JSON, nullable=True), # totaux avant / après, reliquats, écarts
        sa.Column("historique", sa.JSON, nullable=True),    # validations Finance / DG, rejets, remplacements
        sa.Column("remplace", sa.String(80), default=""),
    )
    sa.Table(
        "import_previews", meta,
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("cree_le", sa.DateTime, nullable=False),
        sa.Column("fonction", sa.String(40), nullable=False),
        sa.Column("contexte", sa.JSON, nullable=False),
        sa.Column("donnees", sa.JSON, nullable=False),      # lignes normalisées côté serveur
        sa.Column("condensat", sa.String(64), nullable=False),
        sa.Column("empreinte", sa.String(64), nullable=False),
        sa.Column("fichier", sa.String(300), default=""),
        sa.Column("contenu", sa.LargeBinary, nullable=True),
        sa.Column("statut", sa.String(20), nullable=False),
    )
    sa.Table(
        "import_mappings", meta,
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("lot_id", sa.String(80), nullable=False),
        sa.Column("entite", sa.String(40), nullable=False),
        sa.Column("reference_externe", sa.String(200), nullable=False),
        sa.Column("id_interne", sa.String(80), nullable=False),
        sa.Column("effet", sa.String(30), nullable=False),  # Création, Correspondance, Archive, Reliquat…
        sa.UniqueConstraint("entite", "reference_externe", name="correspondance_unique"),
    )
