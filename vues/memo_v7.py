"""Écrans du circuit financier défini par le mémo V7."""
from pathlib import Path
import hashlib
import streamlit as st
import auth
import db
import ui
import regles as R
import gestion_v7 as V


def execute(fn,*args,**kwargs):
    try:fn(*args,**kwargs)
    except (ValueError,ArithmeticError) as e:st.error(str(e))
    except Exception as e:
        from sqlalchemy.exc import IntegrityError, OperationalError
        if isinstance(e,OperationalError):st.error('La base est occupée. Actualisez puis réessayez ; aucune action partielle ne doit être ressaisie sans vérifier son état.')
        elif isinstance(e,IntegrityError):st.error('Référence déjà utilisée ou données incompatibles. Actualisez et vérifiez la saisie.')
        else:raise
    else:st.success('Enregistrement effectué.');st.rerun()

def money_input(label,key,value=0):return R.cents(st.text_input(label,R.plain(value),key=key))
def select_records(label,rows,key):
    if not rows:st.info('Aucun enregistrement disponible.');return None
    return next(r for r in rows if r['id']==st.selectbox(label,[r['id'] for r in rows],format_func=lambda i:next(r['ref'] for r in rows if r['id']==i),key=key))
def table(rows):
    if rows:st.dataframe(rows,hide_index=True,width='stretch')

def budget_tab():
    budgets=V.records('budget');ops=V.records('operation');projects=db.tout('projects')
    if auth.modifie('chantiers') or auth.modifie('comptabilite'):
        with st.expander('Créer un budget DQE'):
            if not projects:st.info('Créez d’abord un chantier.');return
            with st.form('v7_new_budget'):
                pid=st.selectbox('Chantier',[p['id'] for p in projects],format_func=lambda i:R.name_of(projects,i,'Chantier'))
                code=st.text_input('Code chantier unique')
                rows=st.data_editor([dict(code='MAT',label='Matériaux',budget='0.00',forecast='0.00')],num_rows='dynamic',key='v7_budget_lines',hide_index=True)
                contract=st.text_input('Montant contractuel HT','0.00');forecast=st.text_input('Coût estimé à terminaison HT','0.00')
                ok=st.form_submit_button('Proposer le budget')
            if ok:
                try:lines=[dict(code=x['code'],label=x['label'],budget=R.cents(x['budget']),forecast=R.cents(x['forecast'])) for x in rows]
                except ValueError as e:st.error(str(e))
                else:execute(V.create_budget,pid,code,lines,R.cents(contract),R.cents(forecast))
    b=select_records('Budget',budgets,'v7_budget');
    if not b:return
    st.write('Statut : '+b['data']['status']);m=V.metrics(b,ops);currency=b['currency'];columns=st.columns(4)
    for col,k,label in zip(columns,['budget','available','cost','cash'],['Budget révisé','Disponible à engager','Coûts réalisés','Décaissements']):col.metric(label,R.money(m[k],currency))
    table([{**{k:x[k] for k in ('code','label','alert')},**{k:R.money(x[k],currency) for k in ('budget','open','cost','cash','available','forecast')},'Engagement %':round(x['engagement_rate'],2)} for x in m['lines']])
    st.write(f"Avances à régulariser : {R.money(m['advance'],currency)} · Prévision à terminaison : {R.money(m['forecast'],currency)} · Marge finale : {R.money(m['final_margin'],currency)}")
    legacy=[e for e in db.tout('expenses') if e['project']==b['project']]
    if legacy:st.warning('Des dépenses historiques existent sur ce chantier. Elles doivent être rapprochées et reprises avant de considérer le budget V7 comme exhaustif.')
    if (auth.utilisateur() or {}).get('role')=='admin':
        with st.form('approve_budget'):
            reason=st.text_input('Motif de validation du budget')
            if st.form_submit_button('Approuver le budget',disabled=b['data']['status']=='Approuvé'):execute(V.approve_budget,b['id'],reason)
    if auth.modifie('chantiers') or auth.modifie('comptabilite'):
        with st.expander('Révision et prévision actualisée'):
            with st.form('v7_revision'):
                updated=st.data_editor([dict(code=x['code'],label=x['label'],budget=R.plain(x['budget']),forecast=R.plain(x.get('forecast',x['budget']))) for x in b['data']['lines']],disabled=['code','label'],hide_index=True)
                f=st.text_input('Prévision totale HT',R.plain(b['data']['forecast']));revenue=st.text_input('Chiffre d’affaires final estimé HT',R.plain(b['data']['revenue']));reason=st.text_input('Motif de révision')
                ok=st.form_submit_button('Proposer la révision')
            if ok:
                try:lines=[{**x,'budget':R.cents(x['budget']),'forecast':R.cents(x['forecast'])} for x in updated]
                except ValueError as e:st.error(str(e))
                else:execute(V.revise_budget,b['id'],lines,R.cents(f),R.cents(revenue),reason)
        if b['data'].get('pending'):
            table(b['data']['pending']['lines'])
            if (auth.utilisateur() or {}).get('role')=='admin':
                with st.form('v7_revision_ok'):
                    reason=st.text_input('Motif d’autorisation DG de la révision')
                    if st.form_submit_button('Autoriser la révision'):execute(V.approve_revision,b['id'],reason)

def operations_tab():
    ops=V.records('operation');budgets=[b for b in V.records('budget') if b['data']['status']=='Approuvé'];parties=db.tout('clients')
    if auth.modifie('depenses'):
        with st.expander('Nouvelle demande N0'):
            b=select_records('Budget du chantier',budgets,'v7_op_budget')
            if b and parties:
                with st.form('v7_create_op'):
                    ref=st.text_input('Référence unique');label=st.text_input('Objet de la dépense');post=st.selectbox('Poste DQE',[x['code'] for x in b['data']['lines']]);party=st.selectbox('Bénéficiaire',[p['id'] for p in parties],format_func=lambda i:R.name_of(parties,i,'Tiers'))
                    nature=st.selectbox('Nature',['Achat','Dépense','Avance']);value=st.text_input('Montant autorisé '+b['currency'],'0.00');due=st.date_input('Échéance de paiement ou régularisation');acc=st.selectbox('Compte de charge',[k for k in V.CHART if k.startswith('6')],format_func=lambda k:k+' '+V.CHART[k])
                    ok=st.form_submit_button('Créer le brouillon')
                if ok:execute(V.create_operation,ref,b['project'],post,party,label,nature,R.cents(value),due.isoformat(),acc)
    table([dict(ref=r['ref'],objet=r['data']['label'],statut=r['data']['status'],niveau=V.LEVELS[r['data']['level']] if r['data']['level']<4 else 'Validée',montant=R.money(r['data']['amount'],r['currency']),échéance=r['data']['due']) for r in ops])
    r=select_records('Opération',ops,'v7_operation')
    if not r:return
    d=r['data'];st.subheader(r['ref']+' · '+d['label']);table(d['history'])
    st.write('Statut financier : '+d['status']);paid=sum(x['amount'] for x in d['payments'] if not x.get('reversed'));just=sum(x['amount'] for x in d['justifications'] if x['status']=='Validée');st.write('Payé : '+R.money(paid,r['currency'])+' · Justifié : '+R.money(just,r['currency']))
    if not auth.modifie('depenses'):return
    if d['status']=='Brouillon' and d['creator']==auth.utilisateur()['id'] and st.button('Soumettre à N1'):execute(V.submit,r['id'])
    if d['status']=='Soumise':
        with st.form('v7_approve'):
            reason=st.text_area('Contrôle et décision '+V.LEVELS[d['level']]);exception=st.checkbox('Autorisation DG de dépassement budgétaire',disabled=d['level']!=3)
            a,b=st.columns(2);yes=a.form_submit_button('Valider ce niveau');no=b.form_submit_button('Retourner au créateur')
        if yes or no:execute(V.approve,r['id'],reason,exception,no)
    action=st.selectbox('Action',['Choisir','Modifier la demande','Bon de commande','Réception','Facture fournisseur','Paiement','Justificatif','Contrôle justificatif','Restitution avance','Contre-passation paiement','Annuler'])
    with st.form('v7_action'):
        ref=st.text_input('Référence ou motif');date_=st.date_input('Date de l’opération');value=st.text_input('Montant '+r['currency'],'0.00')
        accounts=[x for x in V.records('account') if x['currency']==r['currency']]
        account=select_records('Compte de trésorerie',accounts,'v7_action_account') if action in ('Paiement','Restitution avance') else None
        if action=='Modifier la demande':newlabel=st.text_input('Objet modifié',d['label'])
        if action=='Justificatif':
            upload=st.file_uploader('Pièce PDF JPEG PNG',type=['pdf','jpg','jpeg','png']);docdate=st.date_input('Date de la pièce')
        if action=='Contrôle justificatif':
            js=[x for x in d['justifications'] if x['status']=='Soumise'];piece=st.selectbox('Pièce',[x['piece'] for x in js]) if js else None;accepted=st.checkbox('Accepter la pièce')
        if action=='Contre-passation paiement':
            ps=[x for x in d['payments'] if not x.get('reversed')];payment=st.selectbox('Paiement',[x['id'] for x in ps],format_func=lambda i:next(x['ref'] for x in ps if x['id']==i)) if ps else None
        ok=st.form_submit_button('Enregistrer cette action',disabled=action=='Choisir')
    if ok:
        day=date_.isoformat()
        try:
            if action=='Modifier la demande':execute(V.edit_operation,r['id'],R.cents(value),newlabel,day)
            elif action=='Bon de commande':execute(V.order,r['id'],ref,day)
            elif action=='Réception':execute(V.receive,r['id'],ref,day,R.cents(value))
            elif action=='Facture fournisseur':execute(V.invoice,r['id'],ref,day,R.cents(value))
            elif action=='Paiement' and account:execute(V.pay,r['id'],account['id'],R.cents(value),day,ref)
            elif action=='Restitution avance' and account:execute(V.return_advance,r['id'],account['id'],R.cents(value),day,ref)
            elif action=='Annuler':execute(V.cancel,r['id'],ref)
            elif action=='Contre-passation paiement' and payment:execute(V.reverse_payment,r['id'],payment,day,ref)
            elif action=='Contrôle justificatif' and piece:execute(V.validate_justification,r['id'],piece,accepted,ref)
            elif action=='Justificatif' and upload:execute(V.upload_piece,r['id'],upload.name,upload.getvalue(),docdate.isoformat(),R.cents(value))
        except ValueError as e:st.error(str(e))
    table(d.get('invoices',[]));table(d['payments']);table(d['justifications'])

def treasury_tab():
    accounts=V.records('account');w=auth.modifie('tresorerie')
    if w:
        with st.expander('Ajouter un compte'):
            with st.form('v7_account_new'):
                ref=st.text_input('Code du compte');label=st.text_input('Libellé');currency=st.selectbox('Devise',R.CURRENCIES);ledger=st.text_input('Compte comptable de banque ou caisse','52');legacy=st.selectbox('Nature de trésorerie',list(R.CASH_ACCOUNTS));ok=st.form_submit_button('Créer le compte')
            if ok:execute(V.create_account,ref,label,currency,ledger,legacy)
    table([dict(compte=a['ref'],devise=a['currency'],solde=R.money(V.balance(a),a['currency'])) for a in accounts])
    st.caption('Les mouvements historiques sans compte V7 restent visibles dans les journaux d’origine. Réconciliez-les avant de saisir les soldes initiaux V7 ; ne les ressaisissez pas comme recettes.')
    with st.expander('Consolidation avec taux explicites'):
        reporting=st.selectbox('Devise de présentation',R.CURRENCIES,key='v7_reporting');chosen={}
        for currency in sorted({a['currency'] for a in accounts if a['currency']!=reporting}):
            rows=[r for r in V.records('rate') if r['currency']==currency and r['data']['target']==reporting]
            chosen[currency]=st.selectbox('Taux historique '+currency,[None]+[r['id'] for r in rows],format_func=lambda i:'Choisir un taux' if i is None else next(r['ref']+' '+r['data']['rate'] for r in rows if r['id']==i),key='v7_conv_'+currency)
        if st.button('Calculer le total consolidé'):
            try:
                result=V.consolidated(reporting,chosen,R.today());st.metric('Trésorerie V7 consolidée',R.money(result['total'],reporting));table(result['rows'])
            except ValueError as e:st.error(str(e))
    if not w or not accounts:return
    action=st.selectbox('Action de trésorerie',['Solde initial','Transfert interne','Rapprochement bancaire','Taux historique'])
    a=select_records('Compte source',accounts,'v7_treasury_source')
    with st.form('v7_treasury_action'):
        ref=st.text_input('Référence du relevé ou mouvement');date_=st.date_input('Date');value=st.text_input('Montant ou solde de relevé','0.00')
        if action=='Transfert interne':b=select_records('Compte destination',accounts,'v7_treasury_target')
        if action=='Taux historique':source=st.selectbox('Devise d’origine',R.CURRENCIES);target=st.selectbox('Devise de conversion',R.CURRENCIES,index=1);rate=st.text_input('1 unité d’origine vaut','1.00')
        if action=='Rapprochement bancaire':
            moves=[m for m in db.tout('movements') if (m.get('journal') or {}).get('v7_account')==a['id']];matched=st.multiselect('Mouvements pointés sur le relevé',[m['id'] for m in moves],format_func=lambda i:next(m['label']+' '+R.money(m['amount'],m['currency']) for m in moves if m['id']==i))
        ok=st.form_submit_button('Enregistrer')
    if ok:
        try:
            if action=='Solde initial':execute(V.opening,a['id'],R.cents(value),date_.isoformat(),ref)
            elif action=='Transfert interne':execute(V.transfer,a['id'],b['id'],R.cents(value),date_.isoformat(),ref)
            elif action=='Taux historique':execute(V.register_rate,ref,source,target,rate,date_.isoformat())
            else:
                from decimal import Decimal
                cents=int(Decimal(value)*100);execute(V.reconcile,a['id'],date_.isoformat(),cents,matched,ref)
        except ValueError as e:st.error(str(e))
    table([dict(ref=r['ref'],**r['data']) for r in V.records('reconciliation')])
    table([dict(ref=r['ref'],source=r['currency'],**r['data']) for r in V.records('rate')])

def accounting_tab():
    st.caption('Écritures automatiques du circuit V7. Les écritures historiques préparatoires restent dans leur rubrique ; elles ne sont pas reprises automatiquement.')
    table([dict(ref=r['ref'],devise=r['currency'],**r['data']) for r in V.records('entry')]);rows=V.ledger();table(rows)
    if rows:st.download_button('Exporter la balance CSV',R.to_csv([['Devise','Compte','Débit','Crédit','Solde']]+[[x[k] for k in ('currency','account','debit','credit','balance')] for x in rows]),'balance_v7.csv','text/csv')
    table([dict(compte=k,libellé=v,statut='Nomenclature proposée à valider') for k,v in V.CHART.items()])

def fiscal_tab():
    st.info('Calculs préparatoires selon la fiche fiscale validée. Les taux réduits BTP, exonérations, cotisations sociales et prélèvements étrangers nécessitent leurs justificatifs et règles applicables. Aucune facture fiscale normalisée n’est émise par cet écran.')
    cfg=db.parametre('v7_fiscal') or {};role=auth.utilisateur()['role']
    if role=='admin':
        with st.expander('Valider le régime fiscal RDC'):
            with st.form('v7_fiscal_config'):
                regime=st.text_input('Régime effectif',cfg.get('regime',''));province=st.text_input('Province',cfg.get('province',''));vat=st.selectbox('Statut TVA',['À vérifier','Assujetti','Non assujetti'],index=['À vérifier','Assujetti','Non assujetti'].index(cfg.get('vat_status','À vérifier')))
                israte=st.text_input('Taux IS %',str(cfg.get('is_rate','30')));minimum=st.text_input('Minimum IS % selon régime',str(cfg.get('is_minimum','1')));vatrate=st.text_input('Taux TVA normal %',str(cfg.get('vat_rate','16')))
                source=st.text_area('Textes et preuves du régime',cfg.get('source',''));reviewed=st.text_input('Responsable ayant vérifié le régime',cfg.get('reviewed_by',''));effective=st.date_input('Date d’effet');confirmed=st.checkbox('Règles vérifiées pour la société et la période')
                ok=st.form_submit_button('Valider les paramètres')
            if ok:execute(V.fiscal_config,dict(regime=regime,province=province,vat_status=vat,is_rate=israte,is_minimum=minimum,vat_rate=vatrate,source=source,reviewed_by=reviewed,effective=effective.isoformat(),confirmed=confirmed))
    if cfg:st.write({k:v for k,v in cfg.items() if k not in ('approved_by',)})
    if auth.modifie('comptabilite'):
        with st.expander('Simulation IS en CDF'):
            with st.form('v7_is'):
                vals=[st.text_input(label,'0.00') for label in ('Chiffre d’affaires','Résultat comptable avant impôt signé','Réintégrations','Déductions admises','Crédits admis','Acomptes versés')];ok=st.form_submit_button('Calculer l’IS préparatoire')
            if ok:
                try:
                    from decimal import Decimal
                    parsed=[R.cents(x) if i!=1 else int(Decimal(x)*100) for i,x in enumerate(vals)];st.write(V.fiscal_estimate(*parsed))
                except (ValueError,ArithmeticError) as e:st.error(str(e))
        with st.expander('Liquidation TVA en CDF'):
            with st.form('v7_vat'):
                c=st.text_input('TVA collectée exigible','0.00');d=st.text_input('TVA légalement déductible','0.00');credit=st.text_input('Crédit antérieur','0.00');ok=st.form_submit_button('Calculer la TVA préparatoire')
            if ok:
                try:st.write(V.vat_estimate(R.cents(c),R.cents(d),R.cents(credit)))
                except ValueError as e:st.error(str(e))
    year=st.number_input('Année des revenus',2020,2100,2026);table(V.fiscal_calendar(int(year)))
    rows=V.records('fiscal');table([dict(ref=r['ref'],**r['data']) for r in rows])
    if auth.modifie('comptabilite'):
        with st.form('v7_due'):
            ref=st.text_input('Référence unique de déclaration');label=st.text_input('Impôt ou obligation');period=st.text_input('Période');due=st.date_input('Échéance légale ou prorogée');amount=st.text_input('Montant CDF','0.00');source=st.text_input('Texte ou communiqué');ok=st.form_submit_button('Ajouter une échéance à suivre')
        if ok:execute(V.save_fiscal_due,ref,label,period,due.isoformat(),R.cents(amount),source)
        row=select_records('Échéance à régulariser',rows,'v7_fiscal_due')
        if row:
            with st.form('v7_done'):
                proof=st.text_input('Références de dépôt et de règlement')
                if st.form_submit_button('Confirmer dépôt et règlement'):execute(V.fiscal_done,row['id'],proof)

def settings_tab():
    table(V.alerts());doc=Path(__file__).parents[1]/'documentation'/'Memo_BatiGestion.docx'
    if doc.exists():st.download_button('Télécharger le mémo de référence',doc.read_bytes(),'Memo_BatiGestion.docx')
    st.markdown('**Circuit :** demande N0 → contrôle N1 → finance N2 → autorisation N3 → DG → paiement par un trésorier distinct. Chaque validation nécessite un compte différent. Les délégations ont une durée, un plafond, une devise et un chantier. Les anciens dossiers restent consultables.')
    if auth.utilisateur()['role']!='admin':return
    with st.form('v7_policy'):
        p=V.policy();thresholds=st.text_input('Seuils budgétaires en % séparés par virgules',','.join(str(x) for x in p['thresholds']));days=st.number_input('Délai proposé pour régulariser les avances',1,365,p['max_advance_days']);ok=st.form_submit_button('Enregistrer les contrôles')
    if ok:
        try:execute(V.configure_policy,dict(thresholds=[float(x) for x in thresholds.split(',')],levels=list(V.LEVELS),max_advance_days=int(days)))
        except ValueError as e:st.error(str(e))
    users=[u for u in db.tout('users') if u['actif'] and u['role'] in ('finance','chantier','admin')];projects=db.tout('projects')
    if users:
        with st.form('v7_delegate'):
            user=st.selectbox('Délégataire',[u['id'] for u in users],format_func=lambda i:next(u['nom'] for u in users if u['id']==i));level=st.selectbox('Niveau',V.LEVELS);project=st.selectbox('Portée chantier',['']+[p['id'] for p in projects],format_func=lambda i:'Tous les chantiers' if not i else R.name_of(projects,i,''));currency=st.selectbox('Devise du plafond',R.CURRENCIES);limit=st.text_input('Plafond','0.00');start=st.date_input('Début de délégation');end=st.date_input('Fin de délégation');reason=st.text_input('Motif de délégation');ok=st.form_submit_button('Accorder la délégation')
        if ok:execute(V.delegate,user,level,project,currency,R.cents(limit),start.isoformat(),end.isoformat(),reason)
    table([dict(ref=r['ref'],**r['data']) for r in V.records('delegation')])
    row=select_records('Délégation à révoquer',V.records('delegation'),'v7_revoke')
    if row:
        with st.form('v7_revoke_form'):
            reason=st.text_input('Motif de révocation')
            if st.form_submit_button('Révoquer'):execute(V.revoke_delegate,row['id'],reason)

def imports_tab():
    from vues import imports as IMP
    st.caption('Budgets, cumuls, besoins N0, reliquats fournisseurs, soldes et balance d’ouverture : import contrôlé, puis validation Finance et activation DG dans le Centre de reprise.')
    IMP.encart(['budgets','besoins','fournisseurs','tresorerie','comptabilite'],'Importer depuis Excel')
    st.subheader('Reliquats repris activés')
    IMP._reliquats_tab()

def page():
    auth.exiger('depenses');ui.en_tete('Circuit financier V7','Budgets DQE, validations, paiements, avances et comptabilité du mémo.')
    tabs=st.tabs(['Budgets DQE','Opérations','Trésorerie','Comptabilité','Fiscalité RDC','Contrôles et mémo','Reprises et imports'])
    for tab,fn,module in zip(tabs,[budget_tab,operations_tab,treasury_tab,accounting_tab,fiscal_tab,settings_tab,imports_tab],['chantiers','depenses','tresorerie','comptabilite','comptabilite','depenses','depenses']):
        with tab:
            if auth.voit(module):
                try:fn()
                except (ValueError, ArithmeticError) as e:st.error(str(e))
            else:st.info('Votre rôle ne donne pas accès à cette rubrique.')
