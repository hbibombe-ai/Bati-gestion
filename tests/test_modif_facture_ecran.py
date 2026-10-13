"""Boîte « Modifier la facture fournisseur » rendue avec Streamlit AppTest (base SQLite temporaire)."""
import os
import sys
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from streamlit.testing.v1 import AppTest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _dialogue(facture_id, role="admin"):
    import os as _os
    import sys as _s
    _s.path.insert(0, _os.environ["BG_RACINE"])
    import streamlit as st
    from vues import comptes_tiers
    st.session_state["utilisateur"] = {"id": 1, "identifiant": role, "nom": role.title(), "role": role,
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

    def _ouvrir(self, facture_id, role="admin"):
        os.environ["BG_RACINE"] = RACINE
        at = AppTest.from_function(_dialogue, args=(facture_id, role), default_timeout=60)
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

    def test_non_administrateur_ne_peut_pas_modifier(self):
        for role in ("finance", "chantier", "lecteur"):
            with self.subTest(role=role):
                at = self._ouvrir("sf1", role=role)
                self.assertTrue(any("réservée à l’administrateur" in e.value for e in at.error))
                self.assertFalse(any(t.label.startswith("Référence") for t in at.text_input))
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


def _creer(role="admin"):
    import os as _os
    import sys as _s
    _s.path.insert(0, _os.environ["BG_RACINE"])
    import streamlit as st
    from vues import comptes_tiers
    st.session_state["utilisateur"] = {"id": 1, "identifiant": role, "nom": role.title(), "role": role,
                                       "doit_changer_mdp": False}
    comptes_tiers.facture_fournisseur()


class CreerFactureAvecPieceJointe(unittest.TestCase):
    def setUp(self):
        import db
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        db.meta.create_all(self.engine)
        self.p = patch.object(db, "moteur", lambda: self.engine)
        self.p.start()
        with self.engine.begin() as c:
            c.execute(db.users.insert().values(id=1, identifiant="admin", nom="Admin", role="admin", mdp_hash="x",
                                               actif=True, doit_changer_mdp=False, version_session=0))
            c.execute(db.projects.insert().values(id="p", name="Projet", currency="USD", status="En cours",
                                                  client="", budget=10000000, progress=0))
            c.execute(db.clients.insert().values(id="f", code="F001", name="Quincaillerie", roles=["supplier"]))

    def tearDown(self):
        self.p.stop()
        self.engine.dispose()

    def test_piece_jointe_rattachee_a_la_nouvelle_facture(self):
        import datetime as dt
        import hashlib
        import db
        os.environ["BG_RACINE"] = RACINE
        at = AppTest.from_function(_creer, args=("finance",), default_timeout=60)
        at.run()
        self.assertFalse(at.exception, f"{at.exception}")
        cible = at.session_state["sf_id_new"]
        # Simule l'ajout d'un bon de commande (le téléversement lui-même est couvert par test_pieces_jointes)
        contenu = b"%PDF-1.4 test"
        with self.engine.begin() as c:
            c.execute(db.pieces_jointes.insert().values(
                id="pj1", entite="supplier_invoice", entite_id=cible, libelle="Bon de commande", nom="bc.pdf",
                mime="application/pdf", taille=len(contenu), sha256=hashlib.sha256(contenu).hexdigest(),
                contenu=contenu, ajoute_par=1, ajoute_le=dt.datetime(2026, 10, 13)))
        at.run()
        at.selectbox(key="sf_t").set_value("f")
        at.selectbox(key="sf_p").set_value("p")
        next(t for t in at.text_input if t.label.startswith("Référence")).input("FR-9")
        next(n for n in at.number_input if n.label.startswith("Montant total")).set_value(150.0)
        next(b for b in at.button if b.label == "Enregistrer").click()
        at.run()
        self.assertFalse(at.exception, f"{at.exception}")
        self.assertEqual([e.value for e in at.error], [])
        with self.engine.connect() as c:
            facture = c.execute(db.supplier_invoices.select().where(db.supplier_invoices.c.reference == "FR-9")).one()
            pj = c.execute(db.pieces_jointes.select().where(db.pieces_jointes.c.id == "pj1")).one()
        self.assertEqual(facture.id, cible)
        self.assertEqual(pj.entite_id, facture.id)


if __name__ == "__main__":
    unittest.main()
