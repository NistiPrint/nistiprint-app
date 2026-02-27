from flask import Blueprint, jsonify, request
from services.database.v2.supabase_db_service import supabase_db
from datetime import datetime
import importlib
import os
import sys

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
        res = supabase_db.client.table('installed_integrations').select('*').eq('id', id).single().execute()
        if not res.data:
            return jsonify({"status": "error", "message": "Integração não encontrada"}), 404
            
        integration = res.data
        module_id = integration.get('module_id')
        
        # Agora aponta para a pasta local services.token_manager
        driver_path = f"services.token_manager.drivers.{module_id}"
        
        try:
            module = importlib.import_module(driver_path)
            update_data = module.refresh_token(integration)
        except ImportError:
            return jsonify({"status": "error", "message": f"Driver para {module_id} não encontrado"}), 501
        except Exception as e:
            # Tentar registrar o erro no banco se a coluna existir
            error_msg = str(e)
            try:
                supabase_db.client.table('installed_integrations').update({
                    "last_refresh_attempt": datetime.utcnow().isoformat(),
                    "refresh_error": error_msg
                }).eq('id', id).execute()
            except:
                pass # Silencioso se a coluna não existir ainda
            return jsonify({"status": "error", "message": error_msg}), 400
        
        if update_data:
            # Campos de controle de renovação
            update_data["last_refresh_attempt"] = datetime.utcnow().isoformat()
            update_data["refresh_error"] = None
            
            # Executar update
            try:
                supabase_db.client.table('installed_integrations').update(update_data).eq('id', id).execute()
                return jsonify({"status": "success", "message": f"Token de {module_id} renovado!"})
            except Exception as db_error:
                # Se der erro de coluna ausente (PGRST204), tenta salvar sem os campos de log
                if "PGRST204" in str(db_error):
                    # Remove campos problemáticos e tenta de novo
                    for col in ["last_refresh_attempt", "refresh_error"]:
                        update_data.pop(col, None)
                    supabase_db.client.table('installed_integrations').update(update_data).eq('id', id).execute()
                    return jsonify({"status": "success", "message": f"Token renovado (Log de tentativa ignorado: aplique as migrações)"})
                raise db_error
                
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@integracoes_api_bp.route('/sync-firestore', methods=['POST'])
def sync_firestore():
    """Aciona sincronização com Firestore."""
    try:
        # Agora aponta para a pasta local services/token_manager
        from services.token_manager.sync_firestore import sync_bling_to_supabase
        sync_bling_to_supabase()
        return jsonify({"status": "success", "message": "Sincronização concluída!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@integracoes_api_bp.route('/sync-legacy', methods=['POST'])
def sync_legacy():
    """Sincroniza pedidos recentes do banco legado MySQL."""
    try:
        from services.legacy_sync_service import LegacySyncService
        result = LegacySyncService.sync_recent_orders(days=14)
        if result.get("success"):
            return jsonify({"status": "success", "message": result.get("message"), "count": result.get("count")})
        else:
            return jsonify({"status": "error", "message": result.get("message")}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500