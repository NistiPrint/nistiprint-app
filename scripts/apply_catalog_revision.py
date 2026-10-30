"""Apply a private reviewed correction plan using existing services over SSH."""
import argparse
import base64
import json
from pathlib import Path
import subprocess

REMOTE=r'''
import base64,copy,json,logging,sys,types
from datetime import datetime,timezone
from dotenv import load_dotenv
load_dotenv('/opt/nistiprint/.env');logging.disable(logging.CRITICAL)
from nistiprint_shared.database.supabase_db_service import supabase_db as db
def emit(event,**data):print(json.dumps(dict(event=event,**data),ensure_ascii=False,default=str),flush=True)
def load(name,source):
 full='nistiprint_shared.services.'+name
 module=types.ModuleType(full);module.__package__='nistiprint_shared.services';sys.modules[full]=module
 exec(compile(base64.b64decode(source),'<catalog_revision_'+name+'>','exec'),module.__dict__)
 return module
load('catalogo_familia_service',SOURCES['catalogo_familia_service'])
product_module=load('product_service',SOURCES['product_service'])
bom_module=load('bom_service',SOURCES['bom_service'])
products=product_module.product_service;bom=bom_module.bom_service
plan=json.loads(base64.b64decode(PLAN));run=plan['run_id']
def all_rows(table):
 result=[]
 for start in range(0,1000000,500):
  rows=db.table(table).select('*').order('id').range(start,start+499).execute().data or []
  result.extend(rows)
  if len(rows)<500:return result
 raise ValueError('inventory_limit')
inventory=all_rows('produtos');by_id={p['id']:p for p in inventory}
lines=all_rows('ficha_tecnica')
def fresh(pid):
 p=db.table('produtos').select('*').eq('id',pid).single().execute().data
 if not p:raise ValueError('product_missing:'+str(pid))
 return p
def write_attrs(pid,attrs,**extra):
 result=db.table('produtos').update(dict(atributos=attrs,**extra)).eq('id',pid).execute().data
 if not result:raise ValueError('empty_update')
 by_id[pid]=result[0]
def prove_own(p):
 if ((p.get('atributos') or {}).get('importacao_catalogo') or {}).get('run_id')!=run or p['status']=='ativo':raise ValueError('not_own_inactive:'+str(p['id']))
paper_ref=next(b for b in lines if b['produto_pai_id']==7 and b['componente_id']==5)
ink_ref=next(b for b in lines if b['produto_pai_id']==7 and b['componente_id']==6)
if abs(float(ink_ref['quantidade_necessaria'])/float(paper_ref['quantidade_necessaria'])-.017)>1e-8:raise ValueError('ink_reference_changed')
emit('reference_verified',core_id=7,paper=paper_ref,ink=ink_ref)
for merge in plan['merges']:
 source=fresh(merge['source']);target=fresh(merge['target']);prove_own(source)
 if any(b['componente_id']==source['id'] for b in lines):raise ValueError('merge_source_has_incoming_bom:'+str(source['id']))
 sa=copy.deepcopy(source.get('atributos') or {});ta=copy.deepcopy(target.get('atributos') or {})
 if sa.get('catalog_merged_into') not in (None,target['id']):raise ValueError('merge_destination_changed')
 units=db.table('produto_anuncios').select('*').eq('produto_id',source['id']).execute().data or []
 for unit in units:
  emit('before_link',before=unit,target=target['id'])
  db.rpc('marketplace_anuncio_vincular',{'p_unidade_id':unit['id'],'p_produto_id':target['id'],'p_motivo':'Consolidação revista: mesmo SKU, capa e especificações compatíveis. '+run,'p_origem':'confirmado','p_usuario':None,'p_expected_version':unit['vinculo_versao']}).execute()
  emit('link',unit_id=unit['id'],source=source['id'],target=target['id'])
 aliases=ta.setdefault('catalog_import_alias_keys',[])
 key=(sa.get('importacao_catalogo') or {}).get('key')
 if key and key not in aliases:aliases.append(key)
 for field in ('images','catalog_import_sources'):
  values=ta.setdefault(field,[])
  for value in sa.get(field) or []:
   if value not in values:values.append(value)
 merged=ta.setdefault('catalog_merged_product_ids',[])
 if source['id'] not in merged:merged.append(source['id'])
 if ta!=target.get('atributos'):emit('before_product',before=target);write_attrs(target['id'],ta)
 if not sa.get('catalog_merged_into'):
  emit('before_product',before=source)
  sa['catalog_merged_into']=target['id'];sa['catalog_merge_evidence']=merge['evidence'];sa['catalog_original_sku']=source['sku'];sa['catalog_original_name']=source['nome']
  products.delete(str(source['id']))
  write_attrs(source['id'],sa,nome=('Consolidado em '+target['sku']+' — '+source['nome'])[:255])
  emit('merge',source=source['id'],target=target['id'])
for change in plan['renames']:
 p=fresh(change['id']);prove_own(p)
 if p['sku']==change['after']:continue
 if p['sku']!=change['before']:raise ValueError('sku_changed_since_review')
 emit('before_product',before=p)
 payload={'sku':change['after']}
 if p.get('parent_id'):payload['expected_version']=fresh(p['parent_id'])['catalogo_versao']
 products.update(str(p['id']),payload)
 # Preserve inactive status, independently of the service draft projection.
 db.table('produtos').update({'status':p['status']}).eq('id',p['id']).execute()
 updated=fresh(p['id']);attrs=copy.deepcopy(updated.get('atributos') or {})
 attrs['catalog_sku_revision']={'original_internal_sku':change['before'],'source_sku':change.get('source_sku'),'current_sku':change['after'],'reason':change.get('kind')}
 write_attrs(p['id'],attrs)
 db.table('produto_catalogo_pendencias').update({'resolved_at':datetime.now(timezone.utc).isoformat()}).eq('produto_id',p['id']).eq('codigo','SKU_OCUPADO').is_('resolved_at','null').execute()
 emit('rename',product_id=p['id'],sku=change['after'])
def add_line(pid,operation):
 current=db.table('ficha_tecnica').select('*').eq('produto_pai_id',pid).eq('componente_id',operation['component']).execute().data or []
 if len(current)>1:raise ValueError('duplicate_bom_line')
 if current and float(current[0]['quantidade_necessaria'])==operation['quantity'] and current[0]['unidade_medida']==operation['unit']:return
 before=operation.get('before')
 if current and (not before or current[0]['id']!=before['id'] or float(current[0]['quantidade_necessaria'])!=float(before['quantidade_necessaria']) or current[0]['unidade_medida']!=before['unidade_medida']):raise ValueError('bom_changed_since_review')
 if before and not current:raise ValueError('bom_removed_since_review')
 emit('before_bom',product_id=pid,before=current)
 bom.add_bom_component(pid,operation['component'],operation['quantity'],operation['unit'],recalculate_cost=False)
 emit('bom',product_id=pid,component=operation['component'],quantity=operation['quantity'],unit=operation['unit'])
for core in plan['cores']:
 for operation in core['operations']:add_line(core['id'],operation)
 p=fresh(core['id']);attrs=copy.deepcopy(p.get('atributos') or {})
 proof={'pages':core['pages'],'sheets':core['sheets'],'rule':'ceil(pages/4)','ink_reference_core_id':7,'ink_per_sheet':.017}
 if attrs.get('catalog_core_consumption')!=proof:emit('before_product',before=p);attrs['catalog_core_consumption']=proof;write_attrs(p['id'],attrs)
for core in plan['split_cores']:
 rows=db.table('produtos').select('*').eq('sku',core['sku']).execute().data or []
 if rows:
  p=rows[0]
  if ((p.get('atributos') or {}).get('importacao_catalogo') or {}).get('key')!=core['key']:raise ValueError('split_sku_taken')
 else:
  p=products.create({'sku':core['sku'],'name':core['name'],'description':'Miolo separado por tipo, páginas e pauta; regra de consumo confirmada pelo usuário.','category_id':6,'unit_of_measure_id':2,'material_type':'intermediario','status':'inativo','formato':'composicao','estrutura':'manufaturado','import_metadata':{'run_id':run,'key':core['key'],'status':'em_preparo'}})
  if not p:raise ValueError('create_empty')
  emit('create_core',product_id=p['id'],key=core['key'],sku=core['sku'])
 for component,quantity in ((5,core['sheets']),(6,core['ink'])):add_line(p['id'],{'component':component,'quantity':quantity,'unit':'un','before':None})
 for source in core['sources']:
  pa=fresh(source['pa_id']);prove_own(pa)
  old=source['original_line']
  add_line(pa['id'],{'component':p['id'],'quantity':float(old['quantidade_necessaria']),'unit':old['unidade_medida'],'before':None})
  old_rows=db.table('ficha_tecnica').select('*').eq('id',old['id']).execute().data or []
  if old_rows:
   if any(old_rows[0].get(k)!=old.get(k) for k in ('produto_pai_id','componente_id','quantidade_necessaria','unidade_medida')):raise ValueError('old_line_changed')
   emit('before_core_transfer',before=old_rows[0],target_core=p['id'])
   db.table('ficha_tecnica').delete().eq('id',old['id']).eq('produto_pai_id',pa['id']).execute()
   emit('core_transfer',pa_id=pa['id'],source_core=old['componente_id'],target_core=p['id'])
 attrs=copy.deepcopy(fresh(p['id']).get('atributos') or {})
 attrs['catalog_core_consumption']={'pages':core['pages'],'sheets':core['sheets'],'rule':'ceil(pages/4)','ink_reference_core_id':7,'ink_per_sheet':.017}
 attrs['catalog_core_source_pa_ids']=sorted(set(source['pa_id'] for source in core['sources']))
 attrs['catalog_import_pending']=['Confirmar arquivo de impressão e demais especificações industriais. Papel e tinta preenchidos conforme regra informada pelo usuário.']
 write_attrs(p['id'],attrs)
for pending in plan['pending']:
 for pid in pending['products']:
  if pid not in by_id:continue
  if (by_id[pid].get('atributos') or {}).get('catalog_merged_into'):continue
  exists=db.table('produto_catalogo_pendencias').select('id').eq('produto_id',pid).eq('codigo',pending['code']).is_('resolved_at','null').execute().data or []
  if not exists:
   db.table('produto_catalogo_pendencias').insert({'produto_id':pid,'produto_pai_id':by_id[pid].get('parent_id') or pid,'codigo':pending['code'],'detalhes':pending}).execute()
   emit('pending',product_id=pid,code=pending['code'])
products.clear_cache()
emit('complete',merges=len(plan['merges']),cores=len(plan['cores']),split_cores=len(plan['split_cores']))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--audit',type=Path,required=True)
    parser.add_argument('--host',required=True)
    parser.add_argument('--identity',required=True)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    plan=json.loads(args.plan.read_text(encoding='utf-8'))
    if not args.apply:print(json.dumps({k:len(v) for k,v in plan.items() if isinstance(v,list)}));return 0
    root=Path(__file__).resolve().parents[1]
    sources={name:base64.b64encode((root/f'packages/shared/nistiprint_shared/services/{name}.py').read_bytes()).decode() for name in ('product_service','bom_service','catalogo_familia_service')}
    program='SOURCES='+repr(sources)+'\nPLAN='+repr(base64.b64encode(json.dumps(plan).encode()).decode())+'\n'+REMOTE
    command=['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10','-i',args.identity,args.host,'cd /opt/nistiprint && .venv/bin/python -']
    with args.audit.open('a',encoding='utf-8') as audit:
        proc=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,encoding='utf-8')
        proc.stdin.write(program);proc.stdin.close()
        for line in proc.stdout:
            audit.write(line);audit.flush()
            try:
                event=json.loads(line)
                if not event['event'].startswith('before_'):print(json.dumps(event,ensure_ascii=False),flush=True)
            except json.JSONDecodeError:print('Non-JSON output saved in private audit.',flush=True)
        return proc.wait()


if __name__=='__main__':raise SystemExit(main())
