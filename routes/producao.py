from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify, current_app
from routes.auth import get_current_user # Importar get_current_user
from nistiprint_shared.services.app_config_service import app_config_service
from nistiprint_shared.services.category_service import category_service
from nistiprint_shared.services.product_service import product_service
from nistiprint_shared.services.daily_production_log_service import daily_production_log_service
from nistiprint_shared.services.demanda_producao_service import demanda_producao_service
from nistiprint_shared.services.estoque_service import estoque_service # Importar
from nistiprint_shared.services.ordem_producao_service import ordem_producao_service # Importar
from datetime import datetime

producao_bp = Blueprint('producao', __name__, url_prefix='/producao')

@producao_bp.route('/controle', methods=['GET'])
def controle_producao():
    """Displays the daily production control screen."""
    selected_date = datetime.now().date()
    date_str = selected_date.strftime('%Y-%m-%d')

    category_id = app_config_service.get_config('producao_miolos_category_id')
    if not category_id:
        flash('A categoria para a tela de produção ainda não foi configurada.', 'warning')
        return redirect(url_for('configuracoes.producao_config'))

    products_data, _ = product_service.get_products(categoria_id=category_id, per_page=10000) # Fetch all products in category
    
    # Filter for active and non-composite products in Python
    products = []
    for p in products_data:
        status = p.get('status')
        if not status:
            status = p.get('atributos', {}).get('status', 'ativo')
        
        if status == 'ativo':
            products.append(p)

    daily_logs = daily_production_log_service.get_logs_for_date(selected_date)
    
    # Obter depósito de produção
    deposito_id = app_config_service.get_config('default_production_deposit_id') or 'principal'

    enriched_products = []
    for product in products:
        # Log de produção diário
        log = daily_logs.get(product['id'])
        product['quantity_produced_today'] = log.get('quantityProduced', 0) if log else 0
        product['quantity_removed_today'] = log.get('quantityRemoved', 0) if log else 0
        
        # Detalhes do estoque
        stock_details = estoque_service.get_saldo_atual(product['id'], deposito_id)
        product['stock_details'] = stock_details
        # Compatibilidade com o campo antigo, se necessário
        product['physicalStock'] = stock_details.get('quantidade', 0)

        enriched_products.append(product)

    total_active_cores = len(enriched_products)

    return render_template(
        'producao/controle.html',
        products=enriched_products,
        selected_date=selected_date,
        date_str=date_str,
        total_active_cores=total_active_cores
    )

@producao_bp.route('/api/controle', methods=['GET'])
def get_controle_data_api():
    """Returns the daily production control data as JSON."""
    user = get_current_user() # Assuming get_current_user provides user object with sector_id
    if not user:
        return jsonify({'success': False, 'error': 'Usuário não autenticado.'}), 401
    
    setor_id = user.get('setor_id') # Get setor_id from the authenticated user
    if not setor_id:
        # current_app.logger.warning(f"User {user.get('email')} does not have a setor_id defined.")
        return jsonify({'success': False, 'error': 'Setor do usuário não definido.'}), 400

    selected_date = datetime.now().date()
    date_str = selected_date.strftime('%Y-%m-%d')
    tipo = request.args.get('tipo', 'miolo') # Get the 'tipo' from query params, default to 'miolo'

    # current_app.logger.debug(f"API: Fetching controle data for tipo: {tipo}, setor_id: {setor_id}, data_selecionada: {date_str}")

    category_id_config_key = None
    if tipo == 'miolo':
        category_id_config_key = 'producao_miolos_category_id'
    elif tipo == 'capa':
        category_id_config_key = 'producao_capas_impressas_category_id'
    elif tipo == 'capa_acabada':
        category_id_config_key = 'producao_capas_category_id'
    else:
        category_id_config_key = 'producao_miolos_category_id'

    category_id = app_config_service.get_config(category_id_config_key)

    if not category_id:
        # current_app.logger.warning(f"API: Category ID for tipo '{tipo}' (config key: {category_id_config_key}) not configured.")
        return jsonify({'success': False, 'error': f'A categoria para produção de {tipo} ainda não foi configurada.'}), 400

    products_data, _ = product_service.get_products(categoria_id=category_id, per_page=10000)
    # current_app.logger.debug(f"API: product_service.get_products for tipo '{tipo}' returned {len(products_data)} raw products.")

    products = []
    for p in products_data:
        status = p.get('status')
        if not status:
            status = p.get('atributos', {}).get('status', 'ativo')
        
        if status == 'ativo':
            products.append(p)

    daily_logs = daily_production_log_service.get_logs_for_date(selected_date)
    deposito_id = app_config_service.get_config('default_production_deposit_id') or 'principal'

    # Buscar saldos em lote para otimização de performance
    product_ids = [product['id'] for product in products]
    saldos_em_lote = estoque_service.get_saldos_em_lote(product_ids, deposito_id)

    enriched_products = []
    for product in products:
        log = daily_logs.get(product['id'])
        product['quantity_produced_today'] = log.get('quantityProduced', 0) if log else 0
        product['quantity_removed_today'] = log.get('quantityRemoved', 0) if log else 0

        stock_details = saldos_em_lote.get(str(product['id']), {'quantidade': 0, 'quantidade_reservada': 0, 'quantidade_disponivel': 0})
        product['stock_details'] = stock_details
        product['physicalStock'] = stock_details.get('quantidade', 0)

        enriched_products.append(product)
    
    # current_app.logger.debug(f"API: Final enriched_products for tipo '{tipo}' prepared: {len(enriched_products)} items.")

    total_active_items = len(enriched_products) # Default to count of active products
    # if tipo == 'miolo':
        # current_app.logger.warning("OrdemProducaoService.get_total_miolos_ativos is causing an AttributeError. Using len(enriched_products) for total_active_items instead.")
    # TODO: Implement get_total_capas_ativas if a similar specific count is needed for 'capa'

    return jsonify({
        'success': True,
        'products': enriched_products,
        'selected_date': date_str,
        'total_active_cores': total_active_items
    })

@producao_bp.route('/registrar-item', methods=['POST'])
def registrar_item_producao():
    """Processes a single production item update asynchronously."""
    data = request.get_json()
    product_id = data.get('product_id')
    quantity_str = data.get('quantity')
    date_str = data.get('date')
    field = data.get('field') # Opcional, vindo da tela de controle

    if not all([product_id, quantity_str, date_str]):
        return jsonify({'success': False, 'error': 'Dados incompletos.'}), 400

    try:
        quantity = int(quantity_str)
        selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        
        user = get_current_user()
        user_id = user.get('email') if user else 'System'

        if field:
            # Caso vindo de uma tela que sensibiliza o dashboard (ex: novas abas de capas)
            # Usar o serviço que suporta recursividade JIT e cascata de dashboard
            result = demanda_producao_service.processar_alocacao_avulsa_otimizado(
                product_id=product_id,
                campo=field,
                quantidade=quantity,
                user_id=user_id
            )
        else:
            # Caso padrão de entrada de estoque simples (miolos ou capas sem vínculo de estágio)
            product = product_service.get_by_id(product_id)
            result = daily_production_log_service.registrar_producao(
                log_date=selected_date,
                product_id=product_id,
                product_name=product.get('name', 'Produto'),
                quantity=quantity,
                user_email=user_id
            )
        
        # Re-fetch stock details for the response
        deposito_id = app_config_service.get_config('default_production_deposit_id') or 'principal'
        new_stock_details = estoque_service.get_saldo_atual(product_id, deposito_id)
        new_stock = new_stock_details.get('quantidade', 0)
        new_stock_available = new_stock_details.get('quantidade_disponivel', 0)

        daily_logs = daily_production_log_service.get_logs_for_date(selected_date)
        daily_log = daily_logs.get(product_id, {})
        new_daily_produced = daily_log.get('quantityProduced', 0)
        new_daily_removed = daily_log.get('quantityRemoved', 0)

        return jsonify({
            'success': True, 
            'message': 'Produção registrada com sucesso!', 
            'new_stock': new_stock,
            'new_stock_available': new_stock_available,
            'new_daily_produced': new_daily_produced,
            'new_daily_removed': new_daily_removed
        })

    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 200
    except Exception as e:
        current_app.logger.error(f"Erro no endpoint {request.path}: {str(e)}")
        return jsonify({'success': False, 'error': f"Erro no processamento: {str(e)}"}), 500

@producao_bp.route('/registrar-saida-estoque', methods=['POST'])
def registrar_saida_estoque():
    """Processes a simple stock removal asynchronously."""
    data = request.get_json()
    product_id = data.get('product_id')
    quantity_str = data.get('quantity')
    date_str = data.get('date')
    demanda_id = data.get('demanda_id') # Optional

    if not all([product_id, quantity_str, date_str]):
        return jsonify({'success': False, 'error': 'Dados incompletos.'}), 400

    try:
        quantity = int(quantity_str)
        selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        
        product = product_service.get_by_id(product_id)
        if not product:
            return jsonify({'success': False, 'error': f'Produto com ID {product_id} não encontrado.'}), 404

        # Registrar a saída no log diário
        daily_production_log_service.registrar_saida_simples(
            log_date=selected_date,
            product_id=product_id,
            product_name=product.get('name', ''),
            quantity=quantity,
            user_email=get_current_user().get('email') if get_current_user() else None
        )
        
        # Se uma demanda foi especificada, tenta associar a saída a ela
        if demanda_id:
            # Basic check for Firestore ID format (usually 20 characters, alphanumeric)
            # This is a heuristic, a more robust check would involve trying to fetch the document
            if len(demanda_id) == 20 and demanda_id.isalnum():
                try:
                    # Verify if the demand actually exists before associating
                    demanda_exists = demanda_producao_service.get_demanda_with_itens(demanda_id) is not None
                    if demanda_exists:
                        demanda_producao_service.associar_saida_a_demanda(
                            demanda_id=demanda_id,
                            product_id=product_id,
                            quantity=quantity
                        )
                    else:
                        print(f"INFO: Demanda com ID {demanda_id} não encontrada. Saída registrada como avulsa.")
                except Exception as e:
                    print(f"WARN: Falha ao associar saída com demanda {demanda_id}. Erro: {e}. Saída registrada como avulsa.")
            else:
                print(f"INFO: Demanda ID '{demanda_id}' não é um formato válido. Saída registrada como avulsa.")

        deposito_id = app_config_service.get_config('default_production_deposit_id') or 'principal'
        new_stock_details = estoque_service.get_saldo_atual(product_id, deposito_id)
        new_stock = new_stock_details.get('quantidade', 0)

        daily_logs = daily_production_log_service.get_logs_for_date(selected_date)
        daily_log = daily_logs.get(product_id, {})
        new_daily_produced = daily_log.get('quantityProduced', 0)
        new_daily_removed = daily_log.get('quantityRemoved', 0)

        return jsonify({
            'success': True, 
            'message': 'Saída de estoque registrada com sucesso!', 
            'new_stock': new_stock,
            'new_daily_produced': new_daily_produced,
            'new_daily_removed': new_daily_removed
        })

    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 200
    except Exception as e:
        current_app.logger.error(f"Erro no endpoint {request.path}: {str(e)}")
        return jsonify({'success': False, 'error': f"Erro no processamento: {str(e)}"}), 500

@producao_bp.route('/components/<product_id>', methods=['GET'])
def get_product_components(product_id):
    """Returns BOM components for a single product."""
    deposito_para_producao = app_config_service.get_config('default_production_deposit_id') or 'principal'
    components = product_service.get_bom_components(product_id, deposito_id=deposito_para_producao)
    return jsonify(components)

@producao_bp.route('/logs/<string:product_id>/<date_str>', methods=['GET'])
def get_daily_logs(product_id, date_str):
    try:
        selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        logs = daily_production_log_service.get_detailed_logs_for_product(product_id, selected_date)
        return jsonify({'success': True, 'logs': logs})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 200
    except Exception as e:
        current_app.logger.error(f"Erro no endpoint {request.path}: {str(e)}")
        return jsonify({'success': False, 'error': f"Erro no processamento: {str(e)}"}), 500

@producao_bp.route('/logs/reverter/<int:log_id>', methods=['POST'])
def reverter_lancamento(log_id):
    try:
        data = request.get_json() or {}
        reverter_estoque = data.get('reverter_estoque', True)

        # Here you would ideally get the user_id from the session
        user = get_current_user()
        user_id = str(user.get('id')) if user else 'system'

        product_id = daily_production_log_service.reverter_lancamento(
            log_id=log_id, 
            user_id=user_id, 
            reverter_estoque=reverter_estoque
        )

        # After reversal, fetch the updated totals and stock
        selected_date = datetime.now().date() # Or get from request if different
        deposito_id = app_config_service.get_config('default_production_deposit_id') or 'principal'

        new_stock_details = estoque_service.get_saldo_atual(product_id, deposito_id)
        new_stock = new_stock_details.get('quantidade_disponivel', 0)

        daily_logs = daily_production_log_service.get_logs_for_date(selected_date)
        daily_log = daily_logs.get(product_id, {})
        new_daily_produced = daily_log.get('quantityProduced', 0)
        new_daily_removed = daily_log.get('quantityRemoved', 0)

        return jsonify({
            'success': True,
            'message': 'Lançamento revertido com sucesso.',
            'new_stock': new_stock,
            'new_daily_produced': new_daily_produced,
            'new_daily_removed': new_daily_removed
        })
    except Exception as e:
        # Log the exception for debugging
        print(f"Error reverting log entry: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@producao_bp.route('/logs/delete/<int:log_id>', methods=['POST'])
def delete_log_entry(log_id):
    """
    Rota legada mantida para compatibilidade.
    Recomenda-se usar /logs/reverter/<log_id> em vez desta.
    """
    return reverter_lancamento(log_id)

@producao_bp.route('/api/auditoria', methods=['GET'])
def get_auditoria_logs():
    """Consulta logs de auditoria com filtros opcionais."""
    try:
        from nistiprint_shared.services.auditoria_service import auditoria_service

        # Parâmetros de filtro
        event_type = request.args.get('event_type')
        user_id = request.args.get('user_id')
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        limit = int(request.args.get('limit', 100))

        # Converter datas se fornecidas
        start_date = None
        end_date = None
        if start_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        if end_date_str:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d')

        # Buscar eventos
        events = auditoria_service.get_events(
            event_type=event_type,
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
            limit=limit
        )

        return jsonify({
            'success': True,
            'events': events,
            'total': len(events)
        })

    except Exception as e:
        print(f"ERROR in get_auditoria_logs: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@producao_bp.route('/api/auditoria/entidade/<string:entity_type>/<string:entity_id>', methods=['GET'])
def get_auditoria_por_entidade(entity_type, entity_id):
    """Consulta logs de auditoria para uma entidade específica."""
    try:
        from nistiprint_shared.services.auditoria_service import auditoria_service

        event_types = request.args.getlist('event_types')  # Lista opcional de tipos de evento

        events = auditoria_service.get_events_for_entity(
            entity_type=entity_type,
            entity_id=entity_id,
            event_types=event_types if event_types else None
        )

        return jsonify({
            'success': True,
            'entity_type': entity_type,
            'entity_id': entity_id,
            'events': events,
            'total': len(events)
        })

    except Exception as e:
        print(f"ERROR in get_auditoria_por_entidade: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@producao_bp.route('/api/miolo/<string:miolo_id>/itens-pendentes', methods=['GET'])
def get_pending_items_for_miolo(miolo_id):
    try:
        demands_with_items = demanda_producao_service.get_pending_items_by_miolo(miolo_id)
        # Render a partial template with the data
        return render_template('producao/_distribution_list.html', demands_dict=demands_with_items)
    except Exception as e:
        print(f"ERROR in get_pending_items_for_miolo: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# Novo endpoint para o painel de produção por setores
@producao_bp.route('/painel-setores', methods=['GET'])
def get_painel_producao_setores():
    """Retorna dados do painel de produção organizado por setores/colunas Kanban."""
    try:
        user = get_current_user()
        if not user:
            return jsonify({'success': False, 'error': 'Usuário não autenticado.'}), 401

        setor_id = user.get('setor_id') or user.get('setor_nome')
        if not setor_id:
            # current_app.logger.warning(f"User {user.get('email')} does not have a setor_id defined.")
            return jsonify({'success': False, 'error': 'Setor do usuário não definido.'}), 400

        painel_data = demanda_producao_service.get_painel_producao_setores(setor_id)

        return jsonify({
            'success': True,
            'painel': painel_data
        })

    except Exception as e:
        # current_app.logger.error(f"ERROR in get_painel_producao_setores: {e}")
        return jsonify({'success': False, 'error': f'Erro interno: {str(e)}'}), 500





