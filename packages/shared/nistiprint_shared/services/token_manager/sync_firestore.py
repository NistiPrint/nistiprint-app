import logging
from datetime import datetime, timedelta
from nistiprint_shared.services.firebase.firebase import initialize_firebase
from firebase_admin import firestore
from nistiprint_shared.database.supabase_db_service import supabase_db

logger = logging.getLogger("SyncFirestore")

def sync_bling_to_supabase():
    """
    Sincroniza as contas do Bling do Firestore para o Supabase (installed_integrations).
    Otimizado para ler credenciais diretamente do documento e usar a estrutura JSONB.
    """
    logger.info("🚀 [SYNC] Iniciando sincronização inteligente Firestore -> Supabase...")
    
    if not initialize_firebase():
        logger.error("❌ [SYNC] Falha ao inicializar Firebase para sincronização.")
        return False

    db = firestore.client()
    try:
        accounts_ref = db.collection("bling_accounts")
        docs = accounts_ref.stream()

        count = 0
        for doc in docs:
            data = doc.to_dict()
            cnpj = data.get("cnpj")
            if not cnpj:
                continue

            # Mapeamento de campos baseado na estrutura real do Firestore (descoberta via MCP)
            instance_name = data.get("account_name", f"Bling - {cnpj}")
            client_id = data.get("client_id")
            client_secret = data.get("client_secret")
            access_token = data.get("access_token")
            refresh_token = data.get("refresh_token")
            
            # Cálculo de expiração
            updated_at_fs = data.get("updated_at") # Timestamp do Firebase
            expires_in = data.get("expires_in", 21600)
            
            expires_at = None
            if updated_at_fs:
                # updated_at_fs é um objeto datetime se vier do stream() do firebase_admin
                expires_at = (updated_at_fs + timedelta(seconds=expires_in)).isoformat()

            # Prepara objeto para o Supabase
            integration_data = {
                "module_id": "bling",
                "instance_name": instance_name,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": expires_at,
                "is_active": True,
                "config": {
                    "cnpj": cnpj,
                    "company_id": data.get("company_id")
                },
                "credentials": {
                    "client_id": client_id,
                    "client_secret": client_secret
                },
                "updated_at": datetime.utcnow().isoformat()
            }

            # 1. Realiza o UPSERT na tabela moderna (installed_integrations)
            try:
                supabase_db.execute_with_retry(
                    supabase_db.table("installed_integrations").upsert(
                        integration_data, 
                        on_conflict="module_id, instance_name"
                    )
                )
                logger.info(f"✅ Sincronizado (installed_integrations): {instance_name} ({cnpj})")
            except Exception as e:
                logger.error(f"❌ Erro ao inserir {cnpj} em installed_integrations: {e}")

            # 2. Realiza o UPSERT na tabela legado (contas_bling) para compatibilidade
            try:
                # O ID no Firestore deve ser o mesmo ID na tabela contas_bling para manter referências
                # Se não tivermos o ID do documento, usamos o CNPJ como chave de busca para o ID
                legacy_id = data.get("id") or doc.id
                
                legacy_data = {
                    "id": legacy_id,
                    "nome": instance_name,
                    "cnpj": cnpj,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "expires_in": expires_in,
                    "platform_name": data.get("platform", "Shopee"), # Fallback
                    "instance_name": instance_name,
                    "ativa": True,
                    "updated_at": datetime.utcnow().isoformat()
                }

                supabase_db.execute_with_retry(
                    supabase_db.table("contas_bling").upsert(
                        legacy_data,
                        on_conflict="id"
                    )
                )
                logger.info(f"✅ Sincronizado (contas_bling): {instance_name} ({cnpj})")
                count += 1
            except Exception as e:
                logger.error(f"❌ Erro ao inserir {cnpj} em contas_bling: {e}")

        logger.info(f"Sincronização concluída. {count} contas processadas.")
        return True

    except Exception as e:
        logger.error(f"Erro crítico durante a sincronização: {e}")
        return False

if __name__ == "__main__":
    # Para execução manual via CLI
    sync_bling_to_supabase()

