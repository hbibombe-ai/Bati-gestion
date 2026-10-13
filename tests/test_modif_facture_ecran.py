"""Boîte « Modifier la facture fournisseur » rendue avec Streamlit AppTest (base SQLite temporaire)."""
import os
import sys
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from streamlit.testing.v1 import AppTest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _dialogue(facture_id):
    import os as _os
    import sys as _s
    _s.path.insert(0, _os.environ["BG_RACINE"])
    import streamlit as st
    from vues import comptes_tiers
    st.session_state["utilisateur"] = {"id": 1, "identifiant": "admin", "nom": "Admin", "role": "admin",
                                       "doit_changer_mdp": False}
    comptes_tiers.modifier_facture(facture_id)


class ModifierFactureEcran(unittest.TestCase):
    def setUp(self):
        import db
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        db.meta.create_all(self.engine)
        self.p = patch.object(db, "moteur", lambda: self.engine)
        self.p.start()
        import sqlalchemy as sa
        with self.engine.begin() as c:
            c.execute(db.users.insert().values(id=1, identifiant="admin", nom="Admin", role="admin", mdp_hash="x",
                                               actif=True, doit_changer_mdp=False, version_session=0))
            c.execute(db.projects.insert().values(id="p", name="Projet", currency="USD", status="En cours",
                                                  client="", budget=10000000, progress=0))
            c.execute(db.clients.insert().values(id="f", code="F001", name="Quincaillerie", roles=["supplier"]))
            c.execute(db.supplier_invoices.insert().values(id="sf1", party_id="f", project="p", reference="FR-1",
                                                           date="2026-10-01", due="2026-10-30", currency="USD",
                                                           amount=10000))
            c.execute(db.supplier_invoices.insert().values(id="sf2", party_id="f", project="p", reference="FR-2",
                                                           date="2026-10-02", due="2026-11-01", currency="USD",
                                                           amount=5000))
        self.sa = sa

    def tearDown(self):
        self.p.stop()
        self.engine.dispose()

    def _ouvrir(self, facture_id):
        os.environ["BG_RACINE"] = RACINE
        at = AppTest.from_function(_dialogue, args=(facture_id,), default_timeout=60)
        at.run()
        self.assertFalse(at.exception, f"{at.exception}")
        return at

    def _enregistrer(self, at):
        bouton = next(b for b in at.button if b.label == "Enregistrer les modifications")
        bouton.click()
        at.run()
        self.assertFalse(at.exception, f"{at.exception}")
        return at

    def _reference(self, facture_id):
        import db
        with self.engine.connect() as c:
            return c.execute(db.supplier_invoices.select().where(db.supplier_invoices.c.id == facture_id)).one().reference

    def test_facture_non_reglee_reference_modifiee(self):
        at = self._ouvrir("sf1")
        next(t for t in at.text_input if t.label.startswith("Référence")).input("FR-1-C")
        self._enregistrer(at)
        self.assertEqual(self._reference("sf1"), "FR-1-C")

    def test_facture_reglee_montant_inferieur_refuse(self):
        import db
        with self.engine.begin() as c:
            c.execute(db.supplier_payments.insert().values(id="pay1", party_id="f", project="p", currency="USD",
                                                           amount=6000, date="2026-10-05", account="bank"))
            c.execute(db.supplier_allocations.insert().values(id="al1", payment_id="pay1", invoice_id="sf1",
                                                              amount=6000, date="2026-10-05"))
        at = self._ouvrir("sf1")
        montant = next(n for n in at.number_input if n.label.startswith("Montant total"))
        montant.set_value(50.0)  # 50,00 : inférieur au réglé de 60,00
        self._enregistrer(at)
        self.assertTrue(any("inférieur au total déjà réglé" in e.value for e in at.error))
        self.assertEqual(self._reference("sf1"), "FR-1")

    def test_facture_reglee_reference_modifiable(self):
        import db
        with self.engine.begin() as c:
            c.execute(db.supplier_payments.insert().values(id="pay2", party_id="f", project="p", currency="USD",
                                                           amount=2000, date="2026-10-05", account="bank"))
            c.execute(db.supplier_allocations.insert().values(id="al2", payment_id="pay2", invoice_id="sf2",
                                                              amount=2000, date="2026-10-05"))
        at = self._ouvrir("sf2")
        next(t for t in at.text_input if t.label.startswith("Référence")).input("FR-2-C")
        self._enregistrer(at)
        self.assertEqual(self._reference("sf2"), "FR-2-C")


if __name__ == "__main__":
    unittest.main()
