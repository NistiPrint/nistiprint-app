"""Build a reviewable one-off import manifest from private provider evidence.

No database writes. Only evidence-backed quantities enter BOMs; unknown
manufacturing consumption is explicitly pending and prevents activation.
"""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from catalog_import_evidence import load_items, normalize
from PIL import Image, ImageChops, ImageOps, ImageStat


def text(value):
    return re.sub(r'\s+', ' ', ''.join(c for c in unicodedata.normalize('NFKD', str(value or '').lower()) if not unicodedata.combining(c))).strip()


def tokens(value):
    return set(re.findall(r'[a-z0-9]+', text(value))) - {'de','da','do','com','para','e','a','o','capa','dura','nisti','print','personalizado','personalizada'}


def compatible_names(left, right):
    a, b = tokens(left), tokens(right)
    years_a, years_b = set(re.findall(r'\b20[12][0-9]\b', left or '')), set(re.findall(r'\b20[12][0-9]\b', right or ''))
    if years_a and years_b and years_a.isdisjoint(years_b):
        return False
    return len(a & b) >= 2 and len(a & b) / max(1, min(len(a),len(b))) >= .65


# Reviewed kit contents. Each entry is one distinct physical product, not raw material.
KITS = {
    '56959775600': [('Caderneta de vacinação',1),('Livro do bebê',1),('Álbum do bebê — 20 folhas brancas 180g',1),('Porta documentos A6',1)],
    '22897666400': [('Planner da noiva — 210 páginas',1),('Livro de assinaturas — 40 páginas',1)],
    '18097777421': [('Planner da noiva — 210 páginas',1),('Livro de assinaturas — 40 páginas',1)],
    '23493175571': [('Planner da noiva — 210 páginas',1),('Livro de assinaturas — 40 páginas',1)],
    '19802174846': [('Caderno de pedidos — 166 páginas',1),('Controle financeiro — 156 páginas',1)],
    '10187032985': [('Caderno Dreams azul — 200 páginas',1),('Caderno Dreams amarelo — 200 páginas',1),('Caderno Dreams rosa — 200 páginas',1)],
    '42615051847': [('Caderneta de vacinação',1),('Livro do bebê',1)],
    '42264402340': [('Caderneta de vacinação',1),('Livro do bebê',1)],
    '41954695702': [('Agenda personalizada — 350 páginas',5)],
    '58263073466': [('Caderno de discos Caramelo — 50 folhas pautadas',1),('Refil de discos A5 — 50 folhas lisas 90g',1)],
    '58212864113': [('Devocional leitura bíblica 365 dias — 368 páginas',1),('Caderno para estudo bíblico — 200 páginas',1)],
    '48415112616': [('Caderneta da gestante',1),('Caderneta de vacinação da criança',1)],
    '58200236775': [('Agenda escolar infantil',1),('Caderno de caligrafia',1)],
    '22696079186': [('Scrapbook de folhas pretas',1),('Conjunto de 6 marcadores metalizados',1)],
    'MLB2014122699': [('Agenda personalizada — 380 páginas, edição 2022',50)],
    'MLB2179863549': [('Caderno Dreams azul — 200 páginas',1),('Caderno Dreams amarelo — 200 páginas',1),('Caderno Dreams rosa — 200 páginas',1)],
    'MLB4001318012': [('Caderno Dreams azul — 200 páginas',1),('Caderno Dreams amarelo — 200 páginas',1),('Caderno Dreams rosa — 200 páginas',1)],
    'MLB2895079692': [('Agenda personalizada — 350 páginas, edição 2025',50)],
    'MLB3492504977': [('Agenda pessoal — 216 páginas, edição 2024',1),('Caderno de anotações — 200 páginas',1)],
    'MLB4166726186': [('Planner semanal e financeiro — 134 páginas',15)],
    'MLB3511307977': [('Planner semanal e financeiro — 134 páginas',15)],
    'MLB4186756566': [('Agenda personalizada — 350 páginas, edição 2024',25)],
    'MLB3520748655': [('Agenda personalizada — edição 2024',50)],
    'MLB4110952286': [('Caderno personalizado — 200 páginas',50)],
    'MLB4147925312': [('Agenda personalizada — 350 páginas, edição 2027',15)],
    'MLB3891325609': [('Agenda personalizada — 350 páginas, edição 2027',50)],
    'MLB3847993431': [('Planner professor Coruja — 258 páginas',24)],
    'MLB4362480082': [('Caderno de pedidos — 162 páginas',1),('Controle financeiro — 156 páginas',1)],
    'MLB5412227070': [('Planner da noiva — 210 páginas',1),('Livro de assinaturas — 40 páginas',1)],
    'MLB3798015361': [('Planner da noiva — 210 páginas',1),('Livro de assinaturas — 40 páginas',1)],
    'MLB4085895411': [('Planner da noiva — 210 páginas',1),('Livro de assinaturas — 40 páginas',1)],
    'MLB3797911129': [('Planner da noiva — 210 páginas',1),('Livro de assinaturas — 40 páginas',1)],
    'MLB5418492936': [('Planner da noiva — 210 páginas',1),('Livro de assinaturas — 40 páginas',1)],
    'MLB3797989451': [('Planner da noiva — 210 páginas',1),('Livro de assinaturas — 40 páginas',1)],
    'MLB4190863797': [('Caderneta de vacinação',1),('Livro do bebê',1)],
    'MLB5724297926': [('Caderneta de vacinação',1),('Livro do bebê',1)],
    'MLB5724270878': [('Caderneta de vacinação',1),('Livro do bebê',1)],
    'MLB5724207214': [('Caderneta de vacinação',1),('Livro do bebê',1)],
    'MLB4190877077': [('Caderneta de vacinação',1),('Livro do bebê',1)],
    'MLB4207837757': [('Caderneta de vacinação',1),('Livro do bebê',1)],
    'MLB5780424324': [('Caderneta de vacinação',1),('Livro do bebê',1)],
    'MLB6449426282': [('Caderneta de vacinação',1),('Livro do bebê',1)],
    '58215260894': [('Caderneta da gestante',1),('Caderneta de vacinação da criança',1)],
    '58215257836': [('Caderneta da gestante',1),('Caderneta de vacinação da criança',1)],
    '58265251106': [('Caderneta da gestante',1),('Caderneta de vacinação da criança',1)],
    '58215247809': [('Caderneta da gestante',1),('Caderneta de vacinação da criança',1)],
    '52865086767': [('Caderneta da gestante',1),('Caderneta de vacinação da criança',1)],
    'MLB5413132976': [('Agenda personalizada — edição 2025',10)],
    'MLB2760762830': [('Agenda personalizada — edição 2026',10)],
    'MLB3365940246': [('Caderno personalizado',10)],
    'MLB3512974959': [('Caderno personalizado',50)],
    'MLB5732874816': [('Caderno personalizado',15)],
    'MLB4261687159': [('Caderno personalizado — 200 páginas',5)],
    'MLB4271866643': [('Agenda personalizada — edição 2027',10)],
    'MLB4092347762': [('Planner financeiro',1),('Agenda pessoal — edição 2026',1),('Caderno de anotações',1)],
    'MLB4279257069': [('Agenda personalizada',50)],
    'MLB3472365125': [('Agenda personalizada — edição 2026',50)],
    'MLB4264298099': [('Agenda personalizada — edição 2026',55)],
    'MLB5081562290': [('Agenda personalizada',50)],
    'MLB4561520791': [('Caderno personalizado',82)],
    'MLB6734634614': [('Caderno personalizado',82)],
    'MLB6861352150': [('Caderno personalizado',50)],
    'MLB5504547736': [('Caderno pautado Black',1),('Controle financeiro Black',1)],
    'MLB5591487394': [('Caderno pautado Black',1),('Controle financeiro Black',1)],
    'MLB4066762858': [('Planner financeiro',1),('Caderno pautado',1)],
    'MLB5593525366': [('Planner financeiro',1),('Caderno pautado',1)],
    'MLB3638130278': [('Scrapbook de folhas pretas',1),('Conjunto de 3 canetas metalizadas',1)],
    'MLB3638121100': [('Scrapbook de folhas pretas',1),('Conjunto de 3 canetas metalizadas',1)],
}

# Manually reviewed cover/variation photos, corroborated by the description's
# inclusion of one tassel. These are existing stockable color variants.
TASSEL_BY_ITEM = {
    '21498515760':147, '43882926550':147, '53662012592':147,
    '43633164130':147, '25846768793':147, '56262008605':147,
    '22796400433':149, '58115140767':150, '21598675601':148,
    '25191537199':150, '18698696650':148, '22097503618':150,
}
TASSEL_BY_SKU = {'VACMNO_URSAV_BAA':150,'VACMNO_URSBA_BAA':150,'VACMNO_URSAT_BBB':147}


def prepare(inputs, image_manifest=None):
    image_paths={}
    if image_manifest:
        for entry in json.loads(image_manifest.read_text(encoding='utf-8')):
            if entry.get('path'):image_paths[entry['url']]=entry['path']
    image_cache={}
    def same_image(left,right):
        def thumb(url):
            if url not in image_paths:return None
            if url not in image_cache:
                with Image.open(image_paths[url]) as picture:
                    image_cache[url]=ImageOps.pad(picture.convert('RGB'),(64,64),color='white')
            return image_cache[url]
        a,b=thumb(left),thumb(right)
        return a is not None and b is not None and max(ImageStat.Stat(ImageChops.difference(a,b)).rms)<=8
    inventory = {}
    coverage = defaultdict(list)
    for path in inputs:
        for line in path.read_text(encoding='utf-8').splitlines():
            row = json.loads(line)
            if row['kind'] == 'inventory':
                inventory.setdefault(row['table'], row['rows'])
            elif row['kind'] in ('page','error','account'):
                coverage[row.get('account_id',0)].append(row)
    items = [normalize(r) for r in load_items(inputs)]
    products = {p['id']:p for p in inventory['produtos']}
    by_sku = defaultdict(list)
    for p in products.values():
        by_sku[text(p['sku'])].append(p)
    linked = {(u['integration_id'],str(u['item_externo_id']),str(u.get('variacao_externa_id') or '')):u for u in inventory['produto_anuncios']}
    records, group_by_sku, used_skus = {}, defaultdict(list), {p['sku'] for p in products.values()}
    for item in items:
        for unit in item['units']:
            identity = f"{item['account_id']}:{item['item_id']}:{unit['id']}"
            source = {**item, 'unit':unit}
            source.pop('units')
            title = item['title'] + (' — '+', '.join(str(v) for v in unit['attributes'].values()) if unit['attributes'] else '')
            prior = linked.get((item['account_id'],item['item_id'],unit['id'])) or {}
            existing_id = prior.get('produto_id')
            candidates = by_sku.get(text(unit['sku']),[]) if unit['sku'] else []
            safe = [p for p in candidates if p.get('papel_catalogo')!='modelo' and compatible_names(title,p['nome'])]
            if not existing_id and len(safe)==1:
                existing_id=safe[0]['id']
            key = 'existing:'+str(existing_id) if existing_id else identity
            # Cross-account consolidation needs a SKU plus corroborating names
            # and matching technical text. Ambiguous records remain separate.
            if not existing_id and unit['sku']:
                for candidate_key in group_by_sku[text(unit['sku'])]:
                    other=records[candidate_key]
                    if other.get('existing_id'):continue
                    first=other['sources'][0]
                    current_images=unit['images'] or item['images']
                    other_images=first['unit']['images'] or first['images']
                    visual_match=bool(current_images and other_images and same_image(current_images[0],other_images[0]))
                    pages_a=set(re.findall(r'(\d+)\s*paginas',text(item['description'])))
                    pages_b=set(re.findall(r'(\d+)\s*paginas',text(first['description'])))
                    specs_conflict=bool(pages_a and pages_b and pages_a.isdisjoint(pages_b))
                    if not specs_conflict and compatible_names(title,other['name']) and ((text(item['description']) and text(item['description'])==text(first['description'])) or visual_match):
                        key=candidate_key;break
            if key not in records:
                sku = unit['sku'] if unit['sku'] and len(unit['sku'])<=100 and unit['sku'] not in used_skus else 'IMP-'+hashlib.sha256(key.encode()).hexdigest()[:20].upper()
                used_skus.add(sku)
                is_kit=item['item_id'] in KITS or (bool(re.search(r'\b(kit|combo)\b',text(title))) and not any(s in text(title) for s in ('adesivo','etiqueta')))
                manufactured=not any(s in text(title) for s in ('estojo','caderno inteligente','papel foto'))
                records[key]={'key':key,'sku':products[existing_id]['sku'] if existing_id else sku,'name':title,'existing_id':existing_id,
                    'category_id':7 if 'agenda' in text(title) or 'planner' in text(title) else 11,
                    'structure':'kit' if is_kit else 'manufaturado' if manufactured else 'simples',
                    'sources':[],'bom':[],'pending':[], 'variation_values':unit['attributes']}
                if not existing_id:
                    for marker,category in [('estojo','Estojos'),('adesivo','Adesivos e etiquetas'),('etiqueta','Adesivos e etiquetas'),('refil','Refis de papelaria'),('papel foto','Papéis para impressão')]:
                        if marker in text(title):
                            records[key]['category_name']=category
                            break
                group_by_sku[text(unit['sku'])].append(key)
            record=records[key]
            record['sources'].append(source)
            if existing_id and not compatible_names(title,products[existing_id]['nome']):
                record['pending'].append('Vínculo existente preservado, mas nome/edição interna diverge do anúncio; revisar equivalência.')
            if candidates and not existing_id:
                record['pending'].append('SKU externo encontrado em cadastro sem equivalência comprovada; revisar possível duplicidade.')
    # Only entirely new, non-kit families are materialized; existing structures remain unchanged.
    families=[]
    for item in items:
        keys=list(dict.fromkeys(k for k,r in records.items() if any(s['account_id']==item['account_id'] and s['item_id']==item['item_id'] for s in r['sources'])))
        if len(keys)<2 or any(records[k]['existing_id'] or records[k].get('parent_key') or records[k]['structure']=='kit' for k in keys):continue
        if not all(records[k]['sources'][0]['item_id']==item['item_id'] and records[k]['variation_values'] for k in keys):continue
        axes=defaultdict(list)
        for key in keys:
            for name,value in records[key]['variation_values'].items():
                if value not in axes[name]:axes[name].append(value)
        if any(set(records[k]['variation_values'])!=set(axes) for k in keys):continue
        if len({json.dumps(records[k]['variation_values'],sort_keys=True) for k in keys})!=len(keys):continue
        parent_key='family:'+str(item['account_id'])+':'+item['item_id']
        families.append({'key':parent_key,'sku':'IMP-FAM-'+str(item['account_id'])+'-'+item['item_id'],'name':item['title'],'category_id':records[keys[0]]['category_id'],'axes':[{'name':k,'options':v} for k,v in axes.items()],'children':keys})
        for key in keys:records[key]['parent_key']=parent_key
    for record in list(records.values()):
        source=record['sources'][0];item_id=source['item_id'];description=text(source['description'])
        if record['structure']=='kit':
            for index,(label,quantity) in enumerate(KITS.get(item_id,[])):
                component_key=record['key']+':component:'+str(index+1)
                component_sku='IMP-C-'+hashlib.sha256(component_key.encode()).hexdigest()[:20].upper()
                records[component_key]={'key':component_key,'sku':component_sku,'name':(label+' — '+record['name'])[:255],
                    'description_override':label+'. Peça integrante de '+record['name']+'. Demais especificações e consumos de fabricação pendentes. Fonte: '+str(source['account_id'])+':'+item_id,
                    'existing_id':None,'category_id':record['category_id'],'structure':'manufaturado',
                    'sources':record['sources'],'bom':[],'pending':['Consumo de materiais, miolo e arte desta peça precisa de confirmação.'],'component_only':True}
                record['bom'].append({'key':component_key,'quantity':quantity,'unit':'un','evidence':'Descrição e imagem do conjunto; conteúdo revisado por anúncio.'})
            record['pending'].append('Materiais e prontidão das peças do kit pendentes. Não ativar o conjunto.')
        elif record['structure']=='manufaturado':
            # Human confirmed CANGURU is the internal document pocket. Do not
            # confuse it with packing envelopes or infer manufacturing yield.
            if re.search(r'(acompanha|inclui|inclusos).{0,100}envelope plastico',description) and not re.search(r'nao acompanha.{0,30}envelope',description):
                record['bom'].append({'existing_id':193,'quantity':1,'unit':'un','evidence':'Anúncio inclui envelope plástico interno; usuário confirmou SKU CANGURU.'})
            tassel=TASSEL_BY_SKU.get(source['unit']['sku']) or TASSEL_BY_ITEM.get(item_id)
            if tassel and 'tassel' in description:
                record['bom'].append({'existing_id':tassel,'quantity':1,'unit':'un','evidence':'Descrição inclui um tassel; cor conferida na foto desta capa/variação e corresponde ao insumo interno.'})
            if item_id in ('40408868038','MLB4128240377'):
                material_key='material:vinil-adesivo-a5'
                records.setdefault(material_key,{'key':material_key,'sku':'VINIL-ADESIVO-A5','name':'Folha de vinil adesivo A5 para impressão','existing_id':None,'category_id':4,'structure':'simples','material_type':'materia_prima','sources':[source],'bom':[],'pending':['Gramatura, fornecedor e custo não informados.'],'component_only':True})
                record['bom'].append({'key':material_key,'quantity':4,'unit':'un','evidence':'Descrição: 2 folhas A5 menino + 2 folhas A5 menina, em vinil adesivo.'})
            if not record['existing_id']:
                record['pending'].append('Ficha parcial: confirmar miolo, capa/contracapa, acabamento e consumos de fabricação. Não estimar perdas, tinta, metragem de elástico/BOPP ou elos do wire-o.')
        if not source['description']:
            record['pending'].append('Descrição indisponível; especificações precisam de revisão.')
        if re.search(r'\b50 paginas\b',description) and re.search(r'\b50 folhas\b',description):
            record['pending'].append('Descrição contradiz a quantidade: 50 páginas e 50 folhas.')
        if '172 etiquetas' in description:
            record['pending'].append('Conferir total: quantidades discriminadas somam 169, anúncio informa 172 etiquetas.')
        if record['structure']=='simples' and not record['existing_id']:
            record['pending'].append('Revisar classificação e prontidão antes da ativação.')
        record['pending']=list(dict.fromkeys(record['pending']))
    return {'version':1,'run_id':'catalog-import-20261029','items':items,'products':list(records.values()),'families':families,'coverage':dict(coverage),
        'assumptions':['CANGURU confirmado pelo usuário como bolso plástico interno.','Custos desconhecidos permanecem nulos.','Novos produtos com pendências ficam inativos.']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inputs',nargs='+',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--image-manifest',type=Path)
    args=parser.parse_args()
    manifest=prepare(args.inputs,args.image_manifest)
    args.output.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'announcements':len(manifest['items']),'products':len(manifest['products']),'reuse':sum(bool(p['existing_id']) for p in manifest['products']),'families':len(manifest['families']),'bom_lines':sum(len(p['bom']) for p in manifest['products'])}))


if __name__=='__main__':main()
