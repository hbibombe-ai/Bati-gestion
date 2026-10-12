"""Droits par utilisateur : modèle du rôle, dérogations par rubrique, retour au modèle, sessions fermées."""
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import auth
import db


class DroitsParUtilisateur(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        db.meta.create_all(self.engine)
        self.p = patch.object(db, 'moteur', lambda: self.engine)
        self.p.start()
        self.addCleanup(self.p.stop)
        with self.engine.begin() as c:
            c.execute(db.users.insert().values(id=1, identifiant='admin', nom='Admin', role='admin', mdp_hash='x',
                                               actif=True, doit_changer_mdp=False, version_session=0))
            c.execute(db.users.insert().values(id=2, identifiant='conducteur', nom='Conducteur', role='chantier',
                                               mdp_hash='x', actif=True, doit_changer_mdp=False, version_session=0))

    def test_modele_du_role_sans_derogation(self):
        self.assertFalse(auth.personnalise(2))
        d = auth.droits_de(2, 'chantier')
        self.assertEqual(d['chantiers'], 'w')
        self.assertIsNone(d['comptabilite'])

    def test_derogation_ajoute_la_comptabilite(self):
        with db.transaction('test') as t:
            t.parametre('droits_utilisateur:2', {'comptabilite': 'r', 'paie': 'x'}, resume='test')
        self.assertTrue(auth.personnalise(2))
        d = auth.droits_de(2, 'chantier')
        self.assertEqual(d['comptabilite'], 'r')          # ajouté
        self.assertIsNone(d['paie'])                       # retiré
        self.assertEqual(d['chantiers'], 'w')              # inchangé

    def test_admin_garde_tout(self):
        with db.transaction('test') as t:
            t.parametre('droits_utilisateur:1', {'comptabilite': 'x'}, resume='test')
        self.assertTrue(all(v == 'w' for v in auth.droits_de(1, 'admin').values()))

    def test_droit_utilise_les_droits_de_session(self):
        with patch.object(auth, 'utilisateur', lambda: {'id': 2, 'role': 'chantier',
                                                         'droits': {'comptabilite': 'w', 'chantiers': 'w'}}):
            self.assertTrue(auth.modifie('comptabilite'))
            self.assertIsNone(auth.droit('tresorerie'))

    def test_droit_sans_droits_de_session_suit_le_role(self):
        with patch.object(auth, 'utilisateur', lambda: {'id': 2, 'role': 'chantier'}):
            self.assertFalse(auth.voit('comptabilite'))
            self.assertTrue(auth.modifie('chantiers'))


class EnregistrementDesEcarts(unittest.TestCase):
    """Reproduit la logique de vues/utilisateurs.py : seuls les écarts avec le modèle sont gardés."""
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        db.meta.create_all(self.engine)
        self.p = patch.object(db, 'moteur', lambda: self.engine)
        self.p.start()
        self.addCleanup(self.p.stop)
        with self.engine.begin() as c:
            c.execute(db.users.insert().values(id=2, identifiant='c', nom='C', role='chantier', mdp_hash='x',
                                               actif=True, doit_changer_mdp=False, version_session=0))

    def _enregistrer(self, role, droits):
        from vues.utilisateurs import _enregistrer_droits
        with db.transaction('test') as t:
            _enregistrer_droits(t, 2, 'c', role, droits)

    def test_identique_au_modele_ne_cree_aucune_derogation(self):
        self._enregistrer('chantier', dict(auth.DROITS['chantier']) | {m: None for m in auth.MODULES if m not in auth.DROITS['chantier']})
        self.assertFalse(auth.personnalise(2))

    def test_ajout_d_une_rubrique_cree_une_derogation(self):
        droits = {m: auth.DROITS['chantier'].get(m) for m in auth.MODULES}
        droits['comptabilite'] = 'w'
        self._enregistrer('chantier', droits)
        self.assertTrue(auth.personnalise(2))
        self.assertEqual(auth.droits_de(2, 'chantier')['comptabilite'], 'w')
        self.assertEqual(db.parametre('droits_utilisateur:2'), {'comptabilite': 'w'})

    def test_retour_au_modele_supprime_la_derogation(self):
        droits = {m: auth.DROITS['chantier'].get(m) for m in auth.MODULES}
        droits['comptabilite'] = 'w'
        self._enregistrer('chantier', droits)
        self._enregistrer('chantier', {m: auth.DROITS['chantier'].get(m) for m in auth.MODULES})
        self.assertFalse(auth.personnalise(2))


class ApprobationsEtImports(unittest.TestCase):
    """Approbations et imports suivent les droits accordés à chaque usager."""
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        db.meta.create_all(self.engine)
        self.p = patch.object(db, 'moteur', lambda: self.engine)
        self.p.start()
        self.addCleanup(self.p.stop)
        with self.engine.begin() as c:
            c.execute(db.users.insert().values(id=2, identifiant='c', nom='C', role='chantier', mdp_hash='x',
                                               actif=True, doit_changer_mdp=False, version_session=0))

    def _accorder(self, **droits):
        with db.transaction('test') as t:
            t.parametre('droits_utilisateur:2', droits, resume='test')

    def test_approbation_n1_du_modele_chantier_puis_n2_accordee(self):
        import gestion_v7 as V
        u = {'id': 2, 'role': 'chantier', 'droits': auth.droits_de(2, 'chantier')}
        self.assertTrue(V.peut(u, 'approbation_n1'))
        self.assertFalse(V.peut(u, 'approbation_n2'))
        self._accorder(approbation_n2='w')
        u = {'id': 2, 'role': 'chantier', 'droits': auth.droits_de(2, 'chantier')}
        self.assertTrue(V.peut(u, 'approbation_n2'))
        self.assertTrue(V.approbateur(u | {'role': 'chantier'}))

    def test_retrait_approbation_n1(self):
        import gestion_v7 as V
        self._accorder(approbation_n1='x')
        u = {'id': 2, 'role': 'chantier', 'droits': auth.droits_de(2, 'chantier')}
        self.assertFalse(V.peut(u, 'approbation_n1'))

    def test_import_comptabilite_refuse_puis_accorde(self):
        from imports import schema as S
        from imports import validation as VA
        fe = next(f for f in S.FEUILLES.values() if f.module == 'comptabilite')
        self.assertFalse(VA.autorise('chantier', fe, auth.droits_de(2, 'chantier')))
        self._accorder(comptabilite='w')
        self.assertTrue(VA.autorise('chantier', fe, auth.droits_de(2, 'chantier')))

    def test_import_du_modele_inchange(self):
        from imports import schema as S
        from imports import validation as VA
        fe = next(f for f in S.FEUILLES.values() if f.module == 'comptabilite')
        self.assertTrue(VA.autorise('finance', fe, auth.DROITS['finance']))
        self.assertFalse(VA.autorise('lecteur', fe, auth.DROITS['lecteur']))

    def test_donnees_de_paie_masquees_sans_acces_paie(self):
        from imports import service as SV
        self.assertNotIn(auth.DROITS['chantier'].get('paie'), ('r', 'w'))
        self._accorder(paie='r')
        self.assertEqual(auth.droits_de(2, 'chantier')['paie'], 'r')


if __name__ == '__main__':
    unittest.main()
