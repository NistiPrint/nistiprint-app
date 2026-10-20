"""Marketplace mirror persistence shared by direct ingest and ERP compatibility callers."""
import logging
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.marketplace_logistics_facts import normalize_sla
from nistiprint_shared.services import logistics_canonicalization
from nistiprint_shared.utils.date_utils import get_now_iso, normalize_to_iso
logger = logging.getLogger(__name__)

def _extract_meli_date_approved(order: dict) -> str | None:
    payments = order.get("payments") or []
    if not isinstance(payments, list):
        return None
    for payment in payments:
        if not isinstance(payment, dict):
            continue
        approved = payment.get("date_approved")
        if approved:
            return approved
    return None

def _upsert_pedido_meli(meli_data: dict, marketplace_integration_id: int, *, db=None) -> int:
    """
    Upsert pedido na tabela pedidos_mercadolivre.
    """
    if not meli_data or meli_data.get('error'):
        logger.error("[upsert_pedido_meli] Dados inválidos ou erro: %s", meli_data)
        raise ValueError(f"Dados do Mercado Livre inválidos: {meli_data.get('error') if meli_data else 'None'}")

    order = meli_data.get('order') or {}
    shipment = meli_data.get('shipment') or {}
    sla = normalize_sla(meli_data.get('sla'))
    
    logger.info("[upsert_pedido_meli] Raw shipment flags - logistic_type: %s, shipping_type: %s", 
                shipment.get('logistic_type'), shipment.get('shipping_type'))

    shipping_option = shipment.get('shipping_option') or {}

    row = {
        'codigo_pedido':     meli_data.get('external_id'),
        'shipment_id':       shipment.get('id'),
        'status':            order.get('status'),
        'mode':              shipment.get('mode'),
        'shipping_type':     shipment.get('shipping_type'),
        'shipping_option_name': shipping_option.get('name'),
        # Provider payloads can contain empty strings for optional timestamps;
        # Postgres timestamptz columns require NULL instead.
        'expected_date':     normalize_to_iso(sla.get('expected_date')),
        'date_approved':     normalize_to_iso(_extract_meli_date_approved(order)),
        'buyer_nickname':    (order.get('buyer') or {}).get('nickname'),
        'raw_order':         order,
        'raw_shipment':      shipment,
        'raw_sla':           meli_data.get('sla'),
        'marketplace_integration_id': marketplace_integration_id,
        'updated_at':        get_now_iso(),
    }
    
    if not row.get('codigo_pedido'):
        raise ValueError("codigo_pedido (external_id) está null - não é possível upsert pedidos_mercadolivre")
    
    res = (db if db is not None else supabase_db).table('pedidos_mercadolivre') \
        .upsert(row, on_conflict='codigo_pedido').execute()
    return res.data[0]['id']

def _upsert_pedido_shopee(shopee_data: dict, marketplace_integration_id: int, *, db=None) -> int:
    """
    Upsert pedido na tabela pedidos_shopee.

    Mapeamento de campos:
    - Shopee order_sn = Código do pedido na Shopee
    - No banco: codigo_pedido (equivale a order_sn, que também é o Bling numeroLoja)
    - Este campo é usado como chave única (on_conflict)
    """
    logger.info("[upsert_pedido_shopee] shopee_data keys: %s", shopee_data.keys() if shopee_data else None)
    logger.info("[upsert_pedido_shopee] shopee_data external_id: %s", shopee_data.get('external_id') if shopee_data else None)
    
    # Se shopee_data tiver 'error', significa que a chamada à API falhou
    if shopee_data and shopee_data.get('error'):
        logger.error("[upsert_pedido_shopee] Erro retornado pelo driver Shopee: %s", shopee_data.get('error'))
        raise ValueError(f"Erro ao buscar dados da Shopee: {shopee_data.get('error')}")
    
    raw_payload = shopee_data.get('raw') if isinstance(shopee_data.get('raw'), dict) else {}
    message_to_seller = shopee_data.get('message_to_seller')
    if message_to_seller is None:
        message_to_seller = raw_payload.get('message_to_seller')

    row = {
        'codigo_pedido':     shopee_data.get('external_id'),  # order_sn (equivale a Bling numeroLoja)
        'shop_id':           shopee_data.get('shop_id'),
        'order_sn':          shopee_data.get('external_id'),
        'order_status':      shopee_data.get('order_status'),
        'buyer_username':    shopee_data.get('buyer_username'),
        'buyer_user_id':     shopee_data.get('buyer_user_id'),
        'fulfillment_flag':  shopee_data.get('fulfillment_flag'),
        'shipping_carrier':  shopee_data.get('shipping_carrier'),
        'package_list':      shopee_data.get('package_list'),
        'item_list':         shopee_data.get('item_list'),
        'recipient_address': shopee_data.get('recipient_address'),
        'pay_time':          shopee_data.get('pay_time'),
        'raw_payload':       shopee_data.get('raw'),
        'enriched_at':       'now()',
        'marketplace_integration_id': marketplace_integration_id,
    }
    if message_to_seller is not None:
        row['mensagem'] = message_to_seller

    # Prazo de postagem como coluna, nao so dentro do raw_payload. Foi preciso
    # cavar jsonb para descobrir que `ship_by_date` vinha zerado enquanto
    # `days_to_ship` vinha preenchido; com os dois em coluna, a mesma pergunta
    # vira uma consulta. Gravados so quando ha valor: o upsert substitui a
    # linha inteira, e um payload sem o campo apagaria o que ja sabiamos.
    ship_by_date = logistics_canonicalization.observe_shopee(shopee_data).dispatch_deadline_raw
    if ship_by_date:
        row['ship_by_date'] = ship_by_date
    dias_para_envio = shopee_data.get('days_to_ship')
    if dias_para_envio in (None, ''):
        dias_para_envio = raw_payload.get('days_to_ship')
    if dias_para_envio not in (None, ''):
        try:
            row['dias_para_envio'] = int(dias_para_envio)
        except (TypeError, ValueError):
            pass
    
    if not row.get('codigo_pedido'):
        logger.error("[upsert_pedido_shopee] codigo_pedido está null - shopee_data: %s", shopee_data)
        raise ValueError("codigo_pedido (external_id) está null - não é possível upsert pedidos_shopee")
    
    res = (db if db is not None else supabase_db).table('pedidos_shopee') \
        .upsert(row, on_conflict='codigo_pedido').execute()
    return res.data[0]['id']

