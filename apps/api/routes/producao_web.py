from flask import render_template, request, flash, redirect, url_for, current_app
from routes.auth import get_current_user
from nistiprint_shared.services.app_config_service import app_config_service
from nistiprint_shared.services.product_service import product_service
from nistiprint_shared.services.daily_production_log_service import daily_production_log_service
from nistiprint_shared.services.estoque_service import estoque_service
from datetime import datetime
from .producao_base import producao_bp

@producao_bp.route('/controle', methods=['GET'])
def controle_producao():
    selected_date = datetime.now().date()
    category_id = app_config_service.get_config('producao_miolos_category_id')
    if not category_id:
        flash('A categoria para a tela de produção ainda não foi configurada.', 'warning')
        return redirect(url_for('configuracoes.producao_config'))

    products_data, _ = product_service.get_products(categoria_id=category_id, per_page=10000)
    products = [p for p in products_data if p.get('status', 'ativo') == 'ativo']
    daily_logs = daily_production_log_service.get_logs_for_date(selected_date)
    deposito_id = app_config_service.get_config('default_production_deposit_id') or 'principal'

    enriched_products = []
    for product in products:
        log = daily_logs.get(product['id'])
        product['quantity_produced_today'] = log.get('quantityProduced', 0) if log else 0
        product['quantity_removed_today'] = log.get('quantityRemoved', 0) if log else 0
        stock_details = estoque_service.get_saldo_atual(product['id'], deposito_id)
        product['stock_details'] = stock_details
        product['physicalStock'] = stock_details.get('quantidade', 0)
        enriched_products.append(product)

    return render_template('producao/controle.html', products=enriched_products, selected_date=selected_date,
                           date_str=selected_date.strftime('%Y-%m-%d'), total_active_cores=len(enriched_products))
