"""Interface façon ERP : grille d'applications, kanban / liste, fiches et fil d'activité (Streamlit AppTest)."""
import os
import tempfile
import unittest

from streamlit.testing.v1 import AppTest

from tests.test_ecrans_imports import RACINE

ROLES = ("admin", "finance", "rh", "chantier", "lecteur")


def _ecran_erp():
    import importlib
    import os
    import sys as _s
    _s.path.insert(0, os.environ["BG_RACINE"])
    import sqlalchemy as sa
    import streamlit as st
    import db
    db.moteur()
    with db.moteur().begin() as c:
        existants = {r[0] for r in c.execute(sa.select(db.users.c.id))}
        for i, r in enumerate(["admin", "finance", "rh", "chantier", "lecteur"], 1):
            if i not in existants:
                c.execute(db.users.insert().values(id=i, identifiant=r, nom=r.title(), role=r, mdp_hash="x", actif=True,
                                                   doit_changer_mdp=False, version_session=0))
        if not c.execute(sa.select(db.projects.c.id).where(db.projects.c.id == "p1")).first():
            c.execute(db.clients.insert().values(id="c1", code="C001", name="Société Kintambo", roles=["client"],
                                                 phone="+243 810 000 000", email="", address="Kinshasa"))
            c.execute(db.clients.insert().values(id="f1", code="F001", name="Quincaillerie Ébène", roles=["supplier"]))
            c.execute(db.projects.insert().values(id="p1", name="Résidence Kintambo", currency="USD", status="En cours",
                                                  client="c1", budget=1000000, progress=40, deadline="2020-01-01",
                                                  location="Kintambo", latitude=-4.33, longitude=15.29))
            c.execute(db.projects.insert().values(id="p2", name="École Limete", currency="USD", status="À démarrer",
                                                  client="", budget=0, progress=0))
            c.execute(db.quotes.insert().values(id="q1", number="DV-001", client="c1", project="p1", date="2026-10-01",
                                                notes="", status="Envoyé", lines=[{"description": "Béton", "qty": 2,
                                                                                    "price": 10000}], currency="USD"))
            c.execute(db.invoices.insert().values(id="i1", number="FA-001", client="c1", project="p1", date="2026-10-02",
                                                  due="2026-10-10", notes="", status="Envoyée",
                                                  lines=[{"description": "Béton", "qty": 2, "price": 10000}],
                                                  currency="USD", paid=5000))
    ident = {"admin": 1, "finance": 2, "rh": 3, "chantier": 4, "lecteur": 5}[os.environ["BG_ROLE"]]
    st.session_state["utilisateur"] = {"id": ident, "identifiant": os.environ["BG_ROLE"], "nom": "Test",
                                       "role": os.environ["BG_ROLE"], "doit_changer_mdp": False}
    if os.environ.get("BG_FICHE"):
        cle, id_ = os.environ["BG_FICHE"].split(":")
        st.session_state.setdefault(f"bg_fiche_{cle}", id_)
    args = [os.environ["BG_ARG"]] if os.environ.get("BG_ARG") else []
    getattr(importlib.import_module(os.environ["BG_MODULE"]), "page")(*args)


class Logique(unittest.TestCase):
    def setUp(self):
        import sys
        sys.path.insert(0, RACINE)

    def test_recherche_sans_accents_et_filtres_ou_et(self):
        import composants as C
        lignes = [{"_id": 1, "nom": "École Limete", "statut": "En cours", "retard": True},
                  {"_id": 2, "nom": "Résidence", "statut": "Terminé", "retard": False},
                  {"_id": 3, "nom": "Ecole Ngaliema", "statut": "À démarrer", "retard": True}]
        f = [("En cours", "État", lambda r: r["statut"] == "En cours"),
             ("À démarrer", "État", lambda r: r["statut"] == "À démarrer"),
             ("En retard", "Alerte", lambda r: r["retard"])]
        self.assertEqual([r["_id"] for r in C.filtrer(lignes, "ecole", ["nom"], f, [])], [1, 3])
        self.assertEqual([r["_id"] for r in C.filtrer(lignes, "", ["nom"], f, ["En cours", "À démarrer"])], [1, 3])
        self.assertEqual([r["_id"] for r in C.filtrer(lignes, "", ["nom"], f, ["À démarrer", "En retard"])], [3])

    def test_regroupement_dans_l_ordre_des_etapes(self):
        import composants as C
        lignes = [{"s": "Terminé"}, {"s": "En cours"}, {"s": ""}, {"s": "Autre"}, {"s": "En cours"}]
        g = C.regrouper(lignes, "s", ["À démarrer", "En cours", "Terminé"])
        self.assertEqual([(k, len(v)) for k, v in g], [("En cours", 2), ("Terminé", 1), ("Autre", 1), ("Non renseigné", 1)])

    def test_changements_lisibles_sans_montants(self):
        import composants as C
        ch = C._changements({"status": "En cours", "budget": 100, "name": "A"}, {"status": "Terminé", "budget": 200, "name": "A"})
        self.assertEqual(len(ch), 2)
        self.assertIn("En cours → Terminé", ch[0])
        self.assertIn("modifiés", ch[1])
        self.assertEqual(C.initiales("Résidence Kintambo"), "RK")


class Ecrans(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(cls.tmp, "erp.db")
        os.environ["BG_RACINE"] = RACINE

    def tearDown(self):
        for k in ("BG_FICHE", "BG_ARG"):
            os.environ.pop(k, None)

    def ouvrir(self, module, role, arg="", fiche=""):
        os.environ["BG_MODULE"], os.environ["BG_ROLE"], os.environ["BG_ARG"] = module, role, arg
        if fiche:
            os.environ["BG_FICHE"] = fiche
        at = AppTest.from_function(_ecran_erp, default_timeout=60)
        at.run()
        self.assertFalse(at.exception, f"{module} {arg} / {role} : {at.exception}")
        return at

    def test_listes_kanban_pour_chaque_role(self):
        for role in ROLES:
            self.ouvrir("vues.chantiers", role)
            self.ouvrir("vues.tiers", role)
            self.ouvrir("vues.devis_factures", role, "quotes")
            self.ouvrir("vues.devis_factures", role, "invoices")

    def test_vue_liste_et_regroupement(self):
        at = self.ouvrir("vues.chantiers", "admin")
        at.segmented_control(key="ch_vue").set_value("Liste").run()
        self.assertFalse(at.exception)
        at.selectbox(key="ch_grp").set_value("Client").run()
        self.assertFalse(at.exception)
        at.text_input(key="ch_q").input("limete").run()
        self.assertFalse(at.exception)
        self.assertTrue(any("1 chantier sur 2" in h.proto.body for h in at.get("html")))

    def test_fiches_et_note_dans_le_fil_d_activite(self):
        import sys
        sys.path.insert(0, RACINE)
        import db
        at = self.ouvrir("vues.chantiers", "admin", fiche="ch:p1")
        self.assertTrue(any("Fil d’activité" in h.proto.body for h in at.get("html")))
        at.text_area[0].input("Livraison du ciment prévue lundi")
        at.button[[b.label for b in at.button].index("Enregistrer la note")].click().run()
        self.assertFalse(at.exception)
        notes = db.requete("select * from audit where action = 'Note' and objet = 'projects' and objet_id = 'p1'")
        self.assertEqual([n["resume"] for n in notes], ["Livraison du ciment prévue lundi"])
        for module, arg, fiche in (("vues.tiers", "", "tiers:c1"), ("vues.devis_factures", "quotes", "doc_quotes:q1"),
                                   ("vues.devis_factures", "invoices", "doc_invoices:i1")):
            for role in ("admin", "lecteur"):
                self.ouvrir(module, role, arg, fiche)

    def test_etape_du_chantier_modifiable_depuis_la_fiche(self):
        import sys
        sys.path.insert(0, RACINE)
        import db
        at = self.ouvrir("vues.chantiers", "admin", fiche="ch:p2")
        at.segmented_control(key="bg_etape_ch_p2_À démarrer").set_value("En cours").run()
        self.assertFalse(at.exception)
        self.assertEqual(db.un("projects", "p2")["status"], "En cours")

    def test_application_complete_grille_des_applications(self):
        at = AppTest.from_file(os.path.join(RACINE, "app.py"), default_timeout=60)
        at.session_state["utilisateur"] = {"id": 1, "identifiant": "admin", "nom": "Hardy Bibombe", "role": "admin",
                                           "doit_changer_mdp": False}
        at.run()
        self.assertFalse(at.exception, at.exception)
        corps = " ".join(h.proto.body for h in at.get("html"))
        self.assertIn("Bonjour Hardy", corps)


if __name__ == "__main__":
    unittest.main()
