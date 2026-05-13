from datetime import datetime, timedelta
import logging

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.installed_integration_service import installed_integration_service

logger = logging.getLogger(__name__)


class TokenRenewalService:
    """Servico compartilhado para renovacao agendada de tokens."""

    def renew_shopee_tokens_expiring_soon(self, expiry_threshold: timedelta = timedelta(hours=1)) -> dict:
        logger.info(
            "Iniciando renovacao agendada de tokens Shopee ativos. "
            "expiry_threshold mantido apenas por compatibilidade."
        )

        response = supabase_db.client.table('installed_integrations') \
            .select('*') \
            .eq('module_id', 'shopee') \
            .eq('is_active', True) \
            .execute()

        integrations = response.data or []
        if not integrations:
            logger.info("Nenhuma integracao Shopee ativa encontrada.")
            return {
                'status': 'SUCCESS',
                'message': 'Nenhuma integracao Shopee ativa encontrada',
                'total': 0,
                'renewed': 0,
                'failed': 0,
                'skipped': 0
            }

        renewed_count = 0
        failed_count = 0
        skipped_count = 0

        for integration in integrations:
            integration_id = str(integration.get('id'))
            instance_name = integration.get('instance_name', f'ID {integration_id}')

            logger.info("Renovando token Shopee para %s.", instance_name)

            try:
                installed_integration_service.renew_integration_token(
                    integration_id,
                    execution_mode='scheduled'
                )
                renewed_count += 1
            except Exception as exc:
                logger.error("Erro ao renovar token para %s: %s", instance_name, exc)
                failed_count += 1
                try:
                    installed_integration_service.update_installed(integration_id, {
                        'last_refresh_attempt': datetime.utcnow().isoformat(),
                        'refresh_error': str(exc),
                    })
                    installed_integration_service.log_table.insert({
                        'integration_id': integration_id,
                        'status': 'error',
                        'message': str(exc),
                        'execution_mode': 'scheduled',
                        'created_at': datetime.utcnow().isoformat()
                    }).execute()
                except Exception as log_error:
                    logger.error(
                        "Erro ao registrar falha de renovacao da integracao %s: %s",
                        integration_id,
                        log_error,
                    )

        result = {
            'status': 'SUCCESS',
            'message': 'Renovacao de tokens Shopee concluida',
            'total': len(integrations),
            'renewed': renewed_count,
            'failed': failed_count,
            'skipped': skipped_count
        }
        logger.info(
            "Renovacao concluida: %s renovados, %s falharam, %s pulados.",
            renewed_count,
            failed_count,
            skipped_count,
        )
        return result


token_renewal_service = TokenRenewalService()
