"""Authenticated management APIs; provider credentials never reach this blueprint."""
import csv
import io
import logging
from datetime import date, datetime, timedelta

from flask import Blueprint, Response, jsonify, request
from routes.auth import get_current_user, require_request_permission, user_has_permission
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.gestao_projection import TZ, local_time, number
from nistiprint_shared.services.gestao_service import GestaoService

gestao_bp = Blueprint('gestao', __name__, url_prefix='/api/v2/gestao')
logger = logging.getLogger(__name__)


@gestao_bp.before_request
def authorize():
    if request.method == 'OPTIONS':
        return None
    denied = require_request_permission('gestao', 'ler' if request.method == 'GET' else 'editar')
    if denied:
        return denied
    if request.endpoint in {'gestao.finance', 'gestao.cost'}:
        return require_request_permission('gestao_financeiro', 'editar')
    if request.endpoint in {'gestao.export', 'gestao.orders'}:
        return require_request_permission('gestao_detalhes', 'ler')


def params():
    today = datetime.now(TZ).date()
    try:
        end = date.fromisoformat(request.args.get('end', today.isoformat()))
        start = date.fromisoformat(request.args.get('start', (today - timedelta(days=29)).isoformat()))
        if end > today or start > end or (end-start).days > 730:
            raise ValueError()
        filters = {k: request.args[k] for k in ('marketplace', 'logistics') if request.args.get(k)}
        for k in ('account_id', 'product_id', 'category_id'):
            if request.args.get(k):
                filters[k] = int(request.args[k])
                if filters[k] <= 0:
                    raise ValueError()
        return start, end, filters
    except (ValueError, TypeError):
        raise ValueError('Informe um período válido de até 731 dias, sem datas futuras, e filtros positivos.')


@gestao_bp.errorhandler(ValueError)
def invalid(exc):
    return jsonify(success=False, error=str(exc)), 400


@gestao_bp.errorhandler(Exception)
def unavailable(exc):
    # Do not return database details, provider responses, or credentials.
    logger.error('Gestão indisponível (%s)', type(exc).__name__)
    return jsonify(success=False, error='Não foi possível consultar Gestão. Verifique a migração e a atualização analítica.'), 503


def service():
    return GestaoService(supabase_db)


@gestao_bp.get('/resumo')
def report():
    start, end, filters = params()
    user = get_current_user()
    finance_allowed = user_has_permission(user, 'gestao_financeiro', 'ler')
    details_allowed = user_has_permission(user, 'gestao_detalhes', 'ler')
    data = service().report(start, end, filters, include_finance=finance_allowed)
    if not details_allowed and 'profitability' in data:
        data['profitability'].pop('orders', None)
    data['access'] = {'finance': finance_allowed, 'details': details_allowed,
                      'edit': user_has_permission(user, 'gestao', 'editar'),
                      'edit_finance': user_has_permission(user, 'gestao_financeiro', 'editar')}
    return jsonify(success=True, data=data)


def detail_page(page):
    from nistiprint_shared.services.gestao_report_repository import order_page
    start,end,filters=params()
    return order_page(supabase_db,start,end,filters,page)


@gestao_bp.get('/pedidos')
def orders():
    try:
        page = int(request.args.get('page', 1))
        if page < 1:
            raise ValueError()
    except ValueError:
        raise ValueError('Página inválida.')
    result = detail_page(page)
    return jsonify(success=True, data=result['data'], total=result['total'], page=page)


def safe_cell(value):
    text = str(value if value is not None else '')
    return "'" + text if text.startswith(('\t','\r','\n')) or text.lstrip().startswith(('=', '+', '-', '@')) else text


@gestao_bp.get('/exportar')
def export():
    from flask import stream_with_context
    start,end,filters=params()
    def chunks():
        output=io.StringIO()
        writer=csv.writer(output,delimiter=';')
        writer.writerow(['Pedido','Número','Data','Marketplace','Conta','Estado','Elegível','Valor dos itens'])
        yield '\ufeff'+output.getvalue()
        after=0
        while True:
            rows=supabase_db.rpc('gestao_export_page',{'p_start':start.isoformat(),'p_end':end.isoformat(),'p_filters':filters,'p_after':after}).execute().data
            if not rows: break
            output.seek(0); output.truncate(0)
            for o in rows:
                writer.writerow([safe_cell(o[k]) for k in ('id','number','sold_on','marketplace','account','stage','eligible','items_value')])
            yield output.getvalue()
            if len(rows)<500: break
            after=rows[-1]['id']
    return Response(stream_with_context(chunks()),mimetype='text/csv',headers={
        'Content-Disposition':'attachment; filename=gestao-pedidos.csv','Cache-Control':'no-store'})


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError('Envie um objeto JSON.')
    return data


def positive_id(value):
    try:
        result = int(value)
        if isinstance(value, bool) or str(result) != str(value) or result <= 0:
            raise ValueError()
        return result
    except (ValueError, TypeError):
        raise ValueError('Identificador inválido.')


@gestao_bp.put('/metas')
def goal():
    data = body()
    month = date.fromisoformat(str(data.get('month', '')))
    target = number(data.get('target'))
    metric = data.get('metric')
    if month.day != 1 or metric not in {'sales','orders','contribution'} or target is None or target <= 0:
        raise ValueError('Meta inválida: mês no primeiro dia e valor positivo.')
    if metric == 'contribution':
        denied = require_request_permission('gestao_financeiro','editar')
        if denied:
            return denied
    account = positive_id(data['account_id']) if data.get('account_id') else 0
    supabase_db.table('gestao_metas').upsert({'month':month.isoformat(),'account_id':account,'metric':metric,'target':target,
        'updated_at':datetime.now(TZ).isoformat()},on_conflict='month,account_id,metric').execute()
    return jsonify(success=True)


@gestao_bp.put('/financeiro/<int:pedido_id>')
def finance(pedido_id):
    positive_id(pedido_id)
    data = body()
    raw = data.get('components')
    allowed = {'net_payout','taxes','operating_cost','ads','fees','shipping','seller_discount','refunds','cogs'}
    if not isinstance(raw,dict) or not raw or set(raw)-allowed:
        raise ValueError('Componentes financeiros inválidos.')
    components={k:number(v) for k,v in raw.items()}
    if any(v is None for v in components.values()) or any(v<0 for k,v in components.items() if k!='net_payout'):
        raise ValueError('Valores financeiros devem ser finitos; despesas devem ser positivas.')
    if not isinstance(data.get('settled',False),bool):
        raise ValueError('settled deve ser booleano.')
    supabase_db.table('gestao_financeiro').upsert({'pedido_id':pedido_id,'components':components,
        'source':'manual','settled':data.get('settled',False),'updated_at':datetime.now(TZ).isoformat()},on_conflict='pedido_id').execute()
    return jsonify(success=True)


@gestao_bp.post('/custos')
def cost():
    data = body()
    value = number(data.get('unit_cost'))
    at = local_time(data.get('valid_from'))
    source = data.get('source','manual')
    if value is None or value<0 or at is None or source not in {'cadastro','ficha_tecnica','realizado','manual'} or not isinstance(data.get('estimated',True),bool):
        raise ValueError('Custo, vigência ou origem inválida.')
    supabase_db.table('gestao_custos').insert({'produto_id':positive_id(data.get('produto_id')),
        'valid_from':at.isoformat(),'unit_cost':value,'source':source,'estimated':data.get('estimated',True)}).execute()
    return jsonify(success=True),201


@gestao_bp.post('/apontamentos')
def event():
    import uuid
    data=body()
    try:
        key=str(uuid.UUID(str(data.get('event_key'))))
    except ValueError:
        raise ValueError('event_key deve ser um UUID para impedir duplicação.')
    stage=data.get('stage')
    at=local_time(data.get('occurred_at')) if data.get('occurred_at') is not None else datetime.now(TZ)
    if at is None:
        raise ValueError('Data de apontamento inválida.')
    if stage not in {'personalizacao','producao','despacho','retrabalho','perda'}:
        raise ValueError('Etapa inválida.')
    row={'event_key':key,'pedido_id':positive_id(data.get('pedido_id')),'stage':stage,'occurred_at':at.isoformat()}
    for k in ('quantity','cost','duration_minutes'):
        if k in data:
            row[k]=number(data[k])
            if row[k] is None or row[k]<0:
                raise ValueError('Quantidade, duração e custo devem ser positivos.')
    if 'cost' in row:
        denied=require_request_permission('gestao_financeiro','editar')
        if denied:
            return denied
    supabase_db.table('gestao_apontamentos').upsert(row,on_conflict='event_key',ignore_duplicates=True).execute()
    return jsonify(success=True),201


@gestao_bp.post('/atualizar')
def refresh():
    from nistiprint_shared.services.celery_app import celery_app
    celery_app.send_task('tasks.gestao_tasks.refresh',queue='gestao_projection')
    return jsonify(success=True, message='Atualização analítica agendada.'),202


@gestao_bp.post('/coletar/<int:account_id>')
def collect(account_id):
    positive_id(account_id)
    from routes.auth import admin_required
    return admin_required(lambda: collect_compat(account_id))()


def collect_compat(account_id):
    denied = require_request_permission('gestao_financeiro','editar')
    if denied:
        return denied
    data=body()
    capability=data.get('capability')
    if capability not in {'shopee_escrow','shopee_product','shopee_ads','ml_visits','ml_ads','ml_billing','bling_history'}:
        raise ValueError('Capacidade inválida.')
    from nistiprint_shared.services.marketplace_insights_service import MarketplaceInsightsService
    return jsonify(MarketplaceInsightsService(supabase_db).configure(account_id,capability,'run')),202
