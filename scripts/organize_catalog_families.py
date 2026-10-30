"""Refresh existing multi-product announcements and organize their families.

Runs reviewed adapters in memory on the application host, without deploying.
Only public catalog attributes and family structure are written. Private audit
evidence is stored in the requested output; credentials are never printed.
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
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sources = {provider: base64.b64encode((root / f'packages/shared/nistiprint_shared/services/platform_drivers/{provider}_catalog.py').read_bytes()).decode() for provider in ('shopee','mercadolivre')}
    program = 'SOURCES=' + repr(sources) + '\n' + r'''
import base64,json,logging,sys,types,time
from collections import Counter,defaultdict
from dotenv import load_dotenv
load_dotenv('/opt/nistiprint/.env')
logging.disable(logging.CRITICAL)
from nistiprint_shared.database.supabase_db_service import supabase_db as db
from nistiprint_shared.services.credential_resolver_service import credential_resolver_service
def emit(kind,**data):print(json.dumps(dict(kind=kind,**data),default=str),flush=True)
def rows(table):
 result=[];offset=0
 while True:
  batch=db.table(table).select('*').order('id').range(offset,offset+499).execute().data or []
  result.extend(batch)
  if len(batch)<500:return result
  offset+=500
units=rows('produto_anuncios');headers={h['id']:h for h in rows('marketplace_anuncios')}
groups=defaultdict(set)
for u in units:
 if u.get('produto_id'):groups[u.get('anuncio_id')].add(u['produto_id'])
selected={aid for aid,products in groups.items() if len(products)>1}
emit('before',products=rows('produtos'),bom=rows('ficha_tecnica'))
counts=Counter()
for account in rows('installed_integrations'):
 provider=(account.get('platform_slug') or account.get('module_id') or '').lower()
 if not account.get('is_active') or provider not in SOURCES:continue
 name='nistiprint_shared.services.platform_drivers.'+provider+'_catalog'
 module=types.ModuleType(name);module.__package__='nistiprint_shared.services.platform_drivers';sys.modules[name]=module
 exec(compile(base64.b64decode(SOURCES[provider]),'<reviewed_adapter>','exec'),module.__dict__)
 integration=credential_resolver_service.hydrate_integration(account)
 for aid in sorted(selected):
  h=headers.get(aid)
  if not h or h['integration_id']!=account['id'] or h.get('absent_since'):continue
  result=module.get_listing_details(integration,[h['item_externo_id']])
  if not result.ok or result.partial:
   emit('refresh_failed',anuncio_id=aid,error=result.error_type);counts['refresh_failed']+=1;continue
  listings=(result.value or {}).get('listings') or []
  if len(listings)!=1:raise RuntimeError('Incomplete listing response')
  for unit in listings[0]['unidades']:
   match=[u for u in units if u.get('anuncio_id')==aid and str(u.get('variacao_externa_id') or '')==str(unit.get('variacao_externa_id') or '')]
   if len(match)!=1:raise RuntimeError('Ambiguous unit identity')
   db.table('produto_anuncios').update({'atributos_variacao':unit.get('atributos_variacao') or {}}).eq('id',match[0]['id']).execute()
  outcome=db.rpc('catalogo_organizar_anuncio',{'p_anuncio':aid}).execute().data
  counts[outcome['status']]+=1;emit('organized',anuncio_id=aid,result=outcome)
  repeated=db.rpc('catalogo_organizar_anuncio',{'p_anuncio':aid}).execute().data
  if repeated['status'] not in ('unchanged','pending','ignored'):raise RuntimeError('Idempotence failure')
  time.sleep(.2)
emit('after',products=rows('produtos'),bom=rows('ficha_tecnica'))
emit('complete',counts=dict(counts))
'''
    command = ['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10','-i',args.identity,args.host,'cd /opt/nistiprint && .venv/bin/python -']
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('w',encoding='utf-8') as output:
        process = subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,encoding='utf-8')
        process.stdin.write(program)
        process.stdin.close()
        for line in process.stdout:
            row=json.loads(line);output.write(line);output.flush()
            print(json.dumps({k:v for k,v in row.items() if k not in ('products','bom')},ensure_ascii=False),flush=True)
        if process.wait():raise RuntimeError('Remote organization failed; inspect private evidence before retry')


if __name__ == '__main__':
    main()
