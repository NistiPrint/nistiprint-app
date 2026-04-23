from celery_config import celery_app
from nistiprint_shared.database.supabase_db_service import supabase_db
from datetime import datetime, timedelta
import importlib
import logging
import sys
import os

# Adicionar diretório do worker ao path para importar task_logger
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from task_logger import log_task_execution

logger = logging.getLogger(__name__)


@celery_app.task(name='tasks.token_renewal_tasks.renew_shopee_tokens')
@log_task_execution(task_type='TOKEN_RENEWAL')
def renew_shopee_tokens_task():
    """
    Tarefa Celery para renovar automaticamente tokens de integrações Shopee.
    
    Esta tarefa:
    1. Busca todas as integrações Shopee ativas
    2. Verifica se o token está próximo de expirar (menos de 24h)
    3. Renova o token usando o driver Shopee
    4. Atualiza a integração com o novo token
    """
    try:
        logger.info("Iniciando renovação de tokens Shopee...")
        
        # Buscar todas as integrações Shopee ativas
        response = supabase_db.client.table('installed_integrations') \
            .select('*') \
            .eq('module_id', 'shopee') \
            .eq('is_active', True) \
            .execute()
        
        integrations = response.data
        
        if not integrations:
            logger.info("Nenhuma integração Shopee ativa encontrada.")
            return {'status': 'SUCCESS', 'message': 'Nenhuma integração Shopee ativa encontrada', 'renewed': 0}
        
        logger.info(f"Encontradas {len(integrations)} integrações Shopee ativas.")
        
        renewed_count = 0
        failed_count = 0
        skipped_count = 0
        
        for integration in integrations:
            integration_id = integration.get('id')
            instance_name = integration.get('instance_name', f'ID {integration_id}')
            
            try:
                # Verificar se o token precisa de renovação
                expires_at = integration.get('expires_at')
                if not expires_at:
                    logger.warning(f"Integração Shopee {instance_name} não tem expires_at. Pulando.")
                    skipped_count += 1
                    continue
                
                # Parsear expires_at
                try:
                    expires_dt = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                except:
                    logger.warning(f"expires_at inválido para {instance_name}: {expires_at}. Pulando.")
                    skipped_count += 1
                    continue
                
                # Verificar se expira em menos de 24 horas
                now = datetime.utcnow()
                time_until_expiry = expires_dt - now
                
                if time_until_expiry > timedelta(hours=24):
                    logger.info(f"Token de {instance_name} ainda válido por {time_until_expiry}. Pulando.")
                    skipped_count += 1
                    continue
                
                logger.info(f"Renovando token para {instance_name} (expira em {time_until_expiry})")
                
                # Importar o driver Shopee
                driver_path = "services.token_manager.drivers.shopee"
                module = importlib.import_module(driver_path)
                
                # Executar renovação
                update_data = module.refresh_token(integration)
                
                if update_data:
                    # Adicionar campos de controle
                    update_data["last_refresh_attempt"] = datetime.utcnow().isoformat()
                    update_data["refresh_error"] = None
                    
                    # Atualizar no Supabase
                    supabase_db.client.table('installed_integrations') \
                        .update(update_data) \
                        .eq('id', integration_id) \
                        .execute()
                    
                    logger.info(f"Token renovado com sucesso para {instance_name}")
                    renewed_count += 1
                else:
                    logger.warning(f"Driver Shopee não retornou dados de atualização para {instance_name}")
                    failed_count += 1
                    
            except Exception as e:
                logger.error(f"Erro ao renovar token para {instance_name}: {str(e)}")
                
                # Registrar erro na integração
                try:
                    supabase_db.client.table('installed_integrations').update({
                        "last_refresh_attempt": datetime.utcnow().isoformat(),
                        "refresh_error": str(e)
                    }).eq('id', integration_id).execute()
                except Exception as db_error:
                    logger.error(f"Erro ao registrar falha de renovação no banco: {str(db_error)}")
                
                failed_count += 1
        
        result = {
            'status': 'SUCCESS',
            'message': 'Renovação de tokens Shopee concluída',
            'total': len(integrations),
            'renewed': renewed_count,
            'failed': failed_count,
            'skipped': skipped_count
        }
        
        logger.info(f"Renovação concluída: {renewed_count} renovados, {failed_count} falharam, {skipped_count} pulados")
        return result
        
    except Exception as e:
        logger.error(f"Erro na tarefa de renovação de tokens Shopee: {str(e)}")
        return {'status': 'FAILED', 'error': str(e)}
