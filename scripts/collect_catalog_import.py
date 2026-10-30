"""Collect a private, resumable catalog evidence snapshot over SSH; no domain writes."""
import argparse
import base64
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True)
    parser.add_argument('--identity', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--provider', choices=['all', 'shopee', 'mercadolivre'], default='all')
    parser.add_argument('--shopee-status-index', type=int, choices=range(4), default=0)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sources = {p: base64.b64encode((root / f'packages/shared/nistiprint_shared/services/platform_drivers/{p}_catalog.py').read_bytes()).decode() for p in ('shopee', 'mercadolivre')}
    program = r'''
import base64,json,logging,sys,types,time
from dotenv import load_dotenv
load_dotenv('/opt/nistiprint/.env')
logging.disable(logging.CRITICAL)
from nistiprint_shared.database.supabase_db_service import supabase_db as db
from nistiprint_shared.services.credential_resolver_service import credential_resolver_service
def emit(kind, **data):
 print(json.dumps(dict(kind=kind,**data),ensure_ascii=False,default=str),flush=True)
def rows(table):
 result=[]
 for start in range(0,1000000,500):
  batch=db.table(table).select('*').order('id').range(start,start+499).execute().data or []
  result.extend(batch)
  if len(batch)<500:return result
 raise RuntimeError('inventory_limit')
for table in ('produtos','unidades_medida','ficha_tecnica','categorias','marketplace_anuncios','produto_anuncios'):
 try:emit('inventory',table=table,rows=rows(table))
 except Exception as exc:emit('error',stage='inventory',table=table,error=type(exc).__name__)
accounts=db.table('installed_integrations').select('*').eq('is_active',True).execute().data or []
for account in accounts:
 provider=(account.get('platform_slug') or account.get('module_id') or '').lower()
 if provider not in ('shopee','mercadolivre') or SELECTED not in ('all',provider):continue
 aid=account['id']
 emit('account',account_id=aid,provider=provider,name=account.get('instance_name'))
 try:
  integration=credential_resolver_service.hydrate_integration(account)
  name='nistiprint_shared.services.platform_drivers.'+provider+'_catalog'
  module=types.ModuleType(name);module.__package__='nistiprint_shared.services.platform_drivers';sys.modules[name]=module
  exec(compile(base64.b64decode(SOURCES[provider]),'<catalog_adapter>','exec'),module.__dict__)
  cursor={'status_index':START_STATUS,'offset':0} if provider=='shopee' and START_STATUS else {};seen=set();page=0
  while True:
   result=module.list_listings(integration,cursor)
   if not result.ok:
    emit('error',stage='list',account_id=aid,error=result.error_type,cursor=cursor);break
   page+=1
   for item_id in result.value['item_ids']:
    if item_id in seen:continue
    seen.add(item_id)
    if (aid,str(item_id)) in DONE:continue
    if provider=='mercadolivre':
     detail=module._get(integration,'/items/'+item_id,{'include_attributes':'all'})
     description=module._get(integration,'/items/'+item_id+'/description')
     if detail.ok:emit('item',account_id=aid,provider=provider,item_id=item_id,data=detail.value,description=description.value if description.ok else None,description_error=None if description.ok else description.error_type)
    else:
     detail=module._get(integration,'/api/v2/product/get_item_base_info',{'item_id_list':str(item_id)})
     if detail.ok:
      item=(detail.value.get('item_list') or [None])[0]
      models=module._get(integration,'/api/v2/product/get_model_list',{'item_id':int(item_id)}) if item and item.get('has_model') else None
      emit('item',account_id=aid,provider=provider,item_id=item_id,data=item,models=models.value if models and models.ok else None,models_error=models.error_type if models and not models.ok else None)
    if not detail.ok:emit('error',stage='detail',account_id=aid,item_id=item_id,error=detail.error_type)
    time.sleep(.15)
   emit('page',account_id=aid,page=page,seen=len(seen),complete=result.value['complete'],cursor=result.value['cursor'])
   if result.value['complete']:break
   next_cursor=result.value['cursor']
   if next_cursor==cursor:raise RuntimeError('cursor_stalled')
   cursor=next_cursor
 except Exception as exc:emit('error',stage='account',account_id=aid,error=type(exc).__name__)
'''
    args.output.parent.mkdir(parents=True, exist_ok=True)
    done = []
    if args.output.exists():
        for line in args.output.read_text(encoding='utf-8').splitlines():
            row = json.loads(line)
            if row['kind'] == 'item':
                done.append((row['account_id'], str(row['item_id'])))
    program = 'SOURCES=' + repr(sources) + '\nDONE=set(' + repr(done) + ')\nSELECTED=' + repr(args.provider) + '\nSTART_STATUS=' + repr(args.shopee_status_index) + '\n' + program
    command = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', '-i', args.identity, args.host, 'cd /opt/nistiprint && .venv/bin/python -']
    with args.output.open('a', encoding='utf-8') as output:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding='utf-8')
        process.stdin.write(program)
        process.stdin.close()
        for line in process.stdout:
            row = json.loads(line)
            output.write(line)
            output.flush()
            print(json.dumps({k: v for k, v in row.items() if k not in ('rows', 'data', 'description', 'models')}, ensure_ascii=False), flush=True)
        return process.wait()


if __name__ == '__main__':
    raise SystemExit(main())
