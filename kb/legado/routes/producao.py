from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from routes.auth import get_current_user # Importar get_current_user
from services.app_config_service import app_config_service
from services.category_service import category_service
from services.product_service import product_service
from services.daily_production_log_service import daily_production_log_service
from services.demanda_producao_service import demanda_producao_service
from services.estoque_service import estoque_service # Importar
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

    products_data, _ = product_service.get_products(category_id=category_id, per_page=10000) # Fetch all products in category
    
    # Filter for active and non-composite products in Python
    products = [p for p in products_data if p.get('status') == 'ativo']

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

@producao_bp.route('/registrar-item', methods=['POST'])
def registrar_item_producao():
    """Processes a single production item update asynchronously."""
    data = request.get_json()
    product_id = data.get('product_id')
    quantity_str = data.get('quantity')
    date_str = data.get('date')

    if not all([product_id, quantity_str, date_str]):
        return jsonify({'success': False, 'error': 'Dados incompletos.'}), 400

    try:
        quantity = int(quantity_str)
        selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        
        product = product_service.get_by_id(product_id)
        if not product:
            return jsonify({'success': False, 'error': f'Produto com ID {product_id} não encontrado.'}), 404

            user_email=get_current_user().get('email') if get_current_user() else None
        
        # Re-fetch stock details for the response
        deposito_id = app_config_service.get_config('default_production_deposit_id') or 'principal'
        new_stock_details = estoque_service.get_saldo_atual(product_id, deposito_id)
        new_stock = new_stock_details.get('quantidade', 0)

        daily_logs = daily_production_log_service.get_logs_for_date(selected_date)
        daily_log = daily_logs.get(product_id, {})
        new_daily_produced = daily_log.get('quantityProduced', 0)
        new_daily_removed = daily_log.get('quantityRemoved', 0)

        return jsonify({
            'success': True, 
            'message': 'Produção registrada com sucesso!', 
            'new_stock': new_stock,
            'new_daily_produced': new_daily_produced,
            'new_daily_removed': new_daily_removed
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

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

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

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
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@producao_bp.route('/logs/delete/<int:log_id>', methods=['POST'])
def delete_log_entry(log_id):
    try:
        # Here you would ideally get the user_id from the session
        # from flask_login import current_user
        user_id = current_user.id if current_user.is_authenticated else None

        product_id = daily_production_log_service.delete_log_entry(log_id, user_id)

        # After deletion, fetch the updated totals and stock
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
            'message': 'Registro de log excluído com sucesso.',
            'new_stock': new_stock,
            'new_daily_produced': new_daily_produced,
            'new_daily_removed': new_daily_removed
        })
    except Exception as e:
        # Log the exception for debugging
        print(f"Error deleting log entry: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
