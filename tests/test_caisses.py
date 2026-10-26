"""Soldes de caisse, refus des sorties supérieures au solde, arrêtés de caisse (mémo V8, § 9.1)."""
import unittest

import caisses as C
import comptabilisation as CPT
import db
import gestion_v7 as V
from tests.test_comptabilite_lot1 import Base, D_

CASH = "h:cash:USD"


def mvt(t, montant, sens="out", compte="cash", devise="USD", date_=D_, **k):
    vals = {"id": db.nouvel_id(), "kind": "manual", "date": date_, "account": compte, "label": "Opération",
            "direction": sens, "amount": montant, "currency": devise, "project": "", "invoice_id": "",
            "invoice_amount": None, "expense_id": "", "supplier_payment_id": "", "supplier_reversal_id": "",
            "cree_le": db.maintenant(), **k}
    t.inserer("movements", vals)
    return vals["id"]


def ecrire(*args, **k):
    with db.transaction("test") as t:
        return mvt(t, *args, **k)


class Soldes(Base):
    def test_un_solde_par_caisse_et_par_devise_sans_conversion(self):
        import devises as DV
        DV.saisir_taux("USD", "CDF", "2800", D_)
        ecrire(500000, "in", devise="CDF")
        ecrire(30000)
        s = {c["cle"]: c for c in C.caisses()}
        self.assertEqual(s[CASH]["solde"], 10000000 - 30000)
        self.assertEqual(s["h:cash:CDF"]["solde"], 500000)
        self.assertEqual(s[f"v7:{self.bank}"]["solde"], 2000000)
        self.assertEqual(s[CASH]["dernier_montant"], -30000)
        self.assertEqual({c["cle"]: c["solde"] for c in C.caisses("2026-10-01")}[CASH], 10000000)  # solde à une date


class SortiesPlafonnees(Base):
    def test_sortie_superieure_au_solde_refusee(self):
        with self.assertRaisesRegex(ValueError, "Solde insuffisant"):
            ecrire(10000001)
        ecrire(10000000)                                      # exactement le solde : accepté
        self.assertEqual(C.solde(CASH), 0)

    def test_sortie_antidatee_qui_creuse_le_passe_refusee(self):
        ecrire(5000000, "in", date_="2026-10-10")
        with self.assertRaisesRegex(ValueError, "2026-10-05"):
            ecrire(12000000, date_="2026-10-05")              # le solde du 5 n'était que de 100 000 $

    def test_entree_et_sortie_dans_la_meme_transaction(self):
        with db.transaction("virement interne") as t:
            mvt(t, 20000000)                                  # jugé sur le résultat de la transaction
            mvt(t, 15000000, "in")
        self.assertEqual(C.solde(CASH), 5000000)

    def test_suppression_d_une_entree_qui_rendrait_la_caisse_negative(self):
        e = ecrire(5000000, "in")
        ecrire(14000000)
        with self.assertRaisesRegex(ValueError, "Solde insuffisant"), db.transaction("suppression") as t:
            t.supprimer("movements", e)

    def test_banque_autorisee_en_decouvert_et_parametre_dg(self):
        ecrire(10000001, compte="bank")                       # découvert bancaire permis par défaut
        self.as_(5)
        C.configurer({"interdire_negatif": {"cash": False}}, "Caisse de chantier tolérée en négatif")
        ecrire(10000001)
        with self.assertRaisesRegex(ValueError, "DG"):
            self.as_(3)
            C.configurer({"interdire_negatif": {"cash": True}}, "x")

    def test_historique_deja_negatif_n_empeche_pas_une_entree(self):
        with self.engine.begin() as c:                         # donnée reprise d'un ancien système
            c.execute(db.movements.insert().values(id="neg", kind="manual", date="2026-09-30", account="mobile",
                                                   label="Ancien", direction="out", amount=500, currency="USD"))
        ecrire(100, "in", compte="mobile")
        with self.assertRaisesRegex(ValueError, "Solde insuffisant"):
            ecrire(1, compte="mobile")


class Arretes(Base):
    def proposer(self, billets, autres=0, explication="", k=CASH, date_=D_):
        self.as_(6)
        return C.proposer_arrete(k, date_, billets, autres, explication)

    def test_manquant_valide_par_une_autre_personne(self):
        a = self.proposer({"100": 999, "50": 1}, 2500, "Pièces manquantes")   # 99 950 + 25 = 99 975 $
        arr = db.un("caisse_arretes", a)
        self.assertEqual((arr["montant_compte"], arr["ecart"]), (9997500, -2500))
        self.as_(6)
        with self.assertRaisesRegex(ValueError, "Séparation des fonctions"):
            C.decider_arrete(a, True)
        self.as_(3)
        C.decider_arrete(a, True, "PV signé")
        arr = db.un("caisse_arretes", a)
        self.assertEqual(arr["statut"], "Validé")
        self.assertEqual(C.solde(CASH), 9997500)              # solde de l'application = billets comptés
        s = {x["compte"]: x["debit"] - x["credit"] for x in CPT.balance(2026)}
        self.assertEqual((s["658"], s["57"]), (2500, -2500))
        self.assertEqual([c["ecart"] for c in CPT.controle_tresorerie()], [0, 0])
        with self.assertRaisesRegex(ValueError, "arrêtée"):
            self.proposer({"100": 1}, k=CASH, date_="2026-10-15")

    def test_excedent_rejet_et_controles(self):
        with self.assertRaisesRegex(ValueError, "explication"):
            self.proposer({"100": 1001})
        with self.assertRaisesRegex(ValueError, "futur"):
            self.proposer({"100": 1000}, date_="2026-12-01")
        a = self.proposer({"100": 1001}, explication="Encaissement non saisi")
        with self.assertRaisesRegex(ValueError, "déjà en attente"):
            self.proposer({"100": 1001}, explication="doublon")
        self.as_(3)
        with self.assertRaisesRegex(ValueError, "Motif"):
            C.decider_arrete(a, False)
        C.decider_arrete(a, False, "Recompter")
        self.assertEqual(C.solde(CASH), 10000000)             # rejet : rien ne change
        a = self.proposer({"100": 1001}, explication="Encaissement non saisi")
        self.as_(3)
        C.decider_arrete(a, True)
        s = {x["compte"]: x["debit"] - x["credit"] for x in CPT.balance(2026)}
        self.assertEqual(s["758"], -10000)

    def test_mouvement_saisi_apres_le_comptage(self):
        a = self.proposer({"100": 1000})
        ecrire(100, date_="2026-10-15")
        self.as_(3)
        with self.assertRaisesRegex(ValueError, "refaites le comptage"):
            C.decider_arrete(a, True)

    def test_arrete_d_une_caisse_v7_et_cloture_du_mois(self):
        self.as_(6)
        caisse = V.create_account("CASH", "Caisse chantier", "USD", "5711", "cash")
        V.opening(caisse, 300000, "2026-10-02", "init")
        k = f"v7:{caisse}"
        self.assertEqual([e["arretee"] for e in C.etat_cloture("2026-10")], [False, False])
        a = self.proposer({"20": 140}, explication="Billet faux retiré", k=k)
        self.as_(3)
        C.decider_arrete(a, True)
        self.assertEqual(V.balance(db.un("v7_records", caisse)), 280000)
        self.assertEqual({c["journal"]: c["ecart"] for c in CPT.controle_tresorerie()}["CA1"], 0)
        etat = {e["caisse"]: e["arretee"] for e in C.etat_cloture("2026-10")}
        self.assertTrue(etat["Caisse chantier (CASH)"])
        self.assertFalse(etat["Caisse (espèces) — journal de caisse"])


if __name__ == "__main__":
    unittest.main()
