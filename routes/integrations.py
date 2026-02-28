from datetime import datetime
from flask import Blueprint, render_template, jsonify, request, redirect, url_for, flash
# from nistiprint_shared.services.firebase.firestore_client import firestore_client  # Firebase removido
from nistiprint_shared.services.bling.bling_client import BlingClient
from nistiprint_shared.services.conta_bling_service import conta_bling_service
from nistiprint_shared.database.supabase_db_service import supabase_db

integrations_bp = Blueprint('integrations', __name__)

@integrations_bp.route('/admin/integrations')
def admin_integrations():
    """Página administrativa das integrações Bling (Migrando para Supabase)."""
    try:
        # TODO: Implementar busca via Supabase
        # accounts = supabase_db.get_all('bling_accounts')
        accounts = [] # Placeholder enquanto a migração não é concluída
        
        return render_template('integrations.html', accounts=accounts)
    except Exception as e:
        print(f"Erro na rota de integrações: {e}")
        return render_template('error.html', error=str(e)), 500

@integrations_bp.route('/api/integrations/status/<account_id>')
def api_integration_status(account_id):
    """API para verificar status do token (Migrando para Supabase)."""
    print(f"🔍 Verificando status do token para conta: {account_id}")

    try:
        # TODO: Implementar busca via Supabase
        # account_data = supabase_db.get('bling_accounts', account_id)
        
        return jsonify({'status': 'MIGRATION_IN_PROGRESS'}), 200

        # Adicionar ID do documento aos dados
        account_data['id'] = account_id

        # Criar cliente com dados específicos da conta
        try:
            client = BlingClient(account_data)

            # Verificar token fazendo chamada para a API Bling
            # Este processo irá chamar o endpoint externo para obter token
            token_valid = client.check_token_simple()
            print(f"🔍 Resultado da verificação do token (via API externa): {'VÁLIDO' if token_valid else 'INVÁLIDO'}")

        except Exception as e:
            print(f"❌ ERRO ao verificar token na API: {str(e)}")
            token_valid = False

        result_status = 'VALID' if token_valid else 'INVALID'

        return jsonify({
            'status': result_status,
            'account_name': account_data.get('account_name'),
            'cnpj': account_data.get('cnpj'),
            'has_token': bool(account_data.get('access_token')),
            'has_refresh_token': bool(account_data.get('refresh_token')),
            'updated_at': account_data.get('updated_at')
        })
    except Exception as e:
        print(f"❌ ERRO GERAL na verificação de status da conta {account_id}: {str(e)}")
        return jsonify({
            'status': 'ERROR',
            'error': str(e)
        }), 500


@integrations_bp.route('/api/integrations/info/<platform>')
def api_integration_info(platform):
    """API para obter informações detalhadas de uma integração."""
    try:
        client = BlingClient.create_client_for_platform(platform)
        info = client.get_account_info()
        return jsonify(info)
    except Exception as e:
        return jsonify({
            'error': str(e),
            'platform': platform
        }), 500

# CRUD routes for Bling accounts
@integrations_bp.route('/admin/integrations/<account_id>/edit', methods=['GET', 'POST'])
def edit_integration(account_id):
    """Edit existing Bling account."""
    account = conta_bling_service.get_by_id(account_id)
    if not account:
        flash('Conta Bling não encontrada.', 'error')
        return redirect(url_for('integrations.admin_integrations'))

    if request.method == 'POST':
        try:
            data = {
                'account_name': request.form['account_name'],
                'cnpj': request.form['cnpj'],
                'client_id': request.form.get('client_id'),
                'client_secret': request.form.get('client_secret'),
                'access_token': request.form.get('access_token'),
                'refresh_token': request.form.get('refresh_token'),
                'expires_in': request.form.get('expires_in')
            }
            # Convert expires_in to int if provided
            if data['expires_in']:
                data['expires_in'] = int(data['expires_in'])

            conta_bling_service.update(account_id, data)
            flash('Conta Bling atualizada com sucesso!', 'success')
            return redirect(url_for('integrations.admin_integrations'))
        except Exception as e:
            flash(f'Erro ao atualizar conta: {str(e)}', 'error')

    return render_template('integration_edit.html', account=account)

@integrations_bp.route('/admin/integrations/<account_id>/delete', methods=['POST'])
def delete_integration(account_id):
    """Delete a Bling account."""
    try:
        conta_bling_service.delete(account_id)
        flash('Conta Bling removida com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao remover conta: {str(e)}', 'error')

    return redirect(url_for('integrations.admin_integrations'))

@integrations_bp.route('/admin/integrations/new', methods=['GET', 'POST'])
def new_integration():
    """Create new Bling account."""
    if request.method == 'POST':
        try:
            data = {
                'account_name': request.form['account_name'],
                'cnpj': request.form['cnpj'],
                'client_id': request.form.get('client_id'),
                'client_secret': request.form.get('client_secret'),
                'access_token': request.form.get('access_token'),
                'refresh_token': request.form.get('refresh_token'),
                'expires_in': request.form.get('expires_in')
            }
            # Convert expires_in to int if provided
            if data['expires_in']:
                data['expires_in'] = int(data['expires_in'])

            conta_bling_service.create(data)
            flash('Conta Bling criada com sucesso!', 'success')
            return redirect(url_for('integrations.admin_integrations'))
        except Exception as e:
            flash(f'Erro ao criar conta: {str(e)}', 'error')

    return render_template('integration_edit.html', account=None)





