"""Prepare private text evidence and contact sheets for manual visual review."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
from io import BytesIO
import json
from pathlib import Path
from urllib.request import urlopen
from PIL import Image, ImageDraw, ImageOps


def load_items(paths):
    items = {}
    for path in paths:
        for line in path.read_text(encoding='utf-8').splitlines():
            row = json.loads(line)
            if row['kind'] == 'item' and row.get('data'):
                items[(row['account_id'], row['item_id'])] = row
    return list(items.values())


def normalize(row):
    data = row['data']
    if row['provider'] == 'shopee':
        models = row.get('models') or {}
        tiers = models.get('tier_variation') or []
        units = []
        model_rows = models.get('model') or ([] if data.get('has_model') else [data])
        for model in model_rows:
            attrs, pictures = {}, []
            for tier, index in zip(tiers, model.get('tier_index') or []):
                option = tier['option_list'][index]
                attrs[tier['name']] = option.get('option')
                if option.get('image', {}).get('image_url'):
                    pictures.append(option['image']['image_url'])
            price_info = model.get('price_info') or []
            stock = ((model.get('stock_info_v2') or {}).get('summary_info') or {}).get('total_available_stock')
            units.append({'id': str(model.get('model_id') or ''), 'sku': model.get('model_sku') or data.get('item_sku'), 'attributes': attrs, 'images': pictures,
                          'price':str(price_info[0]['current_price']) if price_info and price_info[0].get('current_price') is not None else None,
                          'available':str(stock) if stock is not None else None})
        description = data.get('description') or ''
        if not description:
            fields = ((data.get('description_info') or {}).get('extended_description') or {}).get('field_list') or []
            description = '\n'.join(f.get('text') or '' for f in fields)
        title, status = data.get('item_name'), data.get('item_status')
        images = (data.get('image') or {}).get('image_url_list') or []
    else:
        picture_map = {p['id']: p.get('secure_url') or p.get('url') for p in data.get('pictures') or []}
        images = list(picture_map.values())
        units = []
        for model in data.get('variations') or [data]:
            sku = next((a.get('value_name') for a in model.get('attributes', []) if a.get('id') == 'SELLER_SKU'), None)
            sku = sku or model.get('seller_custom_field') or next((a.get('value_name') for a in data.get('attributes', []) if a.get('id') == 'SELLER_SKU'), None)
            units.append({'id': str(model.get('id')) if model is not data else '', 'sku': sku, 'attributes': {a.get('name') or a['id']: a.get('value_name') for a in model.get('attribute_combinations') or []}, 'images': [picture_map[p] for p in model.get('picture_ids') or [] if p in picture_map],
                          'price':str(model.get('price',data.get('price'))) if model.get('price',data.get('price')) is not None else None,
                          'available':str(model.get('available_quantity',data.get('available_quantity'))) if model.get('available_quantity',data.get('available_quantity')) is not None else None})
        description = (row.get('description') or {}).get('plain_text') or ''
        title, status = data.get('title'), data.get('status')
    return {'account_id': row['account_id'], 'provider': row['provider'], 'item_id': row['item_id'], 'title': title, 'status': status, 'description': description, 'images': images, 'units': units,
            'url':data.get('permalink'),'provider_updated_at':data.get('last_updated'),
            'user_product_id':data.get('user_product_id'),'familia_externa_id':data.get('family_id'),'catalogo_externo_id':data.get('catalog_product_id')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inputs', nargs='+', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--images', choices=['none', 'primary', 'products', 'all'], default='none')
    parser.add_argument('--columns', type=int, default=4)
    parser.add_argument('--rows', type=int, default=4)
    parser.add_argument('--cell-size', type=int, default=320)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    items = [normalize(r) for r in load_items(args.inputs)]
    (args.output / 'normalized.json').write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding='utf-8')
    if args.images == 'none':
        print(json.dumps({'items':len(items),'units':sum(len(i['units']) for i in items)}))
        return
    assets = {}
    for item in items:
        urls = item['images'][:1] if args.images in ('primary','products') else item['images']
        if args.images in ('products','all'):
            urls = urls + [url for u in item['units'] for url in u['images']]
        for url in urls:
            assets.setdefault(url, []).append(f"{item['account_id']}:{item['item_id']}")
    directory = args.output / 'images'
    directory.mkdir(exist_ok=True)
    def fetch(entry):
        url, references = entry
        target = directory / (hashlib.sha256(url.encode()).hexdigest()[:24] + '.jpg')
        try:
            if not target.exists():
                with urlopen(url, timeout=25) as response:
                    raw = response.read(15_000_001)
                if len(raw)>15_000_000:raise ValueError('image_too_large')
                Image.open(BytesIO(raw)).convert('RGB').save(target)
            return {'url':url,'references':references,'path':str(target.resolve())}
        except Exception as exc:
            return {'url':url,'references':references,'error':type(exc).__name__}
    with ThreadPoolExecutor(max_workers=6) as pool:
        manifest = list(pool.map(fetch, assets.items()))
    (args.output / 'image-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    good = [r for r in manifest if r.get('path')]
    columns, rows, size = args.columns, args.rows, args.cell_size
    if min(columns,rows,size)<=0:raise ValueError('Invalid sheet dimensions')
    per_sheet=columns*rows
    for start in range(0,len(good),per_sheet):
        sheet=Image.new('RGB',(columns*size,rows*(size+40)),'white');draw=ImageDraw.Draw(sheet)
        for offset,entry in enumerate(good[start:start+per_sheet]):
            x,y=(offset%columns)*size,(offset//columns)*(size+40)
            with Image.open(entry['path']) as pic:
                sheet.paste(ImageOps.contain(pic,(size-4,size-4)),(x,y))
            draw.text((x+3,y+size-1),str(start+offset)+' '+','.join(entry['references'])[:43],fill='black')
            draw.text((x+3,y+size+15),Path(entry['path']).stem,fill='black')
        sheet.save(args.output / f'sheet-{start//per_sheet:03d}.jpg')
    print(json.dumps({'items':len(items),'images':len(good),'failed':len(manifest)-len(good),'sheets':(len(good)+per_sheet-1)//per_sheet}))


if __name__ == '__main__':
    main()
