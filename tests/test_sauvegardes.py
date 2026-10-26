"""Lot 0 V8 : sauvegarde quotidienne, rétention et test de restauration dans une base jetable."""
import datetime as dt
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

import sqlalchemy as sa

import auth
import db

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import sauvegarde_quotidienne as SQ  # noqa: E402
import test_restauration as TR  # noqa: E402


class Sauvegardes(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.engine = sa.create_engine("sqlite:///" + os.path.join(self.dir, "prod.db"))
        db.migrer(self.engine)
        self.p1 = patch.object(db, "moteur", lambda: self.engine)
        self.p1.start()
        self.p2 = patch.object(auth, "utilisateur", lambda: {"id": 1, "role": "admin", "nom": "Admin"})
        self.p2.start()
        with self.engine.begin() as c:
            c.execute(db.users.insert().values(id=1, identifiant="admin", nom="Admin", role="admin", mdp_hash="x"))
            c.execute(db.projects.insert().values(id="p", name="Chantier", currency="USD", status="En cours",
                                                  client="", budget=125000, progress=10))
            c.execute(db.clients.insert().values(id="f", code="F001", name="Fournisseur", roles=["supplier"]))

    def tearDown(self):
        self.p2.stop()
        self.p1.stop()
        self.engine.dispose()

    def test_sauvegarde_puis_restauration_conforme(self):
        dossier = os.path.join(self.dir, "sauv")
        fichiers = SQ.sauvegarder(dossier, 30, dt.datetime(2026, 10, 16, 2, 0))
        self.assertEqual([os.path.basename(f) for f in fichiers], ["bati-20261016-0200.json.gz"])
        self.assertTrue(os.path.exists(fichiers[0] + ".sha256"))
        ok, pv = TR.tester(fichiers[0])
        self.assertTrue(ok, "\n".join(pv))
        self.assertIn("RESTAURATION CONFORME", pv[-1])
        with self.engine.connect() as c:                       # la base de production n'a pas été touchée
            self.assertEqual(c.execute(sa.text("select count(*) from projects")).scalar(), 1)

    def test_fichier_altere_refuse(self):
        dossier = os.path.join(self.dir, "sauv")
        f = SQ.sauvegarder(dossier, 30, dt.datetime(2026, 10, 16, 2, 0))[0]
        with open(f, "ab") as h:
            h.write(b"x")
        with self.assertRaises(ValueError):
            TR.tester(f)

    def test_retention_30_jours_garde_la_derniere(self):
        dossier = os.path.join(self.dir, "sauv")
        for jour in (1, 10, 40, 60):
            SQ.sauvegarder(dossier, 30, dt.datetime(2026, 8, 1, 2, 0) + dt.timedelta(days=jour))
        restants = sorted(f for f in os.listdir(dossier) if f.endswith(".json.gz"))
        # sauvegardes du 2 et du 11 août supprimées au 30 septembre ; celles du 10 et du 30 septembre gardées
        self.assertEqual(restants, ["bati-20260910-0200.json.gz", "bati-20260930-0200.json.gz"])


if __name__ == "__main__":
    unittest.main()
