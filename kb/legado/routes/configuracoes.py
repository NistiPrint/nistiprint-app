from flask import Blueprint, render_template, request, flash, redirect, url_for
from services.app_config_service import app_config_service
from services.category_service import category_service
from services.deposito_service import deposito_service
from services.product_service import product_service
from services.conta_bling_service import conta_bling_service

configuracoes_bp = Blueprint('configuracoes', __name__, url_prefix='/configuracoes')

@configuracoes_bp.route('/producao', methods=['GET', 'POST'])
def producao_config():
    """Manages the production control screen configuration."""
    category_config_key = 'producao_miolos_category_id'
    deposit_config_key = 'default_production_deposit_id'
    safety_days_key = 'material_safety_days'
    sulfite_id_key = 'sulfite_sheet_product_id'

    if request.method == 'POST':
        # Salvar configuração da categoria
        category_id = request.form.get('category_id')
        if category_id:
            app_config_service.set_config(category_config_key, category_id)
        
        # Salvar configuração do depósito
        deposit_id = request.form.get('deposit_id')
        if deposit_id:
            app_config_service.set_config(deposit_config_key, deposit_id)

        # Salvar dias de segurança para insumos
        safety_days = request.form.get('material_safety_days')
        if safety_days:
            app_config_service.set_config(safety_days_key, int(safety_days))

        # Salvar ID do produto de folha sulfite
        sulfite_id = request.form.get('sulfite_sheet_product_id')
        if sulfite_id:
            app_config_service.set_config(sulfite_id_key, sulfite_id)

        flash('Configurações de produção salvas com sucesso!', 'success')
        return redirect(url_for('configuracoes.producao_config'))

    # GET request
    selected_category_id = app_config_service.get_config(category_config_key)
    selected_deposit_id = app_config_service.get_config(deposit_config_key)
    material_safety_days = app_config_service.get_config(safety_days_key) or 15
    selected_sulfite_id = app_config_service.get_config(sulfite_id_key)
    
    all_categories = category_service.get_all()
    all_deposits = deposito_service.get_all()
    # Fetch all products for the selector, assuming get_all() is available and efficient
    all_products, _ = product_service.get_products(per_page=1000) # Assuming a large number to get all

    return render_template(
        'configuracoes/producao.html',
        all_categories=all_categories,
        selected_category_id=selected_category_id,
        all_deposits=all_deposits,
        selected_deposit_id=selected_deposit_id,
        material_safety_days=material_safety_days,
        all_products=all_products,
        selected_sulfite_id=selected_sulfite_id
    )

@configuracoes_bp.route('/bling', methods=['GET', 'POST'])
def bling_config():
    """Manages the default Bling account configuration for product registration."""
    bling_account_config_key = 'default_bling_account_id'

    if request.method == 'POST':
        default_bling_account_id = request.form.get('default_bling_account_id')
        if default_bling_account_id:
            app_config_service.set_config(bling_account_config_key, default_bling_account_id)
            flash('Configuração da conta Bling padrão salva com sucesso!', 'success')
        else:
            # If no account is selected, clear the configuration
            app_config_service.set_config(bling_account_config_key, '')
            flash('Configuração da conta Bling padrão removida com sucesso!', 'info')
        return redirect(url_for('configuracoes.bling_config'))

    # GET request
    selected_bling_account_id = app_config_service.get_config(bling_account_config_key)
    all_bling_accounts = conta_bling_service.get_all()

    return render_template(
        'configuracoes/bling_config.html',
        all_bling_accounts=all_bling_accounts,
        selected_bling_account_id=selected_bling_account_id
    )
