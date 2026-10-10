"""Circuit du mémo : budget, achats, avances, trésorerie, écritures et contrôles.

Montants entiers en centimes. Les paramètres fiscaux ne sont actifs qu'après validation.
Une opération est la source unique des coûts et paiements. Les projections historiques
restent distinctes : aucun ancien mouvement n'est converti en charge automatiquement.
"""
from __future__ import annotations
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
import datetime as dt
import calendar
import sqlalchemy as sa
import auth
import db
import regles as R

LEVELS = ('N1', 'N2', 'N3', 'DG')
KINDS = ('budget', 'operation', 'account', 'entry', 'reconciliation', 'fiscal', 'rate', 'delegation', 'invoice', 'payment', 'carryover')
CHART = {'101':'Capital social','16':'Emprunts','23':'Bâtiments','24':'Matériel et mobilier',
 '28':'Amortissements','32':'Matières premières','4011':'Fournisseurs','4013':'Sous-traitants',
 '4017':'Retenues de garantie fournisseurs','4091':'Avances fournisseurs','411':'Clients',
 '4117':'Retenues de garantie clients','4191':'Avances clients','421':'Avances personnel',
 '422':'Rémunérations dues','43':'Organismes sociaux','441':'Impôt sur le résultat',
 '443':'TVA facturée','444':'TVA due ou crédit','445':'TVA récupérable','447':'Retenues à la source',
 '52':'Banques','57':'Caisse','581':'Régies d’avance','585':'Virements de fonds',
 '602':'Achats de matières','605':'Autres achats','6058':'Travaux achetés','61':'Transport',
 '622':'Locations','624':'Entretien','632':'Honoraires','64':'Impôts et taxes','66':'Personnel',
 '67':'Frais financiers','68':'Amortissements','69':'Provisions','705':'Travaux facturés',
 '706':'Services vendus','89':'Impôts sur le résultat'}
DEFAULT_POLICY = {'thresholds':[70,85,95,100], 'levels':list(LEVELS), 'max_advance_days':30}

def actor(roles=None):
    u=auth.utilisateur() or {};fresh=db.un('users',u.get('id')) if u.get('id') else None
    if not fresh or not fresh.get('actif') or fresh.get('doit_changer_mdp'):
        raise ValueError('Une session active avec mot de passe personnel est requise.')
    if roles and fresh['role'] not in roles:raise ValueError('Votre rôle ne permet pas cette action.')
    return fresh

def amount(v, positive=False):
    if type(v) is not int or v<0 or v>10**14 or (positive and v==0):raise ValueError('Montant invalide en centimes.')
    return v

def date(v):
    if not R.is_date(v):raise ValueError('Date invalide.')
    return v

def records(kind=None, tx=None):
    table=db.TABLES['v7_records'];q=sa.select(table)
    if kind:q=q.where(table.c.kind==kind)
    if tx:return [dict(r._mapping) for r in tx.cx.execute(q)]
    with db.moteur().connect() as c:return [dict(r._mapping) for r in c.execute(q)]

def get(tx, id_,kind=None):
    row=tx.get('v7_records',id_,verrou=True)
    if not row or (kind and row['kind']!=kind):raise ValueError('Enregistrement introuvable.')
    return row

def save(tx,row,data):
    table=db.TABLES['v7_records']
    res=tx.cx.execute(table.update().where(table.c.id==row['id'],table.c.version==row['version']).values(data=data,version=row['version']+1))
    if res.rowcount!=1:raise ValueError('Une autre personne a modifié cette opération. Actualisez.')
    tx._auditer('Modification','v7_records',row['id'],row,{**row,'data':data,'version':row['version']+1})

def insert(tx,kind,ref,project,currency,data):
    if kind not in KINDS or not ref.strip() or len(ref)>200 or currency not in R.CURRENCIES:raise ValueError('Référence ou devise invalide.')
    if any(r['kind']==kind and r['ref'].casefold()==ref.strip().casefold() for r in records(tx=tx)):raise ValueError('Référence déjà utilisée.')
    id_=db.nouvel_id();tx.inserer('v7_records',dict(id=id_,kind=kind,ref=ref.strip().upper(),project=project,currency=currency,data=data,version=1));return id_

def event(data,u,action,note=''):
    data.setdefault('history',[]).append(dict(user=u['id'],name=u['nom'],action=action,note=note,at=db.maintenant().isoformat()))

def policy(tx=None):
    """Seuils de contrôle ; lus dans la transaction en cours si elle est fournie (pas de seconde connexion)."""
    if tx is not None:
        v=tx.cx.execute(sa.select(db.settings.c.valeur).where(db.settings.c.cle=='v7_policy')).scalar()
        return v or deepcopy(DEFAULT_POLICY)
    return db.parametre('v7_policy') or deepcopy(DEFAULT_POLICY)

def configure_policy(data):
    actor(['admin']);thresholds=data.get('thresholds');levels=data.get('levels')
    if not thresholds or len(thresholds)!=4 or not all(isinstance(v,(int,float)) and 0<v<=100 for v in thresholds) or thresholds!=sorted(set(thresholds)) or thresholds[-1]!=100:
        raise ValueError('Quatre seuils croissants, dernier seuil 100 %, requis.')
    if levels!=list(LEVELS):raise ValueError('Le circuit doit conserver N1 N2 N3 DG.')
    if not 1<=int(data.get('max_advance_days',0))<=365:raise ValueError('Délai de régularisation invalide.')
    with db.transaction('Configuration du contrôle V7') as t:t.parametre('v7_policy',data)

def create_account(ref,label,currency,ledger,legacy):
    u=actor(['admin','finance'])
    with db.transaction('Compte de trésorerie V7') as t:return _create_account_tx(t,u,ref,label,currency,ledger,legacy)

def _create_account_tx(t,u,ref,label,currency,ledger,legacy,extra=None):
    """Création d'un compte dans une transaction existante (saisie ou import)."""
    if legacy not in R.CASH_ACCOUNTS or not ledger.startswith(('52','57')):raise ValueError('Compte bancaire ou caisse et rattachement historique requis.')
    if any(r['currency']==currency and r['data']['ledger']==ledger for r in records('account',t)):
        raise ValueError('Utilisez une subdivision comptable distincte par compte et devise.')
    return insert(t,'account',ref,'',currency,dict(label=label,ledger=ledger,legacy=legacy,creator=u['id'],**(extra or {})))

def create_budget(project,code,lines,contract,forecast,revenue=None):
    u=actor(['admin','finance','chantier'])
    with db.transaction('Budget DQE à approuver') as t:return _create_budget_tx(t,u,project,code,lines,contract,forecast,revenue)

def active_budgets(rows):
    """Budgets non rejetés (un budget importé puis rejeté reste conservé mais n'a plus d'effet)."""
    return [r for r in rows if r['data'].get('status')!='Rejeté']

def _create_budget_tx(t,u,project,code,lines,contract,forecast,revenue=None,extra=None):
    p=t.get('projects',project)
    if not p:raise ValueError('Choisissez un chantier existant.')
    if not code.strip() or not lines:raise ValueError('Code chantier et postes DQE requis.')
    seen=set()
    for line in lines:
        if not line.get('code') or line['code'] in seen or not line.get('label'):raise ValueError('Postes DQE manquants ou en double.')
        seen.add(line['code']);amount(line['budget']);amount(line.get('forecast',line['budget']))
    amount(contract);amount(forecast);amount(contract if revenue is None else revenue)
    if any(r['project']==project for r in active_budgets(records('budget',t))):raise ValueError('Ce chantier possède déjà un budget V7.')
    data=dict(code=code,lines=lines,contract=contract,forecast=forecast,revenue=contract if revenue is None else revenue,
              initial=sum(x.get('initial',x['budget']) for x in lines),status='À approuver',creator=u['id'],history=[],revision=1,**(extra or {}))
    event(data,u,'Création budget'+(' (import '+extra['import_lot_ref']+')' if extra and extra.get('import_lot_ref') else ''))
    return insert(t,'budget',code,project,p['currency'],data)

def approve_budget(id_,reason):
    u=actor(['admin'])
    with db.transaction('Approbation du budget DQE') as t:_approve_budget_tx(t,u,id_,reason)

def _approve_budget_tx(t,u,id_,reason):
    r=get(t,id_,'budget');d=deepcopy(r['data'])
    if d['creator']==u['id']:raise ValueError('La DG ne peut pas approuver son propre budget.')
    if not reason.strip():raise ValueError('Motif obligatoire.')
    if d['status']=='Approuvé':raise ValueError('Budget déjà approuvé.')
    if d['status']=='Rejeté':raise ValueError('Budget rejeté : importez un lot corrigé.')
    d['status']='Approuvé';event(d,u,'Approbation DG',reason);save(t,r,d)

def revise_budget(id_,lines,forecast,revenue,reason):
    u=actor(['finance','chantier','admin'])
    with db.transaction('Proposition de révision budgétaire') as t:
        r=get(t,id_,'budget');d=deepcopy(r['data'])
        if d['status']!='Approuvé':raise ValueError('Approuvez la révision en attente avant une nouvelle modification.')
        if not reason.strip() or {x['code'] for x in lines}!={x['code'] for x in d['lines']}:raise ValueError('Motif et mêmes postes DQE requis.')
        for line in lines:amount(line['budget']);amount(line['forecast'])
        amount(forecast);amount(revenue)
        d['pending']=dict(lines=lines,forecast=forecast,revenue=revenue,creator=u['id']);event(d,u,'Révision proposée',reason);save(t,r,d)

def approve_revision(id_,reason):
    u=actor(['admin'])
    with db.transaction('Révision budgétaire autorisée') as t:
        r=get(t,id_,'budget');d=deepcopy(r['data']);p=d.get('pending')
        if not p or p['creator']==u['id'] or not reason.strip():raise ValueError('Révision indépendante et motif requis.')
        d.update({k:p[k] for k in ('lines','forecast','revenue')});d.pop('pending');d['revision']+=1;event(d,u,'Révision approuvée DG',reason);save(t,r,d)

def carry_effects(c):
    """Effets d'un reliquat de reprise approuvé : comptés une seule fois, sans créer de faux paiement."""
    d=c['data'];kind=d['type'];paid=sum(p['amount'] for p in d.get('payments',[]) if not p.get('reversed'))
    returned=sum(p['amount'] for p in d.get('returns',[]));justified=sum(j['amount'] for j in d.get('justifications',[]) if j['status']=='Validée')
    if kind=='cost':return dict(cost=d['amount'],open=0,cash=0,advance=0)
    if kind=='commitment':return dict(cost=0,open=0 if d['status']=='Soldée' else d['amount'],cash=0,advance=0)
    if kind=='debt':return dict(cost=0,open=0,cash=paid,advance=0)
    if kind=='advance':return dict(cost=justified,open=0,cash=-returned,advance=max(0,d['amount']-justified-returned))
    return dict(cost=0,open=0,cash=0,advance=0)

def metrics(budget,ops,carry=None,tx=None):
    d=budget['data'];active=[r for r in ops if r['project']==budget['project'] and r['currency']==budget['currency'] and r['data'].get('status')!='Annulée']
    carry=records('carryover',tx) if carry is None else carry
    carry=[c for c in carry if c['project']==budget['project'] and c['currency']==budget['currency'] and c['data']['status'] in ('Approuvée','Soldée')]
    out=[];thresholds=policy(tx)['thresholds']
    for line in d['lines']:
        selected=[r['data'] for r in active if r['data']['post']==line['code']]
        effects=[carry_effects(c) for c in carry if c['data'].get('post')==line['code']]
        realized=sum(x.get('cost',0) for x in selected)+sum(e['cost'] for e in effects)
        opened=sum(max(0,x['amount']-x.get('cost',0)) for x in selected if x['status'] in ('Approuvée','Commandée','Réceptionnée','Facturée','Partiellement payée','Payée'))+sum(e['open'] for e in effects)
        cash=sum(sum(p['amount'] for p in x.get('payments',[]) if not p.get('reversed'))-sum(p['amount'] for p in x.get('returns',[])) for x in selected)+sum(e['cash'] for e in effects)
        advance=sum(max(0,sum(p['amount'] for p in x.get('payments',[]) if not p.get('reversed'))-sum(j['amount'] for j in x.get('justifications',[]) if j['status']=='Validée')-sum(p['amount'] for p in x.get('returns',[]))) for x in selected if x['nature']=='Avance')+sum(e['advance'] for e in effects)
        committed=opened+realized;rate=100*committed/line['budget'] if line['budget'] else (100 if committed else 0)
        alert=next((label for threshold,label in reversed(list(zip(thresholds,['Information','Vigilance','Critique','Blocage']))) if rate>=threshold),'Normal')
        out.append(dict(code=line['code'],label=line['label'],budget=line['budget'],open=opened,cost=realized,cash=cash,advance=advance,available=line['budget']-committed,engagement_rate=rate,alert=alert,forecast=line.get('forecast',line['budget'])))
    return dict(lines=out,budget=sum(x['budget'] for x in out),open=sum(x['open'] for x in out),cost=sum(x['cost'] for x in out),cash=sum(x['cash'] for x in out),advance=sum(x['advance'] for x in out),available=sum(x['available'] for x in out),forecast=d['forecast'],variance=sum(x['budget'] for x in out)-d['forecast'],margin=d['contract']-sum(x['budget'] for x in out),final_margin=d['revenue']-d['forecast'])

def budget_for(project,tx):
    rows=[r for r in active_budgets(records('budget',tx)) if r['project']==project]
    if not rows or rows[0]['data']['status']!='Approuvé':raise ValueError('Budget DQE approuvé requis.')
    return get(tx,rows[0]['id'],'budget')

def create_operation(ref,project,post,party,label,nature,value,due,expense_account='605',currency=None):
    u=actor(['admin','finance','chantier'])
    with db.transaction('Demande N0 V7') as t:return _create_operation_tx(t,u,ref,project,post,party,label,nature,value,due,expense_account,currency)

def _create_operation_tx(t,u,ref,project,post,party,label,nature,value,due,expense_account='605',currency=None,extra=None):
    """Demande N0 dans une transaction existante (saisie ou import) : toujours en brouillon, sans validation."""
    amount(value,True);date(due)
    if nature not in ('Achat','Dépense','Avance'):raise ValueError('Nature invalide.')
    if not label.strip() or not party or not t.get('clients',party):raise ValueError('Objet et bénéficiaire enregistré requis.')
    if expense_account not in CHART or not expense_account.startswith(('6','2','3')):raise ValueError('Compte de coût ou actif à valider.')
    b=budget_for(project,t)
    if currency and currency!=b['currency']:raise ValueError('Convertissez explicitement dans la devise du budget ; aucune conversion implicite.')
    if post not in {x['code'] for x in b['data']['lines']}:raise ValueError('Poste DQE requis.')
    d=dict(post=post,party=party,label=label,nature=nature,amount=value,due=due,expense_account=expense_account,
           status='Brouillon',creator=u['id'],level=0,approvals=[],payments=[],cost=0,history=[],justifications=[],returns=[],**(extra or {}))
    event(d,u,'Création N0'+(' (import '+extra['import_lot_ref']+')' if extra and extra.get('import_lot_ref') else ''))
    return insert(t,'operation',ref,project,b['currency'],d)

def edit_operation(id_,value,label,due):
    u=actor(['admin','finance','chantier']);amount(value,True);date(due)
    with db.transaction('Modification et nouvelle validation V7') as t:
        r=get(t,id_,'operation');d=deepcopy(r['data'])
        if u['id']!=d['creator'] and u['role']!='admin':raise ValueError('Seul le créateur ou la DG peut modifier.')
        if d.get('payments') or d.get('cost') or d.get('order'):raise ValueError('Opération exécutée : annulation ou nouvelle demande requise.')
        d.update(amount=value,label=label,due=due,status='Brouillon',level=0,approvals=[]);d.pop('exception',None);event(d,u,'Modification réinitialise validations');save(t,r,d)

def submit(id_):
    u=actor(['admin','finance','chantier'])
    with db.transaction('Soumission V7') as t:
        r=get(t,id_,'operation');d=deepcopy(r['data'])
        if d['status']!='Brouillon' or d['creator']!=u['id']:raise ValueError('Seul le créateur soumet son brouillon.')
        d.update(status='Soumise',level=0);event(d,u,'Soumission N1');save(t,r,d)

def authorized_level(u,level,project,currency,value,tx):
    base={'N1':('chantier','admin'),'N2':('finance','admin'),'N3':('finance','admin'),'DG':('admin',)}
    if u['role'] in base[level]:return True
    today=R.today()
    return any(r['data']['user']==u['id'] and r['data']['level']==level and r['currency']==currency and
               r['project'] in ('',project) and r['data']['start']<=today<=r['data']['end'] and value<=r['data']['limit'] and not r['data'].get('revoked') for r in records('delegation',tx))

def delegate(user,level,project,currency,limit,start,end,reason):
    u=actor(['admin']);target=db.un('users',user);date(start);date(end);amount(limit,True)
    if not target or not target['actif'] or target['role'] not in ('finance','chantier','admin') or level not in LEVELS or start>end or not reason.strip():raise ValueError('Délégation invalide.')
    with db.transaction('Délégation limitée V7') as t:return insert(t,'delegation',db.nouvel_id(),project,currency,dict(user=user,level=level,limit=limit,start=start,end=end,reason=reason,issuer=u['id']))

def revoke_delegate(id_,reason):
    u=actor(['admin'])
    with db.transaction('Révocation délégation') as t:
        r=get(t,id_,'delegation');d=deepcopy(r['data'])
        if not reason.strip():raise ValueError('Motif requis.')
        d['revoked']=True;event(d,u,'Révocation',reason);save(t,r,d)

def approve(id_,reason,exception=False,reject=False):
    u=actor(['admin','finance','chantier','rh'])
    with db.transaction('Validation V7') as t:
        r=get(t,id_,'operation');d=deepcopy(r['data'])
        if d['status']!='Soumise' or d['level']>=4:raise ValueError('Aucune validation en attente.')
        level=LEVELS[d['level']]
        if not authorized_level(u,level,r['project'],r['currency'],d['amount'],t):raise ValueError('Niveau ou délégation non autorisé.')
        if u['id']==d['creator'] or any(a['user']==u['id'] for a in d['approvals']):raise ValueError('Séparation des responsabilités : un autre validateur est requis à chaque niveau.')
        if not reason.strip():raise ValueError('Commentaire de contrôle obligatoire.')
        if reject:
            d.update(status='Brouillon',level=0,approvals=[]);event(d,u,'Rejet '+level,reason);save(t,r,d);return
        b=budget_for(r['project'],t);m=metrics(b,records('operation',t),tx=t);line=next(x for x in m['lines'] if x['code']==d['post'])
        if level=='DG' and line['available']<=d['amount'] and not exception:raise ValueError('Seuil 100 % atteint : dérogation DG explicite requise.')
        if exception and level!='DG':raise ValueError('Seule la DG autorise le dépassement.')
        d['approvals'].append(dict(user=u['id'],level=level,at=db.maintenant().isoformat(),reason=reason));d['level']+=1
        if level=='DG':
            d['status']='Approuvée';d['exception']=exception
            # Serialize budget decisions as well as individual operation decisions.
            bd=deepcopy(b['data']);bd['control_version']=bd.get('control_version',0)+1;save(t,b,bd)
        event(d,u,'Approbation '+level,reason);save(t,r,d)

def order(id_,ref,date_):
    u=actor(['admin','finance']);date(date_)
    with db.transaction('Bon de commande V7') as t:
        r=get(t,id_,'operation');d=deepcopy(r['data'])
        if d['status']!='Approuvée' or not ref.strip():raise ValueError('Approbation complète et référence de commande requises.')
        d.update(order=dict(ref=ref,date=date_,user=u['id']),status='Commandée');event(d,u,'Commande',ref);save(t,r,d)

def receive(id_,ref,date_,accepted):
    u=actor(['admin','chantier']);date(date_);amount(accepted,True)
    with db.transaction('Réception V7') as t:
        r=get(t,id_,'operation');d=deepcopy(r['data'])
        if d['status'] not in ('Commandée','Réceptionnée','Facturée','Partiellement payée') or not ref.strip():raise ValueError('Commande et bon de réception requis.')
        if any(x['ref'].strip().casefold()==ref.strip().casefold() for x in d.get('receipts',[])):raise ValueError('Bon de réception déjà utilisé.')
        if accepted+sum(x['amount'] for x in d.get('receipts',[]))>d['amount']:raise ValueError('Réception supérieure à la commande.')
        d.setdefault('receipts',[]).append(dict(ref=ref,date=date_,amount=accepted,user=u['id']));d['status']='Partiellement payée' if any(not p.get('reversed') for p in d['payments']) else ('Facturée' if d.get('invoices') else 'Réceptionnée');event(d,u,'Réception',ref);save(t,r,d)

def _entry(tx,source,project,currency,date_,label,debit,credit,value):
    amount(value,True);date(date_)
    if debit==credit:raise ValueError('Les deux comptes doivent être distincts.')
    return insert(tx,'entry',source,project,currency,dict(date=date_,label=label,lines=[dict(account=debit,debit=value,credit=0),dict(account=credit,debit=0,credit=value)]))

def invoice(id_,ref,date_,value):
    u=actor(['admin','finance']);date(date_);amount(value,True)
    with db.transaction('Facture et charge V7') as t:
        r=get(t,id_,'operation');d=deepcopy(r['data'])
        if d['nature']=='Avance' or d['status'] not in ('Approuvée','Commandée','Réceptionnée','Facturée','Partiellement payée'):raise ValueError('Opération non facturable.')
        if d['nature']=='Achat' and sum(x['amount'] for x in d.get('receipts',[]))<d['cost']+value:raise ValueError('Réception acceptée insuffisante pour cette facture.')
        if d['cost']+value>d['amount']:raise ValueError('Facture supérieure à l’engagement : nouvelle validation requise.')
        invs=[i for op in records('operation',t) for i in op['data'].get('invoices',[]) if op['data']['party']==d['party']]
        if not ref.strip() or any(i['ref'].strip().casefold()==ref.strip().casefold() for i in invs):raise ValueError('Facture fournisseur absente ou déjà enregistrée.')
        insert(t,'invoice',d['party']+':'+ref,r['project'],r['currency'],dict(operation=r['id'],ref=ref,date=date_,amount=value))
        d.setdefault('invoices',[]).append(dict(ref=ref,date=date_,amount=value));d['cost']+=value;d['status']='Facturée'
        _entry(t,'invoice:'+r['id']+':'+ref,r['project'],r['currency'],date_,d['label'],d['expense_account'],'4011',value)
        event(d,u,'Facture comptabilisée',ref);save(t,r,d)

def table_rows(tx,name):
    return [dict(r._mapping) for r in tx.cx.execute(sa.select(db.TABLES[name]))]

def balance(account,tx=None):
    total=0
    rows=table_rows(tx,'movements') if tx else db.tout('movements')
    for m in rows:
        if (m.get('journal') or {}).get('v7_account')==account['id']:total+=m['amount']*(1 if m['direction']=='in' else -1)
    return total

def _move(t,a,source,project,date_,value,direction,label):
    t.inserer('movements',dict(id=db.nouvel_id(),kind='v7',date=date_,account=a['data']['legacy'],label=label,direction=direction,amount=value,currency=a['currency'],project=project,journal=dict(v7_account=a['id'],v7_source=source),cree_le=db.maintenant()))

def _touch_account(t,a):
    d=deepcopy(a['data']);d['sequence']=d.get('sequence',0)+1;save(t,a,d)

def opening(account,value,date_,ref):
    u=actor(['admin','finance']);amount(value,True);date(date_)
    with db.transaction('Solde initial V7') as t:_opening_tx(t,account,value,date_,ref)

def _opening_tx(t,account,value,date_,ref,strict=False):
    amount(value,True);date(date_)
    a=get(t,account,'account');moved=any((m.get('journal') or {}).get('v7_account')==account for m in table_rows(t,'movements'))
    if moved and (strict or records('operation',t)):raise ValueError('Utilisez un ajustement documenté pour un compte déjà mouvementé.')
    _touch_account(t,a);_move(t,a,'opening:'+ref,'',date_,value,'in','Solde initial '+ref)
    _entry(t,'opening:'+account,'',a['currency'],date_,'Solde initial',a['data']['ledger'],'12',value)

def pay(id_,account,value,date_,reference):
    u=actor(['admin','finance']);amount(value,True);date(date_)
    with db.transaction('Paiement partiel V7') as t:
        r=get(t,id_,'operation');d=deepcopy(r['data']);a=get(t,account,'account')
        if d['status'] not in ('Approuvée','Commandée','Réceptionnée','Facturée','Partiellement payée','Payée'):raise ValueError('Circuit de validation incomplet.')
        if u['id']==d['creator'] or any(x['user']==u['id'] for x in d['approvals']):raise ValueError('Le trésorier doit être distinct du créateur et des validateurs.')
        if a['currency']!=r['currency']:raise ValueError('Devise différente : conversion explicite nécessaire.')
        paid=sum(p['amount'] for p in d['payments'] if not p.get('reversed'))
        limit=d['amount'] if d['nature']=='Avance' else d['cost']
        if paid+value>limit:raise ValueError('Paiement supérieur au montant dû ou à l’avance autorisée.')
        if not reference.strip() or any(p['ref']==reference for op in records('operation',t) for p in op['data'].get('payments',[])):raise ValueError('Référence de règlement vide ou déjà utilisée.')
        if balance(a,t)<value:raise ValueError('Solde insuffisant sur le compte.')
        insert(t,'payment',reference,r['project'],r['currency'],dict(operation=r['id'],account=account,amount=value,date=date_))
        _touch_account(t,a);pid=db.nouvel_id();d['payments'].append(dict(id=pid,ref=reference,amount=value,date=date_,account=account,user=u['id']))
        _move(t,a,pid,r['project'],date_,value,'out',r['ref']+' '+reference)
        _entry(t,'pay:'+pid,r['project'],r['currency'],date_,d['label'],'581' if d['nature']=='Avance' else '4011',a['data']['ledger'],value)
        d['status']='Payée' if paid+value==d['amount'] else 'Partiellement payée';event(d,u,'Paiement',reference);save(t,r,d)

def reverse_payment(id_,pid,date_,reason):
    u=actor(['admin','finance']);date(date_)
    with db.transaction('Contre-passation V7') as t:
        r=get(t,id_,'operation');d=deepcopy(r['data']);p=next((x for x in d['payments'] if x['id']==pid),None)
        if not p or p.get('reversed') or not reason.strip() or date_<p['date']:raise ValueError('Contre-passation invalide.')
        if d['nature']=='Avance' and (d.get('returns') or any(j['status']=='Validée' for j in d['justifications'])):raise ValueError('Avance déjà régularisée : contre-passation spécifique nécessaire.')
        a=get(t,p['account'],'account');_touch_account(t,a);p['reversed']=True
        _move(t,a,'reverse:'+pid,r['project'],date_,p['amount'],'in','Contre-passation '+reason)
        _entry(t,'reverse:'+pid,r['project'],r['currency'],date_,reason,a['data']['ledger'],'581' if d['nature']=='Avance' else '4011',p['amount'])
        d['status']='Partiellement payée' if any(not x.get('reversed') for x in d['payments']) else ('Approuvée' if d['nature']=='Avance' else 'Facturée');event(d,u,'Contre-passation',reason);save(t,r,d)

def justification(id_,piece):
    u=actor(['admin','finance','chantier']);p=db.un('pieces',piece)
    if not p or p['uploaded_by']!=u['id']:raise ValueError('Choisissez un justificatif que vous avez déposé.')
    with db.transaction('Pièce associée V7') as t:
        r=get(t,id_,'operation');d=deepcopy(r['data'])
        if d['status']=='Annulée' or p['currency']!=r['currency'] or p['expense_id']:raise ValueError('Pièce déjà liée ou de devise différente.')
        if any(j['piece']==piece for op in records('operation',t) for j in op['data'].get('justifications',[])):raise ValueError('Pièce déjà utilisée dans une opération.')
        d['justifications'].append(dict(piece=piece,amount=p['amount'],status='Soumise',uploader=u['id']));event(d,u,'Justificatif associé',p['name']);save(t,r,d)

def validate_justification(id_,piece,accept,reason):
    u=actor(['admin','finance'])
    with db.transaction('Contrôle de justificatif V7') as t:
        r=get(t,id_,'operation');d=deepcopy(r['data']);j=next((x for x in d['justifications'] if x['piece']==piece),None);p=t.get('pieces',piece,True)
        if not j or j['status']!='Soumise' or u['id'] in (j['uploader'],d['creator']) or not reason.strip():raise ValueError('Contrôle indépendant avec motif requis.')
        if accept and d['nature']!='Avance' and sum(x['amount'] for x in d['justifications'] if x['status']=='Validée')+j['amount']>d['amount']:
            raise ValueError('Justificatifs supérieurs au montant de l’opération.')
        if d['nature']=='Avance' and accept:
            paid=sum(x['amount'] for x in d['payments'] if not x.get('reversed'))
            used=sum(x['amount'] for x in d['justifications'] if x['status']=='Validée')+sum(x['amount'] for x in d['returns'])
            if used+j['amount']>paid:raise ValueError('Justificatifs supérieurs aux fonds à régulariser.')
            d['cost']+=j['amount'];_entry(t,'justify:'+piece,r['project'],r['currency'],p['document_date'],d['label'],d['expense_account'],'581',j['amount'])
        j['status']='Validée' if accept else 'Rejetée';j['validator']=u['id'];j['reason']=reason
        t.maj('pieces',piece,dict(status=j['status'],validated_by=u['id'],validated_at=db.maintenant(),reason=reason));event(d,u,'Contrôle justificatif',reason);save(t,r,d)

def return_advance(id_,account,value,date_,reference):
    u=actor(['admin','finance']);amount(value,True);date(date_)
    with db.transaction('Restitution avance V7') as t:
        r=get(t,id_,'operation');d=deepcopy(r['data']);a=get(t,account,'account')
        if d['nature']!='Avance' or a['currency']!=r['currency']:raise ValueError('Avance et devise concordante requises.')
        available=sum(x['amount'] for x in d['payments'] if not x.get('reversed'))-sum(x['amount'] for x in d['justifications'] if x['status']=='Validée')-sum(x['amount'] for x in d['returns'])
        if value>available or not reference.strip():raise ValueError('Restitution supérieure au solde ou référence absente.')
        _touch_account(t,a);rid=db.nouvel_id();d['returns'].append(dict(id=rid,amount=value,date=date_,ref=reference))
        _move(t,a,rid,r['project'],date_,value,'in','Restitution '+reference);_entry(t,'return:'+rid,r['project'],r['currency'],date_,d['label'],a['data']['ledger'],'581',value);event(d,u,'Restitution',reference);save(t,r,d)

def transfer(source,target,value,date_,reference):
    actor(['admin','finance']);amount(value,True);date(date_)
    with db.transaction('Transfert interne V7') as t:
        if source==target:raise ValueError('Deux comptes distincts requis.')
        # Stable lock order prevents transfer deadlocks.
        accounts={i:get(t,i,'account') for i in sorted([source,target])};a,b=accounts[source],accounts[target]
        if a['currency']!=b['currency']:raise ValueError('Transfert sans change : devises identiques requises.')
        if balance(a,t)<value:raise ValueError('Solde insuffisant.')
        _touch_account(t,a);_touch_account(t,b)
        _entry(t,'transfer:'+reference,'',a['currency'],date_,'Transfert '+reference,b['data']['ledger'],a['data']['ledger'],value)
        _move(t,a,'transfer:'+reference,'',date_,value,'out','Transfert '+reference);_move(t,b,'transfer:'+reference,'',date_,value,'in','Transfert '+reference)

def cancel(id_,reason):
    u=actor(['admin','finance','chantier'])
    with db.transaction('Annulation conservée V7') as t:
        r=get(t,id_,'operation');d=deepcopy(r['data'])
        if d.get('cost') or any(not p.get('reversed') for p in d['payments']) or not reason.strip():raise ValueError('Contrepassez les paiements ; une charge comptabilisée ne peut pas être effacée.')
        if d['creator']!=u['id'] and u['role']!='admin':raise ValueError('Créateur ou DG requis.')
        d['status']='Annulée';event(d,u,'Annulation',reason);save(t,r,d)

def reconcile(account,date_,statement,matched,reference):
    u=actor(['admin','finance']);date(date_)
    if type(statement) is not int:raise ValueError('Solde du relevé invalide.')
    with db.transaction('Rapprochement bancaire V7') as t:
        a=get(t,account,'account');moves=[m for m in table_rows(t,'movements') if (m.get('journal') or {}).get('v7_account')==account and m['date']<=date_]
        ids={m['id'] for m in moves}
        if not set(matched)<=ids:raise ValueError('Mouvement hors compte ou hors période.')
        book=sum(m['amount']*(1 if m['direction']=='in' else -1) for m in moves)
        uncleared=sum(m['amount']*(1 if m['direction']=='in' else -1) for m in moves if m['id'] not in matched)
        return insert(t,'reconciliation',reference,'',a['currency'],dict(account=account,date=date_,statement=statement,book=book,matched=matched,uncleared=uncleared,difference=book-statement-uncleared,user=u['id']))

def ledger():
    result={}
    for r in records('entry'):
        for line in r['data']['lines']:
            key=(r['currency'],line['account']);a=result.setdefault(key,dict(currency=key[0],account=key[1],debit=0,credit=0))
            a['debit']+=line['debit'];a['credit']+=line['credit']
    return [{**a,'balance':a['debit']-a['credit']} for a in result.values()]

def register_rate(ref,source,target,value,date_):
    actor(['admin','finance']);date(date_);v=Decimal(str(value))
    if source not in R.CURRENCIES or target not in R.CURRENCIES or source==target or not v.is_finite() or v<=0:raise ValueError('Taux invalide.')
    with db.transaction('Taux historique V7') as t:return insert(t,'rate',ref,'',source,dict(target=target,rate=str(v),date=date_))

def converted(value,rate):return int((Decimal(value)*Decimal(str(rate))).quantize(Decimal('1'),rounding=ROUND_HALF_UP))

def fiscal_config(data):
    u=actor(['admin']);required=('regime','province','vat_status','source','effective','reviewed_by')
    if any(not str(data.get(k,'')).strip() for k in required):raise ValueError('Fiche fiscale et référence de validation incomplètes.')
    date(data['effective'])
    if data['vat_status'] not in ('Assujetti','Non assujetti','À vérifier'):raise ValueError('Statut TVA invalide.')
    for k in ('is_rate','is_minimum','vat_rate'):
        v=Decimal(str(data[k]))
        if not v.is_finite() or not 0<=v<=100:raise ValueError('Taux fiscal invalide.')
    data={**data,'approved_by':u['id'],'approved_at':db.maintenant().isoformat()}
    with db.transaction('Validation paramètres fiscaux RDC') as t:t.parametre('v7_fiscal',data)

def fiscal_estimate(turnover,profit,addbacks,deductions,credits,advances):
    conf=db.parametre('v7_fiscal')
    if not conf or not conf.get('confirmed') or conf['effective']>R.today():raise ValueError('Paramètres fiscaux vérifiés et applicables requis.')
    for v in (turnover,addbacks,deductions,credits,advances):amount(v)
    if type(profit) is not int:raise ValueError('Résultat comptable invalide.')
    taxable=profit+addbacks-deductions;calculated=converted(max(0,taxable),Decimal(str(conf['is_rate']))/100)
    minimum=converted(turnover,Decimal(str(conf['is_minimum']))/100)
    tax=max(calculated,minimum);return dict(taxable=taxable,calculated=calculated,minimum=minimum,tax=tax,balance=tax-credits-advances,config=conf)

def vat_estimate(collected,deductible,credit):
    c=db.parametre('v7_fiscal')
    if not c or not c.get('confirmed') or c['vat_status']!='Assujetti':raise ValueError('Assujettissement et paramètres validés requis.')
    for v in (collected,deductible,credit):amount(v)
    net=collected-deductible-credit;return dict(due=max(0,net),credit=max(0,-net))

def fiscal_calendar(year):
    rows=[]
    for month in range(1,13):
        following=dt.date(year+1,1,15) if month==12 else dt.date(year,month+1,15)
        rows.append(dict(ref=f'MENSUEL-{year}-{month:02}',period=f'{year}-{month:02}',due=following.isoformat(),label='TVA et retenues applicables à vérifier'))
    rows.extend([dict(ref=f'IS-{year}-{m}',period=str(year),due=f'{year}-{m:02}-25',label='Acompte IS à vérifier') for m in (7,9,11)])
    rows.extend([dict(ref=f'IS-SOLDE-{year}',period=str(year),due=f'{year+1}-04-30',label='Déclaration IS et solde'),dict(ref=f'CLIENTS-{year}',period=str(year),due=f'{year+1}-03-31',label='Liste clients fournisseurs selon obligation')]);return rows

def save_fiscal_due(ref,label,period,due,value,source):
    u=actor(['admin','finance']);date(due);amount(value)
    if not source.strip():raise ValueError('Référence légale ou communiqué requis.')
    with db.transaction('Échéance fiscale suivie') as t:return insert(t,'fiscal',ref,'','CDF',dict(label=label,period=period,due=due,amount=value,source=source,status='À préparer',creator=u['id']))

def fiscal_done(id_,proof):
    actor(['admin','finance'])
    if not proof.strip():raise ValueError('Preuve de dépôt ou règlement requise.')
    with db.transaction('Échéance fiscale régularisée') as t:
        r=get(t,id_,'fiscal');d=deepcopy(r['data']);d.update(status='Déposée et réglée',proof=proof);save(t,r,d)

def alerts():
    out=[];today=R.today()
    for b in active_budgets(records('budget')):
        for l in metrics(b,records('operation'))['lines']:
            if l['alert']!='Normal':out.append(dict(type='Budget',ref=b['ref']+'/'+l['code'],message=l['alert'],due=''))
    for r in records('operation'):
        d=r['data'];paid=sum(x['amount'] for x in d['payments'] if not x.get('reversed'));just=sum(x['amount'] for x in d['justifications'] if x['status']=='Validée')
        if d['status']=='Annulée':continue
        if paid>just and not (d['nature']=='Avance' and paid==just+sum(x['amount'] for x in d['returns'])):out.append(dict(type='Justificatif',ref=r['ref'],message='Fonds à justifier',due=d['due']))
        if d['due']<today and d['status']!='Payée':out.append(dict(type='Échéance',ref=r['ref'],message='Opération échue',due=d['due']))
    for r in records('fiscal'):
        d=r['data']
        if d['status']!='Déposée et réglée' and d['due']<=today:out.append(dict(type='Fiscal',ref=r['ref'],message='Échéance à régulariser',due=d['due']))
    for r in records('operation'):
        d=r['data']
        if d['nature']=='Avance' and d['status']!='Annulée':
            unresolved=sum(x['amount'] for x in d['payments'] if not x.get('reversed'))-sum(x['amount'] for x in d['justifications'] if x['status']=='Validée')-sum(x['amount'] for x in d['returns'])
            first=min((p['date'] for p in d['payments'] if not p.get('reversed')),default=None)
            if first and unresolved>0 and (dt.date.fromisoformat(today)-dt.date.fromisoformat(first)).days>policy()['max_advance_days']:
                out.append(dict(type='Avance échue',ref=r['ref'],message='Délai de régularisation dépassé',due=d['due']))
    for c in records('carryover'):
        d=c['data']
        if d['status']!='Approuvée':continue
        if d['type']=='debt' and d.get('due','9999')<today:out.append(dict(type='Dette reprise',ref=c['ref'],message='Reliquat fournisseur échu',due=d.get('due','')))
        if d['type']=='advance' and carry_effects(c)['advance']>0:out.append(dict(type='Avance reprise',ref=c['ref'],message='Reliquat d’avance à justifier ou restituer',due=d.get('due','')))
    return out

def guard_legacy(project):
    if any(r['project']==project for r in active_budgets(records('budget'))):
        raise ValueError('Chantier suivi en V7 : utilisez Circuit financier V7 pour conserver validations et imputations DQE.')

def upload_piece(id_,name,content,date_,value):
    import hashlib
    from vues.justificatifs import mime_de,nom_sur
    u=actor(['admin','finance','chantier']);amount(value,True);date(date_);mime=mime_de(content)
    if not mime or len(content)>5*1024*1024:raise ValueError('PDF JPEG ou PNG de 5 Mo maximum requis.')
    with db.transaction('Dépôt et association pièce V7') as t:
        r=get(t,id_,'operation');d=deepcopy(r['data'])
        if d['status']=='Annulée':raise ValueError('Opération annulée.')
        pid=db.nouvel_id();t.inserer('pieces',dict(id=pid,expense_id='',batch_id='',name=nom_sur(name,mime),mime=mime,content=content,size=len(content),hash=hashlib.sha256(content).hexdigest(),type='Justificatif V7',beneficiary=d['party'],document_date=date_,amount=value,currency=r['currency'],status='Préparée',reason='',uploaded_at=db.maintenant(),uploaded_by=u['id']))
        d['justifications'].append(dict(piece=pid,amount=value,status='Soumise',uploader=u['id']));event(d,u,'Dépôt justificatif',name);save(t,r,d)

def consolidated(reporting,rates_by_currency,date_):
    date(date_)
    if reporting not in R.CURRENCIES:raise ValueError('Devise de présentation invalide.')
    rates={r['id']:r for r in records('rate')};rows=[]
    for account in records('account'):
        source=account['currency'];value=balance(account)
        if source==reporting:rate='1';rate_id=''
        else:
            r=rates.get(rates_by_currency.get(source))
            if not r or r['currency']!=source or r['data']['target']!=reporting or r['data']['date']>date_:
                raise ValueError('Taux explicite daté requis pour chaque devise consolidée.')
            rate=r['data']['rate'];rate_id=r['id']
        rows.append(dict(account=account['ref'],currency=source,original=value,rate=rate,rate_id=rate_id,converted=converted(value,rate)))
    return dict(currency=reporting,total=sum(r['converted'] for r in rows),rows=rows)

# ------------------------------------------------------------------ reprises à une date de bascule
# Un reliquat repris (dette, avance, coût antérieur, engagement ouvert, solde d'ouverture, balance d'ouverture)
# est un dossier distinct, relié à son archive. Il n'a d'effet qu'après activation par la DG, personne distincte de
# l'importateur. Aucun ancien paiement n'est rejoué et aucune validation antérieure n'est recréée.
CARRY_TYPES=('cost','commitment','debt','advance','opening','entry')
CARRY_LABELS={'cost':'Coûts exécutés antérieurs','commitment':'Engagement ouvert repris','debt':'Dette fournisseur reprise',
              'advance':'Avance restant à justifier','opening':'Solde de trésorerie d’ouverture','entry':'Balance d’ouverture'}

def _carryover_tx(t,u,ref,project,currency,data):
    if data.get('type') not in CARRY_TYPES:raise ValueError('Type de reprise invalide.')
    if data['type'] not in ('entry',):amount(data['amount'],data['type'] in ('opening','debt','advance'))
    d={**data,'status':'À approuver','creator':u['id'],'approvals':[],'payments':[],'returns':[],'justifications':[],'history':[]}
    event(d,u,'Reprise préparée',data.get('lot_ref',''));return insert(t,'carryover',ref,project,currency,d)

def _cash_in_entries(tx,currency):
    return any(r['currency']==currency and any(str(l['account']).startswith(('52','57')) for l in r['data']['lines'])
               for r in records('entry',tx) if r['ref'].startswith('OPENING-BALANCE:'))

def _approve_carryover_tx(t,u,id_,reason):
    r=get(t,id_,'carryover');d=deepcopy(r['data'])
    if u['role']!='admin':raise ValueError('Activation réservée à la DG.')
    if d['creator']==u['id']:raise ValueError('La DG ne peut pas activer une reprise qu’elle a elle-même importée.')
    if d['status']!='À approuver':raise ValueError('Reprise déjà traitée.')
    if not reason.strip():raise ValueError('Motif d’activation obligatoire.')
    if d['type'] in ('cost','commitment') or (d['type'] in ('debt','advance') and d.get('post')):
        b=budget_for(r['project'],t)
        if b['currency']!=r['currency']:raise ValueError('Devise du reliquat différente du budget : aucune conversion implicite.')
        if d.get('post') and d['post'] not in {x['code'] for x in b['data']['lines']}:raise ValueError('Poste DQE absent du budget approuvé.')
    if d['type']=='opening':
        if _cash_in_entries(t,r['currency']):raise ValueError('La balance d’ouverture contient déjà la trésorerie de cette devise : double comptabilisation refusée.')
        _opening_tx(t,d['account'],d['amount'],d['date'],r['ref'],strict=True)
    if d['type']=='entry':
        lines=d['lines']
        if not lines or sum(l['debit'] for l in lines)!=sum(l['credit'] for l in lines):raise ValueError('Écriture déséquilibrée.')
        if any(str(l['account']).startswith(('52','57')) for l in lines) and any(x['ref'].startswith('OPENING:') and x['currency']==r['currency'] for x in records('entry',t)):
            raise ValueError('Des soldes de trésorerie d’ouverture existent déjà pour cette devise : double comptabilisation refusée.')
        insert(t,'entry','OPENING-BALANCE:'+r['ref'],'',r['currency'],dict(date=d['date'],label=d['label'],lines=lines,source='reprise',carryover=r['id']))
    d['status']='Approuvée';d['approvals'].append(dict(user=u['id'],level='DG',at=db.maintenant().isoformat(),reason=reason))
    event(d,u,'Activation DG',reason);save(t,r,d)

def _reject_carryover_tx(t,u,id_,reason):
    r=get(t,id_,'carryover');d=deepcopy(r['data'])
    if d['status']!='À approuver':raise ValueError('Seule une reprise non activée peut être rejetée ; sinon contre-passation contrôlée.')
    d['status']='Rejetée';event(d,u,'Rejet',reason);save(t,r,d)

def _carry_paid(d):return sum(p['amount'] for p in d.get('payments',[]) if not p.get('reversed'))

def pay_carryover(id_,account,value,date_,reference):
    """Règlement d'une dette fournisseur reprise : seul le reliquat est payable, par un trésorier indépendant."""
    u=actor(['admin','finance']);amount(value,True);date(date_)
    with db.transaction('Règlement d’un reliquat repris') as t:
        r=get(t,id_,'carryover');d=deepcopy(r['data']);a=get(t,account,'account')
        if d['type']!='debt' or d['status']!='Approuvée':raise ValueError('Dette reprise activée requise.')
        if u['id']==d['creator'] or any(x['user']==u['id'] for x in d['approvals']):raise ValueError('Le trésorier doit être distinct de l’importateur et de la DG qui a activé la reprise.')
        if a['currency']!=r['currency']:raise ValueError('Devise différente : conversion explicite nécessaire.')
        if date_<d.get('cutover',''):raise ValueError('Un paiement antérieur à la bascule appartient aux archives : il n’est pas redébité.')
        paid=_carry_paid(d)
        if paid+value>d['amount']:raise ValueError('Paiement supérieur au reliquat repris.')
        if not reference.strip() or any(p['ref']==reference for op in records('operation',t)+records('carryover',t) for p in op['data'].get('payments',[])):raise ValueError('Référence de règlement vide ou déjà utilisée.')
        if balance(a,t)<value:raise ValueError('Solde insuffisant sur le compte.')
        insert(t,'payment',reference,r['project'],r['currency'],dict(carryover=r['id'],account=account,amount=value,date=date_))
        _touch_account(t,a);pid=db.nouvel_id();d['payments'].append(dict(id=pid,ref=reference,amount=value,date=date_,account=account,user=u['id']))
        _move(t,a,pid,r['project'],date_,value,'out',r['ref']+' '+reference)
        _entry(t,'pay:'+pid,r['project'],r['currency'],date_,d['label'],'4011',a['data']['ledger'],value)
        if paid+value==d['amount']:d['status']='Soldée'
        event(d,u,'Règlement du reliquat',reference);save(t,r,d)

def upload_carryover_piece(id_,name,content,date_,value):
    import hashlib
    from vues.justificatifs import mime_de,nom_sur
    u=actor(['admin','finance','chantier']);amount(value,True);date(date_);mime=mime_de(content)
    if not mime or len(content)>5*1024*1024:raise ValueError('PDF JPEG ou PNG de 5 Mo maximum requis.')
    with db.transaction('Pièce d’une avance reprise') as t:
        r=get(t,id_,'carryover');d=deepcopy(r['data'])
        if d['type']!='advance' or d['status']!='Approuvée':raise ValueError('Avance reprise activée requise.')
        h=hashlib.sha256(content).hexdigest()
        if t.lire('select id from pieces where hash = :h',h=h):raise ValueError('Ce fichier est déjà enregistré.')
        pid=db.nouvel_id();t.inserer('pieces',dict(id=pid,expense_id='',batch_id='',name=nom_sur(name,mime),mime=mime,content=content,size=len(content),hash=h,type='Justificatif reprise',beneficiary=d.get('party',''),document_date=date_,amount=value,currency=r['currency'],status='Préparée',reason='',uploaded_at=db.maintenant(),uploaded_by=u['id']))
        d['justifications'].append(dict(piece=pid,amount=value,status='Soumise',uploader=u['id']));event(d,u,'Dépôt justificatif',name);save(t,r,d)

def validate_carryover_justification(id_,piece,accept,reason):
    u=actor(['admin','finance'])
    with db.transaction('Contrôle de justificatif repris') as t:
        r=get(t,id_,'carryover');d=deepcopy(r['data']);j=next((x for x in d['justifications'] if x['piece']==piece),None);p=t.get('pieces',piece,True)
        if not j or j['status']!='Soumise' or u['id'] in (j['uploader'],d['creator']) or not reason.strip():raise ValueError('Contrôle indépendant avec motif requis.')
        if accept:
            used=sum(x['amount'] for x in d['justifications'] if x['status']=='Validée')+sum(x['amount'] for x in d['returns'])
            if used+j['amount']>d['amount']:raise ValueError('Justificatifs supérieurs au reliquat de l’avance.')
            _entry(t,'justify:'+piece,r['project'],r['currency'],p['document_date'],d['label'],d.get('expense_account','605'),'581',j['amount'])
        j['status']='Validée' if accept else 'Rejetée';j['validator']=u['id'];j['reason']=reason
        t.maj('pieces',piece,dict(status=j['status'],validated_by=u['id'],validated_at=db.maintenant(),reason=reason))
        if carry_effects({'data':d})['advance']==0:d['status']='Soldée'
        event(d,u,'Contrôle justificatif',reason);save(t,r,d)

def return_carryover_advance(id_,account,value,date_,reference):
    u=actor(['admin','finance']);amount(value,True);date(date_)
    with db.transaction('Restitution d’une avance reprise') as t:
        r=get(t,id_,'carryover');d=deepcopy(r['data']);a=get(t,account,'account')
        if d['type']!='advance' or d['status']!='Approuvée' or a['currency']!=r['currency']:raise ValueError('Avance reprise activée et devise concordante requises.')
        if value>carry_effects({'data':d})['advance'] or not reference.strip():raise ValueError('Restitution supérieure au reliquat ou référence absente.')
        _touch_account(t,a);rid=db.nouvel_id();d['returns'].append(dict(id=rid,amount=value,date=date_,ref=reference))
        _move(t,a,rid,r['project'],date_,value,'in','Restitution '+reference);_entry(t,'return:'+rid,r['project'],r['currency'],date_,d['label'],a['data']['ledger'],'581',value)
        if carry_effects({'data':d})['advance']==0:d['status']='Soldée'
        event(d,u,'Restitution',reference);save(t,r,d)

def close_commitment(id_,reason):
    """Solde un engagement repris lorsqu'il est remplacé par une demande du circuit ou abandonné (pas de double compte)."""
    u=actor(['admin','finance'])
    if not reason.strip():raise ValueError('Motif obligatoire.')
    with db.transaction('Engagement repris soldé') as t:
        r=get(t,id_,'carryover');d=deepcopy(r['data'])
        if d['type']!='commitment' or d['status']!='Approuvée':raise ValueError('Engagement repris activé requis.')
        d['status']='Soldée';event(d,u,'Engagement soldé',reason);save(t,r,d)
