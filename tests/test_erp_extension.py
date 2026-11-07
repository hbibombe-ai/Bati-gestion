"""Extension ERP : CRM, activités planifiées (rappels), planning Gantt, tableau de bord personnalisable et vues
kanban / liste de Personnel, Dépenses et Achats."""
import datetime as dt
import os
import sys
import tempfile
import unittest

from streamlit.testing.v1 import AppTest

from tests.test_ecrans_imports import RACINE

ROLES = ("admin", "finance", "rh", "chantier", "lecteur")


def _ecran_ext():
    import importlib
    import os
    import sys as _s
    _s.path.insert(0, os.environ["BG_RACINE"])
    import datetime as _dt
    import sqlalchemy as sa
    import streamlit as st
    import db
    db.moteur()
    hier = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
    with db.moteur().begin() as c:
        existants = {r[0] for r in c.execute(sa.select(db.users.c.id))}
        for i, r in enumerate(["admin", "finance", "rh", "chantier", "lecteur"], 1):
            if i not in existants:
                c.execute(db.users.insert().values(id=i, identifiant=r, nom=r.title(), role=r, mdp_hash="x", actif=True,
                                                   doit_changer_mdp=False, version_session=0))
        if not c.execute(sa.select(db.projects.c.id).where(db.projects.c.id == "p1")).first():
            c.execute(db.clients.insert().values(id="c1", code="C001", name="Société Kintambo", roles=["client"]))
            c.execute(db.projects.insert().values(id="p1", name="Résidence Kintambo", currency="USD", status="En cours",
                                                  client="c1", budget=1000000, progress=40, deadline="2027-03-01",
                                                  debut="2026-09-01"))
            c.execute(db.projects.insert().values(id="p2", name="École Limete", currency="USD", status="À démarrer",
                                                  client="", budget=0, progress=0))
            c.execute(db.personnel.insert().values(id="e1", code="M001", name="Jean Mbala", job="Maçon", service="Chantier",
                                                   start="2025-01-10", location="Chantier", project="p1", active=True))
            c.execute(db.expenses.insert().values(id="x1", label="Ciment 50 sacs", project="p1", category="Matériaux",
                                                  date="2026-11-02", amount=45000, currency="USD"))
            c.execute(db.TABLES["crm_pistes"].insert().values(
                id="l1", titre="Entrepôt Kingabwa", client="", contact="M. Lukusa", telephone="", email="", source="",
                montant=5000000, devise="USD", probabilite=30, etape="Qualifié", responsable=1, cloture_prevue="",
                priorite=2, notes="", motif_perte="", cree_le=_dt.datetime.now(), archive=False))
            c.execute(db.TABLES["activites"].insert().values(
                id="a1", objet="projects", objet_id="p1", libelle="Résidence Kintambo", type="Appel",
                resume="Appeler le client", echeance=hier, assigne_a=1, cree_par=1, cree_le=_dt.datetime.now(),
                fait=False, compte_rendu=""))
    ident = {"admin": 1, "finance": 2, "rh": 3, "chantier": 4, "lecteur": 5}[os.environ["BG_ROLE"]]
    st.session_state["utilisateur"] = {"id": ident, "identifiant": os.environ["BG_ROLE"], "nom": "Test",
                                       "role": os.environ["BG_ROLE"], "doit_changer_mdp": False}
    if os.environ.get("BG_FICHE"):
        cle, id_ = os.environ["BG_FICHE"].split(":")
        st.session_state.setdefault(f"bg_fiche_{cle}", id_)
    getattr(importlib.import_module(os.environ["BG_MODULE"]), "page")()


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(cls.tmp, "ext.db")
        os.environ["BG_RACINE"] = RACINE
        sys.path.insert(0, RACINE)

    def tearDown(self):
        os.environ.pop("BG_FICHE", None)

    def ouvrir(self, module, role="admin", fiche=""):
        os.environ["BG_MODULE"], os.environ["BG_ROLE"] = module, role
        if fiche:
            os.environ["BG_FICHE"] = fiche
        else:
            os.environ.pop("BG_FICHE", None)
        at = AppTest.from_function(_ecran_ext, default_timeout=60)
        at.run()
        self.assertFalse(at.exception, f"{module} / {role} / {fiche} : {at.exception}")
        return at


class Ecrans(Base):
    def test_toutes_les_pages_pour_chaque_role(self):
        import auth
        pages = {"vues.crm": "commercial", "vues.planning": "chantiers", "vues.activites": "accueil",
                 "vues.tableau_bord": "accueil", "vues.personnel": "personnel", "vues.depenses": "depenses",
                 "vues.achats_stock": "demandes_achat"}
        for role in ROLES:
            for module in pages:
                self.ouvrir(module, role)
        self.assertTrue(auth.DROITS)

    def test_fiches_avec_activites(self):
        for module, fiche in (("vues.crm", "crm:l1"), ("vues.personnel", "pers:e1"), ("vues.depenses", "dep:x1"),
                              ("vues.activites", "act:a1"), ("vues.chantiers", "ch:p1")):
            at = self.ouvrir(module, "admin", fiche)
            corps = " ".join(h.proto.body for h in at.get("html"))
            if module != "vues.activites":
                self.assertIn("Activités planifiées", corps, module)

    def test_gantt_affiche_les_chantiers_dates(self):
        at = self.ouvrir("vues.planning")
        self.assertTrue(at.get("arrow_vega_lite_chart") or at.get("vega_lite_chart"))


class Regles(Base):
    def test_crm_etapes_perte_et_creation_client(self):
        import db
        import erp
        self.ouvrir("vues.crm")      # crée la base de test
        pid = erp.enregistrer_piste({"titre": "Clôture dépôt", "contact": "Mme Bijou", "telephone": "+243 81",
                                     "email": "", "source": "Autre", "montant": 200000, "devise": "USD",
                                     "probabilite": 20, "etape": "Nouveau", "responsable": 1, "cloture_prevue": "",
                                     "priorite": 1, "notes": ""})
        erp.changer_etape(pid, "Proposition")
        self.assertEqual(db.un("crm_pistes", pid)["probabilite"], 50)
        self.assertEqual(erp.montant_pondere(db.un("crm_pistes", pid)), 100000)
        with self.assertRaises(ValueError):
            erp.changer_etape(pid, erp.PERDU)            # motif obligatoire
        cid = erp.creer_client(pid)
        self.assertEqual(db.un("clients", cid)["name"], "Mme Bijou")
        self.assertEqual(db.un("crm_pistes", pid)["client"], cid)
        with self.assertRaises(ValueError):
            erp.enregistrer_piste({"titre": "", "contact": "x", "etape": "Nouveau", "devise": "USD"})

    def test_activites_rappels_terminer_reporter(self):
        import db
        import erp
        self.ouvrir("vues.activites")
        demain = (dt.date.today() + dt.timedelta(days=1)).isoformat()
        aid = erp.planifier("clients", "c1", "Société Kintambo", "Appel", "Relancer pour le devis",
                            dt.date.today().isoformat(), 2, 1)
        r = erp.rappels(2)
        self.assertEqual(r["Aujourd’hui"], 1)
        erp.reporter(aid, demain)
        self.assertEqual(erp.rappels(2)["Aujourd’hui"], 0)
        erp.terminer(aid, "Client d'accord")
        self.assertTrue(db.un("activites", aid)["fait"])
        with self.assertRaises(ValueError):
            erp.terminer(aid)
        journal = db.requete("select resume from audit where objet = 'clients' and objet_id = 'c1' and action = 'Activité'")
        self.assertEqual(len(journal), 2)
        self.assertIn("Client d'accord", journal[-1]["resume"] + journal[0]["resume"])
        self.assertEqual(erp.echeance_etat("2000-01-01"), "En retard")

    def test_dates_du_planning(self):
        import db
        import erp
        self.ouvrir("vues.planning")
        n = erp.enregistrer_dates({"p2": ("2026-12-01", "2027-06-30")})
        self.assertEqual(n, 1)
        self.assertEqual(db.un("projects", "p2")["debut"], "2026-12-01")
        with self.assertRaises(ValueError):
            erp.enregistrer_dates({"p2": ("2027-07-01", "2027-06-30")})

    def test_preferences_du_tableau_de_bord(self):
        import erp
        self.ouvrir("vues.tableau_bord")
        erp.enregistrer_prefs_tableau(5, ["k_activites", "g_avancement"], 1)
        self.assertEqual(erp.prefs_tableau(5), {"widgets": ["k_activites", "g_avancement"], "colonnes": 1})
        self.ouvrir("vues.tableau_bord", "lecteur")

    def test_sauvegarde_inclut_crm_et_activites(self):
        import json
        import migration as M
        self.ouvrir("vues.crm")
        data = json.loads(M.export_json(avec_pieces=False))
        self.assertIn("crm_pistes", data["tables"])
        self.assertIn("activites", data["tables"])


if __name__ == "__main__":
    unittest.main()
