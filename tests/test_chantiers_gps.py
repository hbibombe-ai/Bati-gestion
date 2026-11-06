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
