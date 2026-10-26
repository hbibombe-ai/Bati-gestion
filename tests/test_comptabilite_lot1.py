"""Lot 1 V8 (suite) : comptabilisation du circuit V7, de la trésorerie historique, des dépenses et des comptes tiers.

Critère de sortie du mémo : balance équilibrée ; trésorerie de l'application = soldes des comptes 52 / 57 / 55.
"""
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import auth
import comptabilisation as CPT
import db
import devises as DV
import gestion_v7 as V
import regles as R
import stocks as S

D_ = "2026-10-16"


class Base(unittest.TestCase):
    debut = "2026-10-01"

    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        db.meta.create_all(self.engine)
        self.p1 = patch.object(db, "moteur", lambda: self.engine)
        self.p1.start()
        self.user = None
        self.p2 = patch.object(auth, "utilisateur", lambda: self.user)
        self.p2.start()
        self.p3 = patch.object(R, "today", lambda: D_)
        self.p3.start()
        DV.vider_cache()
        with self.engine.begin() as c:
            for id_, role in enumerate(["chantier", "chantier", "finance", "finance", "admin", "finance", "admin"], 1):
                c.execute(db.users.insert().values(id=id_, identifiant=str(id_), nom=f"User {id_}", role=role,
                                                   mdp_hash="x", actif=True, doit_changer_mdp=False, version_session=0))
            c.execute(db.projects.insert().values(id="p", name="Projet", currency="USD", status="En cours", client="",
                                                  budget=0, progress=0))
            c.execute(db.clients.insert().values(id="f", code="F001", name="Fournisseur", roles=["supplier"]))
            c.execute(db.clients.insert().values(id="c", code="C001", name="Client", roles=["client"]))
        self.as_(5)
        S.fixer_tenue("USD", "PV DG", "Décision", self.debut)
        self.as_(3)
        CPT.importer_plan([dict(numero="12", libelle="Report à nouveau"), dict(numero="62", libelle="Services extérieurs A")],
                          "Extrait du plan validé")
        CPT.configurer({"compte_ouverture": "12", "compte_factures_historiques": "605",
                        "comptes_depenses": {"Matériaux": "605", "Transport": "62"}}, "Paramétrage initial")
        self.as_(1)
        self.b = V.create_budget("p", "CT", [dict(code="MAT", label="Matériaux", budget=10000000)], 15000000, 9000000)
        self.as_(5)
        V.approve_budget(self.b, "ok")
        self.as_(6)
        self.bank = V.create_account("BANK", "Banque", "USD", "5211", "bank")
        V.opening(self.bank, 2000000, "2026-10-02", "init")
        # Fonds du journal de caisse historique, antérieurs au démarrage comptable (ni comptabilisés ni contrôlés) :
        # une sortie ne peut pas dépasser le solde de la caisse.
        with db.transaction("Soldes de départ") as t:
            for compte in ("cash", "bank"):
                t.inserer("movements", {"id": f"ouv-{compte}", "kind": "opening", "date": "2026-09-30",
                                        "account": compte, "label": "Solde de départ", "direction": "in",
                                        "amount": 10000000, "currency": "USD", "project": "", "invoice_id": "",
                                        "invoice_amount": None, "expense_id": "", "supplier_payment_id": "",
                                        "supplier_reversal_id": ""})

    def tearDown(self):
        DV.vider_cache()
        for p in (self.p3, self.p2, self.p1):
            p.stop()
        self.engine.dispose()

    def as_(self, i):
        u = db.un("users", i)
        self.user = {**u, "droits": auth.droits_de(u["id"], u["role"])}

    def op(self, ref="OP1", nature="Achat", valeur=100000, compte=None):
        self.as_(1)
        i = V.create_operation(ref, "p", "MAT", "f", "Ciment", nature, valeur, "2026-10-30", "605")
        V.submit(i)
        for uid in (2, 3, 4, 5):
            self.as_(uid)
            V.approve(i, "ok")
        return i

    def soldes(self):
        return {x["compte"]: x["debit"] - x["credit"] for x in CPT.balance(2026)}

    def equilibre(self):
        bal = CPT.balance(2026)
        self.assertEqual(sum(x["debit"] for x in bal), sum(x["credit"] for x in bal))
        for c in CPT.controle_tresorerie():
            self.assertEqual(c["ecart"], 0, c)


class CircuitV7(Base):
    def test_achat_facture_et_paiement(self):
        i = self.op()
        self.as_(3)
        V.order(i, "BC1", D_)
        self.as_(2)
        V.receive(i, "BL1", D_, 100000)
        self.as_(3)
        V.invoice(i, "FAC1", D_, 100000)
        self.as_(6)
        V.pay(i, self.bank, 40000, D_, "P1")
        V.pay(i, self.bank, 60000, D_, "P2")
        s = self.soldes()
        self.assertEqual((s["605"], s.get("401", 0), s["5211"], s["12"]), (100000, 0, 1900000, -2000000))
        charge = [l for l in db.tout("cpt_lignes") if l["compte"] == "605"][0]
        self.assertEqual((charge["projet"], charge["poste"]), ("p", "MAT"))
        self.equilibre()
        self.assertEqual({p["journal"] for p in db.tout("cpt_pieces")}, {"ACH", "BQ1"})

    def test_contre_passation_paiement(self):
        i = self.op()
        self.as_(3)
        V.order(i, "BC1", D_)
        self.as_(2)
        V.receive(i, "BL1", D_, 100000)
        self.as_(3)
        V.invoice(i, "FAC1", D_, 100000)
        self.as_(6)
        V.pay(i, self.bank, 100000, D_, "P1")
        pid = db.un("v7_records", i)["data"]["payments"][0]["id"]
        V.reverse_payment(i, pid, D_, "erreur de compte")
        s = self.soldes()
        self.assertEqual((s["401"], s["5211"]), (-100000, 2000000))
        self.equilibre()

    def test_avance_justifiee_et_restituee(self):
        i = self.op("ADV", "Avance", 50000)
        self.as_(6)
        caisse = V.create_account("CASH", "Caisse", "USD", "5711", "cash")
        V.opening(caisse, 100000, "2026-10-02", "init")
        V.pay(i, self.bank, 50000, D_, "AV1")
        self.as_(1)
        V.upload_piece(i, "facture.pdf", b"%PDF-1", D_, 35000)
        piece = db.un("v7_records", i)["data"]["justifications"][0]["piece"]
        self.as_(3)
        V.validate_justification(i, piece, True, "Pièce contrôlée")
        self.as_(6)
        V.return_advance(i, caisse, 15000, D_, "RET")
        s = self.soldes()
        self.assertEqual((s.get("581", 0), s["605"], s["5711"]), (0, 35000, 115000))
        self.equilibre()

    def test_virement_entre_comptes(self):
        self.as_(6)
        caisse = V.create_account("CASH", "Caisse", "USD", "5711", "cash")
        V.transfer(self.bank, caisse, 300000, D_, "VIR1")
        s = self.soldes()
        self.assertEqual((s.get("585", 0), s["5211"], s["5711"]), (0, 1700000, 300000))
        self.equilibre()

    def test_ecart_de_change_v7(self):
        self.as_(6)
        DV.saisir_taux("USD", "CDF", "2800", "2026-10-05")
        cdf = V.create_account("BQ-CDF", "Banque CDF", "CDF", "5212", "bank")
        V.opening(cdf, 1000000000, "2026-10-05", "init")
        self.as_(1)
        b2 = V.records("budget")[0]
        with self.engine.begin() as c:
            c.execute(db.projects.insert().values(id="q", name="Projet CDF", currency="CDF", status="En cours", client="",
                                                  budget=0, progress=0))
        b = V.create_budget("q", "CT-CDF", [dict(code="MAT", label="Matériaux", budget=10000000000)], 1, 1)
        self.as_(5)
        V.approve_budget(b, "ok")
        self.as_(1)
        i = V.create_operation("OPC", "q", "MAT", "f", "Sable", "Dépense", 28000000, "2026-10-30", "605")
        V.submit(i)
        for uid in (2, 3, 4, 5):
            self.as_(uid)
            V.approve(i, "ok")
        self.as_(3)
        V.invoice(i, "FC1", "2026-10-05", 28000000)        # 280 000 FC = 100 $ au taux 2 800
        self.as_(6)
        DV.saisir_taux("USD", "CDF", "2850", D_)
        V.pay(i, cdf, 28000000, D_, "PC1")                  # 98,25 $ au taux 2 850 : gain de 1,75 $
        s = self.soldes()
        self.assertEqual((s.get("401", 0), s["776"]), (0, -175))
        self.equilibre()


class TresorerieHistorique(Base):
    def setUp(self):
        super().setUp()
        with self.engine.begin() as c:     # chantier hors circuit V7 (pas de budget DQE)
            c.execute(db.projects.insert().values(id="h", name="Historique", currency="USD", status="En cours",
                                                  client="", budget=0, progress=0))

    def mouvement(self, **k):
        vals = {"id": db.nouvel_id(), "kind": "manual", "date": D_, "account": "cash", "label": "Achat divers",
                "direction": "out", "amount": 10000, "currency": "USD", "project": "", "invoice_id": "",
                "invoice_amount": None, "expense_id": "", "supplier_payment_id": "", "supplier_reversal_id": "",
                "cree_le": db.maintenant(), **k}
        with db.transaction("mouvement") as t:
            t.inserer("movements", vals)
        return vals["id"]

    def test_depense_par_categorie(self):
        with db.transaction("dépense") as t:
            t.inserer("expenses", {"id": "e1", "label": "Gravier", "project": "h", "category": "Matériaux", "date": D_,
                                   "amount": 25000, "currency": "USD", "supplier_id": "", "responsible": ""})
            t.inserer("movements", {"id": "m1", "kind": "expense", "date": D_, "account": "cash", "label": "Gravier",
                                    "direction": "out", "amount": 25000, "currency": "USD", "project": "h",
                                    "invoice_id": "", "invoice_amount": None, "expense_id": "e1",
                                    "supplier_payment_id": "", "supplier_reversal_id": ""})
        s = self.soldes()
        self.assertEqual((s["605"], s["57"]), (25000, -25000))
        with self.assertRaisesRegex(ValueError, "sans compte comptable"), db.transaction("dépense") as t:
            t.inserer("expenses", {"id": "e2", "label": "Divers", "project": "h", "category": "Autre", "date": D_,
                                   "amount": 1000, "currency": "USD", "supplier_id": "", "responsible": ""})
            t.inserer("movements", {"id": "m2", "kind": "expense", "date": D_, "account": "cash", "label": "Divers",
                                    "direction": "out", "amount": 1000, "currency": "USD", "project": "h",
                                    "invoice_id": "", "invoice_amount": None, "expense_id": "e2",
                                    "supplier_payment_id": "", "supplier_reversal_id": ""})
        self.assertIsNone(db.un("expenses", "e2"))        # opération refusée en entier
        # Modification de la dépense : contre-passation puis nouvelle pièce
        with db.transaction("modif") as t:
            t.maj("movements", "m1", {"amount": 30000})
        s = self.soldes()
        self.assertEqual((s["605"], s["57"]), (30000, -30000))
        with db.transaction("suppression") as t:
            t.supprimer_ou("movements", db.movements.c.expense_id == "e1")
        s = self.soldes()
        self.assertEqual((s["605"], s["57"]), (0, 0))
        self.equilibre()

    def test_mouvement_manuel_en_attente_puis_impute(self):
        mid = self.mouvement()
        self.assertEqual(self.soldes()["471"], 10000)
        with db.transaction("imputation") as t:
            t.maj("movements", mid, {"journal": {"piece": "PC-1", "imputation": "transport", "compte": "62",
                                                 "centre": "SIEGE"}})
        s = self.soldes()
        self.assertEqual((s["471"], s["62"], s["57"]), (0, 10000, -10000))
        self.equilibre()

    def test_comptes_tiers_et_client(self):
        with db.transaction("facture fournisseur") as t:
            t.inserer("supplier_invoices", {"id": "si1", "party_id": "f", "project": "h", "reference": "F-77", "date": D_,
                                            "due": "2026-11-15", "currency": "USD", "amount": 50000})
            t.inserer("supplier_payments", {"id": "sp1", "party_id": "f", "project": "h", "currency": "USD",
                                            "amount": 50000, "date": D_, "account": "bank"})
            t.inserer("supplier_allocations", {"id": "sa1", "payment_id": "sp1", "invoice_id": "si1", "amount": 50000,
                                               "date": D_})
            t.inserer("movements", {"id": "m3", "kind": "manual", "date": D_, "account": "bank", "label": "Règlement",
                                    "direction": "out", "amount": 50000, "currency": "USD", "project": "h",
                                    "invoice_id": "", "invoice_amount": None, "expense_id": "",
                                    "supplier_payment_id": "sp1", "supplier_reversal_id": ""})
        with db.transaction("avance") as t:
            t.inserer("supplier_payments", {"id": "sp2", "party_id": "f", "project": "h", "currency": "USD",
                                            "amount": 7000, "date": D_, "account": "bank"})
            t.inserer("movements", {"id": "m4", "kind": "manual", "date": D_, "account": "bank", "label": "Avance",
                                    "direction": "out", "amount": 7000, "currency": "USD", "project": "h",
                                    "invoice_id": "", "invoice_amount": None, "expense_id": "",
                                    "supplier_payment_id": "sp2", "supplier_reversal_id": ""})
            t.inserer("invoices", {"id": "fc1", "number": "FA-1", "client": "c", "project": "h", "date": D_, "due": D_,
                                   "notes": "", "status": "Envoyée", "lines": [], "currency": "USD", "paid": 0})
            t.inserer("movements", {"id": "m5", "kind": "invoice", "date": D_, "account": "bank", "label": "Règlement FA-1",
                                    "direction": "in", "amount": 90000, "currency": "USD", "project": "h",
                                    "invoice_id": "fc1", "invoice_amount": 90000, "expense_id": "",
                                    "supplier_payment_id": "", "supplier_reversal_id": ""})
        s = self.soldes()
        self.assertEqual((s["605"], s.get("401", 0), s["4091"], s["411"], s["521"]), (50000, 0, 7000, -90000, 33000))
        tiers = {l["tiers"] for l in db.tout("cpt_lignes") if l["compte"] in ("401", "4091", "411")}
        self.assertEqual(tiers, {"f", "c"})
        self.equilibre()


class AvantDemarrage(Base):
    debut = "2026-12-01"

    def test_aucune_ecriture_avant_la_date_de_demarrage(self):
        i = self.op()
        self.as_(3)
        V.order(i, "BC1", D_)
        self.as_(2)
        V.receive(i, "BL1", D_, 100000)
        self.as_(3)
        V.invoice(i, "FAC1", D_, 100000)
        with db.transaction("mouvement") as t:
            t.inserer("movements", {"id": "mx", "kind": "manual", "date": D_, "account": "cash", "label": "x",
                                    "direction": "out", "amount": 1, "currency": "USD", "project": "",
                                    "invoice_id": "", "invoice_amount": None, "expense_id": "",
                                    "supplier_payment_id": "", "supplier_reversal_id": ""})
        self.assertEqual(db.tout("cpt_pieces"), [])
        self.assertEqual(CPT.controle_tresorerie(), [])


if __name__ == "__main__":
    unittest.main()
