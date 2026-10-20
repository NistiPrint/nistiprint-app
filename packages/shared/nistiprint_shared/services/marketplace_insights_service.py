"""Account-scoped configuration and scheduling; no provider formats or endpoint knowledge."""
from datetime import datetime, timezone
from nistiprint_shared.services.platform_drivers.insights_registry import CAPABILITIES

LABELS={'shopee_escrow':'Repasses e taxas','shopee_product':'Indicadores de anúncios','shopee_ads':'Publicidade',
        'ml_visits':'Visitas dos anúncios','ml_ads':'Product Ads','ml_billing':'Conciliação financeira','bling_history':'Histórico comercial'}
FINANCIAL={'shopee_escrow','shopee_ads','ml_ads','ml_billing'}


class MarketplaceInsightsService:
    def __init__(self, db): self.db=db

    def account(self, account_id):
        rows=self.db.table('installed_integrations').select('id,module_id,platform_slug,instance_name,is_active').eq('id',account_id).limit(1).execute().data or []
        if not rows or (rows[0].get('platform_slug') or rows[0]['module_id']) not in {'shopee','mercadolivre','bling'}:
            raise ValueError('Conta sem módulo de inteligência disponível.')
        return rows[0]

    def read(self, account_id):
        account=self.account(account_id)
        provider=account.get('platform_slug') or account['module_id']
        rows=self.db.table('gestao_coletas').select('capability,status,enabled,error_code,checked_at,next_attempt_at,checkpoint').eq('account_id',account_id).execute().data or []
        states={r['capability']:r for r in rows}
        coverage=self.db.rpc('marketplace_insights_coverage',{'p_account':account_id}).execute().data or {}
        capabilities=[{'capability':cap,'label':LABELS[cap],'financial':cap in FINANCIAL,
            'enabled':cap in {'shopee_escrow','ml_billing'},'status':'not_checked',**states.get(cap,{})} for cap,p in CAPABILITIES.items() if p==provider]
        # Checkpoints stay internal; counters and provider IDs may contain private operational context.
        for row in capabilities: row.pop('checkpoint',None)
        return {'account_id':account_id,'provider':provider,'automatic':True,'capabilities':capabilities,
            'coverage':coverage,'gestao_url':f'/gestao/visao-geral?account_id={account_id}'}

    def configure(self, account_id, capability, action):
        account=self.account(account_id)
        if not isinstance(capability,str) or not isinstance(action,str):
            raise ValueError('Informe capacidade e ação válidas.')
        if CAPABILITIES.get(capability)!=(account.get('platform_slug') or account['module_id']):
            raise ValueError('A capacidade pertence a outro módulo de marketplace.')
        if action not in {'enable','pause','resume','backfill','run'}:
            raise ValueError('Ação inválida.')
        existing=self.db.table('gestao_coletas').select('*').eq('account_id',account_id).eq('capability',capability).limit(1).execute().data or []
        row=existing[0] if existing else {}
        now=datetime.now(timezone.utc).isoformat()
        # Pause/config changes preserve the checkpoint and an active lease.
        values={'account_id':account_id,'capability':capability,'enabled':action!='pause',
            'status':row.get('status','pending'),'next_attempt_at':now}
        if action!='pause': values.update(status='pending',error_code=None,attempts=0)
        self.db.table('gestao_coletas').upsert(values,on_conflict='account_id,capability').execute()
        if action=='backfill':
            self.db.rpc('marketplace_insights_backfill',{'p_account':account_id,'p_capability':capability}).execute()
        if action!='pause':
            from nistiprint_shared.services.celery_app import celery_app
            celery_app.send_task('tasks.gestao_tasks.collect',kwargs={'account_id':account_id,'capability':capability},queue='marketplace_insights')
        return {'success':True,'message':'Configuração salva.'}
