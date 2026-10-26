"""Taux du jour et affichage consolidé : rien n'est converti en base, les totaux convertis sont indicatifs."""
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import auth
import db
import devises as DV
import gestion_v7 as V
import regles as R
import ui


class Devises(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        db.meta.create_all(self.engine)
        self.p1 = patch.object(db, "moteur", lambda: self.engine)
        self.p1.start()
        self.user = None
        self.p2 = patch.object(auth, "utilisateur", lambda: self.user)
        self.p2.start()
        self.p3 = patch.object(R, "today", lambda: "2026-10-16")
        self.p3.start()
        with self.engine.begin() as c:
            for i, role in ((1, "admin"), (2, "finance"), (3, "chantier")):
                c.execute(db.users.insert().values(id=i, identifiant=f"u{i}", nom=f"U{i}", role=role, mdp_hash="x",
                                                   actif=True, doit_changer_mdp=False, version_session=0))
        DV.vider_cache()
        self.as_(2)

    def tearDown(self):
        DV.vider_cache()
        for p in (self.p3, self.p2, self.p1):
            p.stop()
        self.engine.dispose()

    def as_(self, i):
        self.user = db.un("users", i)

    def test_taux_du_jour_et_conversion(self):
        DV.saisir_taux("USD", "CDF", "2 850", "2026-10-16", "BCC")
        self.assertEqual(DV.convertir(100000, "USD", "CDF"), 285000000)
        self.assertEqual(DV.convertir(285000000, "CDF", "USD"), 100000)      # inverse
        self.assertEqual(DV.convertir(5000, "USD", "USD"), 5000)

    def test_correction_le_meme_jour_tracee(self):
        DV.saisir_taux("USD", "CDF", "2800", "2026-10-16")
        DV.saisir_taux("USD", "CDF", "2850", "2026-10-16")
        rows = V.records("rate")
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["data"]["rate"], rows[0]["data"]["corrige"][0]["ancien"]), ("2850", "2800"))

    def test_dernier_taux_connu_a_la_date(self):
        DV.saisir_taux("USD", "CDF", "2800", "2026-10-01")
        DV.saisir_taux("USD", "CDF", "2850", "2026-10-15")
        self.assertEqual(DV.taux("USD", "CDF", "2026-10-10")["taux"], 2800)
        self.assertEqual(DV.taux("USD", "CDF", "2026-10-16")["taux"], 2850)
        self.assertIsNone(DV.taux("USD", "CDF", "2026-09-30"))

    def test_pivot_eur_cdf_par_usd(self):
        DV.saisir_taux("USD", "CDF", "2850", "2026-10-16")
        DV.saisir_taux("EUR", "USD", "1,10", "2026-10-14")
        t = DV.taux("EUR", "CDF", "2026-10-16")
        self.assertEqual((t["taux"], t["pivot"], t["date"]), (3135, "USD", "2026-10-14"))

    def test_consolidation_sans_conversion_implicite(self):
        DV.saisir_taux("USD", "CDF", "2850", "2026-10-16")
        c = DV.consolider({"USD": 100000, "CDF": 285000000, "EUR": 5000}, "USD")
        self.assertEqual((c["total"], c["manquantes"]), (200000, ["EUR"]))   # EUR jamais converti à 1
        texte = DV.texte_consolide({"USD": 100000, "CDF": 285000000}, "USD")
        self.assertIn("≈ 2", texte)
        self.assertIn("1 USD = 2 850 CDF", texte)
        self.assertEqual(DV.texte_consolide({"USD": 100000}, "USD"), "")      # une seule devise, déjà la bonne
        self.assertIn("aucun taux", DV.texte_consolide({"EUR": 1000}, "USD"))

    def test_taux_ancien_signale(self):
        DV.saisir_taux("USD", "CDF", "2850", "2026-10-01")
        c = DV.consolider({"CDF": 285000000}, "USD")
        self.assertEqual((c["total"], c["anciens"]), (100000, ["CDF"]))
        self.assertTrue(DV.etat_du_jour()[0]["ancien"])
        self.assertFalse(DV.etat_du_jour()[0]["du_jour"])

    def test_controles_de_saisie_et_droits(self):
        for args in (("USD", "USD", "1"), ("USD", "CDF", "0"), ("USD", "CDF", "abc"), ("USD", "XAF", "2")):
            with self.assertRaises(ValueError):
                DV.saisir_taux(*args, "2026-10-16")
        with self.assertRaises(ValueError):
            DV.saisir_taux("USD", "CDF", "2850", "2026-10-17")               # date future
        self.as_(3)
        with self.assertRaises(ValueError):
            DV.saisir_taux("USD", "CDF", "2850", "2026-10-16")               # conducteur de travaux

    def test_affichage_des_totaux_et_reglages(self):
        DV.saisir_taux("USD", "CDF", "2850", "2026-10-16")
        html = ui.montants_html({"USD": 100000, "CDF": 285000000, "EUR": 0})
        self.assertIn("≈", html)
        self.assertIn("≈", ui.montants_texte({"USD": 1, "CDF": 2850}, True, consolide_aussi=True))
        self.assertNotIn("≈", ui.montants_texte({"USD": 1, "CDF": 2850}, True))
        DV.configurer("CDF", 5)
        self.assertEqual(DV.reglages(), {"devise": "CDF", "anciennete_jours": 5})
        self.assertEqual(DV.consolider({"USD": 100000})["total"], 285000000)

    def test_sauvegarde_inclut_les_taux(self):
        import migration
        DV.saisir_taux("USD", "CDF", "2850", "2026-10-16")
        self.as_(1)
        migration.import_json(migration.export_json())
        DV.vider_cache()
        self.assertEqual(DV.taux("USD", "CDF")["taux"], 2850)


if __name__ == "__main__":
    unittest.main()
