"""Ouverture des écrans Demandes d'achat et Utilisateurs avec Streamlit AppTest (base SQLite temporaire)."""
import os
import tempfile
import unittest

from streamlit.testing.v1 import AppTest

from tests.test_ecrans_imports import RACINE, _ecran


class EcransAchats(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(cls.tmp, "ecrans_achats.db")
        os.environ["BG_RACINE"] = RACINE

    def ouvrir(self, module, role):
        os.environ["BG_MODULE"], os.environ["BG_ROLE"] = module, role
        at = AppTest.from_function(_ecran, default_timeout=60)
        at.run()
        self.assertFalse(at.exception, f"{module} / {role} : {at.exception}")
        return at

    def test_demandes_et_utilisateurs_pour_chaque_role(self):
        for module in ("vues.demandes_achat", "vues.utilisateurs"):
            for role in ("admin", "finance", "rh", "chantier", "lecteur"):
                self.ouvrir(module, role)

    def test_onglets_postes_et_profils(self):
        at = self.ouvrir("vues.utilisateurs", "admin")
        self.assertEqual([t.label for t in at.tabs][:2], ["Comptes", "Postes et profils"])


if __name__ == "__main__":
    unittest.main()
