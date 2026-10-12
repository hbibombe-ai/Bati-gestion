"""Appels d'offres sur prospects et contrats : règle de saisie et alertes de dépôt."""
import unittest

import regles as R


def prospect(ref, statut=None, limite=None, depot=None, nom="Route Kasa"):
    v = {"name": nom, "contact": "M. Test", "stage": "Prospect"}
    if statut is not None:
        v["ao_statut"] = statut
    if limite is not None:
        v["ao_limite"] = limite
    if depot is not None:
        v["ao_depot"] = depot
    return {"id": ref, "type": "crm", "ref": ref, "date": "2026-10-01", "project": "", "centre": "", "party": "",
            "currency": "USD", "status": "Brouillon", "values": v, "notes": ""}


class RegleDeSaisie(unittest.TestCase):
    def test_a_deposer_exige_une_date_limite(self):
        with self.assertRaisesRegex(ValueError, "date limite"):
            R.validate_dossier(prospect("P1", R.AO_A_DEPOSER), {})

    def test_depose_exige_la_date_de_depot(self):
        with self.assertRaisesRegex(ValueError, "dépôt effectif"):
            R.validate_dossier(prospect("P2", R.AO_DEPOSE, limite="2026-11-01"), {})

    def test_saisie_complete_acceptee(self):
        R.validate_dossier(prospect("P3", R.AO_DEPOSE, limite="2026-11-01", depot="2026-10-20"), {})
        R.validate_dossier(prospect("P4", R.AO_PAS), {})


class Alertes(unittest.TestCase):
    AUJ = "2026-10-12"

    def alertes(self, *dossiers):
        s = {"erp_dossiers": list(dossiers)}
        return [a for a in R.erp_alerts(s, self.AUJ, avec_rh=False) if a["kind"] == "Appel d’offres"]

    def test_limite_depassee_non_depose(self):
        a = self.alertes(prospect("P1", R.AO_A_DEPOSER, limite="2026-10-05"))
        self.assertEqual(len(a), 1)
        self.assertIn("dépassée", a[0]["reason"])
        self.assertEqual(a[0]["date"], "2026-10-05")

    def test_limite_dans_30_jours(self):
        a = self.alertes(prospect("P2", R.AO_A_DEPOSER, limite="2026-11-01"))
        self.assertEqual(len(a), 1)
        self.assertIn("sous 30 jours", a[0]["reason"])

    def test_limite_lointaine_sans_alerte(self):
        self.assertEqual(self.alertes(prospect("P3", R.AO_A_DEPOSER, limite="2027-03-01")), [])

    def test_depose_ou_absent_sans_alerte(self):
        self.assertEqual(self.alertes(prospect("P4", R.AO_DEPOSE, limite="2026-10-05", depot="2026-10-04")), [])
        self.assertEqual(self.alertes(prospect("P5", R.AO_PAS)), [])
        self.assertEqual(self.alertes(prospect("P6")), [])

    def test_contrat_aussi_concerne(self):
        c = prospect("C1", R.AO_A_DEPOSER, limite="2026-10-09")
        c["type"] = "contrats"
        c["values"] = c["values"] | {"name": "Marché voirie", "amount": 100, "start": "2026-10-01"}
        a = self.alertes(c)
        self.assertEqual(len(a), 1)
        self.assertIn("Marché voirie", a[0]["label"])

    def test_limite_non_renseignee_alerte_d_action(self):
        a = self.alertes(prospect("P7", R.AO_A_DEPOSER))
        self.assertEqual(len(a), 1)
        self.assertIn("non renseignée", a[0]["reason"])


class AppelsOffres(unittest.TestCase):
    """Registre des appels d'offres : la date limite est « deadline », le statut de dépôt est partagé."""
    AUJ = "2026-10-12"

    def appel(self, ref, statut=None, deadline="2026-10-20", depot=None):
        v = {"name": "Voirie Limete", "deadline": deadline}
        if statut is not None:
            v["ao_statut"] = statut
        if depot is not None:
            v["ao_depot"] = depot
        return {"id": ref, "type": "appels", "ref": ref, "date": "2026-10-01", "project": "", "centre": "",
                "party": "", "currency": "USD", "status": "Brouillon", "values": v, "notes": ""}

    def alertes(self, *dossiers):
        return [a for a in R.erp_alerts({"erp_dossiers": list(dossiers)}, self.AUJ, avec_rh=False)
                if a["kind"] == "Appel d’offres"]

    def test_alerte_limite_proche(self):
        a = self.alertes(self.appel("A1", R.AO_A_DEPOSER, deadline="2026-10-20"))
        self.assertEqual(len(a), 1)
        self.assertIn("sous 30 jours", a[0]["reason"])

    def test_alerte_limite_depassee(self):
        a = self.alertes(self.appel("A2", R.AO_A_DEPOSER, deadline="2026-10-01"))
        self.assertIn("dépassée", a[0]["reason"])

    def test_depose_sans_alerte(self):
        self.assertEqual(self.alertes(self.appel("A3", R.AO_DEPOSE, deadline="2026-10-01", depot="2026-09-30")), [])

    def test_depose_exige_date_de_depot(self):
        with self.assertRaisesRegex(ValueError, "dépôt effectif"):
            R.validate_dossier(self.appel("A4", R.AO_DEPOSE), {})

    def test_sans_statut_pas_d_alerte(self):
        self.assertEqual(self.alertes(self.appel("A5")), [])


if __name__ == "__main__":
    unittest.main()
