"""Read-only authenticated probe of recent order list contracts."""
import argparse
import subprocess


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--host',required=True)
    parser.add_argument('--identity',required=True)
    parser.add_argument('--historical',action='store_true')
    args=parser.parse_args()
    program='HISTORICAL='+repr(args.historical)+'\n'+r'''
from dotenv import load_dotenv
load_dotenv('/opt/nistiprint/.env')
import json,time,requests
from datetime import datetime,timedelta,timezone
from nistiprint_shared.database.supabase_db_service import supabase_db as db
from nistiprint_shared.services.credential_resolver_service import credential_resolver_service
from nistiprint_shared.services.platform_drivers import mercadolivre,shopee
for account_id in (6,7091):
 try:
  rows=db.table('installed_integrations').select('*').eq('id',account_id).eq('is_active',True).execute().data or []
  if not rows: print(json.dumps({'account':account_id,'status':'missing'}),flush=True);continue
  account=credential_resolver_service.hydrate_integration(rows[0]);cfg=account.get('config') or {};creds=account.get('credentials') or {}
  if HISTORICAL:
   from nistiprint_shared.services.marketplace_catalog_sync_service import MarketplaceCatalogSyncService
   if not MarketplaceCatalogSyncService(db)._budget_reserver(rows[0])():
    print(json.dumps({'account':account_id,'error':'analytics_budget_wait'}),flush=True);continue
  if account_id==6:
   end=int(datetime(2025,1,2,3,tzinfo=timezone.utc).timestamp()) if HISTORICAL else int(time.time())
   data=shopee.get_orders_list_page(account,{'time_range_field':'create_time' if HISTORICAL else 'update_time','time_from':end-(24 if HISTORICAL else 72)*3600,'time_to':end,'page_size':10})
   orders=data.get('orders') or [];print(json.dumps({'account':account_id,'orders':len(orders),'has_more':data.get('more'),'error':(orders[0].get('error_type') if orders and orders[0].get('error') else None)}),flush=True)
  else:
   end=datetime.now(timezone.utc);seller=cfg.get('seller_id') or cfg.get('user_id') or creds.get('seller_id') or creds.get('user_id')
   if HISTORICAL:end=datetime(2025,1,2,3,tzinfo=timezone.utc)
   field='order.date_created' if HISTORICAL else 'order.date_last_updated'
   params={'seller':seller,field+'.from':(end-timedelta(hours=24 if HISTORICAL else 72)).isoformat(),field+'.to':end.isoformat(),'limit':10,'offset':0}
   response=requests.get(mercadolivre._ml_url('/orders/search'),headers=mercadolivre._auth_headers(account),params=params,timeout=30)
   data=response.json();print(json.dumps({'account':account_id,'http':response.status_code,'has_results_list':isinstance(data.get('results'),list),'results':len(data.get('results') or []),'paging':data.get('paging'),'error':data.get('error')}),flush=True)
 except Exception as exc: print(json.dumps({'account':account_id,'error':type(exc).__name__}),flush=True)
'''
    command=['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10','-i',args.identity,args.host,'cd /opt/nistiprint && .venv/bin/python -']
    completed=subprocess.run(command,input=program,text=True,check=False)
    if completed.returncode:raise SystemExit(completed.returncode)


if __name__=='__main__':main()
