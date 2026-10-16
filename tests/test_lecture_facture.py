"""Lecture automatique d'une facture jointe : champs proposés à partir du texte."""
import unittest

import lecture_facture as L

FACTURE = """QUINCAILLERIE CENTRALE SARL
Facture n° FR-2026-0042
Date de facture : 01/10/2026
Échéance : 30/10/2026
Désignation ciment 50 kg
Total HT : 1 000,00 USD
TVA 16% : 160,00 USD
TOTAL TTC : 1 160,00 USD"""
FOURNISSEURS = [("f1", "Quincaillerie Centrale SARL"), ("f2", "Autre fournisseur")]


class ExtractionFacture(unittest.TestCase):
    def test_champs_extraits(self):
        r = L.extraire(FACTURE, FOURNISSEURS)
        self.assertEqual(r["reference"], "FR-2026-0042")
        self.assertEqual(r["date"], "2026-10-01")
        self.assertEqual(r["due"], "2026-10-30")
        self.assertEqual(r["amount"], 116000)  # TTC, pas le HT
        self.assertEqual(r["currency"], "USD")
        self.assertEqual(r["party_id"], "f1")
        self.assertTrue(r["lisible"])

    def test_texte_vide_ou_image(self):
        r = L.extraire("", FOURNISSEURS)
        self.assertFalse(r["lisible"])
        self.assertIsNone(r["reference"])
        self.assertIsNone(r["amount"])

    def test_montants_formats_differents(self):
        self.assertEqual(L.montant_centimes("1,234.56"), 123456)
        self.assertEqual(L.montant_centimes("1.234,56"), 123456)
        self.assertEqual(L.montant_centimes("1 234 567,89"), 123456789)
        self.assertEqual(L.montant_centimes("12,5"), 1250)
        self.assertEqual(L.montant_centimes("1.234"), 123400)
        self.assertIsNone(L.montant_centimes("abc"))

    def test_date_en_lettres(self):
        self.assertEqual(L.date_iso("Fait le 5 octobre 2026"), "2026-10-05")
        self.assertEqual(L.date_iso("2026-09-30"), "2026-09-30")
        self.assertIsNone(L.date_iso("31/02/2026"))

    def test_reference_ne_prend_pas_une_date(self):
        r = L.extraire("Facture : 05/10/2026\nTOTAL 10,00 USD\nFournisseur Test SARL", [])
        self.assertIsNone(r["reference"])

    def test_bilan(self):
        trouves, manquants = L.bilan({"reference": "X1", "date": None, "due": None, "amount": 100,
                                      "currency": None, "party_id": None})
        self.assertIn("référence", trouves)
        self.assertIn("date de facture", manquants)
        self.assertIn("monnaie", manquants)


if __name__ == "__main__":
    unittest.main()
