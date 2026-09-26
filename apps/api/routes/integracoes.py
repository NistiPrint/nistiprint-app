from flask import Blueprint, jsonify, request
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.installed_integration_service import (
    installed_integration_service,
)
from datetime import datetime, timezone

# Blueprints para compatibilidade com app.py
integracoes_bp = Blueprint('integracoes', __name__)
integracoes_api_bp = Blueprint('integracoes_api_v2', __name__, url_prefix='/api/v2/integracoes')

@integracoes_api_bp.route('/status', methods=['GET'])
def get_status():
    """Retorna o status de todas as integrações no Supabase."""
    try:
        response = supabase_db.client.table('installed_integrations').select('*').execute()
        return jsonify(response.data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@integracoes_api_bp.route('/renovar/<int:id>', methods=['POST'])
def renovar_token(id):
    """Executa a renovação manual de um token."""
    try:
        integration = installed_integration_service.get_installed_by_id(str(id))
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    if not integration:
        return jsonify({"status": "error", "message": "Integração não encontrada"}), 404

    module_id = integration.module_id
    try:
        installed_integration_service.renew_integration_token(
            str(id), execution_mode="manual"
        )
    except Exception as e:
        try:
            installed_integration_service.update_installed(
                str(id),
                {
                    "last_refresh_attempt": datetime.now(timezone.utc).isoformat(),
                    "refresh_error": str(e),
                },
            )
        except Exception:
            pass
        return jsonify({"status": "error", "message": str(e)}), 400

    return jsonify({"status": "success", "message": f"Token de {module_id} renovado!"})

@integracoes_api_bp.route('/sync-firestore', methods=['POST'])
def sync_firestore():
    """Importa tokens do Firebase para o cofre interno, com publish apenas sob demanda."""
    try:
        # Agora aponta para a pasta local services/token_manager
        from nistiprint_shared.services.token_manager.sync_firestore import (
            import_bling_credentials_from_firebase,
            publish_bling_credentials_to_firebase,
        )
        data = request.get_json(silent=True) or {}
        mode = data.get('mode') or request.args.get('mode') or 'import'

        if mode == 'publish':
            result = publish_bling_credentials_to_firebase()
            return jsonify({
                "status": result.get("status", "success"),
                "message": "Credenciais publicadas no Firebase.",
                "result": result,
            })

        result = import_bling_credentials_from_firebase()
        return jsonify({
            "status": result.get("status", "success"),
            "message": "Tokens importados do Firebase para o cofre interno.",
            "result": result,
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@integracoes_api_bp.route('/sync-legacy', methods=['POST'])
def sync_legacy():
    """Sincroniza pedidos recentes do banco legado MySQL."""
    try:
        from nistiprint_shared.services.legacy_sync_service import LegacySyncService
        result = LegacySyncService.sync_recent_orders(days=14)
        if result.get("success"):
            return jsonify({"status": "success", "message": result.get("message"), "count": result.get("count")})
        else:
            return jsonify({"status": "error", "message": result.get("message")}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- NOVOS ENDPOINTS DE ROTEAMENTO (Multi-Conta) ---

@integracoes_api_bp.route('/routing', methods=['GET'])
def get_routing():
    """Retorna as regras de roteamento e dados auxiliares para a UI."""
    try:
        # 1. Buscar regras atuais
        routing = supabase_db.client.table('integration_account_routing').select('*').execute().data
        
        # 2. Buscar contas Bling (instaladas)
        accounts = supabase_db.client.table('installed_integrations') \
            .select('id, instance_name, config->cnpj') \
            .eq('module_id', 'bling') \
            .execute().data
            
        # 3. Buscar Canais de Venda
        channels = supabase_db.client.table('canais_venda').select('id, nome, plataforma_id').execute().data
        
        # 4. Buscar Plataformas
        platforms = supabase_db.client.table('plataformas').select('id, nome').execute().data
        
        return jsonify({
            "routing": routing,
            "accounts": accounts,
            "channels": channels,
            "platforms": platforms,
            "functions": [
                {"id": "ORDER_IMPORT", "name": "Importação de Pedidos"},
                {"id": "NFE_EMISSION", "name": "Emissão de Nota Fiscal (NFe)"},
                {"id": "STOCK_SYNC", "name": "Sincronização de Estoque"},
                {"id": "CATALOG_SYNC", "name": "Sincronização de Catálogo"}
            ]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@integracoes_api_bp.route('/routing', methods=['POST'])
def save_routing():
    """Salva ou atualiza uma regra de roteamento."""
    try:
        data = request.get_json()
        from nistiprint_shared.services.integration_routing_service import integration_routing_service
        
        success = integration_routing_service.set_routing(
            function_name=data.get('function_name'),
            scope_type=data.get('scope_type'),
            scope_id=data.get('scope_id'),
            account_id=data.get('account_id'),
            module=data.get('module', 'bling')
        )
        
        if success:
            return jsonify({"status": "success", "message": "Regra de roteamento salva!"})
        else:
            return jsonify({"status": "error", "message": "Falha ao salvar regra"}), 400
            
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@integracoes_api_bp.route('/routing/<id>', methods=['DELETE'])
def delete_routing(id):
    """Remove uma regra de roteamento."""
    try:
        supabase_db.client.table('integration_account_routing').delete().eq('id', id).execute()
        return jsonify({"status": "success", "message": "Regra removida!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@integracoes_api_bp.route('/bling/lojas', methods=['GET'])
def get_bling_lojas():
    """
    Lista as lojas virtuais cadastradas no Bling.
    Query params:
        account_id: ID da conta Bling no installed_integrations (opcional).
                    Se não informado, tenta pegar a primeira disponível.
    """
    try:
        account_id = request.args.get('account_id')
        from nistiprint_shared.services.bling.bling_client import BlingClient

        client = None

        if account_id:
             # Buscar integração específica
             res = supabase_db.client.table('installed_integrations').select('*').eq('id', account_id).single().execute()
             if res.data:
                 client = BlingClient.create_client_from_integration(res.data)
        else:
             # Buscar qualquer integração Bling ativa
             res = supabase_db.client.table('installed_integrations').select('*').eq('module_id', 'bling').eq('is_active', True).limit(1).execute()
             if res.data:
                 client = BlingClient.create_client_from_integration(res.data[0])

        if not client:
             return jsonify({"error": "Nenhuma conta Bling ativa encontrada. Instale o módulo Bling primeiro."}), 404

        lojas = client.get_stores()
        return jsonify(lojas)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@integracoes_api_bp.route('/bling/accounts', methods=['GET'])
def get_bling_accounts():
    """
    Lista todas as contas Bling instaladas.
    """
    try:
        response = supabase_db.client.table('installed_integrations') \
            .select('*') \
            .eq('module_id', 'bling') \
            .eq('is_active', True) \
            .execute()

        return jsonify({"accounts": response.data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500





