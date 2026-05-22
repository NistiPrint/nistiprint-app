from flask import Blueprint, request, jsonify
from routes.auth import login_required
from nistiprint_shared.services.order_service import order_service
from nistiprint_shared.models.situacao_pedido import SituacaoPedido
from nistiprint_shared.database.supabase_db_service import supabase_db
from utils.api_response import ApiResponse

unified_orders_bp = Blueprint('unified_orders', __name__, url_prefix='/api/v2/order')

@unified_orders_bp.route('/list', methods=['POST'])
@login_required
def get_unified_orders():
    """ObtÃ©m lista de pedidos unificados com filtros e paginaÃ§Ã£o"""
    try:
        data = request.get_json(silent=True) or {}

        page = int(data.get('page', 1))
        per_page = int(data.get('perPage', 50))

        # O list_orders jÃ¡ trata os filtros e a query
        result = order_service.list_orders(
            page=page,
            per_page=per_page,
            filters=data
        )

        return ApiResponse.success(data=result)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return ApiResponse.error(message=str(e), status_code=500)


@unified_orders_bp.route('/list-advanced', methods=['GET'])
@login_required
def get_unified_orders_advanced():
    """Obtém lista de pedidos com filtros avançados (backend nativo, sem RPC)."""
    try:
        situacao_pedido_id = request.args.get('status_id', type=int)
        bling_integration_id = request.args.get('bling_integration_id', type=int)
        canal_venda_id = request.args.get('canal_venda_id', type=int)
        origem_pedido_key = request.args.get('origem_pedido_key') or None
        delivery_start = request.args.get('delivery_start') or None
        delivery_end = request.args.get('delivery_end') or None
        pedido_date_start = request.args.get('pedido_date_start') or None
        pedido_date_end = request.args.get('pedido_date_end') or None
        search = request.args.get('search') or None
        sort = request.args.get('sort', 'numero_pedido')
        order = request.args.get('order', 'desc')
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 50, type=int)
        offset = (page - 1) * limit

        def to_bool(val):
            if val == 'true':
                return True
            if val == 'false':
                return False
            return None

        has_demanda = to_bool(request.args.get('has_demanda'))
        is_flex = to_bool(request.args.get('is_flex'))
        is_fulfillment = to_bool(request.args.get('is_fulfillment'))
        is_personalizado = to_bool(request.args.get('is_personalizado'))

        query = supabase_db.table('pedidos').select(
            'id,numero_pedido,codigo_pedido_externo,data_venda,cliente_nome,cliente_documento,'
            'canal_venda_id,marketplace_integration_id,bling_integration_id,situacao_pedido_id,'
            'is_flex,is_fulfillment,personalizado,data_limite_envio,total_pedido,origem,created_at',
            count='exact'
        )

        if situacao_pedido_id is not None:
            query = query.eq('situacao_pedido_id', situacao_pedido_id)
        if bling_integration_id is not None:
            query = query.eq('bling_integration_id', bling_integration_id)
        if canal_venda_id is not None:
            query = query.eq('canal_venda_id', canal_venda_id)
        if is_flex is not None:
            query = query.eq('is_flex', is_flex)
        if is_fulfillment is not None:
            query = query.eq('is_fulfillment', is_fulfillment)
        if is_personalizado is not None:
            query = query.eq('personalizado', is_personalizado)
        if delivery_start:
            query = query.gte('data_limite_envio', delivery_start)
        if delivery_end:
            query = query.lte('data_limite_envio', delivery_end)
        if pedido_date_start:
            query = query.gte('data_venda', pedido_date_start)
        if pedido_date_end:
            query = query.lte('data_venda', pedido_date_end)
        if search:
            term = str(search).replace('%', '').strip()
            if term:
                query = query.or_(
                    f"numero_pedido.ilike.%{term}%,"
                    f"cliente_nome.ilike.%{term}%,"
                    f"codigo_pedido_externo.ilike.%{term}%,"
                    f"cliente_documento.ilike.%{term}%"
                )
        if origem_pedido_key:
            if origem_pedido_key.startswith('canal:'):
                try:
                    query = query.eq('canal_venda_id', int(origem_pedido_key.split(':', 1)[1]))
                except Exception:
                    pass
            elif origem_pedido_key.startswith('marketplace:'):
                try:
                    query = query.eq('marketplace_integration_id', int(origem_pedido_key.split(':', 1)[1]))
                except Exception:
                    pass

        sort_desc = str(order).lower() != 'asc'
        if sort == 'data_venda':
            query = query.order('data_venda', desc=sort_desc)
        elif sort == 'created_at':
            query = query.order('created_at', desc=sort_desc)
        else:
            query = query.order('numero_pedido', desc=sort_desc)

        demanda_ids = set()

        response = query.range(offset, offset + limit - 1).execute()
        pedidos = response.data or []
        total_count = response.count or 0

        if has_demanda is not None:
            demanda_rows = supabase_db.table('demandas_pedidos').select('pedido_id').execute().data or []
            demanda_ids = {r.get('pedido_id') for r in demanda_rows if r.get('pedido_id') is not None}
            pedidos = [p for p in pedidos if ((p.get('id') in demanda_ids) == has_demanda)]
            full_rows = query.execute().data or []
            total_count = len([p for p in full_rows if ((p.get('id') in demanda_ids) == has_demanda)])
        elif pedidos:
            pedido_ids = [p.get('id') for p in pedidos if p.get('id') is not None]
            if pedido_ids:
                demanda_rows = supabase_db.table('demandas_pedidos').select('pedido_id').in_('pedido_id', pedido_ids).execute().data or []
                demanda_ids = {r.get('pedido_id') for r in demanda_rows if r.get('pedido_id') is not None}

        if pedidos:
            status_ids = list({p.get('situacao_pedido_id') for p in pedidos if p.get('situacao_pedido_id') is not None})
            canal_ids = list({p.get('canal_venda_id') for p in pedidos if p.get('canal_venda_id') is not None})
            bling_ids = list({p.get('bling_integration_id') for p in pedidos if p.get('bling_integration_id') is not None})

            status_map = {}
            canal_map = {}
            bling_map = {}

            if status_ids:
                for s in supabase_db.table('situacoes_pedido').select('id,nome,cor_status').in_('id', status_ids).execute().data or []:
                    status_map[s['id']] = s
            if canal_ids:
                for c in supabase_db.table('canais_venda').select('id,nome').in_('id', canal_ids).execute().data or []:
                    canal_map[c['id']] = c
            if bling_ids:
                for b in supabase_db.table('installed_integrations').select('id,instance_name').in_('id', bling_ids).execute().data or []:
                    bling_map[b['id']] = b

            for pedido in pedidos:
                status = status_map.get(pedido.get('situacao_pedido_id')) or {}
                canal = canal_map.get(pedido.get('canal_venda_id')) or {}
                bling = bling_map.get(pedido.get('bling_integration_id')) or {}

                pedido['status'] = {
                    'id': pedido.get('situacao_pedido_id'),
                    'nome': status.get('nome', 'Desconhecido'),
                    'cor': status.get('cor_status', '#9ca3af')
                }
                pedido['canal_venda_nome'] = canal.get('nome')
                pedido['bling_integration_nome'] = bling.get('instance_name')
                pedido['tem_demanda'] = pedido.get('id') in demanda_ids
                pedido['is_flex'] = bool(pedido.get('is_flex'))
                pedido['is_fulfillment'] = bool(pedido.get('is_fulfillment'))
                pedido['is_personalizado'] = bool(pedido.get('personalizado'))
                pedido['enviar_ate_formatado'] = pedido.get('data_limite_envio') or 'N/A'

        return ApiResponse.success(data={
            'orders': pedidos,
            'pedidos': pedidos,
            'total': total_count,
            'pagination': {
                'total': total_count,
                'page': page,
                'limit': limit,
                'pages': (total_count + limit - 1) // limit
            }
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return ApiResponse.error(message=str(e), status_code=500)
@unified_orders_bp.route('/status-options', methods=['GET'])
@login_required
def get_status_options():
    """ObtÃ©m opÃ§Ãµes de status disponÃ­veis para pedidos"""
    try:
        response = supabase_db.client.table('situacoes_pedido').select('*').execute()
        status_options = response.data
        
        return ApiResponse.success(data={'status_options': status_options})
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return ApiResponse.error(message=str(e), status_code=500)

@unified_orders_bp.route('/update-status', methods=['POST'])
@login_required
def update_order_status():
    """Atualiza o status de um pedido"""
    try:
        data = request.get_json(silent=True) or {}
        
        order_id = data.get('order_id')
        new_status = data.get('new_status')
        
        if not order_id or not new_status:
            return ApiResponse.error(message="ID do pedido e novo status sÃ£o obrigatÃ³rios", status_code=400)
        
        # Verificar se o novo status existe
        status_response = supabase_db.client.table('situacoes_pedido').select('id').eq('nome', new_status).execute()
        if not status_response.data:
            return ApiResponse.error(message=f"Status '{new_status}' nÃ£o encontrado", status_code=404)
        
        new_status_id = status_response.data[0]['id']
        
        # Atualizar o status do pedido
        update_response = supabase_db.client.table('pedidos').update({
            'situacao_pedido_id': new_status_id
        }).eq('id', order_id).execute()
        
        if not update_response.data:
            return ApiResponse.error(message="Pedido nÃ£o encontrado", status_code=404)
        
        # Retornar o pedido atualizado
        updated_order = supabase_db.client.table('pedidos').select(
            '*, situacao_pedido:situacoes_pedido(nome, descricao, cor_status)'
        ).eq('id', order_id).execute().data[0]
        
        return ApiResponse.success(data={'order': updated_order})
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return ApiResponse.error(message=str(e), status_code=500)

@unified_orders_bp.route('/details/<int:order_id>', methods=['GET'])
@login_required
def get_order_details(order_id):
    """ObtÃ©m detalhes de um pedido especÃ­fico"""
    try:
        # Obter pedido com seus itens
        order_response = supabase_db.client.table('pedidos').select(
            '''
            *,
            situacao_pedido:situacoes_pedido(nome, descricao, cor_status),
            itens_pedido!inner(*, produto:produtos(nome, sku))
            '''
        ).eq('id', order_id).execute()
        
        if not order_response.data:
            return ApiResponse.error(message="Pedido nÃ£o encontrado", status_code=404)
        
        order = order_response.data[0]
        
        return ApiResponse.success(data={'order': order})
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return ApiResponse.error(message=str(e), status_code=500)


