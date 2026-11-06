"""Base de données centrale de Bâti Gestion.

En local : un fichier SQLite (donnees/bati_gestion.db). Le schéma est créé et mis à jour par les migrations
Alembic du dossier migrations/ (lot 0 V8).
En ligne : PostgreSQL, dont l'adresse est donnée dans les secrets ([database] url) ou DATABASE_URL.

Les montants sont des entiers en centimes, comme dans le prototype : aucun arrondi flottant.
Les dates sont des textes AAAA-MM-JJ. Chaque écriture métier est enregistrée dans le journal
d'audit dans la même transaction : si l'audit échoue, la modification est annulée.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import uuid
from contextlib import contextmanager

import sqlalchemy as sa
import streamlit as st

meta = sa.MetaData()
Txt = sa.Text
Str = lambda n=200: sa.String(n)  # noqa: E731
Montant = sa.BigInteger
Js = sa.JSON

# ------------------------------------------------------------------ comptes
users = sa.Table(
    "users", meta,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("identifiant", Str(60), nullable=False, unique=True),
    sa.Column("nom", Str(), nullable=False),
    sa.Column("telephone", Str(60), default=""),
    sa.Column("role", Str(30), nullable=False),
    sa.Column("mdp_hash", Str(300), nullable=False),
    sa.Column("doit_changer_mdp", sa.Boolean, default=True),
    sa.Column("actif", sa.Boolean, default=True),
    sa.Column("echecs", sa.Integer, default=0),
    sa.Column("bloque_jusqua", sa.DateTime, nullable=True),
    sa.Column("derniere_connexion", sa.DateTime, nullable=True),
    sa.Column("version_session", sa.Integer, default=0),
    sa.Column("cree_le", sa.DateTime, default=lambda: maintenant()),
)
settings = sa.Table("settings", meta, sa.Column("cle", Str(80), primary_key=True), sa.Column("valeur", Js))
audit = sa.Table(
    "audit", meta,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("quand", sa.DateTime, nullable=False, default=lambda: maintenant()),
    sa.Column("user_id", sa.Integer, nullable=True),
    sa.Column("user_nom", Str(), default=""),
    sa.Column("action", Str(40), nullable=False),
    sa.Column("objet", Str(60), default=""),
    sa.Column("objet_id", Str(80), default=""),
    sa.Column("resume", Txt, default=""),
    sa.Column("avant", Js, nullable=True),
    sa.Column("apres", Js, nullable=True),
)

# ------------------------------------------------------------------ métier
clients = sa.Table(  # tiers : clients, fournisseurs et sous-traitants dans un carnet unique
    "clients", meta,
    sa.Column("id", Str(80), primary_key=True),
    sa.Column("code", Str(60), nullable=False, unique=True),
    sa.Column("name", Str(500), nullable=False),
    sa.Column("phone", Str(500), default=""),
    sa.Column("email", Str(500), default=""),
    sa.Column("address", Txt, default=""),
    sa.Column("registration", Str(500), default=""),
    sa.Column("roles", Js, nullable=False),
    sa.Column("archived", sa.Boolean, default=False),
)
projects = sa.Table(
    "projects", meta,
    sa.Column("id", Str(80), primary_key=True),
    sa.Column("name", Str(500), nullable=False),
    sa.Column("client", Str(80), default=""),
    sa.Column("location", Str(500), default=""),
    sa.Column("deadline", Str(10), default=""),
    sa.Column("budget", Montant, nullable=False, default=0),
    sa.Column("currency", Str(3), nullable=False),
    sa.Column("status", Str(30), nullable=False),
    sa.Column("progress", sa.Float, nullable=False, default=0),
    sa.Column("latitude", sa.Float, nullable=True),     # coordonnées GPS facultatives (carte des chantiers)
    sa.Column("longitude", sa.Float, nullable=True),
)


def _document(nom: str) -> sa.Table:
    cols = [
        sa.Column("id", Str(80), primary_key=True),
        sa.Column("number", Str(100), nullable=False, unique=True),
        sa.Column("client", Str(80), nullable=False),
        sa.Column("project", Str(80), default=""),
        sa.Column("date", Str(10), nullable=False),
        sa.Column("due", Str(10), default=""),
        sa.Column("notes", Txt, default=""),
        sa.Column("status", Str(30), nullable=False),
        sa.Column("lines", Js, nullable=False),
        sa.Column("currency", Str(3), nullable=False),
        sa.Column("company_snapshot", Js, nullable=True),
    ]
    if nom == "invoices":
        cols += [sa.Column("paid", Montant, nullable=False, default=0), sa.Column("quote_id", Str(80), default="")]
    return sa.Table(nom, meta, *cols)


quotes = _document("quotes")
invoices = _document("invoices")
expenses = sa.Table(
    "expenses", meta,
    sa.Column("id", Str(80), primary_key=True),
    sa.Column("label", Str(500), nullable=False),
    sa.Column("project", Str(80), nullable=False),
    sa.Column("category", Str(80), nullable=False),
    sa.Column("date", Str(10), nullable=False),
    sa.Column("amount", Montant, nullable=False),
    sa.Column("currency", Str(3), nullable=False),
    sa.Column("supplier_id", Str(80), default=""),
    sa.Column("responsible", Str(200), default=""),
)
movements = sa.Table(  # journal de caisse / banque / mobile money
    "movements", meta,
    sa.Column("id", Str(80), primary_key=True),
    sa.Column("kind", Str(20), nullable=False),          # manual, opening, invoice, expense
    sa.Column("date", Str(10), default=""),               # vide = historique à compléter
    sa.Column("account", Str(20), nullable=False),        # cash, bank, mobile, unassigned
    sa.Column("label", Txt, nullable=False),
    sa.Column("direction", Str(3), nullable=False),       # in, out
    sa.Column("amount", Montant, nullable=False),
    sa.Column("currency", Str(3), nullable=False),
    sa.Column("project", Str(80), default=""),
    sa.Column("invoice_id", Str(80), default=""),
    sa.Column("invoice_amount", Montant, nullable=True),
    sa.Column("expense_id", Str(80), default=""),
    sa.Column("supplier_payment_id", Str(80), default=""),
    sa.Column("supplier_reversal_id", Str(80), default=""),
    sa.Column("journal", Js, nullable=True),              # imputation, pièce, taux historique
    sa.Column("cree_le", sa.DateTime, default=lambda: maintenant()),
)
supplier_invoices = sa.Table(
    "supplier_invoices", meta,
    sa.Column("id", Str(80), primary_key=True),
    sa.Column("party_id", Str(80), nullable=False),
    sa.Column("project", Str(80), nullable=False),
    sa.Column("reference", Str(500), nullable=False),
    sa.Column("date", Str(10), nullable=False),
    sa.Column("due", Str(10), nullable=False),
    sa.Column("currency", Str(3), nullable=False),
    sa.Column("amount", Montant, nullable=False),
)
supplier_payments = sa.Table(
    "supplier_payments", meta,
    sa.Column("id", Str(80), primary_key=True),
    sa.Column("party_id", Str(80), nullable=False),
    sa.Column("project", Str(80), nullable=False),
    sa.Column("currency", Str(3), nullable=False),
    sa.Column("amount", Montant, nullable=False),
    sa.Column("date", Str(10), nullable=False),
    sa.Column("account", Str(20), nullable=False),
)
supplier_allocations = sa.Table(
    "supplier_allocations", meta,
    sa.Column("id", Str(80), primary_key=True),
    sa.Column("payment_id", Str(80), nullable=False),
    sa.Column("invoice_id", Str(80), nullable=False),
    sa.Column("amount", Montant, nullable=False),
    sa.Column("date", Str(10), nullable=False),
)
supplier_reversals = sa.Table(
    "supplier_reversals", meta,
    sa.Column("id", Str(80), primary_key=True),
    sa.Column("payment_id", Str(80), nullable=False, unique=True),
    sa.Column("date", Str(10), nullable=False),
    sa.Column("reason", Txt, nullable=False),
    sa.Column("created_at", Str(40), nullable=False),
)
personnel = sa.Table(
    "personnel", meta,
    sa.Column("id", Str(80), primary_key=True),
    sa.Column("code", Str(100), nullable=False, unique=True),
    sa.Column("name", Str(500), nullable=False),
    sa.Column("job", Str(500), default=""),
    sa.Column("service", Str(500), default=""),
    sa.Column("phone", Str(500), default=""),
    sa.Column("start", Str(10), nullable=False),
    sa.Column("location", Str(20), nullable=False),       # Bureau, Chantier
    sa.Column("project", Str(80), default=""),
    sa.Column("active", sa.Boolean, default=True),
    sa.Column("details", Js, nullable=True),
    sa.Column("v7", Js, nullable=True),
    sa.Column("salary", Js, nullable=True),               # confidentiel : RH et direction
    sa.Column("assignments", Js, nullable=True),
)
attendance = sa.Table(
    "attendance", meta,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("person_id", Str(80), nullable=False),
    sa.Column("date", Str(10), nullable=False),
    sa.Column("status", Str(20), nullable=False),
    sa.Column("hours", sa.Float, nullable=False, default=0),
    sa.Column("note", Txt, default=""),
    sa.Column("location", Str(20), nullable=True),
    sa.Column("project", Str(80), nullable=True),
    sa.UniqueConstraint("person_id", "date", name="un_pointage_par_jour"),
)
kobo_pointages = sa.Table(  # lignes des fiches KoboCollect déjà traitées (jamais importées deux fois)
    "kobo_pointages", meta,
    sa.Column("id", Str(200), primary_key=True),            # identifiant de la fiche Kobo + n° de ligne
    sa.Column("fiche", Str(80), nullable=False),
    sa.Column("soumis_le", Str(40), default=""),
    sa.Column("date", Str(10), default=""),
    sa.Column("person_id", Str(80), default=""),
    sa.Column("agent", Str(200), default=""),
    sa.Column("statut", Str(20), default=""),
    sa.Column("heures", sa.Float, default=0),
    sa.Column("lieu", Str(120), default=""),
    sa.Column("pointeur", Str(300), default=""),
    sa.Column("resultat", Str(30), nullable=False),          # Importé, Remplacé, Identique, Ignoré
    sa.Column("attendance_id", sa.Integer, nullable=True),
    sa.Column("donnees", Js, nullable=True),
    sa.Column("traite_le", sa.DateTime, nullable=True),
    sa.Column("traite_par", Str(), default=""),
)
payroll = sa.Table(
    "payroll", meta,
    sa.Column("id", Str(80), primary_key=True),
    sa.Column("person_id", Str(80), nullable=False),
    sa.Column("month", Str(7), nullable=False),
    sa.Column("name", Str(500), default=""),
    sa.Column("code", Str(100), default=""),
    sa.Column("job", Str(500), default=""),
    sa.Column("currency", Str(3), nullable=False),
    sa.Column("period", Str(10), nullable=False),
    sa.Column("quantity", sa.Float, nullable=False),
    sa.Column("rate", Montant, nullable=False),
    sa.Column("elements", Js, nullable=False),            # primes, retenues, charges… (centimes)
    sa.Column("method", Str(10), nullable=False),
    sa.Column("notes", Txt, default=""),
    sa.Column("location", Str(20), nullable=False),
    sa.Column("project", Str(80), default=""),
    sa.Column("prepared", Str(10), nullable=False),
    sa.Column("status", Str(30), nullable=False),
    sa.Column("rules", Js, nullable=True),
    sa.Column("employee_snapshot", Js, nullable=True),
    sa.Column("company_snapshot", Js, nullable=True),
    sa.UniqueConstraint("person_id", "month", name="une_paie_par_mois"),
)
erp_dossiers = sa.Table(
    "erp_dossiers", meta,
    sa.Column("id", Str(80), primary_key=True),
    sa.Column("type", Str(40), nullable=False),
    sa.Column("ref", Str(100), nullable=False),
    sa.Column("date", Str(10), nullable=False),
    sa.Column("project", Str(80), default=""),
    sa.Column("centre", Str(80), default=""),
    sa.Column("party", Str(80), default=""),
    sa.Column("currency", Str(3), nullable=False),
    sa.Column("status", Str(30), nullable=False),
    sa.Column("values", Js, nullable=False),
    sa.Column("notes", Txt, default=""),
    sa.Column("company_snapshot", Js, nullable=True),
    sa.UniqueConstraint("type", "ref", name="ref_unique_par_type"),
)
company_history = sa.Table(
    "company_history", meta,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("before", Js, nullable=False),
    sa.Column("after", Js, nullable=False),
    sa.Column("reason", Txt, nullable=False),
    sa.Column("user_nom", Str(), default=""),
)
pieces_jointes = sa.Table(  # documents joints aux fiches (tiers, personnel, chantiers, devis, factures) : PDF, JPEG, PNG
    "pieces_jointes", meta,
    sa.Column("id", Str(80), primary_key=True),
    sa.Column("entite", Str(40), nullable=False),        # tiers, personnel, chantiers, quotes, invoices
    sa.Column("entite_id", Str(80), nullable=False),
    sa.Column("libelle", Str(200), default=""),
    sa.Column("nom", Str(300), nullable=False),
    sa.Column("mime", Str(40), nullable=False),
    sa.Column("taille", sa.Integer, nullable=False),
    sa.Column("sha256", Str(64), nullable=False),
    sa.Column("contenu", sa.LargeBinary, nullable=False),
    sa.Column("ajoute_par", sa.Integer, nullable=True),
    sa.Column("ajoute_le", sa.DateTime, nullable=False),
)
pieces = sa.Table(  # justificatifs : PDF, JPEG ou PNG
    "pieces", meta,
    sa.Column("id", Str(80), primary_key=True),
    sa.Column("expense_id", Str(200), default=""),
    sa.Column("batch_id", Str(80), default=""),
    sa.Column("name", Str(300), nullable=False),
    sa.Column("mime", Str(40), nullable=False),
    sa.Column("content", sa.LargeBinary, nullable=False),
    sa.Column("size", sa.Integer, nullable=False),
    sa.Column("hash", Str(64), nullable=False, unique=True),
    sa.Column("type", Str(60), nullable=False),
    sa.Column("beneficiary", Str(500), default=""),
    sa.Column("document_date", Str(10), nullable=False),
    sa.Column("amount", Montant, nullable=False, default=0),
    sa.Column("currency", Str(3), default=""),
    sa.Column("status", Str(20), nullable=False),         # Préparée, Validée, Rejetée
    sa.Column("reason", Txt, default=""),
    sa.Column("uploaded_at", sa.DateTime, nullable=False),
    sa.Column("uploaded_by", sa.Integer, nullable=True),
    sa.Column("validated_by", sa.Integer, nullable=True),
    sa.Column("validated_at", sa.DateTime, nullable=True),
)
history_batches = sa.Table(  # lots de reprise historique importés depuis le modèle Excel
    "history_batches", meta,
    sa.Column("id", Str(80), primary_key=True),
    sa.Column("project_ref", Str(200), nullable=False, unique=True),
    sa.Column("project", Js, nullable=False),
    sa.Column("rows", Js, nullable=False),
    sa.Column("source", Str(300), default=""),
    sa.Column("created_at", sa.DateTime, nullable=False),
    sa.Column("created_by", sa.Integer, nullable=True),
)

from schema_v7 import ajouter
ajouter(meta)
from imports.tables import ajouter as ajouter_imports
ajouter_imports(meta)
from schema_v8 import ajouter as ajouter_v8, ajouter_caisse, ajouter_compta
ajouter_v8(meta)
ajouter_compta(meta)
ajouter_caisse(meta)

TABLES = {t.name: t for t in meta.sorted_tables}
NOMS_OBJETS = {
    "clients": "Tiers", "projects": "Chantier", "quotes": "Devis", "invoices": "Facture",
    "expenses": "Dépense", "movements": "Mouvement de trésorerie", "caisse_arretes": "Arrêté de caisse", "supplier_invoices": "Facture fournisseur",
    "supplier_payments": "Paiement fournisseur", "supplier_allocations": "Affectation d'avance",
    "supplier_reversals": "Contre-passation", "personnel": "Personnel", "attendance": "Pointage",
    "kobo_pointages": "Pointage KoboCollect",
    "payroll": "Paie", "erp_dossiers": "Dossier", "company_history": "Société", "pieces": "Justificatif",
    "history_batches": "Lot historique", "users": "Utilisateur", "settings": "Paramètre",
    "v7_records": "Circuit V7", "import_lots": "Lot d’import", "import_previews": "Aperçu d’import",
    "import_mappings": "Correspondance d’import",
    "stk_familles": "Famille d’articles", "stk_articles": "Article", "stk_magasins": "Magasin",
    "stk_soldes": "Solde de stock", "stk_mouvements": "Mouvement de stock", "stk_bons_sortie": "Bon de sortie",
    "stk_bon_sortie_lignes": "Ligne de bon de sortie", "stk_reservations": "Réservation de stock",
    "ach_demandes": "Demande d’achat", "ach_demande_lignes": "Ligne de demande d’achat", "ach_commandes": "Bon de commande",
    "ach_commande_lignes": "Ligne de commande", "ach_receptions": "Réception", "ach_reception_lignes": "Ligne de réception",
    "ach_factures": "Facture d’achat", "ach_facture_lignes": "Ligne de facture d’achat",
    "cpt_comptes": "Compte", "cpt_journaux": "Journal", "cpt_periodes": "Période comptable", "cpt_pieces": "Pièce comptable",
    "cpt_lignes": "Ligne d’écriture", "regles_comptables": "Règle comptable",
}


# ------------------------------------------------------------------ moteur
def maintenant() -> dt.datetime:
    return dt.datetime.now().replace(microsecond=0)


def nouvel_id() -> str:
    return str(uuid.uuid4())


def url_base() -> str:
    url = None
    try:
        url = st.secrets["database"]["url"]
    except Exception:  # noqa: BLE001
        url = os.environ.get("DATABASE_URL")
    if not url:
        dossier = os.path.join(os.path.dirname(os.path.abspath(__file__)), "donnees")
        os.makedirs(dossier, exist_ok=True)
        return "sqlite:///" + os.path.join(dossier, "bati_gestion.db")
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url


@st.cache_resource(show_spinner=False)
def moteur() -> sa.Engine:
    url = url_base()
    if url.startswith("sqlite"):
        eng = sa.create_engine(url, connect_args={"check_same_thread": False})

        @sa.event.listens_for(eng, "connect")
        def _pragma(conn, _):
            conn.execute("PRAGMA foreign_keys=ON")
    else:
        eng = sa.create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)
    migrer(eng)
    return eng


def _empreinte_migrations() -> tuple[str, ...]:
    """Liste des fichiers de migration présents : elle change dès qu'une nouvelle migration est déposée."""
    dossier = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations", "versions")
    try:
        return tuple(sorted(f for f in os.listdir(dossier) if f.endswith(".py")))
    except OSError:
        return ()


@st.cache_resource(show_spinner=False)
def _schema_a_jour(empreinte: tuple[str, ...]) -> bool:
    # Pas de « _ » devant le paramètre : Streamlit ignorerait sa valeur et ne relancerait jamais la mise à jour.
    migrer(moteur())
    return True


def assurer_schema() -> None:
    """Applique les nouvelles migrations sans redémarrer le serveur. Streamlit Cloud recharge le code déposé sur
    GitHub sans relancer le processus : la connexion mise en cache ne repasse donc pas par migrer(). Ici, le cache
    dépend de la liste des fichiers de migration ; une nouvelle migration déclenche la mise à jour au premier
    affichage suivant (opération sans effet si la base est déjà à jour)."""
    _schema_a_jour(_empreinte_migrations())


def migrer(eng: sa.Engine) -> None:
    """Met le schéma à jour par les migrations Alembic versionnées (dossier migrations/), au lieu de la
    création implicite des tables. Une base existante est reprise par la révision de base sans perte."""
    from alembic import command
    from alembic.config import Config
    racine = os.path.dirname(os.path.abspath(__file__))
    cfg = Config(os.path.join(racine, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(racine, "migrations"))
    with eng.begin() as c:
        cfg.attributes["connection"] = c
        command.upgrade(cfg, "head")


def version_schema(eng: sa.Engine | None = None) -> str:
    with (eng or moteur()).connect() as c:
        try:
            return c.execute(sa.text("select version_num from alembic_version")).scalar() or ""
        except Exception:  # noqa: BLE001
            return ""


# ------------------------------------------------------------------ lecture
def _ligne(r) -> dict:
    return dict(r._mapping)


def tout(nom: str, sans: tuple[str, ...] = ()) -> list[dict]:
    """Tous les enregistrements d'une table, sous forme de dictionnaires."""
    t = TABLES[nom]
    cols = [c for c in t.c if c.name not in sans]
    with moteur().connect() as c:
        return [_ligne(r) for r in c.execute(sa.select(*cols))]


def un(nom: str, id_) -> dict | None:
    t = TABLES[nom]
    with moteur().connect() as c:
        r = c.execute(sa.select(t).where(t.c.id == id_)).first()
    return _ligne(r) if r else None


def requete(sql: str, **params) -> list[dict]:
    with moteur().connect() as c:
        return [_ligne(r) for r in c.execute(sa.text(sql), params)]


def parametre(cle: str, defaut=None):
    with moteur().connect() as c:
        v = c.execute(sa.select(settings.c.valeur).where(settings.c.cle == cle)).scalar()
    return defaut if v is None else v


# ------------------------------------------------------------------ écriture + audit
SENSIBLES = {"mdp_hash"}  # jamais recopiés dans le journal d'audit


def _json(v):
    """Rend un enregistrement sérialisable pour l'audit (sans les fichiers)."""
    if v is None:
        return None
    out = {}
    for k, x in v.items():
        if k in SENSIBLES:
            out[k] = "<masqué>"
        elif isinstance(x, (bytes, bytearray, memoryview)):
            out[k] = f"<fichier {len(bytes(x))} octets>"
        elif isinstance(x, (dt.date, dt.datetime)):
            out[k] = x.isoformat()
        else:
            out[k] = x
    return json.loads(json.dumps(out, default=str))


class Transaction:
    """Regroupe plusieurs écritures : tout est enregistré, ou rien (audit compris)."""

    def __init__(self, cx: sa.Connection, resume: str):
        self.cx = cx
        self.resume = resume

    def _auditer(self, action: str, nom: str, id_, avant, apres, resume: str | None = None):
        u = st.session_state.get("utilisateur") or {}
        self.cx.execute(audit.insert().values(
            quand=maintenant(), user_id=u.get("id"), user_nom=u.get("nom", "Système"), action=action,
            objet=nom, objet_id=str(id_ or ""), resume=resume or self.resume, avant=_json(avant), apres=_json(apres)))

    def get(self, nom: str, id_, verrou: bool = False) -> dict | None:
        """Lecture dans la transaction ; verrou=True bloque la ligne jusqu'à la fin (PostgreSQL)."""
        t = TABLES[nom]
        q = sa.select(t).where(t.c.id == id_)
        if verrou and self.cx.dialect.name == "postgresql":
            q = q.with_for_update()
        r = self.cx.execute(q).first()
        return _ligne(r) if r else None

    def lire(self, sql: str, **params) -> list[dict]:
        return [_ligne(r) for r in self.cx.execute(sa.text(sql), params)]

    def _chantier_v7(self, project: str) -> bool:
        """Vrai si le chantier possède un budget V7 non rejeté (un budget importé puis rejeté ne bloque rien)."""
        v7 = TABLES["v7_records"]
        rows = self.cx.execute(sa.select(v7.c.data).where(v7.c.kind == "budget", v7.c.project == project)).fetchall()
        return any((r[0] or {}).get("status") != "Rejeté" for r in rows)

    def inserer(self, nom: str, valeurs: dict, resume: str | None = None):
        t = TABLES[nom]
        if nom in ("expenses", "supplier_invoices", "supplier_payments") and valeurs.get("project"):
            if self._chantier_v7(valeurs["project"]):
                raise ValueError("Chantier V7 : utilisez le circuit financier avec imputation DQE et validations.")
        if nom == "movements" and valeurs.get("kind") != "v7" and valeurs.get("direction") == "out" and valeurs.get("project"):
            if self._chantier_v7(valeurs["project"]):
                raise ValueError("Paiement V7 : autorisation du circuit financier requise.")
        res = self.cx.execute(t.insert().values(**valeurs))
        id_ = valeurs.get("id") or (res.inserted_primary_key[0] if res.inserted_primary_key else None)
        self._auditer("Création", nom, id_, None, valeurs, resume)
        self._comptabiliser("creation", nom, None, {**valeurs, "id": id_})
        return id_

    def _comptabiliser(self, action: str, nom: str, avant: dict | None, apres: dict | None) -> None:
        """Comptabilisation automatique (mémo V8, § 3) des écritures saisies par les écrans historiques : mouvements
        du journal de caisse et factures fournisseurs des comptes tiers. Sans effet avant la date de démarrage."""
        if nom not in ("movements", "supplier_invoices"):
            return
        if nom == "movements":
            import caisses
            caisses.noter(self, avant, apres)
        import comptabilisation as CPT
        if nom == "movements":
            if action == "creation":
                CPT.mouvement_tresorerie(self, apres)
            elif action == "modification":
                CPT.mouvement_modifie(self, avant, apres)
            else:
                CPT.mouvement_supprime(self, avant)
        else:
            if action != "creation" and avant:
                CPT._annuler_source(self, "facture_fournisseur", avant["id"], maintenant().date().isoformat())
            if action != "suppression":
                CPT.facture_fournisseur_historique(self, apres)

    def maj(self, nom: str, id_, valeurs: dict, resume: str | None = None) -> None:
        t = TABLES[nom]
        avant = self.get(nom, id_)
        if avant is None:
            raise ValueError("Cet enregistrement n'existe plus. Actualisez la page.")
        if nom == "movements" and avant.get("kind") == "v7":
            if set(valeurs) != {"journal"} or any(valeurs["journal"].get(k) != (avant.get("journal") or {}).get(k) for k in ("v7_account", "v7_source")):
                raise ValueError("Mouvement V7 figé : contre-passation obligatoire.")
        self.cx.execute(t.update().where(t.c.id == id_).values(**valeurs))
        self._auditer("Modification", nom, id_, {k: avant.get(k) for k in valeurs},
                      valeurs, resume)
        self._comptabiliser("modification", nom, avant, {**avant, **valeurs})

    def supprimer(self, nom: str, id_, resume: str | None = None) -> None:
        t = TABLES[nom]
        avant = self.get(nom, id_)
        if nom == "v7_records" or (nom == "movements" and avant and avant.get("kind") == "v7"):
            raise ValueError("Historique V7 conservé : utilisez annulation ou contre-passation.")
        self.cx.execute(t.delete().where(t.c.id == id_))
        self._auditer("Suppression", nom, id_, avant, None, resume)
        if avant:
            self._comptabiliser("suppression", nom, avant, None)

    def supprimer_ou(self, nom: str, condition, resume: str | None = None) -> None:
        t = TABLES[nom]
        lignes = [_ligne(r) for r in self.cx.execute(sa.select(t).where(condition)).fetchall()]
        for r in lignes:
            self._auditer("Suppression", nom, r.get("id"), r, None, resume)
        self.cx.execute(t.delete().where(condition))
        for r in lignes:
            self._comptabiliser("suppression", nom, r, None)

    def parametre(self, cle: str, valeur, resume: str | None = None) -> None:
        avant = self.cx.execute(sa.select(settings.c.valeur).where(settings.c.cle == cle)).scalar()
        if avant is None:
            self.cx.execute(settings.insert().values(cle=cle, valeur=valeur))
        else:
            self.cx.execute(settings.update().where(settings.c.cle == cle).values(valeur=valeur))
        self._auditer("Modification", "settings", cle, {"valeur": avant}, {"valeur": valeur}, resume)

    def evenement(self, action: str, resume: str, objet: str = "", objet_id: str = "") -> None:
        self._auditer(action, objet, objet_id, None, None, resume)


@contextmanager
def transaction(resume: str):
    with moteur().begin() as cx:
        t = Transaction(cx, resume)
        yield t
        if t.__dict__.get("_caisses"):        # contrôle des soldes de caisse sur le résultat de la transaction
            import caisses
            caisses.verifier(t)


def journaliser(action: str, resume: str, objet: str = "", objet_id: str = "") -> None:
    with transaction(resume) as t:
        t.evenement(action, resume, objet, objet_id)
