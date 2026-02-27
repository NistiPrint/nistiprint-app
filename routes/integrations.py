from datetime import datetime
from flask import Blueprint, render_template, jsonify, request, redirect, url_for, flash
from services.firebase.firestore_client import firestore_client
from services.bling.bling_client import BlingClient
from services.conta_bling_service import conta_bling_service

integrations_bp = Blueprint('integrations', __name__)

@integrations_bp.route('/admin/integrations')
def admin_integrations():
    """Página administrativa das integrações Bling."""
    try:
        # Buscar contas diretamente da coleção bling_accounts
        accounts_collection = firestore_client.collection('bling_accounts')
        docs = accounts_collection.stream()

        accounts = []
        for doc in docs:
            account_data = doc.to_dict()
            account_data['id'] = doc.id
            accounts.append(account_data)

        # Não imprimir logs relacionados ao Firestore agora
        return render_template('integrations.html', accounts=accounts)
    except Exception as e:
        print(f"Erro na rota de integrações: {e}")
        return render_template('error.html', error=str(e)), 500

@integrations_bp.route('/api/integrations/status/<account_id>')
def api_integration_status(account_id):
    """API para verificar status do token de uma conta específica."""
    print(f"🔍 Verificando status do token para conta: {account_id}")

    try:
        # Buscar dados da conta específica no Firestore
        accounts_collection = firestore_client.collection('bling_accounts')
        account_doc = accounts_collection.document(account_id).get()

        if not account_doc.exists:
            print(f"❌ Conta {account_id} não encontrada na coleção bling_accounts")
            return jsonify({'status': 'ACCOUNT_NOT_FOUND'}), 404

        account_data = account_doc.to_dict()

        # Verificar se tem tokens necessários
        if not account_data.get('access_token'):
            print("❌ Nenhum token de acesso encontrado")
            return jsonify({'status': 'NO_TOKEN'})

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
