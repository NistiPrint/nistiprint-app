import logging
from flask import Blueprint, render_template, jsonify, request, flash, redirect, url_for
from routes.auth import login_required
from nistiprint_shared.services.ai_personalization_service import process_orders
from nistiprint_shared.services.product_service import product_service
from nistiprint_shared.services.category_service import category_service
from nistiprint_shared.services.tag_service import tag_service
from nistiprint_shared.services.bling_order_processing_service import import_single_order_by_shop_id

ferramentas_bp = Blueprint('ferramentas', __name__)
ferramentas_api_bp = Blueprint('ferramentas_api', __name__, url_prefix='/api/v2/ferramentas')

# API Ferramentas routes
@ferramentas_api_bp.route('/associacao-massa', methods=['POST'])
@login_required
def api_associacao_massa():
    try:
        data = request.get_json()
        component_id = data.get('component_id')
        quantity = data.get('quantity')
        target_ids = data.get('target_ids')

        if not component_id or not quantity or not target_ids:
            return jsonify({'success': False, 'message': 'Dados incompletos.'}), 400

        result = product_service.add_bom_component_to_multiple_products(component_id, float(quantity), target_ids)
        
        return jsonify({
            'success': True,
            'message': f"Processado. Sucessos: {len(result['success'])}, Erros: {len(result['errors'])}",
            'details': result
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@ferramentas_api_bp.route('/importar_pedido_bling', methods=['POST'])
@login_required
def api_importar_pedido_bling():
    data = request.get_json()
    numero_loja = data.get('numero_loja')

    if not numero_loja:
        return jsonify({'success': False, 'message': 'Número do pedido é obrigatório.'}), 400

    try:
        success, message = import_single_order_by_shop_id(numero_loja)
        return jsonify({'success': success, 'message': message}), 200 if success else 400
    except Exception as e:
        error_msg = f'Ocorreu um erro inesperado: {str(e)}'
        return jsonify({'success': False, 'message': error_msg}), 500

@ferramentas_api_bp.route('/processar_nomes_ia', methods=['POST'])
@login_required
def api_processar_nomes_ia():
    try:
        data = request.get_json() or {}
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"API /processar_nomes_ia called. Payload: {data}") # DEBUG LOG
        print(f"DEBUG PRINT: API /processar_nomes_ia called. Payload: {data}") # EXTREME DEBUG

        limit = data.get('limit')
        shopee_order_sn = data.get('shopee_order_sn')

        # Limit handling
        if limit and str(limit).isdigit():
            limit = int(limit)
        else:
            limit = None

        # Robust handling of order_sn:
        # If it's an empty string or explicitly None in JSON, we treat it as bulk (None)
        # BUT if the key is missing AND limit is missing, we might want to be careful.
        # For the Card button, the frontend now ensures it's not empty.
        if shopee_order_sn == "":
            shopee_order_sn = None

        success, message = process_orders(limit=limit, order_sn=shopee_order_sn)

        return jsonify({
            'success': success,
            'message': message
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Erro ao processar: {str(e)}'
        }), 500

@ferramentas_api_bp.route('/update_product_status', methods=['POST'])
@login_required
def api_update_product_status():
    try:
        products, _ = product_service.get_products(per_page=10000)
        updated_count = 0
        for product in products:
            product_service.update(product['id'], {'status': 'ativo'})
            updated_count += 1
        return jsonify({
            'success': True,
            'message': f'{updated_count} products updated to status \'ativo\'.'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error updating products: {str(e)}'
        }), 500

# Regular Ferramentas routes
@ferramentas_bp.route('/ferramentas')
@login_required
def ferramentas():
    return render_template('ferramentas.html')

@ferramentas_bp.route('/ferramentas/importar_pedido_bling', methods=['POST'])
@login_required
def importar_pedido_bling():
    numero_loja = request.form.get('numero_loja')

    if not numero_loja:
        flash('Número do pedido é obrigatório.', 'warning')
        return redirect(url_for('ferramentas.ferramentas'))

    try:
        success, message = import_single_order_by_shop_id(numero_loja)
        
        if success:
            flash(message, 'success')
        else:
            flash(message, 'danger')
    except Exception as e:
        error_msg = f'Ocorreu um erro inesperado: {str(e)}'
        flash(error_msg, 'danger')

    return redirect(url_for('ferramentas.ferramentas'))

@ferramentas_bp.route('/ferramentas/converter_pedidos')
@login_required
def converter_pedidos():
    return render_template('ferramentas/converter_pedidos.html')


@ferramentas_bp.route('/ferramentas/identificar_nomes_ia')
@login_required
def identificar_nomes_ia():
    return render_template('ferramentas/identificar_nomes_ia.html')


@ferramentas_bp.route('/ferramentas/associacao-massa')
@login_required
def associacao_massa():
    categories = category_service.get_all_categories()
    tags = tag_service.get_all_tags()
    return render_template('ferramentas/associacao_massa.html', categories=categories, tags=tags)







