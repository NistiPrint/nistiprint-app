"""Bounded database reports with revision-aware, permission-separated caching."""
from collections import OrderedDict
from copy import deepcopy
from datetime import date, datetime, timedelta
import json
from threading import RLock
from time import monotonic

from nistiprint_shared.services.gestao_projection import TZ

_cache=OrderedDict()
_lock=RLock()


def report(db, start, end, filters, include_finance):
    from nistiprint_shared.services.gestao_service import analyze, paginate, rate
    revision=db.rpc('gestao_report_revision',{'p_account':filters.get('account_id',0)}).execute().data
    key=(id(db),start.isoformat(),end.isoformat(),json.dumps(filters,sort_keys=True),include_finance)
    with _lock:
        cached=_cache.get(key)
        if cached and cached[0]==revision and monotonic()-cached[1]<60:
            _cache.move_to_end(key)
            return deepcopy(cached[2])
    data=analyze([],start,end,filters,include_finance=include_finance)
    payload=db.rpc('gestao_report_cached',{'p_start':start.isoformat(),'p_end':end.isoformat(),
        'p_filters':filters,'p_finance':include_finance}).execute().data
    data.update(payload)
    # JSON aggregation order is not guaranteed by the input CTE ordering.
    data['products'].sort(key=lambda row: (row.get('sales') is not None, row.get('sales') or 0), reverse=True)
    for rows in data.get('rankings', {}).values():
        rows.sort(key=lambda row: (row.get('sales') is not None, row.get('sales') or 0), reverse=True)
    data['names'].sort(key=lambda row: row.get('occurrences') or 0, reverse=True)
    data['regions'].sort(key=lambda row: (row.get('sales') is not None, row.get('sales') or 0), reverse=True)
    data['pairs'].sort(key=lambda row: row.get('orders') or 0, reverse=True)
    data['personalization']['coverage']=rate(data['personalization']['identified_orders'],data['personalization']['eligible_orders'])
    data['customers']['average_gap_days']=data['customers'].pop('avg_gap_days',None)
    for cohort in data['customers']['cohorts']:
        cohort['first_month']=cohort.pop('cohort',None)
        cohort['purchase_month']=cohort.pop('month',None)
    data['options']={
        'accounts':list(paginate(lambda:db.table('installed_integrations').select('id,instance_name,platform_slug').eq('is_active',True).order('id'))),
        'products':list(paginate(lambda:db.table('produtos').select('id,nome').order('id'))),
        'categories':list(paginate(lambda:db.table('categorias').select('id,nome').order('id'))),
    }
    today=datetime.now(TZ).date()
    for row in data['weekdays']:
        days=[d for d in data['daily'] if date.fromisoformat(d['day']).weekday()==row['weekday'] and d['day']<today.isoformat()]
        row.update(occurrences=len(days),average_sales=round(sum(d['sales'] for d in days)/len(days),2) if days and all(d['sales'] is not None for d in days) else None,
            average_orders=round(sum(d['orders'] for d in days)/len(days),2) if days else None)
    # Forecast runs on at most 35 aggregated days, never on the order history.
    history=data.pop('forecast_history',[])
    if len(history)>=35 and all(d['sales'] is not None for d in history):
        training,testing=history[-35:-7],history[-7:]
        averages={w:sum(d['sales'] for d in training if date.fromisoformat(d['day']).weekday()==w)/4 for w in range(7)}
        mae=sum(abs(d['sales']-averages[date.fromisoformat(d['day']).weekday()]) for d in testing)/7
        recent=history[-28:]
        next_average={w:sum(d['sales'] for d in recent if date.fromisoformat(d['day']).weekday()==w)/4 for w in range(7)}
        anchor=date.fromisoformat(history[-1]['day'])
        data['forecast']={'days':[{'day':(anchor+timedelta(days=i)).isoformat(),'sales':round(next_average[(anchor+timedelta(days=i)).weekday()],2)} for i in range(1,8)],
            'mae':round(mae,2),'training_days':28,'test_days':7,'status':'available'}
    data['ad_metrics']=payload.get('ad_metrics',[]) if include_finance else []
    data.setdefault('planning',[])
    data.setdefault('component_requirements',[])
    data.setdefault('goals',[])
    add_planning(db,data,start,end,filters,include_finance)
    from nistiprint_shared.services.gestao_signals import build_signals
    data['opportunities'], data['exceptions'] = build_signals(data, filters)
    data['alerts'] = data['exceptions']  # Existing readers retain the old key.
    with _lock:
        _cache[key]=(revision,monotonic(),deepcopy(data))
        _cache.move_to_end(key)
        while len(_cache)>128: _cache.popitem(last=False)
    return data


def add_planning(db,data,start,end,filters,include_finance):
    import calendar
    from nistiprint_shared.services.gestao_service import rate
    product_ids=[p['product_id'] for p in data['products'] if p.get('product_id')]
    data['planning'],data['component_requirements']=[],[]
    anchor=min(end,datetime.now(TZ).date()-timedelta(days=1))
    enough=bool(data['coverage']) and all(c['from']<=(anchor-timedelta(days=27)).isoformat() for c in data['coverage'])
    if product_ids:
        demand=db.rpc('gestao_product_demand',{'p_start':(anchor-timedelta(days=27)).isoformat(),'p_end':anchor.isoformat(),
            'p_filters':filters,'p_products':product_ids}).execute().data or {}
        bom=db.table('ficha_tecnica').select('produto_pai_id,componente_id,quantidade_necessaria,unidade_medida').in_('produto_pai_id',product_ids).limit(1000).execute().data or []
        ids=list(set(product_ids+[r['componente_id'] for r in bom]))
        stocks={}
        from nistiprint_shared.services.gestao_service import paginate
        for row in paginate(lambda:db.table('estoque_atual').select('id,produto_id,disponivel').in_('produto_id',ids).order('id')):
            if row.get('disponivel') is not None: stocks[row['produto_id']]=stocks.get(row['produto_id'],0)+float(row['disponivel'])
        needs={}
        for p in data['products']:
            pid=p.get('product_id')
            if not pid: continue
            daily=float(demand.get(str(pid),0))/28 if enough else None
            stock=stocks.get(pid)
            suggested=max(0,round(daily*7-stock,2)) if daily is not None and stock is not None else None
            data['planning'].append({'product_id':pid,'name':p['name'],'available':stock,'daily_units':round(daily,2) if daily is not None else None,
                'coverage_days':round(stock/daily,1) if stock is not None and daily else None,'suggested_units':suggested})
            if suggested is not None:
                for c in bom:
                    if c['produto_pai_id']==pid:
                        key=(c['componente_id'],c['unidade_medida'])
                        needs[key]=needs.get(key,0)+suggested*float(c['quantidade_necessaria'] or 0)
        data['component_requirements']=[{'product_id':k[0],'unit':k[1],'required':round(v,4),'available':stocks.get(k[0])} for k,v in needs.items()]
    data['goals']=[]
    if any(filters.get(k) for k in ('product_id','category_id','logistics')) or (filters.get('marketplace') and not filters.get('account_id')): return
    month=end.replace(day=1)
    goals=db.table('gestao_metas').select('*').eq('month',month.isoformat()).eq('account_id',filters.get('account_id',0)).execute().data or []
    goals=[g for g in goals if include_finance or g['metric']!='contribution']
    if not goals: return
    monthly=data if start==month else db.rpc('gestao_report_cached',{'p_start':month.isoformat(),'p_end':end.isoformat(),'p_filters':filters,'p_finance':include_finance}).execute().data
    elapsed=end.day
    if end==datetime.now(TZ).date():
        clock=datetime.now(TZ)
        elapsed=max(.01,end.day-1+(clock.hour*3600+clock.minute*60+clock.second)/86400)
    for g in goals:
        actual=monthly.get('profitability',{}).get('before_ads') if g['metric']=='contribution' else monthly['summary'][g['metric']]
        data['goals'].append({**g,'actual':actual,'progress':rate(actual,float(g['target'])) if actual is not None else None,
            'projected':round(actual/elapsed*calendar.monthrange(end.year,end.month)[1],2) if actual is not None else None,
            'remaining':max(0,round(float(g['target'])-actual,2)) if actual is not None else None})


def order_page(db,start,end,filters,page):
    return db.rpc('gestao_order_page',{'p_start':start.isoformat(),'p_end':end.isoformat(),
        'p_filters':filters,'p_page':page}).execute().data
