"""Pièces jointes aux fiches et sauvegarde : contenu conservé, anciennes sauvegardes acceptées."""
import json
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import auth
import db
import migration as M
import ui

PDF = b"%PDF-1.4 test"


class PiecesJointes(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        db.meta.create_all(self.engine)
        p = patch.object(db, 'moteur', lambda: self.engine); p.start(); self.addCleanup(p.stop)
        with self.engine.begin() as c:
            c.execute(db.users.insert().values(id=1, identifiant='admin', nom='Admin', role='admin', mdp_hash='x',
                                               actif=True, doit_changer_mdp=False, version_session=0))
        with db.transaction('seed') as t:
            t.inserer('clients', {'id': 'c1', 'code': 'C1', 'name': 'Client', 'roles': ['client']})

    def _joindre(self, nom, contenu, entite='tiers', entite_id='c1'):
        empreinte = __import__('hashlib').sha256(contenu).hexdigest()
        with db.transaction(f'Document joint : {nom}') as t:
            t.inserer('pieces_jointes', {'id': db.nouvel_id(), 'entite': entite, 'entite_id': entite_id,
                                         'libelle': '', 'nom': nom, 'mime': ui.mime_fichier(contenu),
                                         'taille': len(contenu), 'sha256': empreinte, 'contenu': contenu,
                                         'ajoute_par': 1, 'ajoute_le': db.maintenant()})

    def test_types_acceptes(self):
        self.assertEqual(ui.mime_fichier(PDF), 'application/pdf')
        self.assertEqual(ui.mime_fichier(b'\xff\xd8\xff\xe0x'), 'image/jpeg')
        self.assertEqual(ui.mime_fichier(b'\x89PNG\r\n'), 'image/png')
        self.assertIsNone(ui.mime_fichier(b'PK\x03\x04docx'))

    def test_rattachement_a_une_fiche(self):
        self._joindre('contrat.pdf', PDF)
        rows = db.requete('select nom from pieces_jointes where entite = :e and entite_id = :i', e='tiers', i='c1')
        self.assertEqual([r['nom'] for r in rows], ['contrat.pdf'])
        self.assertEqual(db.requete('select id from pieces_jointes where entite_id = :i', i='autre'), [])

    def test_sauvegarde_inclut_les_pieces_jointes(self):
        self._joindre('contrat.pdf', PDF)
        with patch.object(M.R, 'company', lambda: {}), patch.object(M.R, 'company_snapshot', lambda *a, **k: {}):
            data = json.loads(M.export_json(avec_pieces=True))
        self.assertIn('pieces_jointes', data['tables'])
        self.assertEqual(len(data['tables']['pieces_jointes']), 1)

    def test_ancienne_sauvegarde_sans_pieces_ne_les_efface_pas(self):
        self._joindre('contrat.pdf', PDF)
        with patch.object(M.R, 'company', lambda: {}), patch.object(M.R, 'company_snapshot', lambda *a, **k: {}):
            data = json.loads(M.export_json(avec_pieces=True))
        del data['tables']['pieces_jointes']        # format antérieur à cette fonctionnalité
        M.verifier_sauvegarde(data, 'admin')        # toujours acceptée : aucune table obligatoire ajoutée
        with patch.object(M, 'verifier_sauvegarde', lambda d, r: None):
            M.import_json(json.dumps(data).encode('utf-8'), 'admin')
        self.assertEqual(len(db.requete('select id from pieces_jointes')), 1)


if __name__ == '__main__':
    unittest.main()
