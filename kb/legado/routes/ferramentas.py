from flask import Blueprint, render_template, jsonify, request, flash, redirect, url_for
from routes.auth import login_required
from services.ai_personalization_service import process_orders
from services.product_service import product_service
from services.bling_order_processing_service import import_single_order_by_shop_id

ferramentas_bp = Blueprint('ferramentas', __name__)

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
        flash(f'Ocorreu um erro inesperado: {str(e)}', 'danger')

    return redirect(url_for('ferramentas.ferramentas'))

@ferramentas_bp.route('/ferramentas/converter_pedidos')
@login_required
def converter_pedidos():
    return render_template('ferramentas/converter_pedidos.html')


@ferramentas_bp.route('/ferramentas/identificar_nomes_ia')
@login_required
def identificar_nomes_ia():
    return render_template('ferramentas/identificar_nomes_ia.html')

@ferramentas_bp.route('/ferramentas/processar_nomes_ia', methods=['POST'])
@login_required
def processar_nomes_ia():
    try:
        # Obter limit e shopee_order_sn dos parâmetros POST
        limit = request.form.get('limit')
        shopee_order_sn = request.form.get('shopee_order_sn')

        if limit and limit.isdigit():
            limit = int(limit)
        else:
            limit = None

        if not shopee_order_sn:
            shopee_order_sn = None

        # Executar processamento
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

@ferramentas_bp.route('/ferramentas/update_status_page')
@login_required
def update_status_page():
    return render_template('ferramentas/update_product_status.html')

@ferramentas_bp.route('/ferramentas/update_product_status')
@login_required
def update_product_status():
    try:
        products, _ = product_service.get_products(per_page=10000)  # Get all products
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
