"""Prepare and apply a reviewed, resumable correction of the initial import.

No provider writes, stock changes, deletion or repricing. Merged records remain
inactive audit references; every external unit points to the canonical product.
"""
import argparse
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_CEILING
import base64
import json
from pathlib import Path
import re
import subprocess

from prepare_catalog_import import text
from prepare_catalog_hierarchy import role


def page_counts(value):
    value = text(value).replace('_x000d_', ' ')
    counts = set()
    # Technical totals only: do not sum section page counts or confuse sheets.
    patterns = [r'(?:total de|total:?)\s*(\d{2,4})\s*(?:paginas|pag\b|pg\b)',
                r'(?:paginas|pag\b|pg\b)\s*(?:do (?:planner|livro))?\s*[:\-]\s*(\d{2,4})\b',
                r'\b(\d{2,4})\s*(?:paginas|pg\b|pag\b)\s*(?:=|\(|/|gramatura|papel|folhas|$)']
    for pattern in patterns:
        counts.update(int(n) for n in re.findall(pattern, value) if 4 <= int(n) <= 2000)
    return counts


def sheet_and_ink(pages, rate='0.017'):
    sheets = int((Decimal(pages) / 4).to_integral_value(rounding=ROUND_CEILING))
    return sheets, float(Decimal(sheets) * Decimal(rate))


def prepare(root, source_skus=False):
    manifest = json.loads((root/'manifest-complete.json').read_text(encoding='utf-8'))
    current = {r['table']: r['rows'] for r in map(json.loads, (root/'revision-before/verification-snapshot.jsonl').read_text(encoding='utf-8').splitlines())}
    products = {p['id']: p for p in current['produtos']}
    keyed = {((p.get('atributos') or {}).get('importacao_catalogo') or {}).get('key'): p for p in products.values()}
    records = {p['key']: p for p in manifest['products']}
    bom = defaultdict(list)
    for b in current['ficha_tecnica']: bom[b['produto_pai_id']].append(b)
    resolved = {}
    for record in manifest['products']:
        p = products.get(record.get('existing_id')) or keyed.get(record['key'])
        if p: resolved[record['key']] = p['id']
    # Respect the core consolidation performed after the original import.
    for record in manifest['products']:
        if record['key'] in resolved or record.get('pi_role') != 'miolo': continue
        pa = resolved.get(record.get('source_pa_key'))
        cores = {b['componente_id'] for b in bom[pa] if products[b['componente_id']].get('categoria_id') == 6}
        if len(cores) == 1: resolved[record['key']] = next(iter(cores))
    plan = {'run_id': manifest['run_id'], 'merges': [], 'renames': [], 'cores': [], 'split_cores': [], 'pending': [], 'resolved': resolved}
    groups = json.loads((root/'duplicate-candidates.json').read_text(encoding='utf-8'))
    # Visual review of all nine contact sheets. These groups have different
    # artwork/editions despite a repeated seller SKU. Group 49 has one outlier.
    different = {0, 3, 5, 37, 41, 50, 55, 78}
    for index, group in enumerate(groups):
        entries = [records[p['key']] for p in group['products']]
        if index in different:
            plan['pending'].append({'code':'SKU_IDENTIDADE_DIVERGENTE', 'sku':group['sku'], 'products':[resolved[p['key']] for p in entries], 'reason':'Capas/edições ou especificações divergentes na revisão visual.'})
            continue
        if index == 49:
            outlier = entries.pop(1)
            plan['pending'].append({'code':'SKU_IDENTIDADE_DIVERGENTE','products':[resolved[outlier['key']]],'sku':group['sku'],'reason':'Capa e encadernação diferentes das demais fontes deste SKU.'})
        # Same artwork does not prove the same core or year.
        pages = {n for p in entries for s in p['sources'] for n in page_counts(s['description'])}
        years = {n for p in entries for s in p['sources'] for n in re.findall(r'\b20(?:2[4-9]|3\d)\b', text(s['title']))}
        structures = {products[resolved[p['key']]].get('estrutura') for p in entries}
        if len(pages) > 1 or len(years) > 1 or len(structures) > 1:
            plan['pending'].append({'code':'SKU_ESPECIFICACOES_DIVERGENTES','sku':group['sku'],'products':[resolved[p['key']] for p in entries],'pages':sorted(pages),'years':sorted(years),'reason':'Revisar divergência antes de consolidar.'})
            continue
        entries.sort(key=lambda p: (not bool(p.get('existing_id')), products[resolved[p['key']]]['sku'].startswith('IMP-'), resolved[p['key']]))
        target = resolved[entries[0]['key']]
        for entry in entries[1:]:
            source = resolved[entry['key']]
            if source == target: continue
            if not ((products[source].get('atributos') or {}).get('importacao_catalogo') or {}).get('run_id') == manifest['run_id']:
                raise ValueError('Cannot archive a preexisting product')
            plan['merges'].append({'source':source,'target':target,'evidence':{'sku':group['sku'],'visual_sheet':index//16,'visual_row':index%16,'pages':sorted(pages),'years':sorted(years)}})
    by_pid={resolved[p['key']]:p for p in manifest['products'] if not p.get('component_only')}
    extra_path=root/'extra-duplicate-candidates.json'
    if extra_path.exists():
        for index,group in enumerate(json.loads(extra_path.read_text(encoding='utf-8'))):
            pids=[group['owner']]+group['ids']
            if index in {30,53,64,101}: continue
            if index==14: pids=[pid for pid in pids if pid!=1614]
            if index==43: pids=[pid for pid in pids if pid!=1179]
            entries=[by_pid[pid] for pid in pids if pid in by_pid]
            if len(entries)<2: continue
            pages={n for p in entries for s in p['sources'] for n in page_counts(s['description'])}
            years={n for p in entries for s in p['sources'] for n in re.findall(r'\b20(?:2[4-9]|3\d)\b',text(s['title']))}
            structures={products[resolved[p['key']]].get('estrutura') for p in entries}
            if len(pages)>1 or len(years)>1 or (len(structures)>1 and index not in {0,1,2}): continue
            target=pids[0]
            for pid in pids[1:]:
                if pid not in by_pid or pid==target: continue
                if not ((products[pid].get('atributos') or {}).get('importacao_catalogo') or {}).get('run_id')==manifest['run_id']: continue
                plan['merges'].append({'source':pid,'target':target,'evidence':{'sku':group['sku'],'extra_visual_sheet':index//16,'extra_visual_row':index%16,'pages':sorted(pages),'years':sorted(years)}})
    redirects = {m['source']:m['target'] for m in plan['merges']}
    for item in plan['merges']:
        while item['target'] in redirects: item['target']=redirects[item['target']]
    redirects = {m['source']:m['target'] for m in plan['merges']}
    sku_owner = {p['sku']:p['id'] for p in products.values()}
    source_skus = defaultdict(set)
    for record in manifest['products']:
        if record.get('component_only'): continue
        pid = resolved[record['key']]
        pid = redirects.get(pid,pid)
        source_skus[pid].update(str(s['unit']['sku']).strip() for s in record['sources'] if s['unit'].get('sku'))
    for pid, skus in source_skus.items():
        p = products[pid]
        if not p['sku'].startswith('IMP-'): continue
        if len(skus) == 1:
            sku = next(iter(skus))
            if len(sku)>100 or (sku_owner.get(sku) not in (None,pid)):
                plan['pending'].append({'code':'SKU_OCUPADO','products':[pid],'sku':sku,'owner':sku_owner.get(sku),'reason':'SKU externo preservado como evidência; conflito de identidade impede reutilização automática.'})
                continue
            plan['renames'].append({'id':pid,'before':p['sku'],'after':sku})
            sku_owner[sku]=pid
        else:
            plan['pending'].append({'code':'SKU_AUSENTE_OU_DIVERGENTE','products':[pid],'skus':sorted(skus),'reason':'Anúncio sem SKU ou fontes com SKUs distintos; não inventar SKU comercial.'})
    # Assess every live core from all current parent PAs, not from stale PI keys.
    evidence = defaultdict(list)
    for record in manifest['products']:
        if record.get('pi_intermediate') or record['structure'] != 'manufaturado': continue
        pid = resolved.get(record['key'])
        for line in bom[pid]:
            core = products[line['componente_id']]
            if core.get('categoria_id') != 6: continue
            if record.get('component_only'):
                candidates = page_counts(record.get('description_override',''))
                proof = record.get('description_override','')
            else:
                candidates = {n for s in record['sources'] for n in page_counts(s['description'])}
                proof = ' | '.join(s['item_id'] for s in record['sources'])
            evidence[core['id']].append({'pa_id':pid,'key':record['key'],'pages':sorted(candidates),'proof':proof})
    for core_id, sources in evidence.items():
        core=products[core_id]
        counts={n for source in sources for n in source['pages']}
        lines={b['componente_id']:b for b in bom[core_id]}
        if len(counts) != 1:
            plan['pending'].append({'code':'MIOLO_PAGINAS_DIVERGENTES' if counts else 'MIOLO_PAGINAS_AUSENTES','products':[core_id],'pages':sorted(counts),'sources':sources,'reason':'Não alterar consumo sem um total único comprovado para este miolo.'})
            continue
        pages=next(iter(counts)); sheets,ink=sheet_and_ink(pages)
        # Paper identity is still required. Black/kraft/drawing papers cannot
        # be silently converted to the existing white 75g stock.
        own_text = ' '.join(records[source['key']].get('description_override','') if records[source['key']].get('component_only') else ' '.join(s['description'] for s in records[source['key']]['sources']) for source in sources)
        normalized=text(own_text)
        incompatible = bool(re.search(r'(?:folhas|papel)\s+(?:pret[ao]s?|kraft)', normalized)) or bool(re.search(r'(?:gramatura\s*[:=]?\s*|papel\s+offset\s+)(?:90|120|150|180|240)\s*g',normalized))
        if incompatible:
            plan['pending'].append({'code':'MIOLO_PAPEL_ESPECIAL','products':[core_id],'pages':[pages],'reason':'Papel especial ou gramatura distinta; sulfite 75g não confirmado.'})
            continue
        operations=[]
        for component,qty in [(5,sheets),(6,ink)]:
            existing=lines.get(component)
            # Apply the confirmed standard to the rounded sheet count. Other
            # manual recipes, without a proved page total, remain untouched.
            if existing and float(existing['quantidade_necessaria'])==qty: continue
            operations.append({'component':component,'quantity':qty,'unit':existing['unidade_medida'] if existing else 'un','before':existing})
        if operations: plan['cores'].append({'id':core_id,'pages':pages,'sheets':sheets,'ink_rate':0.017,'reference_core_id':7,'operations':operations,'sources':sources})
    # A shared core with contradictory page counts cannot receive a single
    # recipe. Separate proved layouts for imported PAs only; retain manual
    # products and unknown layouts unchanged.
    splits={}
    for pending in list(plan['pending']):
        if pending['code'] != 'MIOLO_PAGINAS_DIVERGENTES': continue
        core_id=pending['products'][0]
        for source in pending['sources']:
            record=records[source['key']]
            if len(source['pages'])!=1 or record.get('existing_id'): continue
            pa=products[source['pa_id']]
            if source['pa_id'] in redirects: continue
            label=record.get('description_override','').split('. Peça integrante')[0] if record.get('component_only') else record['name']
            own_text=record.get('description_override','') if record.get('component_only') else ' '.join(s['description'] for s in record['sources'])
            normalized=text(own_text)
            if re.search(r'(?:folhas|papel)\s+(?:pret[ao]s?|kraft)',normalized): continue
            if re.search(r'(?:gramatura\s*[:=]?\s*|papel\s+offset\s+)(?:90|120|150|180|240)\s*g',normalized): continue
            pages=source['pages'][0];sheets,ink=sheet_and_ink(pages)
            kind=role(label)
            layout='-'.join(w for w in ('pontilhado','quadriculado','pautado','liso') if w in normalized) or 'padrao'
            years=sorted(set(re.findall(r'\b202[4-9]\b',text(label)))) if kind in ('agenda','planner','professor') else []
            token=f'{core_id}:{kind}:{pages}:{layout}:'+','.join(years)
            if token not in splits:
                sku=f'MIOLO-{kind.upper()}-{pages}P-{layout.upper()}' + ('-'+ '-'.join(years) if years else '')
                if sku in sku_owner: sku+=f'-REF{core_id}'
                sku_owner[sku]=-1
                splits[token]={'key':'revision:miolo:'+token,'sku':sku,'name':f'{kind.replace("_"," ").capitalize()} — {pages} páginas — {layout}'+(' — '+', '.join(years) if years else ''),'pages':pages,'sheets':sheets,'ink':ink,'sources':[]}
            original=next(b for b in bom[pa['id']] if b['componente_id']==core_id)
            splits[token]['sources'].append(dict(source,original_line=original))
    plan['split_cores']=list(splits.values())
    if source_skus:
        # User approved suffixes for genuinely different products sharing a
        # seller SKU. Keep missing seller SKUs explicit instead of IMP hashes.
        reserved=set(sku_owner)
        retained=[]
        for pending in plan['pending']:
            if pending['code'] not in {'SKU_OCUPADO','SKU_AUSENTE_OU_DIVERGENTE'}:
                retained.append(pending);continue
            pid=pending['products'][0];record=by_pid[pid];p=products[pid];source=record['sources'][0]
            if pending['code']=='SKU_OCUPADO':
                base=pending['sku']
                years=sorted(set(re.findall(r'\b202[4-9]\b',text(record['name']))))
                suffix=years[0] if len(years)==1 else 'KIT' if p.get('estrutura')=='kit' else 'MUSIC' if 'music' in text(record['name']) else source['item_id']
                desired=base+'-'+suffix
                if desired in reserved:desired=base+'-'+suffix+'-'+source['item_id']
                if desired in reserved:desired+='-'+source['unit']['id']
                kind='source_sku_with_conflict_suffix'
            elif not pending.get('skus'):
                desired='SEM-SKU-'+source['item_id']+('-'+source['unit']['id'] if source['unit']['id'] else '')
                kind='missing_source_sku_reference';retained.append(pending)
            else:
                retained.append(pending);continue
            if len(desired)>100 or desired in reserved:raise ValueError('Revision SKU collision: '+desired)
            reserved.add(desired)
            plan['renames'].append({'id':pid,'before':p['sku'],'after':desired,'kind':kind,'source_sku':source['unit'].get('sku')})
        plan['pending']=retained
        plan['source_sku_suffixes_authorized']=True
    (root/'revision-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'merges':len(plan['merges']),'renames':len(plan['renames']),'cores':len(plan['cores']),'split_cores':len(plan['split_cores']),'corrected_pa_core_links':sum(len(c['sources']) for c in plan['split_cores']),'pending':dict(Counter(p['code'] for p in plan['pending']))},ensure_ascii=False))
    return plan


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path('temp/catalog-import-20261029'))
    parser.add_argument('--source-skus',action='store_true',help='Apply the user-approved source SKU suffix policy')
    args=parser.parse_args()
    prepare(args.root,args.source_skus)
