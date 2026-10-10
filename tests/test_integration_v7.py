import unittest
from unittest.mock import patch
from sqlalchemy import create_engine,select
from sqlalchemy.pool import StaticPool
import db,auth,gestion_v7 as V

class Integration(unittest.TestCase):
 def setUp(self):
  self.engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool);db.meta.create_all(self.engine)
  self.p1=patch.object(db,'moteur',lambda:self.engine);self.p1.start();self.user=None;self.p2=patch.object(auth,'utilisateur',lambda:self.user);self.p2.start()
  with self.engine.begin() as c:
   for id_,role in enumerate(['chantier','chantier','finance','finance','admin','finance','admin'],1):
    c.execute(db.users.insert().values(id=id_,identifiant=str(id_),nom='User '+str(id_),role=role,mdp_hash='test',actif=True,doit_changer_mdp=False))
   c.execute(db.projects.insert().values(id='p',name='Projet',currency='USD',status='En cours',client='',budget=10000000,progress=0))
   c.execute(db.clients.insert().values(id='f',code='F001',name='Tiers',roles=['supplier']))
  self.as_(1);self.b=V.create_budget('p','CT004',[dict(code='MAT',label='Matériaux',budget=10000000,forecast=9000000)],15000000,9000000)
  self.as_(5);V.approve_budget(self.b,'validé');self.account=V.create_account('BANK','Banque','USD','5211','bank');self.cash=V.create_account('CASH','Caisse','USD','5711','cash');V.opening(self.account,20000000,'2026-10-01','initial')
 def tearDown(self):self.p2.stop();self.p1.stop();self.engine.dispose()
 def as_(self,i):self.user=db.un('users',i)
 def op(self,ref='OP1',nature='Achat',value=1000000):
  self.as_(1);i=V.create_operation(ref,'p','MAT','f','Matériaux',nature,value,'2026-10-30','602');V.submit(i)
  for uid in (2,3,4,5):self.as_(uid);V.approve(i,'contrôlé')
  return i
 def data(self,i):return db.un('v7_records',i)['data']
 def test_cycle_payments_and_no_double_budget(self):
  i=self.op();self.as_(3);V.order(i,'BC1','2026-10-02');self.as_(2);V.receive(i,'BL1','2026-10-03',1000000);self.as_(3);V.invoice(i,'F001','2026-10-04',1000000)
  self.as_(6);V.pay(i,self.account,400000,'2026-10-05','P1');V.pay(i,self.account,600000,'2026-10-06','P2')
  self.assertEqual(self.data(i)['status'],'Payée');m=V.metrics(db.un('v7_records',self.b),V.records('operation'))
  self.assertEqual((m['cost'],m['open'],m['cash'],m['available']),(1000000,0,1000000,9000000))
  with self.assertRaises(ValueError):V.pay(i,self.account,1,'2026-10-07','P3')
  self.assertEqual(len(self.data(i)['payments']),2)
  self.assertEqual(sum(x['debit']-x['credit'] for x in V.ledger()),0)
 def test_self_approval_and_executor_separation(self):
  self.as_(1);i=V.create_operation('X','p','MAT','f','Dépense','Dépense',100,'2026-10-20');V.submit(i)
  with self.assertRaises(ValueError):V.approve(i,'auto')
  i=self.op('Y','Avance',500000);self.as_(3)
  with self.assertRaises(ValueError):V.pay(i,self.account,500000,'2026-10-05','PAY')
 def test_change_restarts_approval(self):
  i=self.op('E','Dépense');self.as_(1);V.edit_operation(i,2000000,'nouveau','2026-10-30');self.assertEqual((self.data(i)['status'],self.data(i)['level']),('Brouillon',0));self.assertEqual(self.data(i)['approvals'],[])
 def test_budget_block_and_dg_exception(self):
  self.as_(1);i=V.create_operation('BIG','p','MAT','f','Engagement','Dépense',11000000,'2026-10-30');V.submit(i)
  for uid in (2,3,4):self.as_(uid);V.approve(i,'ok')
  self.as_(5)
  with self.assertRaises(ValueError):V.approve(i,'sans dérogation')
  V.approve(i,'dépassement autorisé',exception=True)
  self.assertEqual(V.metrics(db.un('v7_records',self.b),V.records('operation'))['available'],-1000000)
 def test_advance_does_not_create_two_costs(self):
  i=self.op('ADV','Avance',500000);self.as_(6);V.pay(i,self.account,500000,'2026-10-05','ADV-P')
  self.assertEqual(self.data(i)['cost'],0)
  self.as_(1);V.upload_piece(i,'facture.pdf',b'%PDF-fake-for-test','2026-10-06',350000);p=self.data(i)['justifications'][0]['piece'];self.as_(3);V.validate_justification(i,p,True,'Pièce contrôlée')
  m=V.metrics(db.un('v7_records',self.b),V.records('operation'));self.assertEqual((m['advance'],m['cost']),(150000,350000));self.as_(6);V.return_advance(i,self.cash,150000,'2026-10-07','RET')
  self.assertEqual(V.metrics(db.un('v7_records',self.b),V.records('operation'))['advance'],0);self.assertEqual(self.data(i)['cost'],350000)
 def test_transfer_and_reconciliation(self):
  self.as_(6);before=sum(V.balance(a) for a in V.records('account'));V.transfer(self.account,self.cash,1000000,'2026-10-05','T1');self.assertEqual(sum(V.balance(a) for a in V.records('account')),before)
  moves=[m['id'] for m in db.tout('movements') if m['journal']['v7_account']==self.account];i=V.reconcile(self.account,'2026-10-06',19000000,moves,'RELEVE');self.assertEqual(self.data(i)['difference'],0)
  with self.assertRaises(ValueError):V.transfer(self.account,self.cash,100,'2026-10-05','T1')
 def test_reversal_keeps_original_and_ledger(self):
  i=self.op('REV','Avance',200000);self.as_(6);V.pay(i,self.account,200000,'2026-10-05','RP');pid=self.data(i)['payments'][0]['id'];V.reverse_payment(i,pid,'2026-10-06','erreur');self.assertTrue(self.data(i)['payments'][0]['reversed']);self.assertEqual(V.balance(db.un('v7_records',self.account)),20000000)
  with self.assertRaises(ValueError):V.reverse_payment(i,pid,'2026-10-06','bis')
 def test_tax_configuration_guard_and_examples(self):
  with self.assertRaises(ValueError):V.fiscal_estimate(50000000000,2000000000,500000000,200000000,0,480000000)
  self.as_(5);V.fiscal_config(dict(regime='IS général',province='Kinshasa',vat_status='Assujetti',source='Textes vérifiés en test',effective='2026-01-01',reviewed_by='test',confirmed=True,is_rate='30',is_minimum='1',vat_rate='16'))
  result=V.fiscal_estimate(50000000000,2000000000,500000000,200000000,0,480000000);self.assertEqual(result['tax'],690000000);self.assertEqual(result['balance'],210000000)
  self.assertEqual(V.vat_estimate(160000000,64000000,0)['due'],96000000)
  self.assertEqual(V.vat_estimate(0,1000,2000)['credit'],3000)
 def test_version_conflict_rollback(self):
  self.as_(5)
  with db.transaction('test') as t:
   r=V.get(t,self.b);V.save(t,r,r['data'])
   with self.assertRaises(ValueError):V.save(t,r,r['data'])
 def test_readonly_user_and_immutable_movements(self):
  with self.engine.begin() as c:c.execute(db.users.update().where(db.users.c.id==6).values(role='lecteur'))
  self.as_(6)
  with self.assertRaises(ValueError):V.create_account('READ','x','USD','5212','bank')
  with db.transaction('modification interdite') as t:
   move=db.tout('movements')[0]
   with self.assertRaises(ValueError):t.maj('movements',move['id'],{'amount':1})
 def test_backup_roundtrip_includes_v7(self):
  import migration
  self.as_(5);V.configure_policy(dict(thresholds=[60,80,90,100],levels=list(V.LEVELS),max_advance_days=20));content=migration.export_json();migration.import_json(content);self.assertEqual(len(V.records('budget')),1);self.assertEqual(V.policy()['thresholds'][0],60)
 def test_legacy_bypass_blocked(self):
  with db.transaction('legacy bypass') as t:
   with self.assertRaises(ValueError):t.inserer('expenses',dict(id='old',project='p',label='legacy',amount=100,currency='USD',date='2026-10-05',category='Autre'))

class Additional(Integration):
 def test_fx_requires_explicit_rate(self):
  self.as_(5);cdf=V.create_account('CDF','Banque CDF','CDF','5212','bank');V.opening(cdf,200000,'2026-10-01','openingCDF')
  with self.assertRaises(ValueError):V.consolidated('USD',{},'2026-10-10')
  rate=V.register_rate('CDFUSD','CDF','USD','0.0005','2026-10-01');result=V.consolidated('USD',{'CDF':rate},'2026-10-10');self.assertEqual(result['total'],20000100)
 def test_delegation_limits_dates_and_revocation(self):
  self.as_(5);id_=V.delegate(6,'N1','p','USD',1000,'2026-01-01','2026-12-31','test');u=db.un('users',6)
  with db.transaction('delegation test') as t:
   self.assertTrue(V.authorized_level(u,'N1','p','USD',1000,t));self.assertFalse(V.authorized_level(u,'N1','p','USD',1001,t));self.assertFalse(V.authorized_level(u,'N1','other','USD',1000,t))
  V.revoke_delegate(id_,'fin')
  with db.transaction('revocation test') as t:self.assertFalse(V.authorized_level(u,'N1','p','USD',1000,t))
 def test_duplicate_invoice_and_insufficient_balance(self):
  i=self.op('DUP','Dépense',30000000);self.as_(3);V.invoice(i,'DUPINV','2026-10-04',30000000)
  with self.assertRaises(ValueError):V.invoice(i,'DUPINV','2026-10-04',1)
  self.as_(6)
  with self.assertRaises(ValueError):V.pay(i,self.account,30000000,'2026-10-05','INSUFF')
  self.assertEqual(self.data(i)['payments'],[])
 def op(self,ref='OP1',nature='Achat',value=1000000):
  self.as_(1);i=V.create_operation(ref,'p','MAT','f','Matériaux',nature,value,'2026-10-30','602');V.submit(i)
  for uid in (2,3,4,5):self.as_(uid);V.approve(i,'contrôlé',exception=uid==5 and value>=10000000)
  return i

if __name__=='__main__':unittest.main()
