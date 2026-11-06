"""Coordonnées GPS des chantiers : saisie, contrôle et enregistrement (carte des chantiers)."""
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import db
from vues.chantiers import lire_gps, texte_gps


class GpsChantiers(unittest.TestCase):
    def test_lecture_depuis_google_maps(self):
        self.assertEqual(lire_gps("-4.3317, 15.3139"), (-4.3317, 15.3139))
        self.assertEqual(lire_gps(" -4.3317 15.3139 "), (-4.3317, 15.3139))
        self.assertEqual(lire_gps(""), (None, None))

    def test_refus_des_coordonnees_invalides(self):
        for mauvais in ("15.3139, -4.3317", "abc", "1, 2, 3", "-4,33"):
            with self.assertRaises(ValueError):
                lire_gps(mauvais)

    def test_enregistrement_et_coordonnees_facultatives(self):
        eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        db.migrer(eng)
        with patch.object(db, "moteur", lambda: eng):
            with eng.begin() as c:
                c.execute(db.projects.insert().values(id="a", name="Sans GPS", currency="USD", status="En cours",
                                                      client="", budget=0, progress=0))
                c.execute(db.projects.insert().values(id="b", name="Limete", currency="USD", status="En cours",
                                                      client="", budget=0, progress=0, latitude=-4.355, longitude=15.346))
            p = {x["id"]: x for x in db.tout("projects")}
        self.assertIsNone(p["a"]["latitude"])
        self.assertEqual(texte_gps(p["a"]), "")
        self.assertEqual(texte_gps(p["b"]), "-4.355, 15.346")


if __name__ == "__main__":
    unittest.main()


class MigrationSansRedemarrage(unittest.TestCase):
    """Streamlit Cloud recharge le code sans relancer le serveur : la migration 0006 doit tout de même s'appliquer."""

    def setUp(self):
        db._schema_a_jour.clear()

    def test_base_en_0005_mise_a_jour_au_premier_affichage(self):
        import os
        from alembic import command
        from alembic.config import Config
        eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cfg = Config(os.path.join(racine, "alembic.ini"))
        cfg.set_main_option("script_location", os.path.join(racine, "migrations"))
        with eng.begin() as c:                      # base de production restée en 0005
            cfg.attributes["connection"] = c
            command.upgrade(cfg, "0005_arretes_caisse")
        with patch.object(db, "moteur", lambda: eng):
            db.assurer_schema()
        import sqlalchemy as sa
        colonnes = {c["name"] for c in sa.inspect(eng).get_columns("projects")}
        self.assertTrue({"latitude", "longitude"} <= colonnes)

    def test_relance_seulement_si_nouvelle_migration(self):
        with patch.object(db, "moteur", lambda: None), patch.object(db, "migrer") as m, \
                patch.object(db, "_empreinte_migrations", return_value=("0005.py",)):
            db.assurer_schema()
            db.assurer_schema()
            self.assertEqual(m.call_count, 1)        # rien à refaire tant qu'aucune migration n'est ajoutée
            with patch.object(db, "_empreinte_migrations", return_value=("0005.py", "0006.py")):
                db.assurer_schema()
            self.assertEqual(m.call_count, 2)        # nouvelle migration déposée : mise à jour immédiate
