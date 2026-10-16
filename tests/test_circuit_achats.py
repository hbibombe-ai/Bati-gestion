"""Circuit des demandes d'achat : chantier → achats → coordonnateur → opérations V7, postes, profils et périmètres."""
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import achats_circuit as A
import auth
import db
import gestion_v7 as V

# id, rôle (famille), poste
USERS = [(1, "chantier", "conducteur_travaux"), (2, "chantier", "chef_chantier"), (3, "finance", "acheteur"),
         (4, "chantier", "coordonnateur_projet"), (5, "admin", "dg"), (6, "finance", "comptable"),
         (7, "finance", "daf"), (8, "admin", None), (9, "chantier", "chef_chantier")]


class CircuitAchats(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        db.meta.create_all(self.engine)
        self.p1 = patch.object(db, "moteur", lambda: self.engine)
        self.p1.start()
        self.user = None
        self.p2 = patch.object(auth, "utilisateur", lambda: self.user)
        self.p2.start()
        with self.engine.begin() as c:
            for id_, role, _ in USERS:
                c.execute(db.users.insert().values(id=id_, identifiant=f"u{id_}", nom=f"User {id_}", role=role,
                                                   mdp_hash="x", actif=True, doit_changer_mdp=False, version_session=0))
            for pid in ("p", "q"):
                c.execute(db.projects.insert().values(id=pid, name=f"Chantier {pid}", currency="USD", status="En cours",
                                                      client="", budget=10000000, progress=0))
            c.execute(db.clients.insert().values(id="f1", code="F001", name="Cimenterie", roles=["supplier"]))
            c.execute(db.clients.insert().values(id="f2", code="F002", name="Aciers", roles=["supplier"]))
            c.execute(db.clients.insert().values(id="c1", code="C001", name="Client", roles=["client"]))
        self.as_(5)
        with db.transaction("postes de test") as t:
            for id_, role, poste in USERS:
                auth.enregistrer_affectation(t, id_, f"u{id_}", role, poste, None)
        self.budgets = {}
        for pid in ("p", "q"):
            self.as_(1)
            self.budgets[pid] = V.create_budget(pid, f"CT-{pid}", [dict(code="GO", label="Gros œuvre", budget=5000000),
                                                                  dict(code="MAC", label="Maçonnerie", budget=3000000)],
                                                9000000, 8000000)
            self.as_(5)
            V.approve_budget(self.budgets[pid], "validé")

    def tearDown(self):
        self.p2.stop()
        self.p1.stop()
        self.engine.dispose()

    def as_(self, i):
        u = db.un("users", i)
        self.user = {**u, "droits": auth.droits_de(u["id"], u["role"])}

    def data(self, i):
        return db.un("v7_records", i)["data"]

    def nouvelle_da(self, projet="p", lignes=None):
        self.as_(1)
        lignes = lignes or [dict(post="GO", article="Ciment 42,5 (sac)", unite="sac", quantite=100),
                            dict(post="GO", article="Fer HA12", unite="barre", quantite="50"),
                            dict(post="MAC", article="Agglos 15", unite="u", quantite=1000, prix=80, fournisseur="f1")]
        i = A.creer(projet, "Approvisionnement dalle", "Chantier", "2026-11-15", lignes)
        A.soumettre(i)
        return i

    # ------------------------------------------------------------------ cycle complet
    def test_cycle_complet_jusqu_a_la_facture(self):
        i = self.nouvelle_da()
        self.assertTrue(db.un("v7_records", i)["ref"].startswith("DA-"))
        self.as_(1)
        with self.assertRaises(ValueError):          # le demandeur ne valide pas sa propre demande
            A.valider_chantier(i, "ok")
        self.as_(2)
        A.valider_chantier(i, "Quantités conformes au métré")
        self.assertEqual(self.data(i)["statut"], "Validée chantier")
        self.as_(3)
        with self.assertRaises(ValueError):          # la ligne 2 n'a ni prix ni fournisseur
            A.chiffrer(i, {1: {"fournisseur": "f1", "prix": 1150}})
        res = A.chiffrer(i, {1: {"fournisseur": "f1", "prix": 1150, "qte_stock": 20},
                             2: {"fournisseur": "f2", "prix": 920}}, "Prix négociés")
        # 80 × 11,50 + 50 × 9,20 + 1000 × 0,80 = 920 + 460 + 800 = 2 180 $
        self.assertEqual(res["montant"], 218000)
        self.assertEqual(res["statut"], "À valider coordonnateur")   # seuil par défaut : toujours
        lignes = self.data(i)["lignes"]
        self.assertEqual(lignes[2]["source_prix"], "chantier confirmé achats")
        self.as_(4)
        A.valider_coordonnateur(i, "Priorité dalle confirmée")
        d = self.data(i)
        self.assertEqual(d["statut"], "Transmise au circuit V7")
        ops = {o["id"]: o for o in V.records("operation") if o["id"] in d["operations"]}
        # (f1, GO), (f1, MAC), (f2, GO) : trois opérations, toutes soumises, créées au nom du demandeur
        self.assertEqual(len(ops), 3)
        self.assertEqual(sorted(o["data"]["amount"] for o in ops.values()), [46000, 80000, 92000])
        self.assertTrue(all(o["data"]["status"] == "Soumise" and o["data"]["creator"] == 1 for o in ops.values()))
        self.assertTrue(all(o["data"]["demande_ref"] == db.un("v7_records", i)["ref"] for o in ops.values()))
        # Circuit V7 inchangé : N1 (chef), N2 (comptable), N3 (DAF), DG
        for oid in ops:
            for uid in (2, 6, 7, 5):
                self.as_(uid)
                V.approve(oid, "contrôlé")
        f1 = [oid for oid, o in ops.items() if o["data"]["party"] == "f1"]
        self.as_(3)
        A.commande_groupee(f1, "BC-2026-001", "2026-10-20")
        self.assertTrue(all(self.data(o)["order"]["ref"] == "BC-2026-001" and self.data(o)["status"] == "Commandée"
                            for o in f1))
        self.as_(2)
        V.receive(f1[0], "BL-1", "2026-10-22", self.data(f1[0])["amount"])
        self.as_(6)
        V.invoice(f1[0], "FAC-1", "2026-10-23", self.data(f1[0])["amount"])
        self.assertEqual(self.data(f1[0])["status"], "Facturée")
        self.assertIn("facturée", A.execution(db.un("v7_records", i)))

    def test_seuil_et_transmission_directe(self):
        self.as_(5)
        A.configurer_politique({"USD": 300000})          # 3 000 $
        i = self.nouvelle_da()
        self.as_(2)
        A.valider_chantier(i, "ok")
        self.as_(3)
        res = A.chiffrer(i, {1: {"fournisseur": "f1", "prix": 1000}, 2: {"fournisseur": "f2", "prix": 900}})
        self.assertEqual(res["statut"], "Transmise au circuit V7")
        self.assertNotIn("coordonnateur", self.data(i)["validations"])

    def test_depassement_budget_impose_le_coordonnateur(self):
        self.as_(5)
        A.configurer_politique({"USD": 100000000})
        i = self.nouvelle_da(lignes=[dict(post="MAC", article="Agglos", unite="u", quantite=10000)])
        self.as_(2)
        A.valider_chantier(i, "ok")
        self.as_(3)
        res = A.chiffrer(i, {1: {"fournisseur": "f1", "prix": 400}})     # 40 000 $ > 30 000 $ disponibles
        self.assertEqual(res["statut"], "À valider coordonnateur")
        self.assertTrue(res["alertes"])

    def test_entierement_servie_par_le_stock(self):
        i = self.nouvelle_da(lignes=[dict(post="GO", article="Ciment", unite="sac", quantite=10)])
        self.as_(2)
        A.valider_chantier(i, "ok")
        self.as_(3)
        res = A.chiffrer(i, {1: {"qte_stock": 10}})
        self.assertEqual((res["statut"], res["montant"]), ("Servie par stock", 0))
        self.assertEqual(self.data(i)["operations"], [])

    # ------------------------------------------------------------------ séparation et périmètres
    def test_separation_des_responsabilites(self):
        i = self.nouvelle_da()
        self.as_(2)
        A.valider_chantier(i, "ok")
        with patch.dict(auth.PROFILS_STANDARDS["chef_chantier"]["droits"], {"chiffrage_achats": "w"}):
            with self.engine.begin() as c:
                c.execute(db.users.update().where(db.users.c.id == 2).values(role="finance"))
            with db.transaction("x") as t:
                t.parametre("droits_utilisateur:2", {"chiffrage_achats": "w"})
            self.as_(2)
            with self.assertRaisesRegex(ValueError, "Séparation"):      # le valideur chantier ne chiffre pas
                A.chiffrer(i, {1: {"fournisseur": "f1", "prix": 1}, 2: {"fournisseur": "f1", "prix": 1}})

    def test_coordonnateur_distinct_du_chiffreur(self):
        i = self.nouvelle_da()
        self.as_(2)
        A.valider_chantier(i, "ok")
        self.as_(8)                                      # administrateur : tous les accès
        A.chiffrer(i, {1: {"fournisseur": "f1", "prix": 100}, 2: {"fournisseur": "f2", "prix": 100}})
        with self.assertRaisesRegex(ValueError, "Séparation"):
            A.valider_coordonnateur(i, "auto-validation")
        self.as_(4)
        A.valider_coordonnateur(i, "ok")

    def test_perimetre_chantiers_affectes(self):
        self.as_(5)
        with db.transaction("périmètre") as t:
            auth.enregistrer_affectation(t, 9, "u9", "chantier", "chef_chantier", ["q"])
        i = self.nouvelle_da("p")
        self.as_(9)
        with self.assertRaisesRegex(ValueError, "périmètre"):
            A.valider_chantier(i, "hors périmètre")
        self.assertNotIn(i, [r["id"] for r in A.demandes(self.user)])
        self.as_(2)
        A.valider_chantier(i, "ok")

    def test_rejet_puis_modification_et_nouvelle_soumission(self):
        i = self.nouvelle_da()
        self.as_(2)
        A.valider_chantier(i, "quantités trop élevées", rejeter=True)
        self.assertEqual(self.data(i)["statut"], "Rejetée")
        self.as_(1)
        A.modifier(i, "Approvisionnement dalle", "Chantier", "2026-11-20",
                   [dict(post="GO", article="Ciment", unite="sac", quantite=60)])
        A.soumettre(i)
        self.assertEqual((self.data(i)["statut"], self.data(i)["validations"]), ("Soumise", {}))

    def test_controles_de_saisie(self):
        self.as_(1)
        for lignes in ([], [dict(post="XX", article="a", quantite=1)], [dict(post="GO", article="a", quantite=0)],
                       [dict(post="GO", article="a", quantite=1, fournisseur="c1")]):
            with self.assertRaises(ValueError):
                A.creer("p", "Objet", "", "2026-11-01", lignes)
        self.as_(6)                                      # comptable : pas de création de demande
        with self.assertRaises(ValueError):
            A.creer("p", "Objet", "", "2026-11-01", [dict(post="GO", article="a", quantite=1)])

    def test_commande_groupee_un_seul_fournisseur(self):
        i = self.nouvelle_da()
        self.as_(2)
        A.valider_chantier(i, "ok")
        self.as_(3)
        A.chiffrer(i, {1: {"fournisseur": "f1", "prix": 100}, 2: {"fournisseur": "f2", "prix": 100}})
        self.as_(4)
        A.valider_coordonnateur(i, "ok")
        ops = self.data(i)["operations"]
        for oid in ops:
            for uid in (2, 6, 7, 5):
                self.as_(uid)
                V.approve(oid, "ok")
        self.as_(3)
        with self.assertRaises(ValueError):
            A.commande_groupee(ops, "BC-X", "2026-10-20")

    def test_sauvegarde_inclut_les_demandes(self):
        import migration
        i = self.nouvelle_da()
        self.as_(5)
        migration.import_json(migration.export_json())
        self.assertEqual(db.un("v7_records", i)["data"]["statut"], "Soumise")


class ImportAchats(CircuitAchats):
    """Upload Excel : demandes en brouillon (prix facultatifs), puis chiffrage par les achats."""

    def importer(self, fonction, contenu, uid):
        from imports import service as SV
        self.as_(uid)
        ds = SV.parse_file(contenu, fonction)
        pv = SV.preview_import(ds, SV.contexte("en_cours"), contenu, "test.xlsx")
        if pv["preview_id"] is None or pv["rapport"]["errors"]:
            return pv
        return {**pv, **SV.commit_import(pv["preview_id"], {"accepter_alertes": True})}

    def fichier_da(self, ref="DA-XL-1", chantier="p", fournisseur="F001", devise="USD"):
        from tests.test_imports import classeur
        return classeur("demandes_achat", "en_cours", f"LOT-{ref}", {
            "Demandes_Achat": [{"reference_externe": ref, "chantier_ref": chantier, "objet": "Coulage voiles R+1",
                                "date_besoin": "2026-11-20", "lieu_livraison": "Chantier", "devise": devise}],
            "Lignes_Demande_Achat": [
                {"demande_ref": ref, "numero_ligne": 1, "code_dqe": "GO", "article": "Ciment 42,5", "unite": "sac",
                 "quantite": 200},
                {"demande_ref": ref, "numero_ligne": 2, "code_dqe": "GO", "article": "Fer HA10", "unite": "barre",
                 "quantite": 120, "prix_unitaire": "7,40", "fournisseur_ref": fournisseur}]})

    def test_import_demande_puis_chiffrage(self):
        from tests.test_imports import classeur
        r = self.importer("demandes_achat", self.fichier_da(), uid=1)
        self.assertFalse(r["rapport"]["errors"], r["rapport"]["errors"])
        da = next(x for x in V.records(A.KIND) if x["ref"] == "DA-XL-1")
        d = da["data"]
        self.assertEqual((d["statut"], d["creator"], len(d["lignes"])), ("Brouillon", 1, 2))
        self.assertEqual((d["lignes"][1]["prix"], d["lignes"][1]["fournisseur"]), (740, "f1"))
        self.as_(1)
        A.soumettre(da["id"])
        self.as_(2)
        A.valider_chantier(da["id"], "ok")
        # Chiffrage incomplet : la ligne 1 n'a pas de prix → refus de tout le fichier
        ko = classeur("chiffrage_achats", "en_cours", "CHIF-KO", {"Chiffrage_Achats": [
            {"demande_ref": "DA-XL-1", "numero_ligne": 2, "prix_unitaire": "7,20"}]})
        r = self.importer("chiffrage_achats", ko, uid=3)
        self.assertTrue(r["rapport"]["errors"])
        self.assertEqual(self.data(da["id"])["statut"], "Validée chantier")
        okf = classeur("chiffrage_achats", "en_cours", "CHIF-OK", {"Chiffrage_Achats": [
            {"demande_ref": "da-xl-1", "numero_ligne": 1, "fournisseur_ref": "F001", "prix_unitaire": "11,80",
             "quantite_stock": 50},
            {"demande_ref": "DA-XL-1", "numero_ligne": 2, "prix_unitaire": "7,20"}]})
        r = self.importer("chiffrage_achats", okf, uid=3)
        self.assertFalse(r["rapport"]["errors"], r["rapport"]["errors"])
        d = self.data(da["id"])
        # 150 × 11,80 + 120 × 7,20 = 1 770 + 864 = 2 634 $
        self.assertEqual((d["statut"], d["validations"]["chiffrage"]["montant"]), ("À valider coordonnateur", 263400))
        self.assertTrue(d["lignes"][1]["source_prix"].startswith("achats (corrige"), d["lignes"][1]["source_prix"])
        self.assertEqual((d["lignes"][0]["qte_stock"], d["lignes"][0]["fournisseur"]), (50, "f1"))

    def test_import_controle_droits_perimetre_et_devise(self):
        r = self.importer("demandes_achat", self.fichier_da(devise="EUR"), uid=1)
        self.assertTrue(any(e["field"] == "devise" for e in r["rapport"]["errors"]))
        r = self.importer("demandes_achat", self.fichier_da(ref="DA-XL-2", fournisseur="C001"), uid=1)
        self.assertTrue(any(e["field"] == "fournisseur_ref" for e in r["rapport"]["errors"]))
        r = self.importer("demandes_achat", self.fichier_da(ref="DA-XL-3"), uid=6)    # comptable : pas de demandes
        self.assertTrue(r["rapport"]["errors"])
        self.as_(5)
        with db.transaction("périmètre") as t:
            auth.enregistrer_affectation(t, 1, "u1", "chantier", "conducteur_travaux", ["q"])
        r = self.importer("demandes_achat", self.fichier_da(ref="DA-XL-4"), uid=1)
        self.assertTrue(any("périmètre" in e["message"] for e in r["rapport"]["errors"]))
        self.assertEqual([x for x in V.records(A.KIND) if x["ref"].startswith("DA-XL")], [])

    def test_import_chiffrage_par_le_valideur_refuse(self):
        from tests.test_imports import classeur
        self.importer("demandes_achat", self.fichier_da(), uid=1)
        da = next(x for x in V.records(A.KIND) if x["ref"] == "DA-XL-1")
        self.as_(1)
        A.soumettre(da["id"])
        self.as_(8)
        A.valider_chantier(da["id"], "ok")
        f = classeur("chiffrage_achats", "en_cours", "CHIF-ADM", {"Chiffrage_Achats": [
            {"demande_ref": "DA-XL-1", "numero_ligne": 1, "fournisseur_ref": "F001", "prix_unitaire": 10}]})
        r = self.importer("chiffrage_achats", f, uid=8)
        self.assertTrue(any("Séparation" in e["message"] for e in r["rapport"]["errors"]))


class PostesEtProfils(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        db.meta.create_all(self.engine)
        self.p1 = patch.object(db, "moteur", lambda: self.engine)
        self.p1.start()
        self.user = None
        self.p2 = patch.object(auth, "utilisateur", lambda: self.user)
        self.p2.start()
        with self.engine.begin() as c:
            for id_, role in ((1, "admin"), (2, "lecteur"), (3, "chantier"), (4, "finance")):
                c.execute(db.users.insert().values(id=id_, identifiant=f"u{id_}", nom=f"U{id_}", role=role,
                                                   mdp_hash="x", actif=True, doit_changer_mdp=False, version_session=0))
            c.execute(db.projects.insert().values(id="p", name="P", currency="USD", status="En cours", client="",
                                                  budget=0, progress=0))
        self.admin = {"id": 1, "identifiant": "u1", "role": "admin", "droits": auth.droits_de(1, "admin")}
        self.user = self.admin

    def tearDown(self):
        self.p2.stop()
        self.p1.stop()
        self.engine.dispose()

    def test_treize_postes_sans_incompatibilite(self):
        self.assertEqual(len(auth.PROFILS_STANDARDS), 13)
        for code, p in auth.PROFILS_STANDARDS.items():
            self.assertIn(p["role"], auth.ROLES, code)
            self.assertTrue(set(p["droits"]) <= set(auth.MODULES), code)
            if p["role"] != "admin":
                self.assertEqual(auth.incompatibilites(p["droits"]), [], code)
        for role, d in auth.DROITS.items():
            if role != "admin":
                self.assertEqual(auth.incompatibilites(d), [], role)

    def test_poste_donne_le_modele_et_la_derogation_reste_prioritaire(self):
        with db.transaction("poste") as t:
            auth.enregistrer_affectation(t, 4, "u4", "finance", "acheteur", ["p"])
        d = auth.droits_de(4, "finance")
        self.assertEqual((d["chiffrage_achats"], d["approbation_n2"]), ("w", None))
        with db.transaction("dérogation") as t:
            t.parametre("droits_utilisateur:4", {"rapports": "r", "tiers": "x"})
        d = auth.droits_de(4, "finance")
        self.assertEqual((d["rapports"], d["tiers"], d["chiffrage_achats"]), ("r", None, "w"))
        self.assertEqual(auth.projets_de(4), ["p"])
        self.assertTrue(auth.sur_chantier({"id": 4, "role": "finance"}, "p"))
        self.assertFalse(auth.sur_chantier({"id": 4, "role": "finance"}, "autre"))
        self.assertEqual(auth.libelle_poste(4, "finance"), "Acheteur")

    def test_poste_d_une_autre_famille_refuse(self):
        with self.assertRaises(ValueError), db.transaction("x") as t:
            auth.enregistrer_affectation(t, 3, "u3", "chantier", "acheteur", None)
        with self.assertRaises(ValueError), db.transaction("x") as t:
            auth.enregistrer_affectation(t, 3, "u3", "chantier", "chef_chantier", ["inconnu"])

    def test_creation_de_profil_bien_defini(self):
        auth.creer_profil("acheteur_junior", "Acheteur junior", "finance",
                          {"chiffrage_achats": "w", "demandes_achat": "r", "accueil": "r", "approbation_n1": "r"},
                          "Chiffre sans commander seul")
        p = auth.profils()["acheteur_junior"]
        self.assertEqual(p["droits"], {"chiffrage_achats": "w", "demandes_achat": "r", "accueil": "r"})
        with db.transaction("poste") as t:
            auth.enregistrer_affectation(t, 4, "u4", "finance", "acheteur_junior", None)
        self.assertEqual(auth.droits_de(4, "finance")["chiffrage_achats"], "w")
        self.assertIsNone(auth.droits_de(4, "finance")["comptabilite"])
        with self.assertRaises(ValueError):           # code déjà pris
            auth.creer_profil("acheteur_junior", "Doublon", "finance", {"accueil": "r"})
        with self.assertRaises(ValueError):           # code d'un poste standard
            auth.creer_profil("acheteur", "Doublon", "finance", {"accueil": "r"})

    def test_profil_incompatible_ou_sensible_refuse(self):
        with self.assertRaises(ValueError):
            auth.creer_profil("super_achat", "Achat et coordination", "finance",
                              {"chiffrage_achats": "w", "approbation_coordonnateur": "w"})
        with self.assertRaises(ValueError):
            auth.creer_profil("admin_bis", "Administrateur bis", "admin", {"accueil": "r"})
        # un gestionnaire non administrateur ne donne pas la gestion des comptes
        self.user = {"id": 2, "identifiant": "u2", "role": "lecteur",
                     "droits": auth.modele_droits("lecteur", "admin_erp")}
        with self.assertRaises(ValueError):
            auth.creer_profil("gestion_comptes", "Gestion des comptes", "lecteur", {"utilisateurs": "w"})
        auth.creer_profil("lecture_achats", "Lecture achats", "lecteur", {"achats": "r", "demandes_achat": "r"})
        with self.assertRaises(ValueError), db.transaction("x") as t:   # ni un compte administrateur
            auth.enregistrer_affectation(t, 1, "u1", "admin", "dg", None)

    def test_modification_de_profil_ferme_les_sessions(self):
        auth.creer_profil("magasin_bis", "Magasin bis", "chantier", {"achats": "w"})
        with db.transaction("poste") as t:
            auth.enregistrer_affectation(t, 3, "u3", "chantier", "magasin_bis", None)
        auth.modifier_profil("magasin_bis", "Magasin bis", {"achats": "r"}, "", True)
        self.assertEqual(auth.droits_de(3, "chantier")["achats"], "r")
        self.assertEqual(db.un("users", 3)["version_session"], 1)
        auth.modifier_profil("magasin_bis", "Magasin bis", {"achats": "r"}, "", False)   # désactivé : retour au rôle
        self.assertEqual(auth.droits_de(3, "chantier")["chantiers"], "w")
        with self.assertRaises(ValueError):
            auth.modifier_profil("acheteur", "Acheteur", {"achats": "r"}, "", True)


if __name__ == "__main__":
    unittest.main()
