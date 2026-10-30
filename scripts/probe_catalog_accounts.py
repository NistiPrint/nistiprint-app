"""Probe catalog adapters using runtime-owned credentials; print no credentials.

Runs read-only provider requests on the application host. Loads the reviewed
adapter source in memory, without deploying or changing runtime files.
"""
import argparse
import base64
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True)
    parser.add_argument('--identity', required=True)
    parser.add_argument('--ssh', default='ssh')
    parser.add_argument('--provider', choices=['all','mercadolivre','shopee'], default='all')
    parser.add_argument('--authorization', action='store_true', help='Read application/grant metadata; never refresh or revoke tokens')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    modules = {}
    for provider in ('shopee', 'mercadolivre'):
        path = root / f'packages/shared/nistiprint_shared/services/platform_drivers/{provider}_catalog.py'
        modules[provider] = base64.b64encode(path.read_bytes()).decode()
    program = '''
import base64,json,logging,sys,types
from dotenv import load_dotenv
load_dotenv('/opt/nistiprint/.env')
logging.disable(logging.CRITICAL)
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.credential_resolver_service import credential_resolver_service
from nistiprint_shared.services.marketplace_catalog_sync_service import MarketplaceCatalogSyncService
MODULES = ''' + repr(modules) + '''
SELECTED = ''' + repr(args.provider) + '''
AUTHORIZATION = ''' + repr(args.authorization) + '''
for account_id,provider in [(6,'shopee'),(7091,'mercadolivre')]:
 if SELECTED!='all' and provider!=SELECTED: continue
 try:
  rows=supabase_db.table('installed_integrations').select('*').eq('id',account_id).eq('is_active',True).execute().data or []
  if not rows:
   print(json.dumps({'account_id':account_id,'status':'account_missing'}),flush=True);continue
  account=credential_resolver_service.hydrate_integration(rows[0])
  account['_catalog_reserve']=MarketplaceCatalogSyncService(supabase_db)._budget_reserver(rows[0])
  name='nistiprint_shared.services.platform_drivers.'+provider+'_catalog'
  module=types.ModuleType(name);module.__package__='nistiprint_shared.services.platform_drivers'
  sys.modules[name]=module
  exec(compile(base64.b64decode(MODULES[provider]),'<reviewed_catalog_adapter>','exec'),module.__dict__)
  result=module.list_listings(account,{})
  summary={'account_id':account_id,'provider':provider,'list_ok':result.ok,'error_code':result.error_type,'http_status':result.status_code}
  if AUTHORIZATION and provider=='mercadolivre':
   import requests
   from nistiprint_shared.services.marketplace_http import request_json
   from nistiprint_shared.services.platform_drivers.mercadolivre import _auth_headers,ML_API_HOST
   profile=account.get('app_profile') or {}
   config=account.get('config') or {}
   app_id=config.get('client_id') or config.get('app_id') or profile.get('client_id')
   summary.update(app_profile_id=account.get('app_profile_id'),app_profile_name=profile.get('name'),application_id=str(app_id) if app_id else None,configured_redirect_uri=profile.get('redirect_uri'))
   me=module._get(account,'/users/me')
   if app_id and str(app_id).isdigit():
    app=module._get(account,'/applications/'+str(app_id))
    summary['application_http_status']=app.status_code
    if app.ok:
     value=app.value
     summary['application']={key:value.get(key) for key in ('id','name','site_id','active','sandbox_mode','scopes','date_created','redirect_uri','redirect_uris','callback_url','callback_urls','pkce_enabled') if key in value}
   if me.ok:
    reserve=account.get('_catalog_reserve')
    if reserve: reserve()
    grants=request_json(requests.get,ML_API_HOST+'/users/'+str(me.value['id'])+'/applications',provider='mercadolivre',resource_type='verification',list_key='grants',headers=_auth_headers(account))
    summary['grant_http_status']=grants.status_code
    if grants.ok:
     data=grants.value or {}
     entries=data.get('grants') or data.get('applications') or []
     summary['matching_grants']=[{key:entry.get(key) for key in ('app_id','date_created','scopes') if key in entry} for entry in entries if str(entry.get('app_id'))==str(app_id)]
  if not result.ok and provider=='mercadolivre':
   identity=module._get(account,'/users/me')
   summary.update(identity_ok=identity.ok,identity_http_status=identity.status_code,identity_error=identity.error_type)
   capability=module.get_catalog_capabilities(account)
   if identity.ok and capability.ok:
    summary['seller_matches_token']=str(identity.value.get('id'))==str(capability.value.get('seller_id'))
   if isinstance(result.details,dict):
    summary.update(provider_code=result.provider_code,provider_error=result.details.get('error'),provider_cause=result.details.get('code'))
  if result.ok:
   ids=result.value.get('item_ids') or []
   summary.update(page_items=len(ids),page_complete=result.value.get('complete'))
   if ids:
    details=module.get_listing_details(account,ids[:1])
    summary.update(details_ok=details.ok,details_error=details.error_type)
    if details.ok:
     listing=details.value['listings'][0]
     summary.update(units=len(listing['unidades']),has_sku=any(u.get('sku_externo') for u in listing['unidades']))
    if provider=='shopee':
     metrics=module._get(account,'/api/v2/product/get_item_extra_info',{'item_id_list':ids[0]})
     summary.update(statistics_ok=metrics.ok,statistics_error=metrics.error_type)
     if metrics.ok:
      entries=metrics.value.get('item_list') or []
      summary['counter_fields']=sorted({key for entry in entries for key in ('sale','views','likes') if key in entry})
  print(json.dumps(summary),flush=True)
 except Exception as exc:
  print(json.dumps({'account_id':account_id,'status':'failed','error_class':type(exc).__name__}),flush=True)
'''
    command = [args.ssh,'-o','BatchMode=yes','-o','ConnectTimeout=10','-i',args.identity,args.host,
               'cd /opt/nistiprint && .venv/bin/python -']
    return subprocess.run(command, input=program.encode()).returncode


if __name__ == '__main__':
    raise SystemExit(main())
