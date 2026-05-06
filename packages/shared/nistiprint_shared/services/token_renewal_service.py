from datetime import datetime, timedelta, timezone
import logging

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.installed_integration_service import installed_integration_service

logger = logging.getLogger(__name__)


class TokenRenewalService:
    """Serviço compartilhado para renovação agendada de tokens."""

    def renew_shopee_tokens_expiring_soon(self, expiry_threshold: timedelta = timedelta(hours=1)) -> dict:
        logger.info("Iniciando verificação de tokens Shopee com expiração próxima.")

        response = supabase_db.client.table('installed_integrations') \
            .select('*') \
            .eq('module_id', 'shopee') \
            .eq('is_active', True) \
            .execute()

        integrations = response.data or []
        if not integrations:
            logger.info("Nenhuma integração Shopee ativa encontrada.")
            return {
                'status': 'SUCCESS',
                'message': 'Nenhuma integração Shopee ativa encontrada',
                'total': 0,
                'renewed': 0,
                'failed': 0,
                'skipped': 0
            }

        now = datetime.now(timezone.utc)
        renewed_count = 0
        failed_count = 0
        skipped_count = 0

        for integration in integrations:
            integration_id = str(integration.get('id'))
            instance_name = integration.get('instance_name', f'ID {integration_id}')
            expires_at = integration.get('expires_at')

            if not expires_at:
                logger.warning("Integração Shopee %s não tem expires_at. Pulando.", instance_name)
                skipped_count += 1
                continue

            try:
                expires_dt = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                if expires_dt.tzinfo is None:
                    expires_dt = expires_dt.replace(tzinfo=timezone.utc)
            except ValueError:
                logger.warning("expires_at inválido para %s: %s. Pulando.", instance_name, expires_at)
                skipped_count += 1
                continue

            time_until_expiry = expires_dt - now
            if time_until_expiry > expiry_threshold:
                logger.info("Token de %s ainda válido por %s. Pulando.", instance_name, time_until_expiry)
                skipped_count += 1
                continue

            logger.info("Renovando token para %s (expira em %s).", instance_name, time_until_expiry)

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
                        "Erro ao registrar falha de renovação da integração %s: %s",
                        integration_id,
                        log_error,
                    )

        result = {
            'status': 'SUCCESS',
            'message': 'Renovação de tokens Shopee concluída',
            'total': len(integrations),
            'renewed': renewed_count,
            'failed': failed_count,
            'skipped': skipped_count
        }
        logger.info(
            "Renovação concluída: %s renovados, %s falharam, %s pulados.",
            renewed_count,
            failed_count,
            skipped_count,
        )
        return result


token_renewal_service = TokenRenewalService()
