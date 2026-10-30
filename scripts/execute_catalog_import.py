"""Apply a reviewed one-off manifest through existing domain services over SSH.

Source modules are loaded in memory only. Never deploys files, alters providers,
adjusts stock, or reassigns historical order facts. Audits stay in a private file.
"""
import argparse
import base64
import json
from pathlib import Path
import subprocess


REMOTE = r'''
import base64,copy,json,logging,sys,types
from dotenv import load_dotenv
load_dotenv('/opt/nistiprint/.env');logging.disable(logging.CRITICAL)
from nistiprint_shared.database.supabase_db_service import supabase_db as db
def emit(event,**data):print(json.dumps(dict(event=event,**data),ensure_ascii=False,default=str),flush=True)
def load(name,source):
 full='nistiprint_shared.services.'+name
 module=types.ModuleType(full);module.__package__='nistiprint_shared.services';sys.modules[full]=module
 exec(compile(base64.b64decode(source),'<reviewed_import_'+name+'>','exec'),module.__dict__)
 return module
family_module=load('catalogo_familia_service',SOURCES['catalogo_familia_service'])
product_module=load('product_service',SOURCES['product_service'])
bom_module=load('bom_service',SOURCES['bom_service'])
products=product_module.product_service;bom=bom_module.bom_service
from nistiprint_shared.services.category_service import category_service
manifest=json.loads(base64.b64decode(MANIFEST))
def all_rows(table):
 result=[]
 for start in range(0,1000000,500):
  batch=db.table(table).select('*').order('id').range(start,start+499).execute().data or []
  result.extend(batch)
  if len(batch)<500:return result
 raise RuntimeError('inventory_limit')
inventory=all_rows('produtos');by_id={p['id']:p for p in inventory};by_sku={p['sku']:p for p in inventory}
if any((p.get('atributos') or {}).get('catalog_merged_into') for p in inventory) and not IMAGES_ONLY:
 raise ValueError('Catalog was consolidated after this import. Use the reviewed revision plan; do not replay the original manifest.')
if IMAGES_ONLY:
 count=0
 keyed={((p.get('atributos') or {}).get('importacao_catalogo') or {}).get('key'):p for p in inventory}
 for record in manifest['products']:
  if record.get('component_only'):continue
  p=keyed.get(record['key'])
  if not p:continue
  preferred=list(dict.fromkeys(url for s in record['sources'] for url in s['unit']['images']))
  attrs=copy.deepcopy(p.get('atributos') or {});current=attrs.get('images') or []
  desired=preferred+[url for url in current if url not in preferred]
  if desired!=current:
   emit('before_image_order',product_id=p['id'],before=current)
   attrs['images']=desired
   db.table('produtos').update({'atributos':attrs}).eq('id',p['id']).execute()
   emit('image_order',product_id=p['id']);count+=1
 emit('complete_images',updated=count);sys.exit(0)
if manifest.get('version',1)<2 and any(str(((p.get('atributos') or {}).get('importacao_catalogo') or {}).get('key','')).startswith('pi:') for p in inventory):
 raise ValueError('Stale manifest: use the PA-PI-MP manifest after the hierarchy phase')
categories={c['nome']:c['id'] for c in all_rows('categorias')}
for name in sorted({p['category_name'] for p in manifest['products'] if p.get('category_name')}):
 if name not in categories:
  row=category_service.create({'name':name,'description':'Categoria para produtos identificados na importação inicial do catálogo.','comercializavel':True,'componente':False})
  categories[name]=row['id'];emit('create_category',category_id=row['id'],name=name)
for record in manifest['products']:
 if record.get('category_name'):record['category_id']=categories[record['category_name']]
planned_products={p['key']:p for p in manifest['products']}
for family in manifest['families']:
 family['category_id']=planned_products[family['children'][0]]['category_id']
resolved={};created=set();run=manifest['run_id']
def provenance(p):return ((p.get('atributos') or {}).get('importacao_catalogo') or {})
by_key={provenance(p).get('key'):p for p in inventory if provenance(p).get('key') and not (p.get('parent_id') and provenance(p).get('key','').startswith('family:'))}
def create_record(record,role='individual'):
 key=record['key'];existing=by_key.get(key)
 if record.get('existing_id'):
  existing=by_id.get(record['existing_id'])
  if not existing:raise ValueError('existing_product_missing')
 if not existing and record['sku'] in by_sku:
  existing=by_sku[record['sku']]
  if provenance(existing).get('key')!=key:raise ValueError('sku_conflict_after_preview')
 if existing:
  resolved[key]=existing['id'];emit('reuse',key=key,product_id=existing['id']);return existing
 source=(record.get('sources') or [{}])[0]
 payload={'sku':record['sku'],'name':record['name'],'description':record.get('description_override') or source.get('description') or '',
  'category_id':record['category_id'],'unit_of_measure_id':2,'material_type':record.get('material_type','produto_acabado'),
  'status':'inativo','formato':'com_variacao' if role=='modelo' else 'kit' if record.get('structure')=='kit' else 'composicao' if record.get('structure')=='manufaturado' else 'simples',
  'papel_catalogo':role,'estrutura':record.get('structure','manufaturado'),
  'import_metadata':{'run_id':run,'key':key,'status':'em_preparo'}}
 p=products.create(payload)
 if not p:raise RuntimeError('product_create_empty')
 resolved[key]=p['id'];by_key[key]=p;by_id[p['id']]=p;by_sku[p['sku']]=p;created.add(p['id'])
 emit('create',key=key,product_id=p['id'],sku=p['sku']);return p
# Ensure parents are created before canonical family transactions.
for family in manifest['families']:
 try:
  p=create_record(dict(family,structure='manufaturado'),role='modelo')
  children=[r for r in manifest['products'] if r['key'] in family['children']]
  parent_attrs=copy.deepcopy(p.get('atributos') or {})
  family_images=list(parent_attrs.get('images') or [])
  for child in children:
   for source in child['sources']:
    for url in source['images']:
     if url and url not in family_images:family_images.append(url)
  if family_images!=parent_attrs.get('images'):
   emit('before_model_images',product_id=p['id'],before=parent_attrs)
   parent_attrs['images']=family_images
   db.table('produtos').update({'atributos':parent_attrs}).eq('id',p['id']).execute()
   p['atributos']=parent_attrs
  for r in children:
   recovered=by_sku.get(r['sku'])
   if r['key'] not in by_key and recovered and recovered.get('parent_id')==p['id']:
    attrs=recovered.get('atributos') or {};attrs['importacao_catalogo']={'run_id':run,'key':r['key'],'status':'em_preparo'}
    db.table('produtos').update({'atributos':attrs}).eq('id',recovered['id']).execute()
    recovered['atributos']=attrs;by_key[r['key']]=recovered
  missing=[r for r in children if r['key'] not in by_key]
  if missing:
   variants=[{'sku':r['sku'],'nome':r['name'],'descricao':r['sources'][0]['description'],'status':'inativo','variation_values':r['variation_values'],'tipo_material':'produto_acabado','unidade_medida_id':2,'herdar_bom_pai':False} for r in missing]
   family_module.CatalogoFamiliaService(db).save(p['id'],{'expected_version':p.get('catalogo_versao',1),'eixos':family['axes'],'variacoes':variants})
   for r in missing:
    row=db.table('produtos').select('*').eq('sku',r['sku']).single().execute().data
    attrs=row.get('atributos') or {};attrs['importacao_catalogo']={'run_id':run,'key':r['key'],'status':'em_preparo'}
    db.table('produtos').update({'atributos':attrs,'preco_custo':None,'preco_venda':None,'precificacao':{'cost_price':None,'price':None}}).eq('id',row['id']).execute()
    row['atributos']=attrs;by_key[r['key']]=row;by_id[row['id']]=row;by_sku[r['sku']]=row;created.add(row['id'])
    emit('create_variant',key=r['key'],product_id=row['id'],parent_id=p['id'])
 except Exception as exc:
  emit('error',stage='family',key=family['key'],error=type(exc).__name__,message=str(exc)[:220]);raise
for record in manifest['products']:
 try:create_record(record)
 except Exception as exc:emit('error',stage='create',key=record['key'],error=type(exc).__name__,message=str(exc)[:220]);raise
# Enrichment is append-only; preserve every populated internal field.
for record in manifest['products']:
 try:
  pid=resolved[record['key']]
  p=db.table('produtos').select('*').eq('id',pid).single().execute().data
  if record.get('ensure_structure') and p.get('estrutura')!=record['ensure_structure']:
   if provenance(p).get('run_id')!=run or p.get('status')!='inativo':raise ValueError('Structure correction is limited to inactive imported products')
   emit('before_structure',product_id=pid,before={'estrutura':p.get('estrutura'),'formato':p.get('formato'),'status':p.get('status')})
   products.update(str(pid),{'estrutura':record['ensure_structure'],'formato':record['ensure_structure'],'status':'inativo'})
   db.table('produtos').update({'status':'inativo'}).eq('id',pid).execute()
   products.clear_cache()
   p=db.table('produtos').select('*').eq('id',pid).single().execute().data
  before=copy.deepcopy({'atributos':p.get('atributos'),'descricao':p.get('descricao')})
  attrs=p.get('atributos') or {};images=list(attrs.get('images') or [])
  sources=record.get('sources') or []
  if not record.get('component_only'):
   for s in sources:
    for url in s['unit']['images']+s['images']:
     if url and url not in images:images.append(url)
   if provenance(p).get('key')==record['key']:
    preferred=list(dict.fromkeys(url for s in sources for url in s['unit']['images']))
    images=preferred+[url for url in images if url not in preferred]
  if images:attrs['images']=images
  evidence=attrs.get('catalog_import_sources') or []
  for s in sources:
   identity={'account_id':s['account_id'],'item_id':s['item_id'],'variation_id':s['unit']['id']}
   if identity not in evidence:evidence.append(identity)
  attrs['catalog_import_sources']=evidence
  attrs['catalog_import_pending']=list(dict.fromkeys((attrs.get('catalog_import_pending') or [])+record['pending']))
  changes={'atributos':attrs}
  if record.get('category_name') and provenance(p).get('key')==record['key'] and p.get('categoria_id')!=record['category_id']:
   emit('before_category',product_id=pid,before=p.get('categoria_id'))
   changes['categoria_id']=record['category_id']
  if not p.get('descricao') and sources and sources[0]['description']:changes['descricao']=record.get('description_override') or sources[0]['description']
  if record.get('description_override') and provenance(p).get('key')==record['key'] and sources and p.get('descricao')==sources[0]['description']:
   changes['descricao']=record['description_override']
  if changes['atributos']!=before['atributos'] or 'descricao' in changes or 'categoria_id' in changes:
   emit('before_enrich',product_id=pid,before=before)
   db.table('produtos').update(changes).eq('id',pid).execute()
  # Pending rows are visible through the existing family/catalog contract.
  if record['pending']:
   pending=db.table('produto_catalogo_pendencias').select('id').eq('produto_id',pid).eq('codigo','IMPORTACAO_FICHA_PENDENTE').is_('resolved_at','null').execute().data or []
   if not pending:db.table('produto_catalogo_pendencias').insert({'produto_id':pid,'produto_pai_id':p.get('parent_id') or pid,'codigo':'IMPORTACAO_FICHA_PENDENTE','detalhes':{'run_id':run,'itens':record['pending'],'fontes':evidence}}).execute()
  existing=db.table('ficha_tecnica').select('*').eq('produto_pai_id',pid).execute().data or []
  for line in record['bom']:
   cid=line.get('existing_id') or resolved.get(line.get('key')) or (by_key.get(line.get('key')) or {}).get('id')
   if not cid:raise ValueError('BOM component was not resolved: '+str(line.get('key')))
   current=[b for b in existing if b['componente_id']==cid]
   if current:
    if any(float(b['quantidade_necessaria'])!=float(line['quantity']) for b in current):emit('conflict',stage='bom',product_id=pid,component_id=cid)
    continue
   # Respect effective inheritance too, not just local lines.
   effective=db.rpc('bom_efetiva_produto',{'p_produto_id':pid}).execute().data or []
   if any(b['componente_id']==cid for b in effective):continue
   bom.add_bom_component(pid,cid,line['quantity'],line['unit'],recalculate_cost=False)
   emit('bom_add',product_id=pid,component_id=cid,quantity=line['quantity'],evidence=line['evidence'])
  for move in record.get('move_bom',[]):
   if p.get('status')!='inativo' or provenance(p).get('run_id')!=run:
    raise ValueError('BOM transfer is limited to inactive products created by this import')
   matches=db.table('ficha_tecnica').select('*').eq('id',move['line_id']).execute().data or []
   if not matches:continue
   original=matches[0]
   if original['produto_pai_id']!=pid or original['componente_id']!=move['component_id'] or float(original['quantidade_necessaria'])!=float(move['quantity']) or original['unidade_medida']!=move['unit']:
    raise ValueError('BOM transfer source changed')
   target=resolved[move['target_key']]
   destination=db.table('ficha_tecnica').select('*').eq('produto_pai_id',target).eq('componente_id',move['component_id']).execute().data or []
   if len(destination)!=1 or float(destination[0]['quantidade_necessaria'])!=float(move['quantity']) or destination[0]['unidade_medida']!=move['unit']:
    raise ValueError('BOM transfer destination not confirmed')
   emit('before_bom_transfer',product_id=pid,before=original,target_pi_id=target)
   db.table('ficha_tecnica').delete().eq('id',original['id']).execute()
   emit('bom_transfer',product_id=pid,component_id=move['component_id'],target_pi_id=target)
  readiness=db.rpc('produto_dominio_prontidao',{'p_produto_id':pid}).execute().data
  emit('validated',key=record['key'],product_id=pid,pending=len(record['pending']),readiness=readiness)
 except Exception as exc:emit('error',stage='enrich',key=record['key'],error=type(exc).__name__,message=str(exc)[:220]);raise
# Persist observations through the existing transactional catalog RPC, without
# claiming a full sweep or overwriting its checkpoint with an import cursor.
old_headers={(h['integration_id'],h['item_externo_id']):h for h in all_rows('marketplace_anuncios')}
for account_id in sorted({i['account_id'] for i in manifest['items']}):
 items=[i for i in manifest['items'] if i['account_id']==account_id]
 for start in range(0,len(items),20):
  claim=db.rpc('marketplace_catalog_sync_claim',{'p_account':account_id}).execute().data or {}
  if claim.get('status')=='busy':raise RuntimeError('catalog_sync_busy')
  headers=[]
  for i in items[start:start+20]:
   status=i['status'];normalized={'NORMAL':'ativo','UNLIST':'pausado','BANNED':'em_revisao','DELETED':'encerrado','SELLER_DELETE':'encerrado','SHOPEE_DELETE':'encerrado','active':'ativo','paused':'pausado','closed':'encerrado','under_review':'em_revisao'}.get(status,'desconhecido')
   header=dict(old_headers.get((account_id,i['item_id'])) or {})
   header.update({key:i[key] for key in ('url','provider_updated_at','user_product_id','familia_externa_id','catalogo_externo_id') if i.get(key) is not None})
   header.update({'item_externo_id':i['item_id'],'titulo':i['title'],'imagem_comercial':i['images'][0] if i['images'] else None,'situacao_original':status,'situacao_normalizada':normalized,'unidades':[{'variacao_externa_id':u['id'],'sku_externo':u['sku'],'atributos_variacao':u['attributes'],'preco_observado':u.get('price'),'disponibilidade_observada':u.get('available')} for u in i['units']]})
   headers.append(header)
  result=db.rpc('marketplace_catalog_sync_store_page',{'p_account':account_id,'p_owner_token':claim['owner_token'],'p_rows':headers,'p_checkpoint':claim.get('checkpoint') or {},'p_complete':False}).execute().data
  if not result:raise RuntimeError('catalog_lease_lost')
  emit('observations',account_id=account_id,items=len(headers))
# Link current units only. Confirmed links are never silently replaced.
for record in manifest['products']:
 if record.get('component_only'):continue
 for source in record['sources']:
  rows=db.table('produto_anuncios').select('*').eq('integration_id',source['account_id']).eq('item_externo_id',source['item_id']).execute().data or []
  rows=[u for u in rows if str(u.get('variacao_externa_id') or '')==source['unit']['id']]
  if len(rows)!=1:raise RuntimeError('listing_unit_not_unique')
  unit=rows[0];pid=resolved[record['key']]
  if unit.get('produto_id')==pid:emit('link_unchanged',unit_id=unit['id'],product_id=pid);continue
  if unit.get('produto_id') is not None:emit('conflict',stage='link',unit_id=unit['id'],expected=pid,current=unit['produto_id']);continue
  result=db.rpc('marketplace_anuncio_vincular',{'p_unidade_id':unit['id'],'p_produto_id':pid,'p_motivo':'Importação inicial; imagens, descrição e variação revisadas. '+run,'p_origem':'confirmado','p_usuario':None,'p_expected_version':unit['vinculo_versao']}).execute().data
  emit('link',unit_id=unit['id'],product_id=pid,result=result)
emit('complete',products=len(resolved),created=len(created),items=len(manifest['items']))
'''


def subset(manifest, ids):
    selected={r['key'] for r in manifest['products'] if not r.get('component_only') and any(s['item_id'] in ids for s in r['sources'])}
    families=[f for f in manifest['families'] if selected.intersection(f['children'])]
    for f in families:selected.update(f['children'])
    products={r['key']:r for r in manifest['products']}
    for key in list(selected):selected.update(b['key'] for b in products[key]['bom'] if 'key' in b)
    result={**manifest,'products':[r for r in manifest['products'] if r['key'] in selected],'families':families}
    source_ids={(s['account_id'],s['item_id']) for r in result['products'] for s in r['sources']}
    result['items']=[i for i in manifest['items'] if (i['account_id'],i['item_id']) in source_ids]
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--audit',type=Path,required=True)
    parser.add_argument('--host',required=True)
    parser.add_argument('--identity',required=True)
    parser.add_argument('--items',help='Optional comma-separated pilot listing IDs')
    parser.add_argument('--apply',action='store_true',help='Explicitly apply the reviewed manifest')
    parser.add_argument('--images-only',action='store_true',help='Only prioritize variant images on products created by this import')
    args=parser.parse_args()
    manifest=json.loads(args.manifest.read_text(encoding='utf-8'))
    if args.items:manifest=subset(manifest,set(args.items.split(',')))
    if not args.apply:
        print(json.dumps({'dry_run':True,'items':len(manifest['items']),'products':len(manifest['products']),'families':len(manifest['families'])}));return
    root=Path(__file__).resolve().parents[1]
    sources={name:base64.b64encode((root / f'packages/shared/nistiprint_shared/services/{name}.py').read_bytes()).decode() for name in ('product_service','bom_service','catalogo_familia_service')}
    program='SOURCES='+repr(sources)+'\nMANIFEST='+repr(base64.b64encode(json.dumps(manifest).encode()).decode())+'\nIMAGES_ONLY='+repr(args.images_only)+'\n'+REMOTE
    args.audit.parent.mkdir(parents=True,exist_ok=True)
    command=['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10','-i',args.identity,args.host,'cd /opt/nistiprint && .venv/bin/python -']
    with args.audit.open('a',encoding='utf-8') as audit:
        process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,encoding='utf-8')
        process.stdin.write(program);process.stdin.close()
        for line in process.stdout:
            audit.write(line);audit.flush()
            try:
                event=json.loads(line)
                print(json.dumps({k:v for k,v in event.items() if k not in ('before','readiness','result')},ensure_ascii=False),flush=True)
            except json.JSONDecodeError:print('Non-JSON output recorded in private audit.',flush=True)
        return process.wait()


if __name__=='__main__':raise SystemExit(main())
