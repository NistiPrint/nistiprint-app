"""Read back a catalog import, reconcile its manifest, and write private reports."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import subprocess


REMOTE = '''
import json,logging
from dotenv import load_dotenv
load_dotenv('/opt/nistiprint/.env');logging.disable(logging.CRITICAL)
from nistiprint_shared.database.supabase_db_service import supabase_db as db
for table in ('produtos','ficha_tecnica','produto_anuncios','marketplace_anuncios','produto_catalogo_pendencias'):
 result=[]
 for start in range(0,1000000,500):
  batch=db.table(table).select('*').order('id').range(start,start+499).execute().data or []
  result.extend(batch)
  if len(batch)<500:break
 print(json.dumps({'table':table,'rows':result},ensure_ascii=False,default=str),flush=True)
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--host',required=True)
    parser.add_argument('--identity',required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    command=['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10','-i',args.identity,args.host,'cd /opt/nistiprint && .venv/bin/python -']
    result=subprocess.run(command,input=REMOTE.encode(),stdout=subprocess.PIPE,check=True)
    (args.output/'verification-snapshot.jsonl').write_bytes(result.stdout)
    current={r['table']:r['rows'] for r in map(json.loads,result.stdout.decode().splitlines())}
    baseline={}
    for line in args.baseline.read_text(encoding='utf-8').splitlines():
        row=json.loads(line)
        if row['kind']=='inventory':baseline.setdefault(row['table'],row['rows'])
    manifest=json.loads(args.manifest.read_text(encoding='utf-8'))
    products={p['id']:p for p in current['produtos']}
    by_key={((p.get('atributos') or {}).get('importacao_catalogo') or {}).get('key'):p for p in products.values()}
    units={(u['integration_id'],str(u['item_externo_id']),str(u.get('variacao_externa_id') or '')):u for u in current['produto_anuncios']}
    bom_by_product={}
    for line in current['ficha_tecnica']:bom_by_product.setdefault(line['produto_pai_id'],[]).append(line)
    errors=[];report=[];resolved={}
    for record in manifest['products']:
        product=products.get(record['existing_id']) if record.get('existing_id') else by_key.get(record['key'])
        if not product:errors.append({'code':'PRODUCT_MISSING','key':record['key']});continue
        resolved[record['key']]=product['id']
    for record in manifest['products']:
        pid=resolved.get(record['key'])
        if not pid:continue
        p=products[pid]
        if not record.get('existing_id') and p['status']=='ativo':errors.append({'code':'NEW_PRODUCT_ACTIVE','id':pid})
        for line in record['bom']:
            cid=line.get('existing_id') or resolved.get(line.get('key'))
            matches=[b for b in bom_by_product.get(pid,[]) if b['componente_id']==cid]
            if not matches:errors.append({'code':'BOM_LINE_MISSING','id':pid,'component':cid})
            elif len(matches)>1:errors.append({'code':'BOM_DUPLICATE','id':pid,'component':cid})
            elif float(matches[0]['quantidade_necessaria'])!=float(line['quantity']) or matches[0]['unidade_medida']!=line['unit']:
                errors.append({'code':'BOM_QUANTITY_OR_UNIT_MISMATCH','id':pid,'component':cid})
        if not record.get('existing_id'):
            expected={b.get('existing_id') or resolved.get(b.get('key')) for b in record['bom']}
            extra=[b['id'] for b in bom_by_product.get(pid,[]) if b['componente_id'] not in expected]
            if extra:errors.append({'code':'UNEXPECTED_BOM_LINE','id':pid,'lines':extra})
        if not record.get('component_only'):
            for s in record['sources']:
                unit=units.get((s['account_id'],s['item_id'],s['unit']['id']))
                if not unit or unit.get('produto_id')!=pid:errors.append({'code':'LINK_MISMATCH','key':record['key'],'source':[s['account_id'],s['item_id'],s['unit']['id']],'current':unit.get('produto_id') if unit else None})
            preferred=[url for s in record['sources'] for url in s['unit']['images']]
            actual=(p.get('atributos') or {}).get('images') or []
            if not record.get('existing_id') and preferred and (not actual or actual[0]!=preferred[0]):
                errors.append({'code':'VARIANT_PRIMARY_IMAGE_MISMATCH','id':pid})
        report.append({'produto_id':pid,'sku':p['sku'],'nome':p['nome'],'status':p['status'],
                       'tipo_produto':p.get('tipo_produto'),'papel_catalogo':p.get('papel_catalogo'),'estrutura':p.get('estrutura'),
                       'pi_funcao':record.get('pi_role',''),
                       'reutilizado':bool(record['existing_id']),'peca_interna':bool(record.get('component_only')),
                       'fontes':'; '.join(f"{s['account_id']}:{s['item_id']}:{s['unit']['id']}" for s in record['sources']),
                       'imagens':len((p.get('atributos') or {}).get('images') or []),
                       'composicao':'; '.join(f"{b.get('existing_id') or resolved.get(b.get('key'))} x {b['quantity']} {b['unit']}" for b in record['bom']),
                       'pendencias':' | '.join(record['pending'])})
    # All initial BOM lines and commercial/stock settings must survive intact.
    old_bom={b['id']:b for b in baseline['ficha_tecnica']};new_bom={b['id']:b for b in current['ficha_tecnica']}
    for bid,before in old_bom.items():
        after=new_bom.get(bid)
        if not after or any(after.get(k)!=before.get(k) for k in ('produto_pai_id','componente_id','quantidade_necessaria','unidade_medida')):
            errors.append({'code':'EXISTING_BOM_CHANGED','id':bid})
    for before in baseline['produtos']:
        after=products.get(before['id'])
        fields=('sku','parent_id','status','preco_custo','preco_venda','estoque_minimo','estoque_maximo','dados_estoque')
        changes=[k for k in fields if after and before.get(k)!=after.get(k)]
        if not after or changes:errors.append({'code':'EXISTING_PRODUCT_CHANGED','id':before['id'],'fields':changes})
    # Graph validation includes initial and imported local BOM edges.
    graph={}
    for line in current['ficha_tecnica']:
        if line.get('produto_pai_id') is not None and line.get('componente_id') is not None:
            graph.setdefault(line['produto_pai_id'],set()).add(line['componente_id'])
    def visit(node,path):
        if node in path:raise ValueError('cycle:'+str(node))
        for child in graph.get(node,set()):visit(child,path|{node})
    for pid in set(resolved.values()):
        try:visit(pid,set())
        except ValueError:errors.append({'code':'BOM_CYCLE','id':pid})
    imported=[p for p in products.values() if ((p.get('atributos') or {}).get('importacao_catalogo') or {}).get('run_id')==manifest['run_id']]
    summary={'announcements':len(manifest['items']),'external_units':sum(len(i['units']) for i in manifest['items']),
             'coverage':dict(Counter(str(i['account_id'])+':'+i['status'] for i in manifest['items'])),
             'imported_products_including_models_and_components':len(imported),'reused_products':sum(bool(p['existing_id']) for p in manifest['products']),
             'models':sum(p.get('papel_catalogo')=='modelo' for p in imported),'internal_components':sum(bool(p.get('component_only')) for p in manifest['products']),
             'new_finished_products_excluding_models':sum(p.get('tipo_produto')=='PRODUTO_ACABADO' and p.get('papel_catalogo')!='modelo' for p in imported),
             'new_intermediates':sum(p.get('tipo_produto')=='INTERMEDIARIO' for p in imported),
             'new_raw_materials':sum(p.get('tipo_produto')=='MATERIA_PRIMA' for p in imported),
             'kit_finished_components':sum(bool(p.get('component_only')) and not p.get('pi_intermediate') and p.get('material_type')!='materia_prima' for p in manifest['products']),
             'consolidated_external_units':sum(len(p['sources'])-1 for p in manifest['products'] if not p.get('component_only')),
             'products_with_images':sum(bool((p.get('atributos') or {}).get('images')) for p in products.values()),
             'bom_lines_added':len(current['ficha_tecnica'])-len(baseline['ficha_tecnica']),
             'new_products_active':sum(p['status']=='ativo' for p in imported),
             'imported_costs_nonnull':sum(p.get('preco_custo') is not None for p in imported),
             'records_with_pending':sum(bool(p['pending']) for p in manifest['products']),
             'errors':errors}
    (args.output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    with (args.output/'produtos-composicoes-pendencias.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(report[0]),delimiter=';');writer.writeheader();writer.writerows(report)
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    return bool(errors)


if __name__=='__main__':raise SystemExit(main())
