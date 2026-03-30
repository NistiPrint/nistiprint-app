from flask import request, jsonify, current_app
from routes.auth import get_current_user
from nistiprint_shared.services.app_config_service import app_config_service
from nistiprint_shared.services.product_service import product_service
from nistiprint_shared.services.daily_production_log_service import daily_production_log_service
from nistiprint_shared.services.demanda_producao_service import demanda_producao_service
from nistiprint_shared.services.estoque_service import estoque_service
from nistiprint_shared.services.ordem_producao_service import ordem_producao_service
from nistiprint_shared.database.supabase_db_service import supabase_db
from datetime import datetime
from .producao_base import producao_api_bp

@producao_api_bp.route('/controle', methods=['GET'])
def get_controle_data_api():
    user = get_current_user()
    if not user or not user.get('setor_id'): return jsonify({'success': False, 'error': 'Usuário ou setor inválido.'}), 400
    selected_date = datetime.now().date()
    tipo = request.args.get('tipo', 'miolo')
    configs = {'miolo': 'producao_miolos_category_id', 'capa': 'producao_capas_impressas_category_id', 'capa_acabada': 'producao_capas_category_id'}
    category_id = app_config_service.get_config(configs.get(tipo, 'producao_miolos_category_id'))
    if not category_id: return jsonify({'success': False, 'error': 'Categoria não configurada.'}), 400

    products_data, _ = product_service.get_products(categoria_id=category_id, per_page=10000)
    products = [p for p in products_data if p.get('status', 'ativo') == 'ativo']
    daily_logs = daily_production_log_service.get_logs_for_date(selected_date)
    deposito_id = app_config_service.get_config('default_production_deposit_id') or 'principal'
    saldos_em_lote = estoque_service.get_saldos_em_lote([p['id'] for p in products], deposito_id)

    enriched = []
    for p in products:
        log = daily_logs.get(p['id'])
        p['quantity_produced_today'] = log.get('quantityProduced', 0) if log else 0
        p['quantity_removed_today'] = log.get('quantityRemoved', 0) if log else 0
        stock = saldos_em_lote.get(str(p['id']), {'quantidade': 0})
        p['stock_details'], p['physicalStock'] = stock, stock.get('quantidade', 0)
        enriched.append(p)
    return jsonify({'success': True, 'products': enriched, 'total_active_cores': len(enriched)})

@producao_api_bp.route('/painel-setores', methods=['GET'])
def get_painel_setores_api():
    """
    Retorna painel de produção por setores.
    Usado pelas telas Modo Foco e Painel Geral.
    """
    try:
        user = get_current_user()
        if not user or not user.get('setor_id'):
            return jsonify({'success': False, 'error': 'Usuário ou setor inválido.'}), 400
        
        painel = demanda_producao_service.get_painel_producao_setores(user.get('setor_id'))
        return jsonify({'success': True, 'painel': painel})
    except Exception as e:
        return jsonify({'success': False, 'error': f'Erro interno: {str(e)}'}), 500

@producao_api_bp.route('/registrar-item', methods=['POST'])
def registrar_item_producao():
    data = request.get_json()
    if not all([data.get('product_id'), data.get('quantity'), data.get('date')]): return jsonify({'success': False, 'error': 'Dados incompletos.'}), 400
    try:
        user_id = get_current_user().get('email') if get_current_user() else 'System'
        if data.get('field'):
            result = demanda_producao_service.processar_alocacao_avulsa_otimizado(data['product_id'], data['field'], float(data['quantity']), user_id, data.get('sincrono', False))
        else:
            result = ordem_producao_service.registrar_producao_imediata(str(data['product_id']), float(data['quantity']), data['date'], user_id, data.get('sincrono', False))
        return jsonify({'success': True, 'message': 'Produção registrada!'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@producao_api_bp.route('/registrar-saida-estoque', methods=['POST'])
def registrar_saida_estoque():
    data = request.get_json()
    if not all([data.get('product_id'), data.get('quantity'), data.get('date')]): return jsonify({'success': False, 'error': 'Incompleto'}), 400
    try:
        user = get_current_user()
        daily_production_log_service.registrar_saida_simples(datetime.strptime(data['date'], '%Y-%m-%d').date(), data['product_id'], product_service.get_by_id(data['product_id']).get('name', ''), int(data['quantity']), user.get('email') if user else None)
        if data.get('demanda_id'):
            demanda_producao_service.associar_saida_a_demanda(data['demanda_id'], data['product_id'], int(data['quantity']))
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@producao_api_bp.route('/registrar-sinal', methods=['POST'])
def registrar_sinal_producao():
    data = request.get_json()
    if not all([data.get('item_id'), data.get('demanda_id'), data.get('campo'), data.get('quantidade')]): 
        return jsonify({'success': False, 'error': 'Incompleto'}), 400
    try:
        user = get_current_user()
        # Atualiza apenas a intenção no banco (visível no dashboard)
        supabase_db.table('itens_demanda').update({data['campo']: float(data['quantidade'])}).eq('id', data['item_id']).execute()
        
        # Loga evento imutável para o novo motor (Event Sourcing)
        supabase_db.table('eventos_producao_v2').insert({
            'item_demanda_id': data['item_id'], 
            'demanda_id': data['demanda_id'], 
            'estagio': data['campo'],
            'quantidade_reportada': float(data['quantidade']), 
            'tipo_evento': 'SINAL', 
            'processado': False,
            'usuario_id': user.get('id') if user else None
        }).execute()
        
        return jsonify({'success': True, 'message': 'Sinal registrado e aguardando processamento assíncrono'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@producao_api_bp.route('/finalizar-item', methods=['POST'])
def finalizar_item_demanda():
    data = request.get_json()
    if not all([data.get('item_id'), data.get('demanda_id'), data.get('quantidade_finalizada')]): 
        return jsonify({'success': False, 'error': 'Incompleto'}), 400
    try:
        user = get_current_user()
        # Atualiza status e intenção final
        supabase_db.table('itens_demanda').update({
            'finalizados_qtd': float(data['quantidade_finalizada']), 
            'status_item': 'FINALIZADO'
        }).eq('id', data['item_id']).execute()
        
        # Loga evento de liquidação para o novo motor (Event Sourcing)
        supabase_db.table('eventos_producao_v2').insert({
            'item_demanda_id': data['item_id'], 
            'demanda_id': data['demanda_id'], 
            'estagio': 'finalizados_qtd',
            'quantidade_reportada': float(data['quantidade_finalizada']), 
            'tipo_evento': 'LIQUIDACAO', 
            'processado': False,
            'usuario_id': user.get('id') if user else None
        }).execute()
        
        return jsonify({'success': True, 'message': 'Finalização registrada e aguardando processamento assíncrono'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@producao_api_bp.route('/components/<product_id>', methods=['GET'])
def get_product_components(product_id):
    return jsonify(product_service.get_bom_components(product_id, deposito_id=app_config_service.get_config('default_production_deposit_id') or 'principal'))

@producao_api_bp.route('/logs/<string:product_id>/<date_str>', methods=['GET'])
def get_daily_logs(product_id, date_str):
    try:
        return jsonify({'success': True, 'logs': daily_production_log_service.get_detailed_logs_for_product(product_id, datetime.strptime(date_str, '%Y-%m-%d').date())})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@producao_api_bp.route('/logs/reverter/<int:log_id>', methods=['POST'])
def reverter_lancamento(log_id):
    try:
        user = get_current_user()
        pid = daily_production_log_service.reverter_lancamento(log_id, str(user.get('id', 'system')), request.get_json().get('reverter_estoque', True))
        return jsonify({'success': True, 'new_stock': estoque_service.get_saldo_atual(pid, app_config_service.get_config('default_production_deposit_id') or 'principal').get('quantidade_disponivel', 0)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@producao_api_bp.route('/api/auditoria', methods=['GET'])
def get_auditoria_logs():
    try:
        from nistiprint_shared.services.auditoria_service import auditoria_service
        evs = auditoria_service.get_events(request.args.get('event_type'), request.args.get('user_id'), request.args.get('start_date'), request.args.get('end_date'), int(request.args.get('limit', 100)))
        return jsonify({'success': True, 'events': evs, 'total': len(evs)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@producao_api_bp.route('/eventos', methods=['GET'])
def get_eventos_producao():
    """
    Retorna eventos de produção da tabela eventos_producao_v2.
    Query params: limit (default: 100), tipo (SINAL|LIQUIDACAO), processado (true|false)
    """
    try:
        limit = int(request.args.get('limit', 100))
        tipo = request.args.get('tipo')
        processado = request.args.get('processado')
        
        query = supabase_db.table('eventos_producao_v2').select('*')
        
        if tipo:
            query = query.eq('tipo_evento', tipo)
        
        if processado is not None:
            query = query.eq('processado', processado.lower() == 'true')
        
        response = query.order('created_at', desc=True).limit(limit).execute()
        
        return jsonify({'success': True, 'eventos': response.data or [], 'total': len(response.data or [])})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
