"""Lot 0 V8 : migrations Alembic (base neuve, reprise d'une base existante, schéma conforme au modèle)."""
import os
import tempfile
import unittest

import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

import db


def _ecarts(eng):
    with eng.connect() as c:
        diff = compare_metadata(MigrationContext.configure(c, opts={"compare_type": True}), db.meta)
    # Écarts de type purement SQLite (JSON relu comme JSON, etc.) ignorés : on contrôle tables, colonnes, index.
    return [d for d in diff if not (isinstance(d, list) and d and d[0][0] == "modify_type")]


class Migrations(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def moteur(self, nom):
        return sa.create_engine("sqlite:///" + os.path.join(self.dir, nom))

    def test_base_neuve_conforme_au_modele(self):
        eng = self.moteur("neuve.db")
        db.migrer(eng)
        self.assertEqual(_ecarts(eng), [])
        self.assertTrue(db.version_schema(eng))

    def test_reprise_d_une_base_existante_sans_perte(self):
        eng = self.moteur("existante.db")
        nouvelles = ("ach_", "stk_", "cpt_", "regles_comptables", "caisse_")
        anciennes = [t for t in db.meta.sorted_tables if not t.name.startswith(nouvelles)]
        db.meta.create_all(eng, tables=anciennes)       # base créée par l'ancien démarrage (create_all)
        with eng.begin() as c:
            c.execute(db.users.insert().values(identifiant="admin", nom="Admin", role="admin", mdp_hash="x"))
            c.execute(sa.text("drop index if exists ix_v7_records_kind_project"))
        db.migrer(eng)
        db.migrer(eng)                                   # idempotent
        self.assertEqual(_ecarts(eng), [])
        with eng.connect() as c:
            self.assertEqual(c.execute(sa.text("select count(*) from users")).scalar(), 1)
            idx = {i["name"] for i in sa.inspect(c).get_indexes("v7_records")}
        self.assertIn("ix_v7_records_kind_project", idx)

    def test_unicite_v7_portee_par_la_base(self):
        eng = self.moteur("unicite.db")
        db.migrer(eng)
        with eng.begin() as c:
            c.execute(db.TABLES["v7_records"].insert().values(id="a", kind="operation", ref="OP1", project="",
                                                              currency="USD", data={}, version=1))
        with self.assertRaises(sa.exc.IntegrityError), eng.begin() as c:
            c.execute(db.TABLES["v7_records"].insert().values(id="b", kind="operation", ref="OP1", project="",
                                                              currency="USD", data={}, version=1))


if __name__ == "__main__":
    unittest.main()
