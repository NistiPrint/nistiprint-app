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
    """Botao [+] da tela de Controle de Producao: PRODUZ o item.

    Producao imediata = entrada do produto no estoque + consumo da BOM. E a
    primeira das tres etapas do fluxo: producao -> alocacao na demanda ->
    saida fisica.

    A tela mandava `field` em toda chamada, o que desviava para
    `processar_alocacao_avulsa_otimizado` — que ALOCA em demanda em vez de
    produzir. O resultado no banco era PROD_INT seguido de CONS_INT com o
    mesmo correlation_id: saldo liquido zero, materia-prima debitada, miolo
    nunca disponivel em estoque. O ramo de producao virou codigo morto.

    `field` continua aceito por compatibilidade, mas e o caminho de ALOCACAO,
    nao o de producao. A alocacao propria da tela e o botao [-], que passa
    por /demanda_producao/registrar-saida.
    """
    data = request.get_json()
    if not all([data.get('product_id'), data.get('quantity'), data.get('date')]):
        return jsonify({'success': False, 'error': 'Dados incompletos.'}), 400
    try:
        user_id = get_current_user().get('email') if get_current_user() else 'System'

        if data.get('field'):
            # Caminho legado de alocacao avulsa. Mantido para chamadores antigos.
            result = demanda_producao_service.processar_alocacao_avulsa_otimizado(
                data['product_id'], data['field'], float(data['quantity']),
                user_id, data.get('sincrono', False)
            ) or {}
            status = result.get('status')
            # 'sem_alvo' significa que NADA foi gravado. Antes a resposta era
            # sempre 'Produção registrada!' com o result descartado, entao o
            # operador via sucesso enquanto o registro sumia.
            if status == 'sem_alvo':
                return jsonify({
                    'success': False,
                    'error': result.get('message') or 'Nenhuma demanda ativa recebeu a alocação.',
                    'status': status,
                    'quantidade_alocada': 0,
                    'quantidade_nao_alocada': result.get('quantidade_nao_alocada'),
                }), 409
            resposta = {
                'success': True,
                'message': result.get('message') or 'Alocação registrada!',
                'status': status,
                'quantidade_alocada': result.get('quantidade_alocada'),
                'quantidade_nao_alocada': result.get('quantidade_nao_alocada'),
            }
            if status == 'partial':
                resposta['warning'] = (
                    f"Apenas {result.get('quantidade_alocada')} de {result.get('quantidade_solicitada')} "
                    f"foram alocados — nao ha demanda ativa para o restante."
                )
            return jsonify(resposta)

        # Caminho padrao: producao imediata com entrada em estoque.
        # sincrono=True processa a BOM na hora; a tela sempre pede sincrono.
        result = ordem_producao_service.registrar_producao_imediata(
            str(data['product_id']), float(data['quantity']), data['date'],
            user_id, data.get('sincrono', False)
        ) or {}
        return jsonify({
            'success': True,
            'message': result.get('message') or 'Produção registrada!',
            'correlation_id': result.get('correlation_id'),
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@producao_api_bp.route('/registrar-saida-estoque', methods=['POST'])
def registrar_saida_estoque():
    """Saida AVULSA: baixa imediata do estoque, sem vinculo com demanda.

    E a terceira porta da tela de Controle de Producao, ao lado de [+] (produz)
    e [-] (aloca em demanda). Aqui a mercadoria simplesmente sai — perda,
    amostra, uso interno, venda fora do fluxo de demanda. Nao ha reserva, nao
    ha reconciliacao depois: a saida ja e definitiva no momento do clique.

    Esta rota aceitava `demanda_id` e chamava associar_saida_a_demanda depois
    da baixa. Com a alocacao virando reserva, isso passou a ser dupla contagem:
    o item sairia aqui e sairia de novo na reconciliacao da demanda. Vinculo
    com demanda agora e exclusivamente /demanda_producao/registrar-saida.
    """
    data = request.get_json() or {}
    if not all([data.get('product_id'), data.get('quantity'), data.get('date')]):
        return jsonify({'success': False, 'error': 'Incompleto'}), 400

    if data.get('demanda_id'):
        return jsonify({
            'success': False,
            'error': ('Saída avulsa não aceita vínculo com demanda. '
                      'Para destinar o item a uma demanda use a alocação ([-]), '
                      'que reserva o estoque e dá baixa na finalização.')
        }), 400

    try:
        quantidade = float(data['quantity'])
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'Quantidade inválida.'}), 400
    if quantidade <= 0:
        return jsonify({'success': False, 'error': 'Quantidade deve ser maior que zero.'}), 400

    try:
        produto = product_service.get_by_id(data['product_id']) or {}
        deposito_id = app_config_service.get_config('default_production_deposit_id') or 'principal'

        # Confere o DISPONIVEL, nao o saldo fisico: o que esta reservado para
        # uma demanda nao pode ser levado por uma saida avulsa.
        saldo = estoque_service.get_saldo_atual(data['product_id'], deposito_id)
        disponivel = float(saldo.get('quantidade_disponivel') or 0)
        if disponivel < quantidade:
            return jsonify({
                'success': False,
                'error': (f"Saldo disponível insuficiente. Disponível: {disponivel}, "
                          f"solicitado: {quantidade}. "
                          f"Reservado para demandas: {saldo.get('quantidade_reservada') or 0}.")
            }), 400

        user = get_current_user()
        daily_production_log_service.registrar_saida_simples(
            datetime.strptime(data['date'], '%Y-%m-%d').date(),
            data['product_id'],
            produto.get('name', ''),
            quantidade,
            user.get('email') if user else None,
        )
        novo_saldo = estoque_service.get_saldo_atual(data['product_id'], deposito_id)
        return jsonify({
            'success': True,
            'message': f"Saída avulsa de {quantidade:g} un registrada. O estoque já foi baixado.",
            'saldo': novo_saldo,
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
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
