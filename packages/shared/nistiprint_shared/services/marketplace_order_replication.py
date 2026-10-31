"""Resumable read-only discovery of recently updated marketplace orders."""
from datetime import datetime, timedelta
from nistiprint_shared.services.credential_resolver_service import credential_resolver_service
from nistiprint_shared.services.marketplace_webhook_ingest_service import marketplace_webhook_ingest_service
from nistiprint_shared.services.platform_drivers import mercadolivre, shopee
from nistiprint_shared.services.marketplace_catalog_sync_service import MarketplaceCatalogSyncService


class ReplicationFailure(Exception):
    def __init__(self, code, retry_after=None):
        self.code=code
        self.retry_after=retry_after
        super().__init__(code)


class OrderReplication:
    def __init__(self, db): self.db=db

    def run_page(self, account_id):
        rows=self.db.table('installed_integrations').select('*').eq('id',account_id).eq('is_active',True).limit(1).execute().data or []
        if not rows: return {'status':'account_missing'}
        account=rows[0]
        provider=(account.get('platform_slug') or account.get('module_id') or '').lower()
        if provider not in ('shopee','mercadolivre'): return {'status':'unavailable'}
        claim=self.db.rpc('marketplace_pedidos_claim',{'p_account':account_id}).execute().data or {}
        if claim.get('status')=='busy': return {'status':'busy'}
        token=claim['owner_token']
        operation_id=claim.get('operation_id')
        try:
            integration=credential_resolver_service.hydrate_integration(account)
            reserve=MarketplaceCatalogSyncService(self.db)._budget_reserver(account)
            if not reserve(): raise ValueError('analytics_budget_wait')
            config=integration.get('config') or {}
            credentials=integration.get('credentials') or {}
            cursor=claim.get('cursor') or {}
            search_field=claim.get('search_field') or 'updated'
            window_start=datetime.fromisoformat(claim['window_start'].replace('Z','+00:00'))
            window_end=datetime.fromisoformat(claim['window_end'].replace('Z','+00:00'))
            # Historical discovery starts with recent days, so usable data arrives
            # before the older provider-dependent part of the requested period.
            if search_field=='created':
                slice_end=datetime.fromisoformat(cursor['slice_end']) if cursor.get('slice_end') else window_end
                slice_start=max(window_start,slice_end-timedelta(days=1))
            else:
                slice_start=datetime.fromisoformat(cursor['slice_start']) if cursor.get('slice_start') else window_start
                slice_end=min(window_end,slice_start+timedelta(days=1))
            boundary={'slice_end':slice_end.isoformat()} if search_field=='created' else {'slice_start':slice_start.isoformat()}
            if provider=='shopee':
                identity=config.get('shop_id') or credentials.get('shop_id')
                if not identity: raise ValueError('account_identity_missing')
                start=int(slice_start.timestamp())
                end=int(slice_end.timestamp())
                page=shopee.get_orders_list_page(integration,{'time_range_field':'create_time' if search_field=='created' else 'update_time','time_from':start,'time_to':end,'page_size':1,'cursor':cursor.get('cursor')})
                orders=page.get('orders') or []
                next_cursor=page.get('next_cursor')
                if page.get('more') and (not next_cursor or next_cursor==cursor.get('cursor')): raise ValueError('cursor_stalled')
                next_state={**boundary,'cursor':next_cursor} if page.get('more') else {}
                complete=not page.get('more')
                def payload(external): return {'code':3,'shop_id':identity,'data':{'ordersn':external}}
            else:
                identity=config.get('seller_id') or config.get('user_id') or credentials.get('seller_id') or credentials.get('user_id')
                if not identity: raise ValueError('account_identity_missing')
                offset=int(cursor.get('offset',0))
                date_filters=({'date_created_from':slice_start.isoformat(),'date_created_to':slice_end.isoformat()}
                    if search_field=='created' else {'last_updated_after':slice_start.isoformat(),'last_updated_before':slice_end.isoformat()})
                orders=mercadolivre.get_orders_list(integration,{'seller':identity,**date_filters,'limit':1,'offset':offset}) or []
                if len(orders)==1 and offset+1>=1000: raise ValueError('provider_pagination_limit')
                complete=len(orders)<1
                next_state={} if complete else {**boundary,'offset':offset+1}
                def payload(external): return {'topic':'orders_v2','resource':f'/orders/{external}','user_id':identity}
            if complete and search_field=='created' and slice_start > window_start:
                next_state={'slice_end':slice_start.isoformat()}
                complete=False
            elif complete and search_field!='created' and slice_end < window_end:
                next_state={'slice_start':slice_end.isoformat()}
                complete=False
            for order in orders:
                if isinstance(order,dict) and order.get('error'):
                    raise ReplicationFailure(order.get('error_type') or 'provider_error',order.get('retry_after'))
                if not isinstance(order,dict) or not order.get('external_id'):
                    raise ValueError('invalid_order_page')
                if not reserve(): raise ValueError('analytics_budget_wait')
                result=marketplace_webhook_ingest_service.process(provider,payload(str(order['external_id'])))
                if result.get('status')!='success': raise ReplicationFailure(result.get('error_type') or result.get('event_status') or 'order_processing_failed',result.get('retry_after'))
            saved=self.db.rpc('marketplace_pedidos_finish',{'p_account':account_id,'p_token':token,'p_cursor':next_state,'p_complete':complete}).execute().data
            return {'status':'complete' if complete else 'available','processed':len(orders),'operation_id':operation_id} if saved else {'status':'lease_lost','retryable':True,'operation_id':operation_id}
        except Exception as exc:
            code=str(exc) if isinstance(exc,(ValueError,ReplicationFailure)) else type(exc).__name__
            retry_after=getattr(exc,'retry_after',None)
            try: retry_after=min(2147483647,max(0,int(float(retry_after)))) if retry_after is not None else None
            except (TypeError,ValueError,OverflowError): retry_after=None
            self.db.rpc('marketplace_pedidos_finish',{'p_account':account_id,'p_token':token,'p_cursor':{},'p_complete':False,'p_error':code[:100],'p_retry_after':retry_after}).execute()
            unavailable=code in {'provider_pagination_limit','account_identity_missing','provider_access_forbidden','credential_action_required'}
            return {'status':'unavailable' if unavailable else 'failed','error_code':code[:100],
                    'retryable':not unavailable,'operation_id':operation_id}
