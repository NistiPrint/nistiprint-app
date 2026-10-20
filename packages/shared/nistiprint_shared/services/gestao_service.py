"""Business metrics with explicit populations, coverage and provenance."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from itertools import combinations
from statistics import mean

from nistiprint_shared.services.gestao_projection import TZ, local_time, number

METRICS = {
    'orders': 'Pedidos canônicos elegíveis: pagos/em preparação, enviados ou entregues. Cancelados e devolvidos separados.',
    'sales': 'Soma dos subtotais dos itens elegíveis. Frete, cupons e subsídios ainda não conciliados não são receita líquida.',
    'ticket': 'Valor dos itens elegíveis dividido pelos pedidos elegíveis no recorte.',
    'buyer_total': 'Total registrado no pedido, separado do valor dos produtos e do repasse ao vendedor.',
    'contribution': 'Repasse líquido menos custo dos produtos, tributos variáveis e despesas operacionais variáveis. Taxas já descontadas do repasse não são subtraídas novamente.',
    'recurrence': 'Compradores identificados com compra elegível anterior, na mesma conta e marketplace; somente histórico observado.',
    'names': 'Ocorrências com status SUCCESS e texto não vazio. Unidades somente quando a quantidade é explícita.',
    'forecast': 'Média por dia da semana nas últimas quatro semanas; erro absoluto médio em retrospectiva de sete dias. Sem sazonalidade anual.',
}


def days_between(start, end):
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def rate(n, d):
    return round(100 * n / d, 2) if d else None


def sales(order):
    values = [i.get('subtotal') for i in order['items']]
    return sum(values) if values and all(v is not None for v in values) else None


def summary(orders):
    valid = [o for o in orders if o['eligible']]
    amounts = [sales(o) for o in valid]
    known = [v for v in amounts if v is not None]
    return {'orders': len(valid), 'created': len(orders), 'sales': round(sum(known), 2) if known or not valid else None,
            'sales_known_orders': len(known), 'sales_coverage': rate(len(known), len(valid)),
            'units': sum(i['quantity'] or 0 for o in valid for i in o['items']),
            'ticket': round(sum(known) / len(known), 2) if known else None,
            'buyer_total': round(sum(o['total'] for o in valid if o.get('total') is not None), 2),
            'cancelled': sum(o['stage'] == 'cancelled' for o in orders),
            'returned': sum(o['stage'] == 'returned' for o in orders),
            'refunded': sum(o['stage'] == 'refunded' for o in orders),
            'partially_refunded': sum(o.get('stage')=='partially_refunded' or o.get('payment_status') in {'partially_refunded','partial_refund'} for o in orders),
            'awaiting_payment': sum(o['stage'] == 'awaiting_payment' for o in orders),
            'unknown': sum(o['stage'] == 'unknown' for o in orders),
            'cancel_rate': rate(sum(o['stage'] == 'cancelled' for o in orders), len(orders))}


def contribution(order):
    finance = order.get('finance') or {}
    c = finance.get('components') or {}
    items = order['items']
    cost_known = bool(items) and all(i.get('unit_cost') is not None and i.get('quantity') is not None for i in items)
    cost = sum(i['unit_cost'] * i['quantity'] for i in items) if cost_known else None
    if not order['eligible']:
        # Returned inventory may have been recovered. Do not guess its consumption.
        cost = number(c.get('cogs'))
        cost_known = cost is not None
    required = ('net_payout', 'taxes', 'operating_cost')
    complete = cost_known and all(number(c.get(k)) is not None for k in required)
    before = number(c['net_payout']) - cost - number(c['taxes']) - number(c['operating_cost']) if complete else None
    ads = number(c.get('ads'))
    return {'id': order['id'], 'number': order.get('number'), 'account': order['account_name'],
            'source': finance.get('source'), 'components': c, 'cost': round(cost, 2) if cost is not None else None,
            'before_ads': round(before, 2) if before is not None else None,
            'after_ads': round(before - ads, 2) if before is not None and ads is not None else None,
            'state': ('estimated' if not finance.get('settled') or any(i['cost_estimated'] for i in items) else 'settled') if complete else 'incomplete'}


def analyze(facts, start, end, filters=None, *, include_finance=False, now=None):
    filters = filters or {}
    now = now or datetime.now(TZ)
    today = now.date()
    # Current partial day is compared only to the same elapsed clock interval.
    span = (end - start).days + 1
    previous_start, previous_end = start - timedelta(days=span), start - timedelta(days=1)
    all_history = []
    for raw in facts:
        o = dict(raw)
        if filters.get('marketplace') and o['marketplace'] != filters['marketplace']:
            continue
        if filters.get('account_id') and o.get('account_id') != filters['account_id']:
            continue
        if filters.get('logistics') and o.get('logistics') != filters['logistics']:
            continue
        if filters.get('product_id') or filters.get('category_id'):
            selected = [i for i in o['items'] if
                        (not filters.get('product_id') or i.get('product_id') == filters['product_id']) and
                        (not filters.get('category_id') or i.get('category_id') == filters['category_id'])]
            if not selected:
                continue
            o['items'] = selected
            o['names'] = [n for n in o['names'] if n['item_id'] in {i['id'] for i in selected}]
            # Order-wide financial totals cannot be assigned to a filtered item without allocation evidence.
            o['finance'] = None
        if date.fromisoformat(o['sold_on']) <= end:
            all_history.append(o)
    current = [o for o in all_history if start.isoformat() <= o['sold_on'] <= end.isoformat()]
    previous = [o for o in all_history if previous_start.isoformat() <= o['sold_on'] <= previous_end.isoformat()]
    comparable_current, comparable_previous = current, previous
    comparison_note = None
    if end == today:
        # Day-only records cannot be cut at the current hour: compare completed days for them.
        def elapsed(o, cutoff):
            at = local_time(o['sold_at'])
            return o['sold_on'] < cutoff.isoformat() or (o['hour'] is not None and at.time() <= now.time().replace(tzinfo=None))
        comparable_current = [o for o in current if elapsed(o, end)]
        comparable_previous = [o for o in previous if elapsed(o, previous_end)]
        comparison_note = 'Último dia comparado até o horário atual; registros sem horário entram apenas em dias completos.'
    totals, previous_totals = summary(current), summary(previous)
    compare_a, compare_b = summary(comparable_current), summary(comparable_previous)
    changes = {k: round((compare_a[k] / compare_b[k] - 1) * 100, 2) if compare_b[k] and compare_a[k] is not None else None for k in ('sales', 'orders', 'units')}
    account_first={}
    for o in all_history:
        key=(o['marketplace'],o['account_id'])
        account_first[key]=min(account_first.get(key,o['sold_on']),o['sold_on'])
    if any(account_first[(o['marketplace'],o['account_id'])]>previous_start.isoformat() for o in current):
        changes={k:None for k in changes}
        comparison_note='Cobertura histórica insuficiente em pelo menos uma conta para comparar os períodos completos.'
    eligible = [o for o in current if o['eligible']]
    daily_groups, channel_groups, region_groups = defaultdict(list), defaultdict(list), defaultdict(list)
    product_groups, name_groups = {}, {}
    previous_products = Counter()
    def product_key(i, o):
        return f"product:{i['product_id']}" if i.get('product_id') else f"listing:{o['account_id']}:{i.get('listing') or i.get('sku') or i['id']}:{i.get('variation') or ''}"
    for o in previous:
        if o['eligible']:
            for i in o['items']:
                previous_products[product_key(i,o)] += i.get('subtotal') or 0
    for o in current:
        daily_groups[o['sold_on']].append(o)
        channel_groups[(o['marketplace'],o['account_id'],o['account_name'])].append(o)
    for o in eligible:
        region_groups[(o.get('region') or 'Não informado',o.get('city') or 'Não informada')].append(o)
        for i in o['items']:
            key = product_key(i,o)
            p = product_groups.setdefault(key, {'key': key, 'name': i['name'], 'product_id': i.get('product_id'),
                'family_id': i.get('family_id'), 'category_id': i.get('category_id'), 'format': i.get('format'),
                'mapping': i['mapping'], 'sales': 0, 'known_items':0, 'units': 0, 'orders': set(), 'channels': {}})
            p['sales'] += i.get('subtotal') or 0
            p['known_items'] += int(i.get('subtotal') is not None)
            p['units'] += i.get('quantity') or 0
            p['orders'].add(o['id'])
            ch = p['channels'].setdefault(f"{o['marketplace']} / {o['account_name']}", {'sales':0,'units':0})
            ch['sales'] += i.get('subtotal') or 0
            ch['units'] += i.get('quantity') or 0
        for n in o['names']:
            if n['status'] != 'SUCCESS':
                continue
            for kind in ('name', 'initial'):
                if not n.get(kind):
                    continue
                key = (kind, n[kind].casefold())
                g = name_groups.setdefault(key, {'kind':kind, 'name':n[kind], 'occurrences':0,'units':0,'quantity_known':0,'confirmed':0})
                g['occurrences'] += 1
                g['confirmed'] += int(n['confirmed'])
                if n.get('quantity') is not None:
                    g['units'] += n['quantity']
                    g['quantity_known'] += 1
    products = sorted(product_groups.values(), key=lambda p:p['sales'], reverse=True)
    accumulated = 0
    for p in products:
        p['orders'] = len(p['orders'])
        p['share'] = rate(p['sales'], totals['sales'])
        p['abc'] = ('A' if accumulated < .8 * (totals['sales'] or 0) else 'B' if accumulated < .95 * (totals['sales'] or 0) else 'C') if p['known_items'] else None
        accumulated += p['sales']
        old = previous_products[p['key']]
        p['change'] = round((p['sales']/old-1)*100,2) if old else None
        p['unit_price'] = round(p['sales']/p['units'],2) if p['units'] else None
        p['sales'] = round(p['sales'],2) if p['known_items'] else None
    dimensions={}
    for dimension in ('listings','families','categories','formats'):
        buckets={}
        for o in eligible:
            for i in o['items']:
                if dimension=='listings':
                    key=f"{o['account_id']}:{i.get('listing') or i.get('sku') or i['id']}:{i.get('variation') or ''}"
                    label=f"{i.get('listing_title') or i['name']} · {o['account_name']} · {i.get('variation_name') or i.get('variation') or 'sem variação'}"
                elif dimension=='families':
                    key=i.get('family_id') or 'unknown';label=i.get('family_name') or 'Família não identificada'
                elif dimension=='categories':
                    key=i.get('category_id') or 'unknown';label=f"Categoria {key}" if key!='unknown' else 'Categoria não identificada'
                else:
                    key=i.get('format') or 'unknown';label=i.get('format') or 'Formato não identificado'
                g=buckets.setdefault(key,{'key':key,'name':label,'sales':0,'units':0,'order_ids':set()})
                g['sales']+=i.get('subtotal') or 0;g['units']+=i.get('quantity') or 0;g['order_ids'].add(o['id'])
        dimensions[dimension]=sorted([{'key':g['key'],'name':g['name'],'sales':round(g['sales'],2),'units':g['units'],
            'orders':len(g['order_ids']),'share':rate(g['sales'],totals['sales'])} for g in buckets.values()],key=lambda p:p['sales'],reverse=True)
    daily = [{'day':d.isoformat(), **summary(daily_groups[d.isoformat()])} for d in days_between(start,end)]
    weekdays = []
    for weekday in range(7):
        complete_days = [d for d in daily if date.fromisoformat(d['day']).weekday()==weekday and d['day']<today.isoformat()]
        weekdays.append({'weekday':weekday,'occurrences':len(complete_days),
                         'average_sales':round(mean(d['sales'] for d in complete_days if d['sales'] is not None),2) if complete_days and all(d['sales'] is not None for d in complete_days) else None,
                         'average_orders':round(mean(d['orders'] for d in complete_days),2) if complete_days else None})
    hours = [{'hour':h, **summary([o for o in eligible if o['hour']==h])} for h in range(24)]
    # Buyer IDs remain internal. Neither aggregates nor drilldowns expose them.
    purchases = defaultdict(list)
    for o in sorted(all_history,key=lambda o:o['sold_at']):
        if o['eligible'] and o.get('buyer_key'):
            purchases[o['buyer_key']].append(o)
    buyers = {o['buyer_key'] for o in eligible if o.get('buyer_key')}
    repeat = sum(any(o['sold_on']<start.isoformat() for o in purchases[b]) for b in buyers)
    gaps=[]
    cohorts=defaultdict(set)
    cohort_sizes=Counter(history[0]['sold_on'][:7] for history in purchases.values())
    segments=Counter('Uma compra' if len(purchases[b])==1 else 'Duas ou três compras' if len(purchases[b])<=3 else 'Quatro ou mais compras' for b in buyers)
    for b in buyers:
        history=purchases[b]
        for first,second in zip(history,history[1:]):
            if second['sold_on']>=start.isoformat():
                gaps.append((date.fromisoformat(second['sold_on'])-date.fromisoformat(first['sold_on'])).days)
        first_month=history[0]['sold_on'][:7]
        for o in history:
            if o['sold_on']>=start.isoformat():
                cohorts[(first_month,o['sold_on'][:7])].add(b)
    pair_counts=Counter()
    for o in eligible:
        keys=sorted({product_key(i,o) for i in o['items']})
        pair_counts.update(combinations(keys,2))
    coverage_groups=defaultdict(list)
    for o in all_history:
        coverage_groups[(o['marketplace'],o['account_id'])].append(o)
    coverage=[{'marketplace':k[0],'account_id':k[1],'from':min(o['sold_on'] for o in group),
               'to':max(o['sold_on'] for o in group),'orders':len(group)} for k,group in coverage_groups.items()]
    # Fixed 28-day training window, and an actual 7-day holdout, including zero-sales days.
    series=Counter()
    for o in all_history:
        if o['eligible']:
            series[o['sold_on']]+=sales(o) or 0
    first=min((date.fromisoformat(o['sold_on']) for o in all_history),default=end)
    anchor=min(end,today-timedelta(days=1))
    forecast=[]
    if (anchor-first).days>=27 and all(sales(o) is not None for o in all_history if o['eligible']):
        for d in days_between(anchor+timedelta(days=1),anchor+timedelta(days=7)):
            samples=[series[x.isoformat()] for x in days_between(anchor-timedelta(days=27),anchor) if x.weekday()==d.weekday()]
            forecast.append({'day':d.isoformat(),'sales':round(mean(samples),2)})
    errors=[]
    if (anchor-first).days>=34:
        for d in days_between(anchor-timedelta(days=6),anchor):
            samples=[series[x.isoformat()] for x in days_between(d-timedelta(days=28),d-timedelta(days=1)) if x.weekday()==d.weekday()]
            errors.append(abs(mean(samples)-series[d.isoformat()]))
    alerts=[]
    if changes['sales'] is not None and changes['sales']<=-20:
        alerts.append({'title':'Queda no valor dos itens','evidence':f"{changes['sales']}% contra o período comparável",'action':'Verifique canais, produtos e cobertura antes de alterar campanhas.'})
    if previous_totals['created']>=10 and totals['created']>=10 and totals['cancel_rate'] is not None and previous_totals['cancel_rate'] is not None and totals['cancel_rate']-previous_totals['cancel_rate']>=5:
        alerts.append({'title':'Aumento de cancelamentos','evidence':f"{totals['cancel_rate']}% contra {previous_totals['cancel_rate']}% no período anterior",'action':'Investigue motivos por canal, disponibilidade e prazos antes de ampliar campanhas.'})
    if products and (products[0]['share'] or 0)>=40:
        alerts.append({'title':'Concentração em um produto/anúncio','evidence':f"{products[0]['name']}: {products[0]['share']}% do valor dos itens",'action':'Avalie dependência, estoque e alternativas de catálogo.'})
    if totals['unknown']:
        alerts.append({'title':'Estados comerciais não classificados','evidence':f"{totals['unknown']} pedidos fora dos indicadores de vendas elegíveis",'action':'Revise a classificação da fonte para completar a análise.'})
    all_items=[i for o in current for i in o['items']]
    personalized=[o for o in eligible if o.get('personalized')]
    names_orders=sum(any(n['status']=='SUCCESS' and (n.get('name') or n.get('initial')) for n in o['names']) for o in personalized)
    result={
        'period':{'start':start.isoformat(),'end':end.isoformat(),'previous_start':previous_start.isoformat(),'previous_end':previous_end.isoformat()},
        'summary':totals,'previous':previous_totals,'changes':changes,'comparison_note':comparison_note,
        'daily':daily,'weekdays':weekdays,'hours':hours,'products':products,'rankings':dimensions,
        'channels':[{'marketplace':k[0],'account_id':k[1],'name':k[2],**summary(v)} for k,v in channel_groups.items()],
        'regions':[{'region':k[0],'city':k[1],**summary(v)} for k,v in sorted(region_groups.items(),key=lambda pair:sum(sales(o) or 0 for o in pair[1]),reverse=True)],
        'names':sorted(name_groups.values(),key=lambda n:n['occurrences'],reverse=True),
        'personalization':{'eligible_orders':len(personalized),'identified_orders':names_orders,'coverage':rate(names_orders,len(personalized)),
                           'pending':sum(n['status']=='NEEDS_REVIEW' for o in eligible for n in o['names'])},
        'customers':{'identified':len(buyers),'returning':repeat,'new_observed':len(buyers)-repeat,'segments':[{'name':k,'buyers':v} for k,v in segments.items()],
                     'repeat_rate':rate(repeat,len(buyers)), 'average_gap_days':round(mean(gaps),1) if gaps else None,
                     'cohorts':[{'first_month':k[0],'purchase_month':k[1],'buyers':len(v),'cohort_size':cohort_sizes[k[0]],'retention':rate(len(v),cohort_sizes[k[0]])} for k,v in sorted(cohorts.items())]},
        'pairs':[{'first':a,'second':b,'orders':n} for (a,b),n in pair_counts.most_common(30)],
        'forecast':{'days':forecast,'mae':round(mean(errors),2) if errors else None,'training_days':28,'test_days':len(errors), 'status':'estimated' if forecast else 'insufficient_history'},
        'alerts':alerts,'coverage':coverage,
        'quality':{'orders':len(current),'mapped_items':sum(i['product_id'] is not None for i in all_items), 'items':len(all_items),
                   'mapping_conflicts':sum(i['mapping']=='conflict' for i in all_items),
                   'geography':rate(sum(bool(o.get('region')) for o in eligible),len(eligible)),
                   'buyer_identity':rate(sum(bool(o.get('buyer_key')) for o in eligible),len(eligible)),
                   'hour':rate(sum(o['hour'] is not None for o in eligible),len(eligible))},
        'definitions':{k:v for k,v in METRICS.items() if k!='contribution' or include_finance},
        'generated_at':now.isoformat(), 'timezone':'America/Sao_Paulo',
    }
    if include_finance:
        margin_orders=eligible+[o for o in current if not o['eligible'] and o.get('finance')]
        margins=[contribution(o) for o in margin_orders]
        known=[m for m in margins if m['before_ads'] is not None]
        after=[m for m in margins if m['after_ads'] is not None]
        result['profitability']={'orders':margins,'coverage':rate(len(known),len(margin_orders)),
            'before_ads':round(sum(m['before_ads'] for m in known),2) if known else None,
            'after_ads':round(sum(m['after_ads'] for m in after),2) if after else None,
            'after_ads_orders':len(after),'estimated_orders':sum(m['state']=='estimated' for m in margins)}
        grouped=defaultdict(lambda:{'orders':0,'known':0,'before_ads':0,'after_ads':0,'after_ads_known':0})
        for o,m in zip(margin_orders,margins):
            g=grouped[(o['marketplace'],o['account_name'])]
            g['orders']+=1
            if m['before_ads'] is not None:
                g['before_ads']+=m['before_ads'];g['known']+=1
            if m['after_ads'] is not None:
                g['after_ads']+=m['after_ads'];g['after_ads_known']+=1
        result['profitability']['channels']=[{'marketplace':k[0],'name':k[1],**g,
            'coverage':rate(g['known'],g['orders']), 'before_ads':round(g['before_ads'],2) if g['known'] else None,
            'after_ads':round(g['after_ads'],2) if g['after_ads_known'] else None} for k,g in grouped.items()]
        allocated=defaultdict(lambda:{'name':'','before_ads':0,'after_ads':0,'known':0,'after_ads_known':0})
        for o,m in zip(margin_orders,margins):
            total=sales(o)
            if m['before_ads'] is None or not total or total<=0 or not o['eligible']:
                continue
            c=o['finance']['components']
            net=number(c['net_payout'])-number(c['taxes'])-number(c['operating_cost'])
            for i in o['items']:
                p=allocated[product_key(i,o)]
                fraction=i['subtotal']/total
                p['name']=i['name'];p['known']+=1
                before=net*fraction-i['unit_cost']*i['quantity']
                p['before_ads']+=before
                if number(c.get('ads')) is not None:
                    p['after_ads']+=before-number(c['ads'])*fraction;p['after_ads_known']+=1
        result['profitability']['products']=[{'key':key,**v,'before_ads':round(v['before_ads'],2),
            'after_ads':round(v['after_ads'],2) if v['after_ads_known'] else None,'allocation':'proporcional_ao_valor_dos_itens'} for key,v in allocated.items()]
        negative=[m for m in known if m['before_ads']<0]
        if negative:
            alerts.append({'title':'Pedidos com contribuição negativa','evidence':f"{len(negative)} pedidos com componentes conhecidos",'action':'Confira taxas, custo vigente e despesas antes de revisar preço ou publicidade.'})
    events=[e for o in all_history for e in o.get('events',[]) if start.isoformat()<=str(e['occurred_at'])[:10]<=end.isoformat()]
    observed_dispatches=[o for o in all_history if local_time(o.get('shipped_at')) and local_time(o.get('deadline')) and start<=local_time(o['shipped_at']).date()<=end]
    result['operations']={'events':len(events),'stages':dict(Counter(e['stage'] for e in events)),
        'duration_minutes':sum(number(e.get('duration_minutes')) or 0 for e in events),
        'late_dispatches':sum(local_time(o['shipped_at'])>local_time(o['deadline']) for o in observed_dispatches),
        'observed_dispatches':len(observed_dispatches)}
    return result


def paginate(query_factory, size=1000):
    offset=0
    while True:
        rows=query_factory().range(offset,offset+size-1).execute().data
        if rows is None:
            raise RuntimeError('Fonte analítica indisponível')
        yield from rows
        if len(rows)<size:
            break
        offset+=size


class GestaoService:
    def __init__(self, db):
        self.db=db

    def report(self, start, end, filters, include_finance=False):
        from nistiprint_shared.services.gestao_report_repository import report
        return report(self.db,start,end,filters,include_finance)
