"""Add the existing PA -> PI -> MP manufacturing structure to an import.

Creates explicit intermediate records for cores and covers. Existing intermediate
recipes are reused only when an existing PA provides matching description evidence.
No paper yield, ink, board thickness, lamination or binding consumption is inferred.
"""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
from prepare_catalog_import import text, compatible_names


def role(name):
    value=text(name)
    for marker,label in [('vacinacao','vacina'),('gestante','gestante'),('livro do bebe','livro_bebe'),('noiva','noiva'),('assinaturas','assinaturas'),('professor','professor'),('creche','creche'),('escolar','escolar'),('caligrafia','caligrafia'),('devocional','devocional'),('financeiro','financeiro'),('pedidos','pedidos'),('receitas','receitas'),('scrapbook','scrapbook'),('album','album'),('diario','diario'),('agenda','agenda'),('planner','planner')]:
        if marker in value:
            return label + ('_menina' if 'menina' in value and label=='vacina' else '_menino' if 'menino' in value and label=='vacina' else '')
    return 'caderno'


def fingerprint(record):
    source=record['sources'][0]
    description=text(source['description'])
    if not description:return 'unknown:'+record['key']
    label=record.get('description_override','').split('. Peça integrante')[0] if record.get('component_only') else role(record['name'])
    return hashlib.sha256((label+'\n'+description).encode()).hexdigest()[:24]


def prepare(manifest, baseline, snapshot):
    old_products={p['id']:p for p in baseline['produtos']}
    current={p['id']:p for p in snapshot['produtos']}
    imported_by_key={((p.get('atributos') or {}).get('importacao_catalogo') or {}).get('key'):p for p in current.values()}
    baseline_bom_ids={b['id'] for b in baseline['ficha_tecnica']}
    by_parent=defaultdict(list)
    for line in baseline['ficha_tecnica']:by_parent[line['produto_pai_id']].append(line)
    current_bom=defaultdict(list)
    for line in snapshot['ficha_tecnica']:current_bom[line['produto_pai_id']].append(line)
    known_cores=defaultdict(set)
    for record in manifest['products']:
        if not record.get('existing_id') or record.get('component_only'):continue
        old=old_products[record['existing_id']]
        if not compatible_names(old['nome'],record['name']):continue
        for line in by_parent[record['existing_id']]:
            component=old_products.get(line['componente_id'],{})
            if component.get('categoria_id')==6 and component.get('tipo_produto')=='INTERMEDIARIO':
                known_cores[fingerprint(record)].add(component['id'])
    additions={};delta_roots=[];adjustments=[]
    existing_keys={p['key'] for p in manifest['products']}
    def intermediate(key,name,category,record,kind):
        if key in additions or key in existing_keys:return key
        source=record['sources'][0]
        proof={'account_id':source['account_id'],'provider':source['provider'],'item_id':source['item_id'],'status':source['status'],
               'title':source['title'],'description':f'{name}. Intermediário identificado na imagem/descrição do PA de origem. Consumos industriais, arquivo e materiais ainda sujeitos à revisão.',
               'images':[],'unit':{'id':source['unit']['id'],'sku':source['unit']['sku'],'attributes':{},'images':[]}}
        additions[key]={'key':key,'sku':'PI-IMP-'+hashlib.sha256(key.encode()).hexdigest()[:20].upper(),'name':name[:255],
                        'existing_id':None,'category_id':category,'material_type':'intermediario','structure':'manufaturado',
                        'sources':[proof],'bom':[],'pending':['Confirmar especificações industriais, arquivo e consumo de MPs deste PI; não estimar perdas ou rendimentos.'],
                        'component_only':True,'pi_intermediate':True,'pi_role':kind,'source_pa_key':record['key']}
        return key
    for record in list(manifest['products']):
        if record.get('material_type')=='materia_prima' or record.get('existing_id') or record['structure']!='manufaturado':continue
        if record.get('pi_intermediate'):continue
        if record.get('hierarchy_prepared') or any(str(b.get('key','')).startswith('pi:') for b in record['bom']):continue
        source=record['sources'][0]
        # A kit's component must be classified by its own label, not by the
        # complete bundle description (which mentions every other component).
        label=record.get('description_override','').split('. Peça integrante')[0] if record.get('component_only') else record['name']
        title=text(label)
        if any(word in title for word in ('marcador','caneta','estojo','papel foto')):continue
        live=imported_by_key.get(record['key'])
        if not live and record.get('hierarchy_new_pa') and record.get('component_only'):
            live={'id':None,'sku':record['sku'],'nome':record['name'],'tipo_produto':'PRODUTO_ACABADO','categoria_id':record['category_id']}
        if not live:raise ValueError('Missing applied PA: '+record['key'])
        if live['tipo_produto']!='PRODUTO_ACABADO':continue
        root_additions=[];moves=[]
        stickers=any(word in title for word in ('adesivo','etiqueta','cartoes'))
        if stickers:
            adhesive=any(word in title for word in ('adesivo','etiqueta'))
            key=intermediate('pi:adesivos:'+record['key'],('Impressos adesivos — ' if adhesive else 'Impressos gráficos — ')+record['name'],5,record,'adesivos' if adhesive else 'impressos')
            root_additions.append({'key':key,'quantity':1,'unit':'un','evidence':'Um conjunto de impressos/recortes por unidade do produto anunciado.'})
            # Transfer only this import's known printing material, never an
            # original BOM line or an accessory consumed at PA assembly.
            transferable=[b for b in record['bom'] if b.get('key')=='material:vinil-adesivo-a5']
            for line in transferable:
                additions[key]['bom'].append(line)
                vinyl=imported_by_key.get(line['key'])
                for existing in current_bom[live['id']]:
                    if vinyl and existing['componente_id']==vinyl['id']:
                        if existing['id'] in baseline_bom_ids:raise ValueError('Cannot move original BOM')
                        moves.append({'line_id':existing['id'],'component_id':vinyl['id'],'quantity':line['quantity'],'unit':line['unit'],'target_key':key})
                record['bom'].remove(line)
        else:
            # Only physical paper goods with an identifiable core/body qualify.
            if not any(word in title for word in ('agenda','planner','caderno','caderneta','livro','biblia','scrapbook','album','diario','refil','miolo','porta documentos','cardapio','fichario','devocional','controle financeiro')):continue
            is_holder='porta documentos' in title
            is_refill='refil' in title or title.startswith('miolo ')
            core_quantity=20 if source['item_id']=='MLB2013183410' else 1
            core_label='Miolo unitário de agenda 2022' if core_quantity==20 else label
            if not is_holder:
                signature=fingerprint(record)
                choices=known_cores.get(signature,set())
                if len(choices)==1:
                    root_additions.append({'existing_id':next(iter(choices)),'quantity':core_quantity,'unit':'un','evidence':'Mesmo conteúdo descritivo de PA existente cuja ficha identifica este PI de miolo.'})
                else:
                    key=intermediate('pi:miolo:'+signature,'Miolo — '+core_label,6,record,'miolo')
                    root_additions.append({'key':key,'quantity':core_quantity,'unit':'un','evidence':'Quantidade de miolos/corpos físicos do produto anunciado; sem deduzir consumo de papel.'})
                    if choices:additions[key]['pending'].append('Mais de um miolo existente candidato; equivalência não confirmada.')
            cover_evidence=text(label+' '+source['description'])
            has_covers=any(value in cover_evidence for value in ('capa dura','encadern','wire-o','espiral'))
            if not is_refill and has_covers:
                for side,part in [('capa','Capa pronta'),('contra','Contracapa pronta')]:
                    key=intermediate('pi:'+side+':'+record['key'],part+' — '+record['name'],3,record,side)
                    root_additions.append({'key':key,'quantity':1,'unit':'un','evidence':'Uma '+part.lower()+' por produto físico, conforme fotos e descrição da encadernação.'})
        if root_additions:
            record['bom'].extend(root_additions)
            record['hierarchy_prepared']=True
            delta_roots.append({'key':record['key'],'sku':live['sku'],'name':live['nome'],'existing_id':live['id'],
                                'category_id':live['categoria_id'],'structure':record['structure'],'sources':record['sources'] if live['id'] is None else [],
                                'description_override':record.get('description_override'),
                                'bom':root_additions,'pending':[],'component_only':True,'move_bom':moves})
            adjustments.append({'product_id':live['id'],'pa_key':record['key'],'new_pi_lines':len(root_additions),'material_lines_transferred':len(moves)})
    manifest['products'].extend(additions.values())
    manifest['version']=2
    manifest['assumptions'].extend(['PA utiliza PIs de miolo/capas; MPs de acabamento podem ficar no PA, conforme confirmação do usuário.','Kits reúnem PAs; cada PA segue a sua composição de PIs e MPs.'])
    delta={'version':2,'run_id':manifest['run_id'],'products':list(additions.values())+delta_roots,'families':[],'items':[],
           'coverage':manifest['coverage'],'assumptions':manifest['assumptions']}
    return manifest,delta,adjustments


def complete_bundle_parts(manifest,snapshot):
    """Two explicit book + 3-pen offers do not contain the word 'kit'."""
    existing_keys={r['key'] for r in manifest['products']}
    current={((p.get('atributos') or {}).get('importacao_catalogo') or {}).get('key'):p for p in snapshot['produtos']}
    extra=[];kit_roots=[]
    for record in list(manifest['products']):
        if record.get('pi_intermediate') or record.get('component_only'):continue
        if not any(s['item_id'] in ('MLB3638130278','MLB3638121100') for s in record['sources']):continue
        if record['structure']=='kit':continue
        if record['bom']:raise ValueError('Bundle already has a manufacturing BOM; review before restructuring')
        live=current[record['key']]
        for index,label in enumerate(('Scrapbook de folhas pretas','Conjunto de 3 canetas metalizadas'),1):
            key=record['key']+':component:'+str(index)
            if key in existing_keys:raise ValueError('Unexpected existing bundle component')
            part={'key':key,'sku':'IMP-C-'+hashlib.sha256(key.encode()).hexdigest()[:20].upper(),
                  'name':(label+' — '+record['name'])[:255],'description_override':label+'. Peça integrante de '+record['name']+'. Demais especificações pendentes.',
                  'existing_id':None,'category_id':11,'structure':'manufaturado' if index==1 else 'simples',
                  'sources':record['sources'],'bom':[],'pending':['Consumos ou cadastro de compra da peça precisam de confirmação.'],
                  'component_only':True,'hierarchy_new_pa':True}
            extra.append(part)
            record['bom'].append({'key':key,'quantity':1,'unit':'un','evidence':'Imagem e título anunciam um scrapbook acompanhado de um conjunto de três canetas metalizadas.'})
        record['structure']='kit'
        kit_roots.append({'key':record['key'],'sku':live['sku'],'name':live['nome'],'existing_id':live['id'],'category_id':live['categoria_id'],
                          'structure':'kit','ensure_structure':'kit','sources':[],'bom':record['bom'],'pending':[],'component_only':True})
    manifest['products'].extend(extra)
    return extra,kit_roots


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',required=True,type=Path)
    parser.add_argument('--baseline',required=True,type=Path)
    parser.add_argument('--snapshot',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--delta',required=True,type=Path)
    parser.add_argument('--complete-bundles',action='store_true')
    args=parser.parse_args()
    baseline={}
    for line in args.baseline.read_text(encoding='utf-8').splitlines():
        row=json.loads(line)
        if row['kind']=='inventory':baseline.setdefault(row['table'],row['rows'])
    snapshot={r['table']:r['rows'] for r in map(json.loads,args.snapshot.read_text(encoding='utf-8').splitlines())}
    manifest=json.loads(args.manifest.read_text(encoding='utf-8'))
    extra,kit_roots=complete_bundle_parts(manifest,snapshot) if args.complete_bundles else ([],[])
    manifest,delta,adjustments=prepare(manifest,baseline,snapshot)
    delta_keys={p['key'] for p in delta['products']}
    delta['products'].extend(p for p in extra if p['key'] not in delta_keys)
    delta['products'].extend(kit_roots)
    args.output.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    args.delta.write_text(json.dumps(delta,ensure_ascii=False,indent=2),encoding='utf-8')
    args.delta.with_suffix('.review.json').write_text(json.dumps(adjustments,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'new_pi':sum(bool(p.get('pi_intermediate')) for p in delta['products']),
                      'pa_completed':len(adjustments),'pa_pi_lines':sum(a['new_pi_lines'] for a in adjustments),
                      'material_lines_transferred':sum(a['material_lines_transferred'] for a in adjustments)}))


if __name__=='__main__':main()
