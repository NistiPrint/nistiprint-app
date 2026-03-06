# ===========================================
# CELERY TASKS - WEBHOOKS
# ===========================================
# Tasks assíncronas para processamento de webhooks
# Recebem dados do n8n via Redis e processam no Supabase
# ===========================================

import logging
from datetime import datetime
from celery import shared_task
from nistiprint_shared.database.supabase_db_service import SupabaseDBService

logger = logging.getLogger(__name__)


def get_supabase_client():
    """
    Factory function para obter cliente Supabase
    """
    return SupabaseDBService()


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_shopee_webhook(self, webhook_data: dict):
    """
    Processa webhook da Shopee recebido pelo n8n

    Args:
        webhook_data: Dict com dados do webhook
            - order_sn: Order serial number
            - event_type: Tipo de evento (order.created, order.updated, etc.)
            - payload: Dados completos do webhook
    """
    try:
        logger.info(f"Processando webhook Shopee: {webhook_data.get('order_sn', 'N/A')}")

        # Conectar ao Supabase
        supabase = get_supabase_client()

        event_type = webhook_data.get('event_type', 'unknown')
        order_sn = webhook_data.get('order_sn')
        payload = webhook_data.get('payload', {})

        # Log do webhook para auditoria
        supabase.table('webhook_logs').insert({
            'plataforma': 'shopee',
            'event_type': event_type,
            'order_sn': order_sn,
            'payload': payload,
            'processed': True,
            'processed_at': datetime.now().isoformat(),
            'status': 'success'
        }).execute()

        # Processar baseado no tipo de evento
        if event_type in ['order.created', 'order.paid']:
            _process_shopee_order_creation(supabase, payload)
        elif event_type == 'order.updated':
            _process_shopee_order_update(supabase, payload)
        elif event_type == 'order.cancelled':
            _process_shopee_order_cancel(supabase, payload)

        logger.info(f"Webhook Shopee processado com sucesso: {order_sn}")
        return {'status': 'success', 'order_sn': order_sn}

    except Exception as e:
        logger.error(f"Erro ao processar webhook Shopee: {str(e)}")
        raise self.retry(exc=e, countdown=60)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_bling_webhook(self, webhook_data: dict):
    """
    Processa webhook do Bling recebido pelo n8n

    Args:
        webhook_data: Dict com dados do webhook
            - id: ID do pedido no Bling
            - event: Tipo de evento (sale.created, sale.changed, etc.)
            - payload: Dados completos
    """
    try:
        logger.info(f"Processando webhook Bling: {webhook_data.get('id', 'N/A')}")

        supabase = get_supabase_client()

        event = webhook_data.get('event', 'unknown')
        order_id = webhook_data.get('id')
        payload = webhook_data.get('data', {})

        # Log do webhook
        supabase.table('webhook_logs').insert({
            'plataforma': 'bling',
            'event_type': event,
            'order_id': order_id,
            'payload': payload,
            'processed': True,
            'processed_at': datetime.now().isoformat(),
            'status': 'success'
        }).execute()

        # Processar baseado no evento
        if event == 'sale.created':
            _process_bling_sale_created(supabase, payload)
        elif event == 'sale.changed':
            _process_bling_sale_changed(supabase, payload)
        elif event in ['product.created', 'product.changed']:
            _process_bling_product_change(supabase, payload)
        elif event == 'stock.changed':
            _process_bling_stock_change(supabase, payload)

        logger.info(f"Webhook Bling processado com sucesso: {order_id}")
        return {'status': 'success', 'order_id': order_id}

    except Exception as e:
        logger.error(f"Erro ao processar webhook Bling: {str(e)}")
        raise self.retry(exc=e, countdown=60)


@shared_task
def process_pending_webhooks():
    """
    Task periódica para processar webhooks pendentes
    Roda a cada 5 minutos via Celery Beat
    """
    try:
        supabase = get_supabase_client()

        # Buscar webhooks não processados
        response = supabase.table('webhook_logs')\
            .select('*')\
            .eq('processed', False)\
            .limit(100)\
            .execute()

        webhooks = response.data

        if not webhooks:
            return {'status': 'success', 'processed': 0, 'message': 'No pending webhooks'}

        processed_count = 0
        for webhook in webhooks:
            try:
                plataforma = webhook.get('plataforma')
                payload = webhook.get('payload', {})

                if plataforma == 'shopee':
                    process_shopee_webhook.delay({
                        'order_sn': payload.get('order_sn'),
                        'event_type': webhook.get('event_type'),
                        'payload': payload
                    })
                elif plataforma == 'bling':
                    process_bling_webhook.delay({
                        'id': payload.get('id'),
                        'event': webhook.get('event_type'),
                        'data': payload
                    })

                # Marcar como em processamento
                supabase.table('webhook_logs')\
                    .update({'processing': True})\
                    .eq('id', webhook.get('id'))\
                    .execute()

                processed_count += 1

            except Exception as e:
                logger.error(f"Erro ao enfileirar webhook {webhook.get('id')}: {str(e)}")

        return {'status': 'success', 'processed': processed_count}

    except Exception as e:
        logger.error(f"Erro na task process_pending_webhooks: {str(e)}")
        return {'status': 'error', 'message': str(e)}


# ===========================================
# HELPERS INTERNOS
# ===========================================

def _process_shopee_order_creation(supabase, payload: dict):
    """Processa criação de pedido Shopee"""
    # Implementação específica de criação de pedido
    logger.info(f"Criando pedido Shopee: {payload.get('order_sn')}")
    # TODO: Implementar lógica de criação


def _process_shopee_order_update(supabase, payload: dict):
    """Processa atualização de pedido Shopee"""
    logger.info(f"Atualizando pedido Shopee: {payload.get('order_sn')}")
    # TODO: Implementar lógica de atualização


def _process_shopee_order_cancel(supabase, payload: dict):
    """Processa cancelamento de pedido Shopee"""
    logger.info(f"Cancelando pedido Shopee: {payload.get('order_sn')}")
    # TODO: Implementar lógica de cancelamento


def _process_bling_sale_created(supabase, payload: dict):
    """Processa venda criada no Bling"""
    logger.info(f"Venda criada no Bling: {payload.get('id')}")
    # TODO: Implementar lógica


def _process_bling_sale_changed(supabase, payload: dict):
    """Processa venda alterada no Bling"""
    logger.info(f"Venda alterada no Bling: {payload.get('id')}")
    # TODO: Implementar lógica


def _process_bling_product_change(supabase, payload: dict):
    """Processa alteração de produto no Bling"""
    logger.info(f"Produto alterado no Bling: {payload.get('id')}")
    # TODO: Implementar lógica


def _process_bling_stock_change(supabase, payload: dict):
    """Processa alteração de estoque no Bling"""
    logger.info(f"Estoque alterado no Bling: {payload.get('productId')}")
    # TODO: Implementar lógica

