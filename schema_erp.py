"""Tables de l'extension « ERP » : pistes commerciales (CRM) et activités planifiées (rappels).

La date de début des chantiers (planning Gantt) est une colonne de « projects », déclarée dans db.py.
"""
import sqlalchemy as sa

ETAPES_CRM = ["Nouveau", "Qualifié", "Proposition", "Négociation", "Gagné"]
PERDU = "Perdu"
SOURCES_CRM = ["Bouche-à-oreille", "Appel d’offres", "Client existant", "Réseaux sociaux", "Visite au bureau",
               "Partenaire", "Autre"]
TYPES_ACTIVITE = ["Appel", "Réunion", "E-mail", "Visite de chantier", "Relance", "À faire"]


def ajouter_erp(meta: sa.MetaData) -> None:
    sa.Table("crm_pistes", meta,
             sa.Column("id", sa.String(80), primary_key=True),
             sa.Column("titre", sa.String(500), nullable=False),
             sa.Column("client", sa.String(80), nullable=False, default=""),       # tiers existant (facultatif)
             sa.Column("contact", sa.String(300), nullable=False, default=""),     # prospect pas encore client
             sa.Column("telephone", sa.String(100), nullable=False, default=""),
             sa.Column("email", sa.String(300), nullable=False, default=""),
             sa.Column("source", sa.String(60), nullable=False, default=""),
             sa.Column("montant", sa.BigInteger, nullable=False, default=0),       # centimes
             sa.Column("devise", sa.String(3), nullable=False),
             sa.Column("probabilite", sa.Integer, nullable=False, default=10),     # 0 à 100
             sa.Column("etape", sa.String(30), nullable=False),
             sa.Column("responsable", sa.Integer, nullable=True),                  # users.id
             sa.Column("cloture_prevue", sa.String(10), nullable=False, default=""),
             sa.Column("priorite", sa.Integer, nullable=False, default=0),         # 0 à 3 étoiles
             sa.Column("notes", sa.Text, nullable=False, default=""),
             sa.Column("motif_perte", sa.String(500), nullable=False, default=""),
             sa.Column("cree_le", sa.DateTime, nullable=False),
             sa.Column("archive", sa.Boolean, nullable=False, default=False))
    sa.Table("activites", meta,
             sa.Column("id", sa.String(80), primary_key=True),
             sa.Column("objet", sa.String(60), nullable=False),        # table de la fiche : projects, clients, crm_pistes…
             sa.Column("objet_id", sa.String(80), nullable=False),
             sa.Column("libelle", sa.String(500), nullable=False, default=""),   # nom de la fiche, pour les listes
             sa.Column("type", sa.String(40), nullable=False),
             sa.Column("resume", sa.String(500), nullable=False),
             sa.Column("echeance", sa.String(10), nullable=False),
             sa.Column("assigne_a", sa.Integer, nullable=True),
             sa.Column("cree_par", sa.Integer, nullable=True),
             sa.Column("cree_le", sa.DateTime, nullable=False),
             sa.Column("fait", sa.Boolean, nullable=False, default=False),
             sa.Column("fait_le", sa.DateTime, nullable=True),
             sa.Column("compte_rendu", sa.Text, nullable=False, default=""),
             sa.Index("ix_activites_objet", "objet", "objet_id"),
             sa.Index("ix_activites_assigne", "assigne_a", "fait"))
