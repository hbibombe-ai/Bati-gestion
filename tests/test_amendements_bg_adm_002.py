"""Amendements BG-ADM-002 (sauvegarde, délégations, soldes à date), sur base SQLite isolée."""
import base64
import json
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, func, select
from sqlalchemy.pool import StaticPool

import auth
import db
import gestion_v7 as V
import migration as M


class Amendements(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        db.meta.create_all(self.engine)
        self.p1 = patch.object(db, 'moteur', lambda: self.engine); self.p1.start()
        self.user = None
        self.p2 = patch.object(auth, 'utilisateur', lambda: self.user); self.p2.start()
        with self.engine.begin() as c:
            for id_, role in enumerate(['chantier', 'chantier', 'finance', 'finance', 'admin', 'finance', 'admin'], 1):
                c.execute(db.users.insert().values(id=id_, identifiant=str(id_), nom='User ' + str(id_), role=role,
                                                   mdp_hash='test', actif=True, doit_changer_mdp=False))
            c.execute(db.projects.insert().values(id='p', name='Projet', currency='USD', status='En cours',
                                                  client='', budget=10000000, progress=0))
        self.as_(5)
        self.account = V.create_account('BANK', 'Banque', 'USD', '5211', 'bank')
        self.cash = V.create_account('CASH', 'Caisse', 'USD', '5711', 'cash')
        V.opening(self.account, 20000000, '2026-10-01', 'initial')

    def tearDown(self):
        self.p2.stop(); self.p1.stop(); self.engine.dispose()

    def as_(self, i):
        self.user = db.un('users', i)

    def nb(self, table):
        with self.engine.connect() as c:
            return c.execute(select(func.count()).select_from(db.TABLES[table])).scalar()

    def sauvegarde(self):
        return json.loads(M.export_json().decode('utf-8'))

    def envoyer(self, data, role):
        return M.import_json(json.dumps(data).encode('utf-8'), role)

    # §1 : une table absente n'est jamais interprétée comme une table à vider
    def test_table_absente_refusee_sans_rien_vider(self):
        data = self.sauvegarde()
        self.as_(5); V.transfer(self.account, self.cash, 1000000, '2026-10-05', 'T1')
        mouvements = self.nb('movements'); comptes = self.nb('v7_records')
        del data['tables']['movements']
        with self.assertRaises(ValueError) as ctx:
            self.envoyer(data, 'admin')
        self.assertIn('movements', str(ctx.exception))
        self.assertEqual(self.nb('movements'), mouvements)
        self.assertEqual(self.nb('v7_records'), comptes)

    def test_empreinte_piece_incoherente_refusee(self):
        data = self.sauvegarde()
        contenu = b'%PDF-fausse-piece'
        data['tables']['pieces'].append(dict(id='P-X', name='facture.pdf', mime='application/pdf',
                                             content={'__b64__': base64.b64encode(contenu).decode()},
                                             hash='0' * 64, size=len(contenu)))
        mouvements = self.nb('movements')
        with self.assertRaises(ValueError) as ctx:
            self.envoyer(data, 'admin')
        self.assertIn('empreinte', str(ctx.exception))
        self.assertEqual(self.nb('movements'), mouvements)

    def test_identifiant_en_double_refuse(self):
        data = self.sauvegarde()
        data['tables']['clients'] = [{'id': 'X', 'code': 'A'}, {'id': 'X', 'code': 'B'}]
        with self.assertRaises(ValueError):
            self.envoyer(data, 'admin')

    # Délégations financières V7 : restauration réservée à la DG
    def test_delegation_restauree_seulement_par_la_dg(self):
        data = self.sauvegarde()
        comptes = self.nb('v7_records')
        data['tables']['v7_records'].append(dict(id='D-1', kind='delegation', ref='DEL-1', project='', currency='USD',
                                                 data={'user': 3, 'level': 'N2', 'limit': 1000000}, version=1))
        with self.assertRaises(ValueError) as ctx:
            self.envoyer(data, 'finance')
        self.assertIn('DG', str(ctx.exception))
        self.assertEqual(self.nb('v7_records'), comptes)  # aucune écriture sur refus
        with self.engine.connect() as c:
            self.assertIsNone(c.execute(select(db.TABLES['v7_records']).where(db.TABLES['v7_records'].c.id == 'D-1')).first())

    def test_sauvegarde_normale_restaurable(self):
        self.as_(5); V.transfer(self.account, self.cash, 1000000, '2026-10-05', 'T1')
        compte = self.envoyer(self.sauvegarde(), 'admin')
        self.assertEqual(compte['movements'], self.nb('movements'))
        self.assertEqual(sum(V.balance(a) for a in V.records('account')), 20000000)

    # §1 : soldes et consolidation à la date de situation
    def test_solde_exclut_les_mouvements_posterieurs_a_la_situation(self):
        self.as_(5); V.transfer(self.account, self.cash, 1000000, '2026-10-05', 'T1')
        bank = db.un('v7_records', self.account); cash = db.un('v7_records', self.cash)
        self.assertEqual(V.balance(bank), 19000000)
        self.assertEqual(V.balance(bank, date_='2026-10-03'), 20000000)
        self.assertEqual(V.balance(cash, date_='2026-10-03'), 0)
        self.assertEqual(V.balance(cash, date_='2026-10-05'), 1000000)

    def test_consolidation_respecte_la_date_de_situation(self):
        self.as_(5); V.transfer(self.account, self.cash, 1000000, '2026-10-05', 'T1')
        avant = V.consolidated('USD', {}, '2026-10-03')
        self.assertEqual(avant['total'], 20000000)
        apres = V.consolidated('USD', {}, '2026-10-10')
        self.assertEqual(apres['total'], 20000000)


if __name__ == '__main__':
    unittest.main()
