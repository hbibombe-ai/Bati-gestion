"""Contrôle de doublon et de règlement à la saisie d'une facture fournisseur."""
import unittest

import regles as R


def _base(paye=0):
    s = {
        "supplier_invoices": [
            {"id": "f1", "party_id": "p1", "project": "c1", "currency": "USD", "reference": "FR-1",
             "date": "2026-10-01", "due": "2026-10-30", "amount": 10000},
        ],
        "supplier_payments": [], "supplier_allocations": [], "supplier_reversals": [],
    }
    if paye:
        s["supplier_payments"].append({"id": "pay1", "party_id": "p1", "project": "c1", "currency": "USD",
                                       "amount": paye, "date": "2026-10-05", "account": "bank"})
        s["supplier_allocations"].append({"payment_id": "pay1", "invoice_id": "f1", "amount": paye,
                                          "date": "2026-10-05"})
    return s


class StatutFactureFournisseur(unittest.TestCase):
    def test_aucune_facture_correspondante(self):
        self.assertIsNone(R.statut_facture_fournisseur(_base(), "p1", "FR-99", 10000))
        self.assertIsNone(R.statut_facture_fournisseur(_base(), "p9", "FR-1", 10000))
        self.assertIsNone(R.statut_facture_fournisseur(_base(), "p1", "  ", 10000))

    def test_non_reglee(self):
        r = R.statut_facture_fournisseur(_base(), "p1", "fr-1", 10000)
        self.assertEqual(r["statut"], "non réglée")
        self.assertEqual(r["reste"], 10000)
        self.assertTrue(r["montant_identique"])

    def test_partiellement_reglee(self):
        r = R.statut_facture_fournisseur(_base(paye=4000), "p1", "FR-1", 10000)
        self.assertEqual(r["statut"], "partiellement réglée")
        self.assertEqual(r["paye"], 4000)
        self.assertEqual(r["reste"], 6000)

    def test_reglee(self):
        r = R.statut_facture_fournisseur(_base(paye=10000), "p1", "FR-1", 10000)
        self.assertEqual(r["statut"], "réglée")
        self.assertEqual(r["reste"], 0)

    def test_paiement_contrepasse_ne_compte_pas(self):
        s = _base(paye=10000)
        s["supplier_reversals"] = [{"payment_id": "pay1"}]
        self.assertEqual(R.statut_facture_fournisseur(s, "p1", "FR-1", 10000)["statut"], "non réglée")

    def test_montant_different_signale(self):
        r = R.statut_facture_fournisseur(_base(), "p1", "FR-1", 9000)
        self.assertFalse(r["montant_identique"])


if __name__ == "__main__":
    unittest.main()
