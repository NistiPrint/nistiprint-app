from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from services.app_config_service import app_config_service
from services.category_service import category_service
from services.deposito_service import deposito_service
from services.product_service import product_service
from services.conta_bling_service import conta_bling_service

configuracoes_bp = Blueprint('configuracoes', __name__, url_prefix='/configuracoes')
configuracoes_api_bp = Blueprint('configuracoes_api', __name__, url_prefix='/api/v2/configuracoes')

# API Configuracoes routes
@configuracoes_api_bp.route('/demanda-permissions', methods=['GET', 'POST'])
def api_demanda_permissions():
    """Manages the permission mapping for Demanda Dashboard (API)."""
    key = 'demanda_dashboard_permissions'
    if request.method == 'POST':
        data = request.get_json()
        app_config_service.set_config(key, data)
        return jsonify({'success': True, 'message': 'Permissões atualizadas com sucesso!'})
    else:
        config = app_config_service.get_config(key)
        return jsonify({'config': config, 'success': True})

@configuracoes_api_bp.route('/sistema', methods=['GET', 'POST'])
def api_sistema_config():
    """Manages general system configurations (Operational Mode, etc)."""
    if request.method == 'POST':
        try:
            data = request.get_json()
            if not data:
                return jsonify({'success': False, 'message': 'Nenhum dado recebido.'}), 400

            # Mode switch: 'v2' or 'legacy'
            if 'database_operational_mode' in data:
                mode = data['database_operational_mode']
                if mode not in ['v2', 'legacy']:
                    return jsonify({'success': False, 'message': 'Modo inválido. Use "v2" ou "legacy".'}), 400
                app_config_service.set_config('database_operational_mode', mode)

            return jsonify({'success': True, 'message': 'Configurações de sistema salvas com sucesso!'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500
    else:
        mode = app_config_service.get_operational_mode()
        return jsonify({
            'success': True,
            'database_operational_mode': mode
        })


@configuracoes_api_bp.route('/producao', methods=['GET', 'POST'])
def api_producao_config():
    """Manages the production control screen configuration (API version)."""
    if request.method == 'POST':
        try:
            data = request.get_json()
            if not data:
                return jsonify({'success': False, 'message': 'Nenhum dado recebido.'}), 400

            # Extract production configurations (Supporting both old and new names for migration safety)
            producao_configs = {
                'producao_miolos_category_id': data.get('producao_miolos_category_id'),
                'producao_capas_category_id': data.get('producao_capas_category_id') or data.get('producao_covers_category_id'),
                'producao_capas_impressas_category_id': data.get('producao_capas_impressas_category_id'),
                'default_production_deposit_id': data.get('default_production_deposit_id'),
                'material_safety_days': int(data.get('material_safety_days')) if data.get('material_safety_days') else 15,
                'sulfite_sheet_product_id': data.get('sulfite_sheet_product_id')
            }

            app_config_service.set_multiple_configs(producao_configs)

            return jsonify({'success': True, 'message': 'Configurações de produção salvas com sucesso!'})
        except ValueError:
            return jsonify({'success': False, 'message': 'Valor inválido para dias de segurança.'}), 400
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500
    else:
        # GET request - return current production configurations
        producao_configs = app_config_service.get_multiple_configs([
            'producao_miolos_category_id',
            'producao_capas_category_id',
            'producao_covers_category_id',
            'producao_capas_impressas_category_id',
            'default_production_deposit_id',
            'material_safety_days',
            'sulfite_sheet_product_id'
        ])

        # Get additional data that might be needed for the UI
        all_categories = category_service.get_all()
        all_deposits = deposito_service.get_all()
        all_products = [] # product_service.get_products(per_page=1000) - Removed to prevent performance issues and errors

        # Return the configuration values at the root level to match frontend expectations
        return jsonify({
            'success': True,
            'producao_miolos_category_id': producao_configs.get('producao_miolos_category_id'),
            'producao_capas_category_id': producao_configs.get('producao_capas_category_id') or producao_configs.get('producao_covers_category_id'),
            'producao_capas_impressas_category_id': producao_configs.get('producao_capas_impressas_category_id'),
            'default_production_deposit_id': producao_configs.get('default_production_deposit_id'),
            'material_safety_days': producao_configs.get('material_safety_days', 15),
            'sulfite_sheet_product_id': producao_configs.get('sulfite_sheet_product_id'),
            'all_categories': all_categories,
            'all_deposits': all_deposits,
            'all_products': all_products
        })


# Regular Configuracoes routes
@configuracoes_bp.route('/producao', methods=['GET', 'POST'])
def producao_config():
    """Manages the production control screen configuration."""
    if request.method == 'POST':
        miolos_category_id = request.form.get('producao_miolos_category_id')
        covers_category_id = request.form.get('producao_covers_category_id')
        deposit_id = request.form.get('default_production_deposit_id')
        safety_days = request.form.get('material_safety_days')
        sulfite_id = request.form.get('sulfite_sheet_product_id')

        # Set production configurations as a group
        producao_configs = {
            'producao_miolos_category_id': miolos_category_id or None,
            'producao_covers_category_id': covers_category_id or None,
            'default_production_deposit_id': deposit_id or None,
            'material_safety_days': int(safety_days) if safety_days else 15,
            'sulfite_sheet_product_id': sulfite_id or None
        }

        app_config_service.set_multiple_configs(producao_configs)

        flash('Configurações de produção salvas com sucesso!', 'success')
        return redirect(url_for('configuracoes.producao_config'))

    # GET request
    producao_configs = app_config_service.get_multiple_configs([
        'producao_miolos_category_id',
        'producao_covers_category_id',
        'default_production_deposit_id',
        'material_safety_days',
        'sulfite_sheet_product_id'
    ])

    all_categories = category_service.get_all()
    all_deposits = deposito_service.get_all()
    all_products = [] # product_service.get_products(per_page=1000)

    return render_template(
        'configuracoes/producao.html',
        all_categories=all_categories,
        producao_miolos_category_id=producao_configs.get('producao_miolos_category_id'),
        producao_covers_category_id=producao_configs.get('producao_covers_category_id'),
        all_deposits=all_deposits,
        default_production_deposit_id=producao_configs.get('default_production_deposit_id'),
        material_safety_days=producao_configs.get('material_safety_days', 15),
        all_products=all_products,
        sulfite_sheet_product_id=producao_configs.get('sulfite_sheet_product_id')
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
