"""Circuit d'achat V8 (mémo § 5) et stock permanent (§ 4) : recette sur base SQLite isolée.

Scénario 1 du mémo (§ 12.2) : besoin de 100 sacs, 40 en stock → bon de sortie de 40 et demande d'achat de 60 →
validations → commande → réception de 55 acceptés et 5 rejetés → facture de 55 → paiement en deux fois →
sortie vers le chantier ; plus les contrôles bloquants, la séparation des fonctions, les devises et la reprise.
"""
import unittest
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import achats as A
import auth
import comptabilisation as CPT
import db
import derogations as DR
import devises as DV
import gestion_v7 as V
import regles as R
import stocks as S

D_ = "2026-10-16"
# id, famille de rôle, poste
USERS = [(1, "chantier", "conducteur_travaux"), (2, "chantier", "chef_chantier"), (3, "finance", "comptable"),
         (4, "finance", "daf"), (5, "admin", "dg"), (6, "finance", "acheteur"), (7, "chantier", "magasinier_central"),
         (8, "finance", None), (9, "finance", "comptable"), (10, "admin", None)]


class Base(unittest.TestCase):
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
            for id_, role, _ in USERS:
                c.execute(db.users.insert().values(id=id_, identifiant=f"u{id_}", nom=f"User {id_}", role=role,
                                                   mdp_hash="x", actif=True, doit_changer_mdp=False, version_session=0))
            c.execute(db.projects.insert().values(id="p", name="Résidence", currency="USD", status="En cours",
                                                  client="", budget=0, progress=0))
            c.execute(db.clients.insert().values(id="f", code="F001", name="Cimenterie", roles=["supplier"]))
            c.execute(db.clients.insert().values(id="g", code="F002", name="Aciers", roles=["supplier"]))
        self.as_(10)
        with db.transaction("postes") as t:
            for id_, role, poste in USERS:
                auth.enregistrer_affectation(t, id_, f"u{id_}", role, poste, None)
        self.as_(1)
        self.b = V.create_budget("p", "CT-P", [dict(code="GO", label="Gros œuvre", budget=1000000),
                                              dict(code="MO", label="Main-d’œuvre", budget=500000)], 2000000, 1500000)
        self.as_(5)
        V.approve_budget(self.b, "ok")
        S.fixer_tenue("USD", "PV DG 2026-10-16", "Décision de la DG avec l’expert-comptable")
        A.configurer(5, 5, {}, 1, "Note DG 01", "Tolérances d’achat")
        self.as_(3)
        S.enregistrer_famille("CIMENT", "Ciments", "602", "321", "6032")
        S.enregistrer_famille("SERV", "Services", "605")
        self.as_(6)
        self.cim = S.enregistrer_article("CIM42", "Ciment 42,5 sac 50 kg", "CIMENT", "stocke", "sac")
        self.loc = S.enregistrer_article("LOC-GRUE", "Location grue (jour)", "SERV", "prestation", "jour")
        self.mc = S.enregistrer_magasin("MC", "Dépôt central", "central")
        self.mch = S.enregistrer_magasin("MCH-P", "Magasin Résidence", "chantier", "p")
        self.as_(6)
        self.compte = V.create_account("BANQUE", "Banque", "USD", "5211", "bank")
        V.opening(self.compte, 5000000, "2026-10-01", "init")

    def tearDown(self):
        DV.vider_cache()
        for p in (self.p3, self.p2, self.p1):
            p.stop()
        self.engine.dispose()

    def as_(self, i):
        u = db.un("users", i)
        self.user = {**u, "droits": auth.droits_de(u["id"], u["role"])}

    def stock_initial(self, qte=40, cout=40000, magasin=None):
        self.as_(7)
        with db.transaction("stock initial") as t:
            S.entree(t, self.user, self.cim, magasin or self.mch, Decimal(qte), cout, "USD", D_, "test", "init")

    def approuver_tout(self, demande):
        for uid in (2, 3, 4, 5):
            self.as_(uid)
            A.approuver(demande, "contrôlé")

    def demande(self, qte=60, prix=1200, article=None, poste="GO", magasin=None, alertes=False):
        self.as_(1)
        d = A.creer_demande("p", D_, magasin or self.mch, [dict(article=article or self.cim, poste=poste, quantite=qte,
                                                                  prix_estime=prix, motif_hors_stock="test")])
        A.soumettre(d, accepter_alertes=alertes)
        return d

    def ligne(self, demande):
        return A.lignes_demande(None, demande)[0]


class Scenario1(Base):
    def test_achat_stocke_de_bout_en_bout(self):
        self.stock_initial()
        self.as_(1)
        r = A.besoin_chantier("p", self.mch, D_, [dict(article=self.cim, poste="GO", quantite=100, prix_estime=1200)])
        bon, da = r["bon_sortie"], r["demande"]
        self.assertEqual(S.D(A.lignes_demande(None, da)[0]["quantite"]), 60)
        self.assertEqual(S.disponible(None, self.cim, self.mch), 0)          # 40 réservés pour le bon
        A.soumettre(da)
        self.assertEqual(db.un("ach_demandes", da)["statut"], "Soumise")
        m = V.metrics(db.un("v7_records", self.b), V.records("operation"))
        self.assertEqual(m["lines"][0]["open"], 72000)                        # engagement prévisionnel 60 × 12 $
        self.approuver_tout(da)
        self.assertEqual(A.statut_demande(db.un("ach_demandes", da)), "Approuvée")
        l = self.ligne(da)
        self.as_(6)
        cmd = A.commander("f", "USD", D_, [dict(demande_ligne=l["id"], quantite=60, prix_unitaire=1150)])
        self.assertEqual(A.statut_demande(db.un("ach_demandes", da)), "Commandée")
        cl = A.lignes_commande(None, cmd)[0]
        self.as_(7)
        A.receptionner(cmd, D_, "BL-001", [dict(commande_ligne=cl["id"], qte_acceptee=55, qte_rejetee=5,
                                                 motif="sacs éventrés")])
        self.assertEqual(A.statut_ligne(db.un("ach_demandes", da), self.ligne(da)), "Partiellement reçue")
        art = db.un("stk_articles", self.cim)
        # CMUP : (40 × 10 $ + 55 × 11,50 $) / 95 = 1 032,50 / 95 = 10,8684 $
        self.assertEqual((S.D(art["qte_totale"]), art["valeur_totale"]), (95, 103250))
        self.assertAlmostEqual(float(art["cmup"]), 1086.842105, places=5)
        # Coût réalisé seulement à la sortie (article stocké)
        m = V.metrics(db.un("v7_records", self.b), V.records("operation"))
        self.assertEqual(m["lines"][0]["cost"], 0)
        S.servir_bon(bon)
        m = V.metrics(db.un("v7_records", self.b), V.records("operation"))
        self.assertEqual(m["lines"][0]["cost"], 43474)                        # 40 × 10,8684 $
        self.as_(3)
        fac = A.enregistrer_facture("f", "FAC-778", D_, "2026-11-15", "USD", 63250, 0,
                                    [dict(commande_ligne=cl["id"], quantite=55, prix_unitaire=1150)])
        with self.assertRaisesRegex(ValueError, "saisit"):
            A.valider_facture(fac, "auto")
        self.as_(9)
        A.valider_facture(fac, "Rapprochement BC / BR / facture conforme")
        self.assertEqual(A.statut_ligne(db.un("ach_demandes", da), self.ligne(da)), "Facturée")
        self.as_(8)
        A.payer(fac, self.compte, 30000, D_, "VIR-1")
        A.payer(fac, self.compte, 33250, D_, "VIR-2")
        with self.assertRaises(ValueError):
            A.payer(fac, self.compte, 1, D_, "VIR-3")
        self.as_(6)
        A.cloturer_ligne(self.ligne(da)["id"], "5 sacs rejetés non remplacés")
        self.assertEqual(A.statut_demande(db.un("ach_demandes", da)), "Soldée")
        # Sortie des 55 sacs reçus : tout le coût est réalisé, l'engagement ferme est soldé
        self.as_(1)
        b2 = S.creer_bon_sortie("p", self.mch, D_, [dict(article=self.cim, poste="GO", quantite=55)])
        self.as_(7)
        S.servir_bon(b2)
        art = db.un("stk_articles", self.cim)
        self.assertEqual((S.D(art["qte_totale"]), art["valeur_totale"]), (0, 0))
        m = V.metrics(db.un("v7_records", self.b), V.records("operation"))
        go = m["lines"][0]
        self.assertEqual((go["cost"], go["open"], go["cash"]), (103250, 0, 63250))
        self.assertEqual(sum(x["debit"] - x["credit"] for x in V.ledger()), 0)
        # Comptabilité : balance équilibrée, stock = comptes 32, fournisseur soldé, pièces par journal
        bal = CPT.balance(2026)
        self.assertEqual(sum(x["debit"] for x in bal), sum(x["credit"] for x in bal))
        self.assertEqual(CPT.controle_stock_comptes()["ecart"], 0)
        soldes = {x["compte"]: x["debit"] - x["credit"] for x in bal}
        self.assertEqual(soldes["401"], 0)
        self.assertEqual(soldes["602"], 63250)                          # achat au prix facturé
        self.assertEqual(soldes["6032"], 0)                              # entrées et sorties : variation nulle
        journaux = sorted({p["journal"] for p in db.tout("cpt_pieces")})
        self.assertEqual(journaux, ["ACH", "BQ1", "STK"])
        nums = sorted(p["numero"] for p in db.tout("cpt_pieces") if p["journal"] == "STK")
        self.assertEqual(nums, list(range(1, len(nums) + 1)))           # numérotation sans trou
        sortie = [l for l in db.tout("cpt_lignes") if l["compte"] == "6032" and l["debit"]]
        self.assertTrue(all(l["projet"] == "p" and l["poste"] == "GO" for l in sortie))
        ch = A.chaine(da)
        self.assertEqual((len(ch["commandes"]), len(ch["receptions"]), len(ch["factures"]), len(ch["mouvements"])),
                         (1, 1, 1, 1))


class Controles(Base):
    def test_stock_disponible_impose_un_motif(self):
        self.stock_initial(10, 10000, self.mc)
        self.as_(1)
        d = A.creer_demande("p", D_, self.mch, [dict(article=self.cim, poste="GO", quantite=5, prix_estime=1000)])
        with self.assertRaisesRegex(ValueError, "disponibles en stock"):
            A.soumettre(d)

    def test_stock_jamais_negatif(self):
        self.stock_initial(10)
        self.as_(1)
        with self.assertRaisesRegex(ValueError, "disponible insuffisant"):
            S.creer_bon_sortie("p", self.mch, D_, [dict(article=self.cim, poste="GO", quantite=11)])
        S.creer_bon_sortie("p", self.mch, D_, [dict(article=self.cim, poste="GO", quantite=6)])
        with self.assertRaisesRegex(ValueError, "disponible insuffisant"):     # 4 restent hors réservation
            S.creer_bon_sortie("p", self.mch, D_, [dict(article=self.cim, poste="GO", quantite=5)])

    def test_validateurs_distincts_et_niveaux(self):
        d = self.demande()
        self.as_(1)
        with self.assertRaises(ValueError):
            A.approuver(d, "auto")
        self.as_(3)                                         # N2 avant N1 : niveau non autorisé
        with self.assertRaisesRegex(ValueError, "N1"):
            A.approuver(d, "trop tôt")
        self.as_(2)
        A.approuver(d, "N1")
        with self.assertRaises(ValueError):                 # même personne au niveau suivant
            A.approuver(d, "encore")

    def test_depassement_budget_derogation_dg(self):
        self.as_(1)
        x = A.creer_demande("p", D_, self.mch, [dict(article=self.cim, poste="GO", quantite=1000, prix_estime=1200,
                                                     motif_hors_stock="test")])
        with self.assertRaisesRegex(ValueError, "120 %"):    # alerte de seuil à confirmer à la soumission
            A.soumettre(x)
        d = self.demande(qte=1000, prix=1200, alertes=True)  # 12 000 $ > 10 000 $
        for uid in (2, 3, 4):
            self.as_(uid)
            A.approuver(d, "ok")
        self.as_(5)
        with self.assertRaisesRegex(ValueError, "dérogation"):
            A.approuver(d, "sans dérogation")
        A.approuver(d, "dépassement autorisé", derogation=True)
        self.assertTrue(db.un("ach_demandes", d)["derogation_dg"])

    def test_modification_apres_validation_relance_le_circuit(self):
        d = self.demande()
        self.as_(2)
        A.approuver(d, "N1")
        self.as_(1)
        A.modifier_demande(d, D_, self.mch, [dict(article=self.cim, poste="GO", quantite=50, prix_estime=1200,
                                                  motif_hors_stock="test")])
        x = db.un("ach_demandes", d)
        self.assertEqual((x["statut"], x["niveau"], x["approbations"]), ("Brouillon", 0, []))

    def test_commande_quantite_prix_parametres(self):
        d = self.demande()
        self.approuver_tout(d)
        l = self.ligne(d)
        self.as_(6)
        with self.assertRaisesRegex(ValueError, "approuvée restante"):
            A.commander("f", "USD", D_, [dict(demande_ligne=l["id"], quantite=61, prix_unitaire=1200)])
        with self.assertRaisesRegex(ValueError, "tolérance"):
            A.commander("f", "USD", D_, [dict(demande_ligne=l["id"], quantite=10, prix_unitaire=1300)])
        with patch.object(A, "parametres", lambda tx=None: {}):
            with self.assertRaisesRegex(ValueError, "Paramètre DG manquant"):
                A.commander("f", "USD", D_, [dict(demande_ligne=l["id"], quantite=10, prix_unitaire=1200)])
        A.commander("f", "USD", D_, [dict(demande_ligne=l["id"], quantite=30, prix_unitaire=1200)])
        A.commander("g", "USD", D_, [dict(demande_ligne=l["id"], quantite=30, prix_unitaire=1190)])
        self.assertEqual(A.statut_demande(db.un("ach_demandes", d)), "Commandée")

    def test_mise_en_concurrence(self):
        self.as_(5)
        A.configurer(5, 5, {"USD": 50000}, 3, "Note DG 02", "Trois devis au-delà de 500 $")
        d = self.demande()
        self.approuver_tout(d)
        l = self.ligne(d)
        self.as_(6)
        with self.assertRaisesRegex(ValueError, "3 devis"):
            A.commander("f", "USD", D_, [dict(demande_ligne=l["id"], quantite=60, prix_unitaire=1200)])
        devis = [dict(fournisseur=x, reference=f"DV-{x}", montant=1) for x in ("Cimenterie", "Aciers", "Autre")]
        A.commander("f", "USD", D_, [dict(demande_ligne=l["id"], quantite=60, prix_unitaire=1200)], devis)

    def test_commande_regroupe_plusieurs_demandes(self):
        d1, d2 = self.demande(qte=10), self.demande(qte=20)
        self.approuver_tout(d1)
        self.approuver_tout(d2)
        self.as_(6)
        cmd = A.commander("f", "USD", D_, [dict(demande_ligne=self.ligne(d1)["id"], quantite=10, prix_unitaire=1200),
                                            dict(demande_ligne=self.ligne(d2)["id"], quantite=20, prix_unitaire=1200)])
        self.assertEqual(len(A.lignes_commande(None, cmd)), 2)

    def test_reception_et_facture_controles(self):
        d = self.demande()
        self.approuver_tout(d)
        self.as_(6)
        cmd = A.commander("f", "USD", D_, [dict(demande_ligne=self.ligne(d)["id"], quantite=60, prix_unitaire=1200)])
        cl = A.lignes_commande(None, cmd)[0]
        self.as_(7)
        with self.assertRaisesRegex(ValueError, "supérieure à la commande"):
            A.receptionner(cmd, D_, "BL", [dict(commande_ligne=cl["id"], qte_acceptee=64)])   # > 60 × 1,05
        A.receptionner(cmd, D_, "BL", [dict(commande_ligne=cl["id"], qte_acceptee=20)])
        self.as_(3)
        with self.assertRaisesRegex(ValueError, "supérieure à la quantité reçue"):
            A.enregistrer_facture("f", "F1", D_, D_, "USD", 30000, 0, [dict(commande_ligne=cl["id"], quantite=25,
                                                                             prix_unitaire=1200)])
        with self.assertRaisesRegex(ValueError, "tolérance"):
            A.enregistrer_facture("f", "F1", D_, D_, "USD", 28000, 0, [dict(commande_ligne=cl["id"], quantite=20,
                                                                             prix_unitaire=1400)])
        A.enregistrer_facture("f", "F1", D_, D_, "USD", 12000, 0, [dict(commande_ligne=cl["id"], quantite=10,
                                                                         prix_unitaire=1200)])
        with self.assertRaisesRegex(ValueError, "déjà enregistrée"):
            A.enregistrer_facture("f", "F1", D_, D_, "USD", 6000, 0, [dict(commande_ligne=cl["id"], quantite=5,
                                                                            prix_unitaire=1200)])
        with self.assertRaisesRegex(ValueError, "différent du montant HT"):
            A.enregistrer_facture("f", "F2", D_, D_, "USD", 6001, 0, [dict(commande_ligne=cl["id"], quantite=5,
                                                                            prix_unitaire=1200)])

    def test_separation_reception_facture_paiement(self):
        d = self.demande()
        self.approuver_tout(d)
        self.as_(6)
        cmd = A.commander("f", "USD", D_, [dict(demande_ligne=self.ligne(d)["id"], quantite=60, prix_unitaire=1200)])
        cl = A.lignes_commande(None, cmd)[0]
        # Le demandeur (conducteur) obtient le droit magasin, mais ne réceptionne pas sa propre demande
        with db.transaction("x") as t:
            t.parametre("droits_utilisateur:1", {"magasin": "w"})
        self.as_(1)
        with self.assertRaisesRegex(ValueError, "réceptionnaire"):
            A.receptionner(cmd, D_, "BL", [dict(commande_ligne=cl["id"], qte_acceptee=60)])
        self.as_(5)
        DR.accorder(1, "receptionnaire_demandeur", D_, D_, "Petite équipe sur le chantier isolé")
        self.as_(1)
        A.receptionner(cmd, D_, "BL", [dict(commande_ligne=cl["id"], qte_acceptee=60)])
        self.as_(3)
        f = A.enregistrer_facture("f", "F9", D_, D_, "USD", 72000, 0, [dict(commande_ligne=cl["id"], quantite=60,
                                                                         prix_unitaire=1200)])
        with db.transaction("x") as t:                     # l'acheteur reçoit le droit facture, sans la valider
            t.parametre("droits_utilisateur:6", {"factures_achat": "w"})
        self.as_(6)
        with self.assertRaisesRegex(ValueError, "acheteur"):
            A.valider_facture(f, "ok")
        self.as_(9)
        A.valider_facture(f, "ok")
        self.as_(4)                                         # le DAF a validé la demande (N3) : il ne paie pas
        with db.transaction("x") as t:
            t.parametre("droits_utilisateur:4", {"tresorerie": "w"})
        self.as_(4)
        with self.assertRaisesRegex(ValueError, "trésorier"):
            A.payer(f, self.compte, 1000, D_, "P1")
        self.assertEqual(len(DR.etat()), 1)


class Devises(Base):
    def test_commande_en_cdf_convertie_au_taux_historique(self):
        d = self.demande()
        self.approuver_tout(d)
        l = self.ligne(d)
        self.as_(6)
        with self.assertRaisesRegex(ValueError, "Aucun taux CDF"):
            A.commander("f", "CDF", D_, [dict(demande_ligne=l["id"], quantite=60, prix_unitaire=3400000)])
        self.as_(8)
        DV.saisir_taux("USD", "CDF", "2850", D_, "BCC")
        self.as_(6)
        cmd = A.commander("f", "CDF", D_, [dict(demande_ligne=l["id"], quantite=60, prix_unitaire=3400000)])
        cl = A.lignes_commande(None, cmd)[0]
        self.assertEqual(cl["montant_budget"], 71579)       # 60 × 34 000 FC / 2 850 = 715,79 $
        self.as_(7)
        A.receptionner(cmd, D_, "BL", [dict(commande_ligne=cl["id"], qte_acceptee=60)])
        mv = db.tout("stk_mouvements")[0]
        self.assertEqual((mv["cout_devise"], mv["cout_origine"], mv["valeur"]), ("CDF", 204000000, 71579))

    def test_monnaie_de_tenue_obligatoire_et_figee(self):
        self.stock_initial()
        self.as_(5)
        with self.assertRaisesRegex(ValueError, "ne peut plus changer"):
            S.fixer_tenue("CDF", "PV 2", "changement")
        with db.transaction("x") as t:
            t.parametre("comptabilite_tenue", None)
        self.as_(7)
        with self.assertRaisesRegex(ValueError, "Monnaie de tenue non fixée"), db.transaction("y") as t:
            S.entree(t, self.user, self.cim, self.mch, Decimal(1), 100, "USD", D_, "test", "x")


class Comptabilite(Base):
    def test_ecart_de_change_au_paiement(self):
        self.as_(8)
        DV.saisir_taux("USD", "CDF", "2800", "2026-10-10", "BCC")
        d = self.demande()
        self.approuver_tout(d)
        self.as_(6)
        cmd = A.commander("f", "CDF", "2026-10-10", [dict(demande_ligne=self.ligne(d)["id"], quantite=10,
                                                          prix_unitaire=2800000)])
        cl = A.lignes_commande(None, cmd)[0]
        self.as_(7)
        A.receptionner(cmd, "2026-10-10", "BL", [dict(commande_ligne=cl["id"], qte_acceptee=10)])
        self.as_(3)
        f = A.enregistrer_facture("f", "FC-1", "2026-10-10", "2026-11-10", "CDF", 28000000, 0,
                                  [dict(commande_ligne=cl["id"], quantite=10, prix_unitaire=2800000)])
        self.as_(9)
        A.valider_facture(f, "ok")                          # 280 000 FC = 100 $ au taux 2 800
        self.as_(6)
        caisse = V.create_account("CAISSE-CDF", "Caisse CDF", "CDF", "5711", "cash")
        V.opening(caisse, 100000000, "2026-10-01", "init")
        self.as_(8)
        DV.saisir_taux("USD", "CDF", "2850", D_, "BCC")    # le franc s'est déprécié : gain de change
        A.payer(f, caisse, 28000000, D_, "CA-1")            # sous-compte 5711 créé sous 57
        self.assertIn("CA1", {p["journal"] for p in db.tout("cpt_pieces")})
        bal = {x["compte"]: x["debit"] - x["credit"] for x in CPT.balance(2026)}
        self.assertEqual(bal["401"], 0)
        self.assertEqual(bal["776"], -175)                  # 100,00 $ dus, 98,25 $ décaissés
        self.assertNotIn("676", bal)

    def test_periode_cloturee_refuse_toute_ecriture(self):
        self.stock_initial()
        self.as_(3)
        CPT.changer_periode("2026-10", "Clôturée provisoirement", "Clôture d’octobre")
        self.as_(1)
        b = S.creer_bon_sortie("p", self.mch, D_, [dict(article=self.cim, poste="GO", quantite=5)])
        self.as_(7)
        with self.assertRaisesRegex(ValueError, "clôturée"):
            S.servir_bon(b)
        self.assertEqual(S.D(db.un("stk_articles", self.cim)["qte_totale"]), 40)   # rien n'a bougé
        self.as_(5)
        CPT.changer_periode("2026-10", "Ouverte", "Réouverture motivée")
        self.as_(7)
        S.servir_bon(b)

    def test_contre_passation_de_mouvement(self):
        self.stock_initial()
        mvt = db.tout("stk_mouvements")[0]["id"]
        S.contre_passer(mvt, "saisie en double")
        self.assertEqual(S.D(db.un("stk_articles", self.cim)["qte_totale"]), 0)
        pieces = db.tout("cpt_pieces")
        self.assertEqual(len(pieces), 2)
        self.assertEqual(sum(x["debit"] - x["credit"] for x in CPT.balance(2026)), 0)
        self.assertTrue(all(v == 0 for v in [x["debit"] - x["credit"] for x in CPT.balance(2026)]))

    def test_regle_proposee_par_finance_activee_par_dg(self):
        self.as_(3)
        rid = CPT.proposer_regle("stock_entree", "STK", [dict(sens="D", compte="{compte_stock}", montant="valeur",
                                                              par="ligne"),
                                                         dict(sens="C", compte="{compte_variation}", montant="valeur",
                                                              par="ligne")], D_, "Reformulation")
        self.as_(5)
        CPT.activer_regle(rid)
        self.stock_initial()
        self.assertEqual(db.tout("cpt_pieces")[0]["regle_version"], 2)


class Services(Base):
    def test_prestation_cout_realise_a_la_reception(self):
        d = self.demande(qte=3, prix=50000, article=self.loc, poste="GO")
        self.approuver_tout(d)
        self.as_(6)
        cmd = A.commander("g", "USD", D_, [dict(demande_ligne=self.ligne(d)["id"], quantite=3, prix_unitaire=48000)])
        cl = A.lignes_commande(None, cmd)[0]
        m = V.metrics(db.un("v7_records", self.b), V.records("operation"))["lines"][0]
        self.assertEqual((m["open"], m["cost"]), (144000, 0))
        self.as_(7)
        A.receptionner(cmd, D_, "Attestation de service fait n° 12", [dict(commande_ligne=cl["id"], qte_acceptee=2)])
        m = V.metrics(db.un("v7_records", self.b), V.records("operation"))["lines"][0]
        self.assertEqual((m["open"], m["cost"]), (48000, 96000))
        self.assertEqual(db.tout("stk_mouvements"), [])


class Reprise(Base):
    def test_reprise_des_demandes_transitoires(self):
        with db.transaction("ancienne demande") as t:
            V.insert(t, "purchase_request", "DA-2026-0001", "p", "USD", dict(
                objet="Coffrage", lieu="", date_besoin="2026-10-10", statut="Soumise", creator=1, validations={},
                operations=[], history=[], lignes=[dict(n=1, post="GO", article="Ciment 42,5 sac 50 kg", unite="sac",
                                                        quantite=10, prix=1200, fournisseur="f"),
                                                   dict(n=2, post="GO", article="Planches de coffrage", unite="u",
                                                        quantite=30, prix=None, fournisseur="")]))
        self.assertEqual(len(A.reprendre_transitoires()), 1)
        self.as_(5)
        A.reprendre_transitoires(execute=True)
        d = [x for x in db.tout("ach_demandes") if x["origine"].startswith("reprise")][0]
        lignes = A.lignes_demande(None, d["id"])
        self.assertEqual(lignes[0]["article"], self.cim)                         # rapproché par libellé
        self.assertTrue(db.un("stk_articles", lignes[1]["article"])["a_qualifier"])
        self.as_(1)
        with self.assertRaisesRegex(ValueError, "à qualifier"):
            A.soumettre(d["id"])
        self.assertEqual(V.records("purchase_request")[0]["data"]["statut"], "Reprise V8")


class Import(Base):
    def importer(self, fonction, contenu, uid):
        from imports import service as SV
        self.as_(uid)
        ds = SV.parse_file(contenu, fonction)
        pv = SV.preview_import(ds, SV.contexte("en_cours"), contenu, "test.xlsx")
        if pv["preview_id"] is None or pv["rapport"]["errors"]:
            return pv
        return {**pv, **SV.commit_import(pv["preview_id"], {"accepter_alertes": True})}

    def test_referentiel_puis_demande(self):
        from tests.test_imports import classeur
        r = self.importer("referentiel_stock", classeur("referentiel_stock", "en_cours", "REF-1", {
            "Articles": [{"reference_externe": "FER12", "libelle": "Fer HA 12", "famille": "CIMENT", "nature": "stocke",
                          "unite_stock": "barre", "seuil_min": 20}],
            "Magasins": [{"reference_externe": "MT", "libelle": "Transit port", "type": "transit"}]}), 6)
        self.assertFalse(r["rapport"]["errors"], r["rapport"]["errors"])
        r = self.importer("demandes_achat", classeur("demandes_achat", "en_cours", "DA-XL", {
            "Demandes_Achat": [{"reference_externe": "EXT-1", "chantier_ref": "p", "date_souhaitee": D_,
                                "magasin_ref": "MCH-P", "devise": "USD"}],
            "Lignes_Demande_Achat": [{"demande_ref": "EXT-1", "numero_ligne": 1, "article_ref": "FER12",
                                      "code_dqe": "GO", "quantite": 120, "prix_estime": "9,50",
                                      "fournisseur_ref": "F002"}]}), 1)
        self.assertFalse(r["rapport"]["errors"], r["rapport"]["errors"])
        d = db.tout("ach_demandes")[0]
        self.assertEqual((d["statut"], d["demandeur"]), ("Brouillon", 1))
        self.assertEqual(A.lignes_demande(None, d["id"])[0]["prix_estime"], 950)
        r = self.importer("demandes_achat", classeur("demandes_achat", "en_cours", "DA-XL2", {
            "Demandes_Achat": [{"reference_externe": "EXT-2", "chantier_ref": "p", "date_souhaitee": D_, "devise": "EUR"}],
            "Lignes_Demande_Achat": [{"demande_ref": "EXT-2", "numero_ligne": 1, "article_ref": "INCONNU",
                                      "code_dqe": "GO", "quantite": 1}]}), 1)
        champs = {e["field"] for e in r["rapport"]["errors"]}
        self.assertIn("devise", champs)


class Profils(unittest.TestCase):
    def test_postes_sans_incompatibilite(self):
        for code, p in auth.PROFILS_STANDARDS.items():
            if p["role"] != "admin":
                self.assertEqual(auth.incompatibilites(p["droits"]), [], code)
                self.assertTrue(set(p["droits"]) <= set(auth.MODULES), code)
        for role, d in auth.DROITS.items():
            if role != "admin":
                self.assertEqual(auth.incompatibilites(d), [], role)


if __name__ == "__main__":
    unittest.main()
