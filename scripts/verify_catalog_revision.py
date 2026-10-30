"""Read-only validation and report for the SKU/core correction."""
import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import subprocess
from verify_catalog_import import REMOTE


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path('temp/catalog-import-20261029'))
    parser.add_argument('--host',required=True)
    parser.add_argument('--identity',required=True)
    args=parser.parse_args();root=args.root
    result=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10','-i',args.identity,args.host,'cd /opt/nistiprint && .venv/bin/python -'],input=REMOTE.encode(),stdout=subprocess.PIPE,check=True)
    output=root/'revision-report';output.mkdir(exist_ok=True)
    (output/'snapshot.jsonl').write_bytes(result.stdout)
    current={r['table']:r['rows'] for r in map(json.loads,result.stdout.decode().splitlines())}
    before={r['table']:r['rows'] for r in map(json.loads,(root/'revision-before/verification-snapshot.jsonl').read_text(encoding='utf-8').splitlines())}
    plan=json.loads((root/'revision-plan.json').read_text(encoding='utf-8'))
    products={p['id']:p for p in current['produtos']};keyed={((p.get('atributos') or {}).get('importacao_catalogo') or {}).get('key'):p for p in products.values()}
    units={u['id']:u for u in current['produto_anuncios']};bom={b['id']:b for b in current['ficha_tecnica']}
    redirects={m['source']:m['target'] for m in plan['merges']};errors=[]
    for old in before['produtos']:
        p=products.get(old['id'])
        if not p:errors.append(['PRODUCT_REMOVED',old['id']]);continue
        for field in ('preco_custo','preco_venda','precificacao','dados_estoque','estoque_minimo','estoque_maximo','status','parent_id','tipo_produto'):
            if p.get(field)!=old.get(field):errors.append(['PRODUCT_FIELD_CHANGED',p['id'],field])
    for old in before['produto_anuncios']:
        u=units.get(old['id']);expected=redirects.get(old.get('produto_id'),old.get('produto_id'))
        if not u or u.get('produto_id')!=expected:errors.append(['LINK_MISMATCH',old['id'],expected])
        if u and any(u.get(k)!=old.get(k) for k in ('integration_id','item_externo_id','variacao_externa_id','sku_externo','preco_observado','disponibilidade_observada')):errors.append(['EXTERNAL_OBSERVATION_CHANGED',old['id']])
    removed={s['original_line']['id'] for c in plan['split_cores'] for s in c['sources']}
    modified={o['before']['id'] for c in plan['cores'] for o in c['operations'] if o.get('before')}
    for old in before['ficha_tecnica']:
        if old['id'] in removed:
            if old['id'] in bom:errors.append(['OLD_CORE_LINK_REMAINS',old['id']])
            continue
        new=bom.get(old['id'])
        if not new:errors.append(['UNEXPECTED_BOM_REMOVAL',old['id']]);continue
        if old['id'] not in modified and any(new[k]!=old[k] for k in ('produto_pai_id','componente_id','quantidade_necessaria','unidade_medida')):errors.append(['UNEXPECTED_BOM_CHANGE',old['id']])
    by_pair=defaultdict(list)
    for b in bom.values():by_pair[b['produto_pai_id'],b['componente_id']].append(b)
    def check(pid,cid,qty,unit):
        rows=by_pair[pid,cid]
        if len(rows)!=1 or float(rows[0]['quantidade_necessaria'])!=qty or rows[0]['unidade_medida']!=unit:errors.append(['BOM_MISMATCH',pid,cid,qty,unit])
    report=[]
    for c in plan['cores']:
        for operation in c['operations']:check(c['id'],operation['component'],operation['quantity'],operation['unit'])
        report.append({'produto_id':c['id'],'sku':products[c['id']]['sku'],'paginas':c['pages'],'folhas':c['sheets'],'tinta':next((b['quantidade_necessaria'] for b in bom.values() if b['produto_pai_id']==c['id'] and b['componente_id']==6),None),'pas_corrigidos':0})
    for c in plan['split_cores']:
        p=keyed.get(c['key'])
        if not p:errors.append(['CORE_MISSING',c['key']]);continue
        if p['status']=='ativo' or p.get('preco_custo') is not None:errors.append(['NEW_CORE_ACTIVE_OR_PRICED',p['id']])
        check(p['id'],5,c['sheets'],'un');check(p['id'],6,c['ink'],'un')
        for source in c['sources']:check(source['pa_id'],p['id'],float(source['original_line']['quantidade_necessaria']),source['original_line']['unidade_medida'])
        report.append({'produto_id':p['id'],'sku':p['sku'],'paginas':c['pages'],'folhas':c['sheets'],'tinta':c['ink'],'pas_corrigidos':len(c['sources'])})
    for m in plan['merges']:
        if (products[m['source']].get('atributos') or {}).get('catalog_merged_into')!=m['target']:errors.append(['MERGE_MARKER_MISSING',m['source']])
    for change in plan['renames']:
        if products[change['id']]['sku']!=change['after']:errors.append(['SKU_NOT_RENAMED',change['id']])
    graph=defaultdict(set)
    for b in bom.values():
        if b.get('produto_pai_id') is None or b.get('componente_id') is None:continue
        if float(b['quantidade_necessaria'])<=0:errors.append(['NONPOSITIVE_QUANTITY',b['id']])
        graph[b['produto_pai_id']].add(b['componente_id'])
    def visit(pid,path):
        if pid in path:raise ValueError(pid)
        for cid in graph[pid]:visit(cid,path|{pid})
    for pid in list(graph):
        try:visit(pid,set())
        except ValueError:errors.append(['CYCLE',pid])
    summary={'merged_products':len(plan['merges']),'external_units_relinked':sum(old.get('produto_id') in redirects for old in before['produto_anuncios']),'renamed_products':len(plan['renames']),'existing_cores_completed_or_corrected':len(plan['cores']),'new_cores_with_paper_and_ink':len(plan['split_cores']),'pa_core_links_corrected':sum(len(c['sources']) for c in plan['split_cores']),'pending_groups':dict(Counter(p['code'] for p in plan['pending'])),'errors':errors}
    (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'pendencias.json').write_text(json.dumps(plan['pending'],ensure_ascii=False,indent=2),encoding='utf-8')
    with (output/'miolos-consumos.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(report[0]),delimiter=';');writer.writeheader();writer.writerows(report)
    print(json.dumps(summary,ensure_ascii=False,indent=2));return bool(errors)


if __name__=='__main__':raise SystemExit(main())
