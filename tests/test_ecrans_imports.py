"""Ouverture des écrans d'import avec Streamlit AppTest (base SQLite temporaire, sans exception)."""
import os
import sys
import tempfile
import unittest

from streamlit.testing.v1 import AppTest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ecran():
    import os
    import sys as _s
    _s.path.insert(0, os.environ["BG_RACINE"])
    import importlib
    import streamlit as st
    import db
    import sqlalchemy as sa
    db.moteur()
    with db.moteur().begin() as c:
        if not c.execute(sa.select(db.users.c.id)).first():
            for i, r in enumerate(["admin", "finance", "rh", "chantier", "lecteur"], 1):
                c.execute(db.users.insert().values(id=i, identifiant=r, nom=r.title(), role=r, mdp_hash="x", actif=True,
                                                   doit_changer_mdp=False, version_session=0))
    ident = {"admin": 1, "finance": 2, "rh": 3, "chantier": 4, "lecteur": 5}[os.environ["BG_ROLE"]]
    st.session_state["utilisateur"] = {"id": ident, "identifiant": os.environ["BG_ROLE"], "nom": "Test",
                                       "role": os.environ["BG_ROLE"], "doit_changer_mdp": False}
    getattr(importlib.import_module(os.environ["BG_MODULE"]), "page")()


class Ecrans(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(cls.tmp, "ecrans.db")
        os.environ["BG_RACINE"] = RACINE

    def ouvrir(self, module, role):
        os.environ["BG_MODULE"], os.environ["BG_ROLE"] = module, role
        at = AppTest.from_function(_ecran, default_timeout=60)
        at.run()
        self.assertFalse(at.exception, f"{module} / {role} : {at.exception}")
        return at

    def test_centre_et_pages_metier(self):
        for module in ("vues.imports", "vues.tiers", "vues.chantiers", "vues.personnel", "vues.memo_v7"):
            for role in ("admin", "finance", "rh", "chantier", "lecteur"):
                try:
                    self.ouvrir(module, role)
                except AssertionError:
                    raise

    def test_modele_telechargeable_et_controle_affiche(self):
        at = self.ouvrir("vues.imports", "admin")
        self.assertTrue(any("Fonction" == s.label for s in at.selectbox))
        self.assertGreaterEqual(len(at.tabs), 4)


if __name__ == "__main__":
    unittest.main()
