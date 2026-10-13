"""Modification d'une facture fournisseur : règles de validation (sans et avec règlements)."""
import unittest

import regles as R


def _base():
    return {
        "clients": [], "projects": [],
        "supplier_invoices": [
            {"id": "f1", "party_id": "p1", "project": "c1", "currency": "USD", "reference": "FR-1",
             "date": "2026-10-01", "due": "2026-10-30", "amount": 10000},
            {"id": "f2", "party_id": "p1", "project": "c1", "currency": "USD", "reference": "FR-2",
             "date": "2026-10-02", "due": "2026-11-01", "amount": 5000},
        ],
        "supplier_payments": [{"id": "pay1", "party_id": "p1", "project": "c1", "currency": "USD",
                               "amount": 6000, "date": "2026-10-05", "account": "bank"}],
        "supplier_allocations": [],
        "supplier_reversals": [],
    }


def _nouvelles(**changements):
    base = {"party_id": "p1", "project": "c1", "currency": "USD", "reference": "FR-1",
            "date": "2026-10-01", "due": "2026-10-30", "amount": 10000}
    base.update(changements)
    return base


class ModificationSansReglement(unittest.TestCase):
    def test_tous_les_champs_modifiables(self):
        s = _base()
        R.valider_modif_facture_fournisseur(s, "f1", _nouvelles(
            reference="FR-1-BIS", date="2026-09-30", due="2026-11-15", amount=12000, project="c2", currency="EUR"))

    def test_reference_obligatoire(self):
        with self.assertRaisesRegex(ValueError, "référence"):
            R.valider_modif_facture_fournisseur(_base(), "f1", _nouvelles(reference="  "))

    def test_reference_en_double_pour_le_meme_fournisseur_refusee(self):
        with self.assertRaisesRegex(ValueError, "existe déjà"):
            R.valider_modif_facture_fournisseur(_base(), "f1", _nouvelles(reference="fr-2"))

    def test_meme_reference_chez_un_autre_fournisseur_acceptee(self):
        R.valider_modif_facture_fournisseur(_base(), "f1", _nouvelles(party_id="p9", reference="FR-2"))

    def test_echeance_avant_date_refusee(self):
        with self.assertRaisesRegex(ValueError, "échéance"):
            R.valider_modif_facture_fournisseur(_base(), "f1", _nouvelles(due="2026-09-01"))

    def test_montant_nul_refuse(self):
        with self.assertRaisesRegex(ValueError, "positif"):
            R.valider_modif_facture_fournisseur(_base(), "f1", _nouvelles(amount=0))

    def test_paiement_contrepasse_ne_bloque_pas(self):
        s = _base()
        s["supplier_allocations"] = [{"payment_id": "pay1", "invoice_id": "f1", "amount": 6000, "date": "2026-10-05"}]
        s["supplier_reversals"] = [{"payment_id": "pay1"}]
        R.valider_modif_facture_fournisseur(s, "f1", _nouvelles(party_id="p9", amount=3000))


class ModificationAvecReglement(unittest.TestCase):
    def setUp(self):
        self.s = _base()
        self.s["supplier_allocations"] = [{"payment_id": "pay1", "invoice_id": "f1", "amount": 6000,
                                           "date": "2026-10-05"}]

    def test_reference_et_echeance_modifiables(self):
        R.valider_modif_facture_fournisseur(self.s, "f1", _nouvelles(reference="FR-1-C", due="2026-12-01"))

    def test_montant_superieur_au_regle_accepte(self):
        R.valider_modif_facture_fournisseur(self.s, "f1", _nouvelles(amount=15000))

    def test_montant_egal_au_regle_accepte(self):
        R.valider_modif_facture_fournisseur(self.s, "f1", _nouvelles(amount=6000))

    def test_montant_inferieur_au_regle_refuse(self):
        with self.assertRaisesRegex(ValueError, "inférieur au total déjà réglé"):
            R.valider_modif_facture_fournisseur(self.s, "f1", _nouvelles(amount=5999))

    def test_changement_de_fournisseur_refuse(self):
        with self.assertRaisesRegex(ValueError, "ne peuvent plus être modifiés"):
            R.valider_modif_facture_fournisseur(self.s, "f1", _nouvelles(party_id="p9"))

    def test_changement_de_chantier_monnaie_ou_date_refuse(self):
        for changement in ({"project": "c2"}, {"currency": "EUR"}, {"date": "2026-09-30"}):
            with self.subTest(changement=changement):
                with self.assertRaisesRegex(ValueError, "ne peuvent plus être modifiés"):
                    R.valider_modif_facture_fournisseur(self.s, "f1", _nouvelles(**changement))

    def test_facture_inconnue_refusee(self):
        with self.assertRaisesRegex(ValueError, "introuvable"):
            R.valider_modif_facture_fournisseur(self.s, "inconnue", _nouvelles())


if __name__ == "__main__":
    unittest.main()
