"""Opt-in, bounded provider reads with durable checkpoints and account leases."""
from datetime import datetime, timedelta
from nistiprint_shared.services.gestao_projection import TZ, number
from nistiprint_shared.services.marketplace_http import request_json

from nistiprint_shared.services.platform_drivers.insights_registry import CAPABILITIES


from nistiprint_shared.services.platform_drivers.insights_contract import CollectionError


def provider_get(integration, resource, params=None, headers=None):
    from nistiprint_shared.services.platform_drivers.insights_registry import driver_for
    return driver_for(integration.get('platform_slug') or integration['module_id']).get(
        integration,resource,params,headers,request_json=request_json)


def metric(db,account,resource,day,kind,values,source,*,resource_type=None,
           timezone_name='America/Sao_Paulo',semantic='diaria',partial=False):
    # Keep native attribution fields: visits and accumulated counters are not interchangeable.
    db.table('gestao_metricas_anuncio').upsert({'account_id':account,'resource_id':str(resource),
        'day':day,'kind':kind,'metrics':values,'source':source,'updated_at':datetime.now(TZ).isoformat()},
        on_conflict='account_id,resource_id,day,kind').execute()
    db.table('gestao_metricas_anuncio_periodo').upsert({
        'account_id':account,'recurso_tipo':resource_type or ('ad_group' if kind=='ads' else 'listing'),
        'resource_id':str(resource),'periodo_inicio':day,'periodo_fim':day,'source':source,'kind':kind,
        'fuso_origem':timezone_name,'semantica':semantic,'metrics':values,'parcial':bool(partial),
        'collected_at':datetime.now(TZ).isoformat(),
    },on_conflict='account_id,recurso_tipo,resource_id,periodo_inicio,periodo_fim,source,kind').execute()


def finance(db,pedido_id,components,source,settled,evidence):
    existing=db.table('gestao_financeiro').select('*').eq('pedido_id',pedido_id).limit(1).execute().data or []
    old=existing[0] if existing else {}
    # Explicit reconciliation takes precedence over estimates downloaded later.
    if old.get('source')=='manual':
        return
    db.table('gestao_financeiro').upsert({'pedido_id':pedido_id,'components':{**(old.get('components') or {}),**components},
        'source':source,'settled':settled,'evidence':evidence,'updated_at':datetime.now(TZ).isoformat()},on_conflict='pedido_id').execute()


def order_batch(db,account,cp):
    return db.rpc('marketplace_insights_claim',{'p_account':account,'p_capability':cp['_capability']}).execute().data or []


def collect_batch(db,account,capability):
    if capability not in CAPABILITIES:
        raise ValueError('Capacidade desconhecida')
    statistics = capability in {'ml_visits', 'shopee_product'}
    if statistics:
        row = db.rpc('gestao_statistics_claim', {'p_account':account,'p_capability':capability}).execute().data
        if not row:
            return {'status':'busy'}
    else:
        if not db.rpc('gestao_collection_lease',{'p_account':account,'p_capability':capability}).execute().data:
            return {'status':'busy'}
        row=db.table('gestao_coletas').select('*').eq('account_id',account).eq('capability',capability).single().execute().data
    cp=dict(row.get('checkpoint') or {})
    if row.get('enabled') is False or row.get('status')=='forbidden':
        db.table('gestao_coletas').update({'lease_until':'-infinity'}).eq('account_id',account).eq('capability',capability).execute()
        return {'status':'paused'}
    status,error='available',None
    retry_after = None
    has_more=False
    try:
        rows=db.table('installed_integrations').select('*').eq('id',account).eq('is_active',True).limit(1).execute().data or []
        if not rows or (rows[0].get('platform_slug') or rows[0]['module_id'])!=CAPABILITIES[capability]:
            raise CollectionError('account_platform_mismatch',True)
        from nistiprint_shared.services.credential_resolver_service import credential_resolver_service
        integration=credential_resolver_service.hydrate_integration(rows[0])
        today=datetime.now(TZ).date()
        from nistiprint_shared.services.platform_drivers.insights_registry import driver_for
        import os
        # Unknown limits use a conservative 0.1 req/s ceiling; known capacity may be configured.
        fraction=max(.001,min(float(os.getenv('MARKETPLACE_INSIGHTS_BUDGET_FRACTION','0.1')),0.1))
        known_rps=float(os.getenv(f'{CAPABILITIES[capability].upper()}_KNOWN_RPS','3' if CAPABILITIES[capability]=='bling' else '1'))
        interval=max(1,1/max(.001,known_rps*fraction))
        scope=f"{CAPABILITIES[capability]}:app:{integration.get('app_profile_id') or 'default'}"
        def reserve():
            if not db.rpc('marketplace_insights_budget',{'p_account':account,'p_interval':interval,'p_scope':scope}).execute().data:
                raise CollectionError('analytics_budget_wait')
        def limited_get(*args,**kwargs):
            reserve()
            if statistics and not db.rpc('gestao_statistics_renew', {'p_account':account,'p_capability':capability,'p_owner':row['owner_token']}).execute().data:
                raise CollectionError('statistics_lease_lost')
            return provider_get(*args,**kwargs)
        integration['_insights_reserve']=reserve
        cp['_capability']=capability
        def store_metric(_db, metric_account, resource, day, kind, values, source, **options):
            if not statistics:
                return metric(_db, metric_account, resource, day, kind, values, source, **options)
            if metric_account != account:
                raise CollectionError('account_platform_mismatch', True)
            saved = db.rpc('gestao_statistics_metric', {'p_account':account,'p_capability':capability,
                'p_owner':row['owner_token'], 'p_row': {
                    'resource_id':str(resource),'day':day,'kind':kind,'metrics':values,'source':source,
                    'resource_type':options.get('resource_type','listing'),
                    'timezone':options.get('timezone_name','America/Sao_Paulo'),
                    'semantic':options.get('semantic','contador_acumulado' if kind=='counter' else 'diaria'),
                    'partial':options.get('partial',False)}}).execute().data
            if not saved:
                raise CollectionError('statistics_lease_lost')
        has_more=driver_for(CAPABILITIES[capability]).collect(db,account,capability,integration,cp,limited_get,store_metric,finance,order_batch)
    except CollectionError as exc:
        retry_after = exc.retry_after
        status,error=('forbidden' if exc.forbidden else 'failed'),exc.code
        if error=='analytics_budget_wait':
            status,has_more='available',True
            db.rpc('marketplace_insights_release',{'p_account':account,'p_capability':capability}).execute()
    except Exception as exc:
        # Persist only a class/code. Exception text can include credentials or personal data.
        status,error=('forbidden' if getattr(exc,'status_code',None) in {401,403} else 'failed'),type(exc).__name__
    cp.pop('_capability',None)
    attempts=(row.get('attempts') or 0)+1 if status=='failed' else 0
    delay=min(21600,30*2**min(attempts,9)) if status=='failed' else (15 if has_more else 21600)
    if retry_after is not None:
        delay = max(delay, int(retry_after))
    if statistics and status == 'available' and not has_more:
        now = datetime.now(TZ)
        next_run = (now + timedelta(days=1)).replace(hour=3, minute=0, second=0, microsecond=0)
        delay = max(1, int((next_run-now).total_seconds()))
    state={'status':status,'error_code':error,'checkpoint':cp,'attempts':attempts,
        'next_attempt_at':(datetime.now(TZ)+timedelta(seconds=delay)).isoformat(),
        'checked_at':datetime.now(TZ).isoformat(),'lease_until':'-infinity'}
    if statistics:
        saved = db.rpc('gestao_statistics_finish', {'p_account':account,'p_capability':capability,
                    'p_owner':row['owner_token'],'p_state':state}).execute().data
        if not saved:
            return {'status':'lease_lost','has_more':False}
    else:
        db.table('gestao_coletas').update(state).eq('account_id',account).eq('capability',capability).execute()
    return {'status':status,'has_more':has_more,'error_code':error}
