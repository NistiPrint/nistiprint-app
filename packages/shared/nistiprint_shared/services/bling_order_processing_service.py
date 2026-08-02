import logging
import json
import traceback
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter
import unicodedata

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.correlation_service import (
    generate_correlation_id,
    set_correlation_id,
)
from nistiprint_shared.services.integration_resolution_service import (
    integration_resolution_service,
)
from nistiprint_shared.services.credential_resolver_service import (
    credential_resolver_service,
)
from nistiprint_shared.services.order_status_decision import is_authoritative
from nistiprint_shared.services.canonical_order_status_service import (
    canonical_order_status_service,
)
from nistiprint_shared.services.canonical_order_repository import (
    OrderIdentityUnresolvedError,
    canonical_order_repository,
)
from nistiprint_shared.services.logistica_coleta_service import logistica_coleta_service
from nistiprint_shared.services.personalized_classification_service import (
    item_indicates_personalized,
    persist_classification_from_payload,
)
from nistiprint_shared.services.platform_drivers import shopee as shopee_driver
from nistiprint_shared.services.platform_drivers import mercadolivre as meli_driver
from nistiprint_shared.services import flex_classifier_service, fulfillment_classifier_service
from nistiprint_shared.utils.date_utils import get_now_iso, unix_to_app_iso, parse_datetime, normalize_to_iso

logger = logging.getLogger("bling_order_processing")


class BlingDetailUnavailableError(RuntimeError):
    """Erro tipado para quando o detalhe do pedido no Bling nao pode ser obtido."""

    def __init__(self, message: str, *, error_type: str = 'bling_detail_unavailable', retry_after: float | None = None):
        super().__init__(message)
        self.error_type = error_type
        self.retry_after = retry_after



@dataclass
class FlexClassificationResult:
    is_flex: bool
    is_fulfillment: bool = False
    modalidade: str = 'STANDARD'
    motivo: str = ''
    matched_rule_id: int | None = None
    raw_decision: dict | None = None


def _start_correlation_id(correlation_id: str | None = None) -> str:
    if not correlation_id:
        correlation_id = generate_correlation_id()
    set_correlation_id(correlation_id)
    return correlation_id


def _update_webhook_event(webhook_event_id: int | None, **fields):
    if not webhook_event_id or not fields:
        return

    try:
        supabase_db.table('webhook_events').update(fields).eq('id', webhook_event_id).execute()
    except Exception as e:
        logger.warning("[ingest] Erro ao atualizar webhook_events id=%s: %s", webhook_event_id, e)


def _normalize_carrier(value: str | None) -> str:
    if not value:
        return ""
    nfkd = unicodedata.normalize("NFKD", value)
    return "".join(char for char in nfkd if not unicodedata.combining(char)).lower().strip()


def _classify_fulfillment(
    shopee_data: dict | None,
    meli_data: dict | None,
    numero_loja: str | None,
    marketplace_slug: str | None,
    canal_venda_id: int | None = None,
    marketplace_integration_id: int | None = None,
    correlation_id: str | None = None,
) -> FlexClassificationResult:
    """
    Classifica se o pedido é fulfillment usando fulfillment_classifier_service.
    """
    shipping_carrier = _resolve_shipping_carrier(shopee_data, numero_loja)
    fulfillment_flag = (shopee_data or {}).get('fulfillment_flag')

    # Fallback determinístico para Shopee, mesmo sem regra parametrizada no banco.
    if marketplace_slug == 'shopee':
        is_full_carrier = str(shipping_carrier or '').strip().lower() == 'full'
        is_fulfillment_flag = str(fulfillment_flag or '').strip() == 'fulfilled_by_shopee'
        if is_full_carrier or is_fulfillment_flag:
            motivo = (
                f"fallback_shopee carrier={shipping_carrier!r} fulfillment_flag={fulfillment_flag!r} "
                f"→ is_fulfillment=True"
            )
            return FlexClassificationResult(
                is_flex=False,
                is_fulfillment=True,
                modalidade='FULFILLMENT',
                motivo=motivo,
                matched_rule_id=None,
                raw_decision={
                    'source': 'fallback_shopee',
                    'shipping_carrier': shipping_carrier,
                    'fulfillment_flag': fulfillment_flag,
                }
            )

    fields = {
        'fulfillment_flag': fulfillment_flag,
        'shipping_carrier': shipping_carrier,
        'canal_venda_id': canal_venda_id
    }

    if marketplace_slug == 'mercadolivre' and meli_data:
        shipment = meli_data.get('shipment') or {}
        fields['logistic_type'] = shipment.get('logistic_type') or shipment.get('shipping_type')

    res = fulfillment_classifier_service.classify(
        supabase_db,
        fields=fields,
        marketplace_integration_id=marketplace_integration_id,
        log_context={'correlation_id': correlation_id, 'numero_loja': numero_loja}
    )

    return FlexClassificationResult(
        is_flex=False, # Não é flex aqui
        is_fulfillment=res.is_fulfillment,
        modalidade=res.modalidade,
        motivo=res.motivo,
        matched_rule_id=res.matched_rule_id,
        raw_decision={'fields': fields, 'res': res.__dict__}
    )


def _classify_flex(
    shopee_data: dict | None,
    meli_data: dict | None,
    numero_loja: str | None,
    marketplace_slug: str | None,
    is_fulfillment: bool = False,
) -> FlexClassificationResult:
    if is_fulfillment:
        return FlexClassificationResult(
            is_flex=False,
            is_fulfillment=True,
            modalidade='FULFILLMENT',
            motivo='pedido ja classificado como fulfillment, ignorando flex',
        )

    if marketplace_slug == 'mercadolivre':
        if not meli_data:
             return FlexClassificationResult(
                is_flex=False,
                modalidade='STANDARD',
                motivo='meli_data ausente para mercadolivre',
            )
        
        shipment = meli_data.get('shipment') or {}
        shipping_option = shipment.get('shipping_option') or {}
        
        mode = str(shipment.get('mode') or '').lower()
        # MELI returns logistic_type at the root of shipment detail
        shipping_type = str(shipment.get('logistic_type') or shipment.get('shipping_type') or '').lower()
        option_name_raw = str(shipping_option.get('name') or '')
        option_name = _normalize_carrier(option_name_raw) # Reusing existing normalization
        
        logger.info("[flex] MELI comparison: mode=%s, type=%s, option=%s (raw=%s)", 
                    mode, shipping_type, option_name, option_name_raw)
        
        is_meli_flex = (
            mode == "me2" and 
            shipping_type == "self_service" and 
            (option_name == "prioritario" or option_name == "flex")
        )
        
        if is_meli_flex:
            return FlexClassificationResult(
                is_flex=True,
                modalidade='FLEX',
                motivo=f"meli: mode={mode}, type={shipping_type}, option={option_name}",
                raw_decision={'mode': mode, 'shipping_type': shipping_type, 'option_name': option_name}
            )
        else:
             return FlexClassificationResult(
                is_flex=False,
                modalidade='STANDARD',
                motivo=f"meli: nao atende criterios flex (mode={mode}, type={shipping_type}, option={option_name})",
                raw_decision={'mode': mode, 'shipping_type': shipping_type, 'option_name': option_name}
            )

    if marketplace_slug != 'shopee':
        return FlexClassificationResult(
            is_flex=False,
            modalidade='STANDARD',
            motivo=f"plataforma={marketplace_slug!r} nao e shopee ou mercadolivre",
            raw_decision={'marketplace_slug': marketplace_slug, 'numero_loja': numero_loja},
        )

    carrier = _resolve_shipping_carrier(shopee_data, numero_loja)
    normalized_carrier = _normalize_carrier(carrier)

    if not normalized_carrier:
        return FlexClassificationResult(
            is_flex=False,
            modalidade='STANDARD',
            motivo='shipping_carrier ausente',
            raw_decision={'marketplace_slug': marketplace_slug, 'shipping_carrier': carrier},
        )

    if 'entrega rapida' in normalized_carrier:
        return FlexClassificationResult(
            is_flex=True,
            modalidade='FLEX',
            motivo=f"shipping_carrier={carrier!r} contem 'entrega rapida'",
            raw_decision={'marketplace_slug': marketplace_slug, 'shipping_carrier': carrier},
        )

    return FlexClassificationResult(
        is_flex=False,
        modalidade='STANDARD',
        motivo=f"shipping_carrier={carrier!r} nao contem 'entrega rapida'",
        raw_decision={'marketplace_slug': marketplace_slug, 'shipping_carrier': carrier},
    )


def _build_payload_summary(payload: dict) -> dict:
    total = payload.get('total')
    if total is None and isinstance(payload.get('valor'), (int, float, str)):
        total = payload.get('valor')

    situacao = payload.get('situacao') or {}
    loja = payload.get('loja') or {}

    return {
        'bling_id': payload.get('id'),
        'numero': payload.get('numero'),
        'numero_loja': payload.get('numeroLoja'),
        'total': total,
        'situacao_id': situacao.get('id') or payload.get('situacao_id'),
        'loja_id': _extract_bling_loja_id(payload),
    }


def _response_data(response, default=None):
    if response is None:
        return default
    return getattr(response, 'data', default)


def _extract_bling_loja_id(payload: dict | None):
    if not isinstance(payload, dict):
        return None

    loja = payload.get('loja') if isinstance(payload.get('loja'), dict) else {}
    loja_id = loja.get('id')
    if loja_id not in (None, ''):
        return loja_id

    for key in ('loja_id', 'shop_id', 'bling_loja_id'):
        value = payload.get(key)
        if value not in (None, ''):
            return value

    return None


def _get_webhook_processing_link(bling_integration_id: int | None, loja_id: str | None) -> dict | None:
    if not bling_integration_id or not loja_id:
        return None

    rows = (
        supabase_db.table('channel_connections')
        .select('id,process_webhooks,ingest_origin_mode,marketplace_integration_id,marketplace_module_id,channel_id,aggregator_store_id,bling_integration_id')
        .eq('bling_integration_id', bling_integration_id)
        .eq('aggregator_store_id', str(loja_id))
        .eq('is_active', True)
        .limit(1)
        .execute()
        .data
    )
    if rows:
        return rows[0]

    rows = (
        supabase_db.table('erp_marketplace_links')
        .select('id,process_webhooks,ingest_origin_mode,marketplace_integration_id,marketplace_module_id,erp_store_id,erp_integration_id')
        .eq('erp_integration_id', bling_integration_id)
        .eq('erp_store_id', str(loja_id))
        .eq('is_active', True)
        .limit(1)
        .execute()
        .data
    )
    if not rows:
        return None
    link = dict(rows[0])
    link['bling_integration_id'] = link.get('erp_integration_id')
    link['aggregator_store_id'] = link.get('erp_store_id')
    return link


def _preserve_original_bling_fields(detail_payload: dict, original_payload: dict) -> dict:
    """
    O detalhe do Bling e o webhook/listagem podem ter formatos diferentes.
    Nunca descartamos identificadores de origem que vieram no payload original.
    """
    if not isinstance(detail_payload, dict):
        return original_payload

    merged = dict(detail_payload)
    original_loja_id = _extract_bling_loja_id(original_payload)
    detail_loja_id = _extract_bling_loja_id(detail_payload)

    if original_loja_id and not detail_loja_id:
        loja = merged.get('loja') if isinstance(merged.get('loja'), dict) else {}
        merged['loja'] = {**loja, 'id': original_loja_id}

    if original_payload.get('numeroLoja') and not merged.get('numeroLoja'):
        merged['numeroLoja'] = original_payload.get('numeroLoja')
    if original_payload.get('numero') and not merged.get('numero'):
        merged['numero'] = original_payload.get('numero')

    return merged


def _compact(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str, separators=(',', ':'))
    except Exception:
        return str(value)


def _parse_datetime(value):
    return parse_datetime(value)


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


def _resolve_marketplace_timestamps(payload: dict, shopee_data=None, meli_data=None) -> dict:
    order = (meli_data or {}).get("order") if meli_data else {}
    raw_shopee = (shopee_data or {}).get("raw") if shopee_data else {}

    data_compra = None
    data_pagamento = None
    data_envio = None
    payment_source = None

    if shopee_data:
        data_compra = shopee_data.get("create_time") or unix_to_app_iso((raw_shopee or {}).get("create_time"))
        data_pagamento = shopee_data.get("pay_time") or unix_to_app_iso((raw_shopee or {}).get("pay_time"))
        if data_pagamento:
            payment_source = "shopee.pay_time"
        data_envio = shopee_data.get("ship_time") or unix_to_app_iso((raw_shopee or {}).get("ship_time"))
    elif meli_data:
        data_compra = order.get("date_created")
        data_pagamento = _extract_meli_date_approved(order)
        if data_pagamento:
            payment_source = "mercadolivre.payments.date_approved"
        data_envio = order.get("date_closed")

    if not data_compra:
        data_compra = _clean_date(payload.get("data"))

    logger.info(
        "[bling-ingest] marketplace timestamps resolved source=%s payload_id=%s result=%s",
        "shopee" if shopee_data else ("mercadolivre" if meli_data else "bling_only"),
        payload.get("numeroLoja") or payload.get("id"),
        {
            "data_compra_marketplace": data_compra,
            "data_pagamento_marketplace": data_pagamento,
            "data_envio_marketplace": data_envio,
            "payment_time_source": payment_source,
        },
    )

    return {
        "data_compra_marketplace": data_compra,
        "data_pagamento_marketplace": data_pagamento,
        "data_envio_marketplace": data_envio,
        "payment_time_source": payment_source,
    }


def _set_stage_details(ctx: dict, message: str | None, details=None):
    ctx['message'] = message
    ctx['_stage_payload_summary'] = details if isinstance(details, dict) else None


def _consume_stage_payload_summary(ctx: dict):
    stage_payload = ctx.pop('_stage_payload_summary', None)
    return stage_payload or ctx.get('payload_summary')


def _write_ingest_log(
    *,
    correlation_id: str,
    stage: str,
    status: str,
    message: str | None,
    duration_ms: int | None,
    payload_summary: dict | None,
    bling_integration_id: int | None = None,
    numero_loja: str | None = None,
    pedido_id: int | None = None,
):
    row = {
        'correlation_id': correlation_id,
        'bling_integration_id': bling_integration_id,
        'numero_loja': numero_loja,
        'stage': stage,
        'status': status,
        'message': message,
        'duration_ms': duration_ms,
        'payload_summary': payload_summary,
        'pedido_id': pedido_id,
    }

    try:
        supabase_db.table('pedido_ingest_log').insert(row).execute()
    except Exception as e:
        logger.warning("[ingest] Erro ao gravar pedido_ingest_log stage=%s: %s", stage, e)


def _link_pedido_correlation(pedido_id: int | None, correlation_id: str):
    if not pedido_id or not correlation_id:
        return

    try:
        supabase_db.table('entity_correlation_mapping').upsert(
            {
                'entity_type': 'pedido',
                'entity_id': pedido_id,
                'correlation_id': correlation_id,
            },
            on_conflict='entity_type,entity_id,correlation_id',
        ).execute()
    except Exception as e:
        logger.warning(
            "[ingest] Erro ao registrar entity_correlation_mapping pedido_id=%s correlation_id=%s: %s",
            pedido_id,
            correlation_id,
            e,
        )


@contextmanager
def ingest_step(stage: str, ctx: dict):
    """
    Registra uma linha em pedido_ingest_log para cada etapa do pipeline.

    O próprio bloco pode enriquecer `ctx` com `status`, `message`, `pedido_id`
    e `payload_summary`. Em caso de erro, o traceback é persistido em `message`.
    """
    started = perf_counter()
    ctx['status'] = 'success'
    ctx['message'] = None
    try:
        yield ctx
    except Exception as exc:
        ctx['status'] = 'failed'
        ctx['message'] = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        ctx['_failure_logged'] = True
        _write_ingest_log(
            correlation_id=ctx['correlation_id'],
            stage=stage,
            status=ctx['status'],
            message=ctx['message'],
            duration_ms=int((perf_counter() - started) * 1000),
            payload_summary=_consume_stage_payload_summary(ctx),
            bling_integration_id=ctx.get('bling_integration_id'),
            numero_loja=ctx.get('numero_loja'),
            pedido_id=ctx.get('pedido_id'),
        )
        if ctx.get('pedido_id') and not ctx.get('_pedido_mapping_written'):
            _link_pedido_correlation(ctx.get('pedido_id'), ctx['correlation_id'])
            ctx['_pedido_mapping_written'] = True
        raise
    else:
        _write_ingest_log(
            correlation_id=ctx['correlation_id'],
            stage=stage,
            status=ctx.get('status', 'success'),
            message=ctx.get('message'),
            duration_ms=int((perf_counter() - started) * 1000),
            payload_summary=_consume_stage_payload_summary(ctx),
            bling_integration_id=ctx.get('bling_integration_id'),
            numero_loja=ctx.get('numero_loja'),
            pedido_id=ctx.get('pedido_id'),
        )
        if ctx.get('pedido_id') and not ctx.get('_pedido_mapping_written'):
            _link_pedido_correlation(ctx.get('pedido_id'), ctx['correlation_id'])
            ctx['_pedido_mapping_written'] = True

def _process_bling_reference_webhook(
    payload: dict,
    original_payload: dict,
    bling_inst: dict,
    processing_link: dict,
    *,
    correlation_id: str,
    webhook_event_id: int | None,
) -> dict:
    """Consumes a Bling webhook only to bind ERP identity to a direct marketplace order."""
    reference = _preserve_original_bling_fields(payload or {}, original_payload or {})
    if reference.get("id") and (
        not reference.get("numero") or not reference.get("numeroLoja")
    ):
        try:
            detail = _fetch_bling_order_detail(bling_inst, reference["id"], require_materialization_fields=False)
            reference = _preserve_original_bling_fields(detail, reference)
        except BlingDetailUnavailableError as exc:
            logger.warning(
                "[bling-reference] detail unavailable integration_id=%s bling_id=%s: %s",
                bling_inst.get("id"),
                reference.get("id"),
                exc,
            )
            return {
                "status": "error",
                "event_status": "reference_pending",
                "error_type": getattr(exc, "error_type", "bling_detail_unavailable"),
                "retryable": True,
                "retry_after": getattr(exc, "retry_after", None),
                "message": str(exc),
                "correlation_id": correlation_id,
            }

    bling_id = reference.get("id")
    bling_number = str(reference.get("numero") or "").strip()
    store_id = str(_extract_bling_loja_id(reference) or "").strip()
    marketplace_order_id = str(reference.get("numeroLoja") or "").strip()
    marketplace_module_id = processing_link.get("marketplace_module_id")
    if not marketplace_module_id:
        marketplace_module_id = canonical_order_repository.resolve_module_id(
            processing_link.get("marketplace_integration_id")
        )

    ref_payload = {
        "mode": "reference_only",
        "correlation_id": correlation_id,
        "webhook_event_id": webhook_event_id,
        "bling_integration_id": bling_inst.get("id"),
        "bling_loja_id": store_id or None,
        "bling_order_id": bling_id,
        "bling_order_number": bling_number or None,
        "numeroLoja": marketplace_order_id or None,
        "marketplace_module_id": marketplace_module_id,
    }

    if not bling_id or not bling_number or not marketplace_order_id:
        canonical_order_repository.defer_unresolved_erp_order(
            erp_integration_id=bling_inst.get("id"),
            erp_store_id=store_id or None,
            erp_order_id=bling_id,
            erp_order_number=bling_number or None,
            marketplace_order_id=marketplace_order_id or None,
            marketplace_module_id=marketplace_module_id,
            payload=ref_payload,
            reason="direct_marketplace_reference",
        )
        return {
            "status": "success",
            "event_status": "reference_ignored_invalid",
            "resolution_status": "reference_ignored_invalid",
            "retryable": False,
            "message": "Webhook Bling sem numeroLoja, id ou numero completo",
            "correlation_id": correlation_id,
        }

    if not marketplace_module_id:
        canonical_order_repository.defer_unresolved_erp_order(
            erp_integration_id=bling_inst.get("id"),
            erp_store_id=store_id or None,
            erp_order_id=bling_id,
            erp_order_number=bling_number,
            marketplace_order_id=marketplace_order_id,
            payload=ref_payload,
            reason="direct_marketplace_reference",
        )
        return {
            "status": "success",
            "event_status": "reference_pending",
            "resolution_status": "reference_pending",
            "retryable": False,
            "message": "Vinculo marketplace da conta Bling ainda nao foi resolvido",
            "correlation_id": correlation_id,
        }

    rows = (
        supabase_db.table("pedidos")
        .select(
            "id,erp_integration_id,erp_store_id,erp_order_id,erp_order_number,"
            "bling_integration_id,bling_loja_id,bling_order_id,bling_order_number"
        )
        .eq("marketplace_module_id", marketplace_module_id)
        .eq("marketplace_order_id", marketplace_order_id)
        .limit(2)
        .execute()
        .data
        or []
    )

    if not rows:
        canonical_order_repository.defer_unresolved_erp_order(
            erp_integration_id=bling_inst.get("id"),
            erp_store_id=store_id,
            erp_order_id=bling_id,
            erp_order_number=bling_number,
            marketplace_order_id=marketplace_order_id,
            marketplace_module_id=marketplace_module_id,
            payload=ref_payload,
            reason="direct_marketplace_reference",
        )
        return {
            "status": "success",
            "event_status": "reference_pending",
            "resolution_status": "reference_pending",
            "retryable": False,
            "message": "Pedido marketplace ainda nao materializado",
            "correlation_id": correlation_id,
        }

    pedido = rows[0]
    existing_integration = pedido.get("erp_integration_id") or pedido.get("bling_integration_id")
    existing_order_id = pedido.get("erp_order_id") or pedido.get("bling_order_id")
    existing_number = pedido.get("erp_order_number") or pedido.get("bling_order_number")
    if (
        (existing_integration and str(existing_integration) != str(bling_inst.get("id")))
        or (existing_order_id and str(existing_order_id) != str(bling_id))
        or (existing_number and str(existing_number) != bling_number)
    ):
        canonical_order_repository.defer_unresolved_erp_order(
            erp_integration_id=bling_inst.get("id"),
            erp_store_id=store_id,
            erp_order_id=bling_id,
            erp_order_number=bling_number,
            marketplace_order_id=marketplace_order_id,
            marketplace_module_id=marketplace_module_id,
            payload={**ref_payload, "existing_reference": pedido},
            reason="direct_marketplace_reference_conflict",
        )
        return {
            "status": "success",
            "event_status": "reference_conflict",
            "resolution_status": "reference_conflict",
            "retryable": False,
            "pedido_id": pedido.get("id"),
            "message": "Pedido ja possui referencia ERP diferente",
            "correlation_id": correlation_id,
        }

    supabase_db.rpc("enrich_order_erp_reference", {
        "p_pedido_id": pedido["id"],
        "p_erp_integration_id": bling_inst.get("id"),
        "p_erp_store_id": store_id or None,
        "p_erp_order_id": bling_id,
        "p_erp_order_number": bling_number,
        "p_marketplace_order_id": marketplace_order_id,
    }).execute()
    return {
        "status": "success",
        "event_status": "reference_applied",
        "resolution_status": "reference_applied",
        "retryable": False,
        "pedido_id": pedido.get("id"),
        "bling_integration_id": bling_inst.get("id"),
        "bling_loja_id": store_id,
        "bling_order_id": bling_id,
        "bling_order_number": bling_number,
        "numeroLoja": marketplace_order_id,
        "correlation_id": correlation_id,
    }


def process_webhook(
    payload: dict,
    bling_integration_hint: int | None = None,
    company_id: str | None = None,
    correlation_id: str | None = None,
    webhook_event_id: int | None = None,
) -> dict:
    """
    Pipeline linear, idempotente.
    - payload: corpo do pedido Bling (já buscado da API com detalhes completos).
    - bling_integration_hint: quando o caller já sabe a instância Bling (ex.: webhook
      veio com header de identificação), evita lookup.
    - company_id: ID da empresa Bling do webhook wrapper (usado para resolver instância)
    """
    correlation_id = _start_correlation_id(correlation_id)
    pipeline_started = perf_counter()
    original_payload = dict(payload or {})
    ingest_ctx = {
        'correlation_id': correlation_id,
        'payload_summary': _build_payload_summary(payload),
        'bling_integration_id': bling_integration_hint,
        'numero_loja': payload.get('numeroLoja'),
        'pedido_id': None,
        'webhook_event_id': webhook_event_id,
        '_failure_logged': False,
    }

    _write_ingest_log(
        correlation_id=correlation_id,
        stage='received',
        status='success',
        message=f"processando webhook: {_compact(ingest_ctx['payload_summary'])}",
        duration_ms=0,
        payload_summary=ingest_ctx['payload_summary'],
        bling_integration_id=bling_integration_hint,
        numero_loja=payload.get('numeroLoja'),
    )

    try:
        # 1. Resolver instância Bling
        with ingest_step('resolve_bling_instance', ingest_ctx):
            bling_inst = _resolve_bling_instance(payload, bling_integration_hint, company_id)
            ingest_ctx['bling_integration_id'] = bling_inst['id']
            _set_stage_details(
                ingest_ctx,
                f"identificando bling: resposta {_compact({'bling_integration_id': bling_inst['id'], 'company_id': company_id, 'cnpj': (bling_inst.get('config') or {}).get('cnpj')})}",
                {
                    'bling_integration_id': bling_inst['id'],
                    'company_id': company_id,
                    'cnpj': (bling_inst.get('config') or {}).get('cnpj'),
                },
            )
            logger.info(
                "[ingest] bling_instance resolved id=%s cnpj=%s",
                bling_inst['id'],
                (bling_inst.get('config') or {}).get('cnpj'),
            )

        original_loja_id = str(_extract_bling_loja_id(original_payload) or '')
        if original_loja_id:
            with ingest_step('check_webhook_processing', ingest_ctx):
                processing_link = _get_webhook_processing_link(bling_inst['id'], original_loja_id)
                ingest_origin_mode = (processing_link or {}).get('ingest_origin_mode') or 'erp_bling'
                skip_reason = None
                event_status = 'skipped'
                if processing_link and ingest_origin_mode == 'marketplace_direct':
                    return _process_bling_reference_webhook(
                        payload,
                        original_payload,
                        bling_inst,
                        processing_link,
                        correlation_id=correlation_id,
                        webhook_event_id=webhook_event_id,
                    )
                if processing_link and processing_link.get('process_webhooks') is False:
                    skip_reason = 'process_webhooks=false'

                if skip_reason:
                    ingest_ctx['status'] = 'skipped'
                    message = (
                        f"webhook ignorado: vinculo {processing_link.get('id')} "
                        f"motivo={skip_reason} ingest_origin_mode={ingest_origin_mode} "
                        f"(bling_integration_id={bling_inst['id']}, loja_id={original_loja_id})"
                    )
                    _set_stage_details(
                        ingest_ctx,
                        message,
                        {
                            'channel_connection_id': processing_link.get('id'),
                            'bling_integration_id': bling_inst['id'],
                            'loja_id': original_loja_id,
                            'numero_loja': original_payload.get('numeroLoja'),
                            'process_webhooks': processing_link.get('process_webhooks'),
                            'ingest_origin_mode': ingest_origin_mode,
                            'skip_reason': skip_reason,
                        },
                    )
                    _write_ingest_log(
                        correlation_id=correlation_id,
                        stage='webhook_ignored',
                        status='skipped',
                        message=message,
                        duration_ms=int((perf_counter() - pipeline_started) * 1000),
                        payload_summary=ingest_ctx.get('payload_summary'),
                        bling_integration_id=bling_inst['id'],
                        numero_loja=original_payload.get('numeroLoja'),
                        pedido_id=None,
                    )
                    _update_webhook_event(
                        webhook_event_id,
                        bling_id=ingest_ctx.get('payload_summary', {}).get('bling_id'),
                        numero_loja=original_payload.get('numeroLoja'),
                        last_status=event_status,
                        last_attempt_at=get_now_iso(),
                    )
                    logger.info("[ingest] %s", message)
                    return {
                        'status': 'skipped',
                        'message': message,
                        'correlation_id': correlation_id,
                        'bling_integration_id': bling_inst['id'],
                        'numero_loja': original_payload.get('numeroLoja'),
                        'event_status': event_status,
                        'skip_reason': skip_reason,
                    }

        # 2. Buscar detalhe completo do pedido na API do Bling
        # O webhook é apenas um aviso de alteração, precisamos dos dados atualizados
        with ingest_step('fetch_bling', ingest_ctx):
            if payload.get('id'):
                # Deixar o erro subir para o consumidor (Redis) para retry
                detalhe = _fetch_bling_order_detail(bling_inst, payload['id'])
                payload = _preserve_original_bling_fields(detalhe, original_payload)
                ingest_ctx['payload_summary'] = _build_payload_summary(payload)
                _set_stage_details(
                    ingest_ctx,
                    f"buscando bling: resposta {_compact(ingest_ctx['payload_summary'])}",
                    ingest_ctx['payload_summary'],
                )
                logger.info("[ingest] payload Bling atualizado via /pedidos/vendas/%s", payload.get('id'))

            detalhe_disponivel = bool(payload.get('itens')) or bool(payload.get('contato'))
            if not detalhe_disponivel:
                raise BlingDetailUnavailableError(
                    f"detalhe Bling indisponível (sem itens ou contato) para id={ingest_ctx['payload_summary'].get('bling_id')} "
                    f"(inst={bling_inst['id']})"
                )

        # 3. UPSERT pedidos_bling (espelho do payload)
        with ingest_step('upsert_bling', ingest_ctx):
            pedido_bling_id = _upsert_pedido_bling(payload, bling_inst['id'])
            _set_stage_details(
                ingest_ctx,
                f"salvando espelho bling: resposta {_compact({'pedido_bling_id': pedido_bling_id, 'bling_id': payload.get('id'), 'bling_integration_id': bling_inst['id']})}",
                {
                    'pedido_bling_id': pedido_bling_id,
                    'bling_id': payload.get('id'),
                    'bling_integration_id': bling_inst['id'],
                },
            )
            logger.info("[ingest] pedidos_bling upserted id=%s", pedido_bling_id)

        # 4. Resolver instância marketplace pela loja_id
        loja_id = str(_extract_bling_loja_id(payload) or '')
        marketplace_inst, pedido_shopee_id, shopee_data = None, None, None
        pedido_mercadolivre_id, meli_data = None, None
        
        if loja_id:
            with ingest_step('resolve_marketplace', ingest_ctx):
                try:
                    marketplace_inst = _resolve_marketplace_instance(loja_id, bling_inst['id'])
                except Exception as e:
                    ingest_ctx['status'] = 'warning'
                    ingest_ctx['message'] = f"falha ao resolver marketplace para loja_id={loja_id}: {e}"
                    logger.warning(
                        "[ingest] falha ao resolver marketplace para loja_id=%s: %s — seguindo só com dados do Bling",
                        loja_id, e, exc_info=True,
                    )
                    marketplace_inst = None

                if marketplace_inst:
                    logger.info("[ingest] marketplace resolved id=%s plataforma=%s nome=%s",
                                marketplace_inst['id'],
                                marketplace_inst.get('plataforma_slug'),
                                marketplace_inst.get('instance_name'))

                    # 5. Enriquecimento via API marketplace
                    plataforma = marketplace_inst.get('plataforma_slug')
                    
                    if plataforma == 'shopee':
                        with ingest_step('enrich_shopee', ingest_ctx):
                            try:
                                shopee_data = _fetch_shopee_detail(
                                    marketplace_inst,
                                    payload.get('numeroLoja'),
                                )
                                if shopee_data and not shopee_data.get('error'):
                                    pedido_shopee_id = _upsert_pedido_shopee(
                                        shopee_data,
                                        marketplace_integration_id=marketplace_inst['id'],
                                    )
                                else:
                                    ingest_ctx['status'] = 'warning'
                                    ingest_ctx['message'] = (
                                        f"enriquecimento Shopee retornou erro para order_sn={payload.get('numeroLoja')}: "
                                        f"{(shopee_data or {}).get('error')}"
                                    )
                                    logger.warning(
                                        "[ingest] enriquecimento Shopee retornou erro para order_sn=%s: %s — seguindo só com dados do Bling",
                                        payload.get('numeroLoja'),
                                        (shopee_data or {}).get('error'),
                                    )
                                    shopee_data = None
                                    pedido_shopee_id = None
                            except Exception as e:
                                ingest_ctx['status'] = 'warning'
                                ingest_ctx['message'] = f"enriquecimento Shopee falhou para order_sn={payload.get('numeroLoja')}: {e}"
                                logger.warning(
                                    "[ingest] enriquecimento Shopee falhou para order_sn=%s: %s — seguindo só com dados do Bling",
                                    payload.get('numeroLoja'),
                                    e,
                                    exc_info=True,
                                )
                                shopee_data, pedido_shopee_id = None, None
                    
                    elif plataforma == 'mercadolivre':
                        with ingest_step('enrich_mercadolivre', ingest_ctx):
                            try:
                                meli_data = _fetch_meli_detail(
                                    marketplace_inst,
                                    payload.get('numeroLoja'),
                                )
                                if meli_data and not meli_data.get('error'):
                                    pedido_mercadolivre_id = _upsert_pedido_meli(
                                        meli_data,
                                        marketplace_integration_id=marketplace_inst['id'],
                                    )
                                else:
                                    ingest_ctx['status'] = 'warning'
                                    ingest_ctx['message'] = (
                                        f"enriquecimento MELI retornou erro para order_id={payload.get('numeroLoja')}: "
                                        f"{(meli_data or {}).get('error')}"
                                    )
                                    logger.warning(
                                        "[ingest] enriquecimento MELI retornou erro para order_id=%s: %s — seguindo só com dados do Bling",
                                        payload.get('numeroLoja'),
                                        (meli_data or {}).get('error'),
                                    )
                                    meli_data = None
                                    pedido_mercadolivre_id = None
                            except Exception as e:
                                ingest_ctx['status'] = 'warning'
                                ingest_ctx['message'] = f"enriquecimento MELI falhou para order_id={payload.get('numeroLoja')}: {e}"
                                logger.warning(
                                    "[ingest] enriquecimento MELI falhou para order_id=%s: %s — seguindo só com dados do Bling",
                                    payload.get('numeroLoja'),
                                    e,
                                    exc_info=True,
                                )
                                meli_data, pedido_mercadolivre_id = None, None

                else:
                    ingest_ctx['status'] = 'warning'
                    ingest_ctx['message'] = f"loja_id={loja_id} sem instância marketplace mapeada"
                    logger.warning("[ingest] loja_id=%s sem instância marketplace mapeada", loja_id)

        # 6. Resolver canal_venda_id pela channel_connection ativa
        with ingest_step('resolve_canal_venda', ingest_ctx):
            canal_venda_id = _resolve_canal_venda_id(
                (marketplace_inst or {}).get('id'),
                bling_inst['id'],
                loja_id
            )

        # 6.5. Classificar Fulfillment
        with ingest_step('classify_fulfillment', ingest_ctx):
            fulfillment = _classify_fulfillment(
                shopee_data,
                meli_data,
                payload.get('numeroLoja'),
                (marketplace_inst or {}).get('plataforma_slug'),
                canal_venda_id=canal_venda_id,
                marketplace_integration_id=(marketplace_inst or {}).get('id'),
                correlation_id=correlation_id,
            )
            ingest_ctx['fulfillment_motivo'] = fulfillment.motivo

        # 7. Classificar Flex
        with ingest_step('classify_flex', ingest_ctx):
            flex = _classify_flex(
                shopee_data,
                meli_data,
                payload.get('numeroLoja'),
                (marketplace_inst or {}).get('plataforma_slug'),
                is_fulfillment=fulfillment.is_fulfillment,
            )
            ingest_ctx['flex_motivo'] = flex.motivo

        # 8. UPSERT pedidos
        with ingest_step('upsert_pedido', ingest_ctx):
            pedido_id = _upsert_pedido_master(
                payload,
                pedido_bling_id=pedido_bling_id,
                pedido_shopee_id=pedido_shopee_id,
                pedido_mercadolivre_id=pedido_mercadolivre_id,
                bling_integration_id=bling_inst['id'],
                marketplace_integration_id=(marketplace_inst or {}).get('id'),
                canal_venda_id=canal_venda_id,
                is_flex=flex.is_flex,
                is_fulfillment=fulfillment.is_fulfillment,
                modalidade=fulfillment.modalidade if fulfillment.is_fulfillment else flex.modalidade,
                shopee_data=shopee_data,
                meli_data=meli_data,
            )
            ingest_ctx['pedido_id'] = pedido_id
            logger.info("[ingest] pedido upserted id=%s is_flex=%s is_fulfillment=%s modalidade=%s",
                        pedido_id, flex.is_flex, fulfillment.is_fulfillment, 
                        fulfillment.modalidade if fulfillment.is_fulfillment else flex.modalidade)
            _update_webhook_event(
                webhook_event_id,
                pedido_id=pedido_id,
                bling_id=ingest_ctx['payload_summary'].get('bling_id'),
                numero_loja=payload.get('numeroLoja'),
            )

        # 8.5. Detectar e marcar pedido como personalizado
        with ingest_step('detect_personalizado', ingest_ctx):
            try:
                _detect_and_mark_personalized(payload, pedido_id)
            except Exception as e:
                ingest_ctx['status'] = 'warning'
                ingest_ctx['message'] = f"detecção de personalizado falhou pedido_id={pedido_id}: {e}"
                logger.warning(
                    "[ingest] detecção de personalizado falhou pedido_id=%s: %s",
                    pedido_id, e, exc_info=True,
                )

        # 9. Auditoria
        with ingest_step('upsert_auditoria', ingest_ctx):
            _log_ingest(
                pedido_id=pedido_id,
                bling_id=ingest_ctx['payload_summary']['bling_id'],
                marketplace_integration_id=(marketplace_inst or {}).get('id'),
                is_flex=flex.is_flex,
                flex_motivo=flex.motivo,
                is_fulfillment=fulfillment.is_fulfillment,
                fulfillment_motivo=fulfillment.motivo,
                matched_rule_id=flex.matched_rule_id if hasattr(flex, 'matched_rule_id') else None,
                raw_decision={
                    'flex': flex.raw_decision if hasattr(flex, 'raw_decision') else None,
                    'fulfillment': fulfillment.raw_decision if hasattr(fulfillment, 'raw_decision') else None,
                },
            )

        detail_unavailable = bool(ingest_ctx.get('detail_unavailable'))
        final_status = 'failed' if detail_unavailable else 'success'
        final_stage_status = 'warning' if detail_unavailable else 'success'
        final_message = (
            f"pedido_id={pedido_id}; detalhe Bling indisponivel para reprocessamento posterior: "
            f"{ingest_ctx.get('detail_unavailable_message')}"
            if detail_unavailable
            else f"pedido_id={pedido_id}"
        )

        _write_ingest_log(
            correlation_id=correlation_id,
            stage='done',
            status=final_stage_status,
            message=final_message,
            duration_ms=int((perf_counter() - pipeline_started) * 1000),
            payload_summary=ingest_ctx['payload_summary'],
            bling_integration_id=ingest_ctx.get('bling_integration_id'),
            numero_loja=payload.get('numeroLoja'),
            pedido_id=pedido_id,
        )

        logger.info("[ingest] done %s", {'correlation_id': correlation_id, **ingest_ctx['payload_summary']})
        _update_webhook_event(
            webhook_event_id,
            pedido_id=pedido_id,
            bling_id=ingest_ctx['payload_summary'].get('bling_id'),
            numero_loja=payload.get('numeroLoja'),
            last_status=final_status,
            last_attempt_at=get_now_iso(),
        )
        return {
            'status': 'error' if detail_unavailable else 'success',
            'message': final_message,
            'pedido_id': pedido_id,
            'is_flex': flex.is_flex,
            'flex_motivo': flex.motivo,
            'correlation_id': correlation_id,
            'error_type': 'bling_detail_unavailable' if detail_unavailable else None,
        }
    except BlingDetailUnavailableError:
        _update_webhook_event(
            webhook_event_id,
            pedido_id=ingest_ctx.get('pedido_id'),
            bling_id=ingest_ctx.get('payload_summary', {}).get('bling_id'),
            numero_loja=ingest_ctx.get('numero_loja'),
            last_status='failed',
            last_attempt_at=get_now_iso(),
        )
        raise
    except Exception as e:
        logger.error("[ingest] Erro no processamento do webhook: %s", e, exc_info=True)
        if not ingest_ctx.get('_failure_logged'):
            _write_ingest_log(
                correlation_id=correlation_id,
                stage='failed',
                status='failed',
                message=''.join(traceback.format_exception(type(e), e, e.__traceback__)),
                duration_ms=int((perf_counter() - pipeline_started) * 1000),
                payload_summary=ingest_ctx.get('payload_summary'),
                bling_integration_id=ingest_ctx.get('bling_integration_id'),
                numero_loja=ingest_ctx.get('numero_loja'),
                pedido_id=ingest_ctx.get('pedido_id'),
            )
        _update_webhook_event(
            webhook_event_id,
            pedido_id=ingest_ctx.get('pedido_id'),
            bling_id=ingest_ctx.get('payload_summary', {}).get('bling_id'),
            numero_loja=ingest_ctx.get('numero_loja'),
            last_status='failed',
            last_attempt_at=get_now_iso(),
        )
        return {
            'status': 'error',
            'message': str(e),
            'pedido_id': ingest_ctx.get('pedido_id'),
            'correlation_id': correlation_id,
            'error_type': 'processing_error',
        }


# ---------- helpers ----------

def _fetch_bling_order_detail(bling_inst: dict, bling_order_id, *, require_materialization_fields: bool = True) -> dict:
    """Busca pedido detalhado no Bling e falha de forma explícita se não houver detalhe."""
    if not bling_order_id:
        raise BlingDetailUnavailableError(
            f"sem id para fetch detalhe Bling (inst={bling_inst.get('id')})"
        )

    from nistiprint_shared.services.bling.bling_client import (
        BlingClient,
        BlingRateLimitedError,
        BlingTransientHTTPError,
    )

    try:
        client = BlingClient.create_client_for_integration_id(int(bling_inst['id']))
        detalhe = client.get_order(bling_order_id)
    except BlingRateLimitedError as e:
        logger.warning(
            "[ingest] rate limit ao buscar detalhe Bling id=%s inst=%s retry_after=%s",
            bling_order_id,
            bling_inst.get('id'),
            e.retry_after,
        )
        raise BlingDetailUnavailableError(
            f"rate limit ao buscar detalhe Bling id={bling_order_id} inst={bling_inst.get('id')}",
            error_type='rate_limited',
            retry_after=e.retry_after,
        ) from e
    except BlingTransientHTTPError as e:
        logger.warning(
            "[ingest] Bling temporariamente indisponivel id=%s inst=%s retry_after=%s",
            bling_order_id,
            bling_inst.get('id'),
            e.retry_after,
        )
        raise BlingDetailUnavailableError(
            f"falha temporaria ao buscar detalhe Bling id={bling_order_id} inst={bling_inst.get('id')}",
            error_type='transient_http_error',
            retry_after=e.retry_after,
        ) from e
    except Exception as e:
        logger.error(
            "[ingest] falha fetch detalhe Bling id=%s inst=%s: %s",
            bling_order_id,
            bling_inst.get('id'),
            e,
            exc_info=True,
        )
        raise BlingDetailUnavailableError(
            f"falha ao buscar detalhe Bling id={bling_order_id} inst={bling_inst.get('id')}"
        ) from e

    if not detalhe or (require_materialization_fields and not (detalhe.get('itens') or detalhe.get('contato'))):
        raise BlingDetailUnavailableError(
            f"detalhe Bling indisponível para id={bling_order_id} inst={bling_inst.get('id')}"
        )

    return detalhe

def _resolve_bling_instance(payload, hint, company_id=None):
    if hint:
        response = (
            supabase_db.table('installed_integrations')
            .select('*')
            .eq('id', hint)
            .eq('module_id', 'bling')
            .eq('is_active', True)
            .maybe_single()
            .execute()
        )
        row = _response_data(response)
        if row:
            return row
        raise LookupError(f"Instancia Bling ativa nao encontrada para id={hint}")
    
    # Try company_id first (from webhook wrapper)
    if company_id:
        cached = integration_resolution_service.resolve_bling_by_company_id(company_id)
        if cached:
            return cached

        response = supabase_db.rpc(
            'find_bling_integration_by_company_id',
            {'p_company_id': company_id}
        ).execute()
        rows = _response_data(response, []) or []
        if rows:
            if len(rows) > 1:
                ids = [row.get('id') for row in rows]
                raise LookupError(f"company_id={company_id} resolveu multiplas contas Bling: {ids}")
            return rows[0]
    
    # Fallback to CNPJ from payload
    cnpj = (
        (payload.get('intermediador') or {}).get('cnpj')
        or (payload.get('loja') or {}).get('cnpj')
        or (payload.get('empresa') or {}).get('cnpj')
        or payload.get('cnpj')
    )
    if not cnpj:
        raise ValueError("Não foi possível identificar instância Bling: CNPJ ausente e company_id não fornecido")
    cached = integration_resolution_service.resolve_bling_by_cnpj(cnpj)
    if cached:
        return cached

    response = supabase_db.rpc('find_bling_integration_by_cnpj', {'p_cnpj': cnpj}).execute()
    rows = _response_data(response, []) or []
    if not rows:
        raise LookupError(f"Nenhuma installed_integration Bling ativa para CNPJ={cnpj}")
    if len(rows) > 1:
        ids = [row.get('id') for row in rows]
        raise LookupError(f"CNPJ={cnpj} resolveu multiplas contas Bling: {ids}")
    return rows[0]

def _resolve_marketplace_instance(loja_id: str, bling_integration_id: int | None = None):
    loja_id = str(loja_id)
    cached = integration_resolution_service.resolve_marketplace_by_shop_id(
        loja_id,
        bling_integration_id=bling_integration_id,
    )
    if cached:
        return cached

    rows = supabase_db.rpc('find_marketplace_by_bling_loja',
                           {'p_loja_id': loja_id, 'p_bling_integration_id': bling_integration_id}).execute().data
    if rows:
        inst = rows[0]
        # Anexar slug da plataforma para conveniencia do caller
        mod = supabase_db.table('integration_modules') \
            .select('slug').eq('id', inst['module_id']).single().execute().data
        inst['plataforma_slug'] = (mod or {}).get('slug')
        return inst

    # Fallback por vinculo ERP, inclusive quando nao existe integracao direta instalada.
    try:
        link_query = (supabase_db.table("erp_marketplace_links")
            .select("marketplace_module_id,marketplace_integration_id")
            .eq("erp_integration_id", bling_integration_id)
            .eq("erp_store_id", loja_id)
            .eq("is_active", True)
            .limit(1).execute().data or [])
        if link_query and link_query[0].get("marketplace_module_id"):
            module_id = link_query[0]["marketplace_module_id"]
            mod = supabase_db.table("integration_modules").select("id,slug,name").eq("id", module_id).maybe_single().execute().data or {}
            return {
                "id": link_query[0].get("marketplace_integration_id"),
                "module_id": module_id,
                "plataforma_slug": mod.get("slug") or module_id,
                "instance_name": mod.get("name") or module_id,
            }
    except Exception as e:
        logger.warning("[ingest] Erro no fallback ERP marketplace loja_id=%s: %s", loja_id, e)
    # Fallback: aceitar mapeamento por marketplace_module_id mesmo sem
    # installed_integration de marketplace.
    try:
        cc = supabase_db.table('channel_connections') \
            .select('marketplace_module_id') \
            .eq('aggregator_store_id', loja_id) \
            .eq('is_active', True)
        if bling_integration_id:
            cc = cc.eq('bling_integration_id', bling_integration_id)
        cc = cc.limit(1).execute().data
        if not cc:
            return None

        module_id = (cc[0] or {}).get('marketplace_module_id')
        if not module_id:
            return None

        mod = supabase_db.table('integration_modules') \
            .select('id,slug,name') \
            .eq('id', module_id) \
            .maybe_single().execute().data or {}
        plataforma_slug = mod.get('slug') or module_id
        module_name = mod.get('name') or plataforma_slug

        return {
            'id': None,
            'module_id': module_id,
            'instance_name': f"{module_name} (module-link)",
            'plataforma_slug': plataforma_slug,
        }
    except Exception as e:
        logger.warning('[ingest] Erro no fallback marketplace por module_id loja_id=%s: %s', loja_id, e)
        return None

def _resolve_canal_venda_id(marketplace_integration_id, bling_integration_id, loja_id):
    """
    Resolve canal_venda_id pela channel_connection ativa.
    Fallback para canais_venda legado se necessário.
    """
    try:
        if loja_id and bling_integration_id:
            cc = supabase_db.table('channel_connections') \
                .select('channel_id') \
                .eq('aggregator_store_id', str(loja_id)) \
                .eq('bling_integration_id', bling_integration_id) \
                .eq('is_active', True) \
                .limit(1).execute().data
            if cc:
                return cc[0].get('channel_id')

        if not marketplace_integration_id:
            return None

        # Buscar channel_connection ativa
        cc = supabase_db.table('channel_connections') \
            .select('channel_id') \
            .eq('marketplace_integration_id', marketplace_integration_id) \
            .eq('is_active', True) \
            .limit(1).execute().data
        if cc:
            return cc[0].get('channel_id')

        # Fallback: buscar na tabela canais_venda (legado)
        if loja_id:
            cv = supabase_db.table('canais_venda') \
                .select('id') \
                .eq('conta_bling_id', str(loja_id)) \
                .limit(1).execute().data
            if cv:
                return cv[0].get('id')
    except Exception as e:
        logger.warning("[ingest] Erro ao resolver canal_venda_id: %s", e)

    return None


def _log_ingest(pedido_id, bling_id, marketplace_integration_id,
                is_flex, flex_motivo, is_fulfillment=False, fulfillment_motivo=None,
                matched_rule_id=None, raw_decision=None):
    """Retorna o resumo da auditoria para ser anexado ao log estruturado."""
    return {
        'pedido_id': pedido_id,
        'bling_id': bling_id,
        'marketplace_integration_id': marketplace_integration_id,
        'is_flex': is_flex,
        'flex_motivo': flex_motivo,
        'is_fulfillment': is_fulfillment,
        'fulfillment_motivo': fulfillment_motivo,
        'matched_rule_id': matched_rule_id,
        'raw_decision': raw_decision,
    }

def _detect_and_mark_personalized(payload: dict, pedido_id: int | None = None):
    """
    Classifica personalizado apenas por descricao/nome do item.

    Evita buscar cadastro de produto no Bling, porque IDs de produto sao
    especificos de cada conta Bling no ingest multi-conta.
    """
    return persist_classification_from_payload(payload, pedido_id, log=logger)

def _item_name_indicates_personalized(item: dict | None) -> bool:
    return item_indicates_personalized(item)

def _fetch_shopee_detail(marketplace_inst, order_sn):
    integration = credential_resolver_service.hydrate_integration(
        dict(marketplace_inst or {})
    )
    logger.info("[fetch_shopee_detail] Chamando driver com order_sn=%s, integration config keys=%s", order_sn, integration.keys())
    result = shopee_driver.get_order_detail(integration, [order_sn])
    logger.info("[fetch_shopee_detail] Resultado do driver: %s", result)
    return result

def _fetch_meli_detail(marketplace_inst, order_sn):
    integration = credential_resolver_service.hydrate_integration(
        dict(marketplace_inst or {})
    )
    logger.info("[fetch_meli_detail] Chamando driver com order_sn=%s", order_sn)
    
    # 1. Obter detalhes do pedido
    order_data = meli_driver.get_order_detail(integration, [order_sn])
    if not order_data or order_data.get('error'):
        return order_data
    
    # 2. Obter detalhes do envio (se houver shipment.id)
    shipping = order_data.get('shipping') or {}
    shipment_id = shipping.get('id')
    
    shipment_data = {}
    sla_data = {}
    
    if shipment_id:
        shipment_data = meli_driver.get_shipment(integration, str(shipment_id))
        sla_data = meli_driver.get_shipment_sla(integration, str(shipment_id))
    
    return {
        'order': order_data,
        'shipment': shipment_data,
        'sla': sla_data,
        'external_id': order_sn
    }

def _upsert_pedido_meli(meli_data: dict, marketplace_integration_id: int) -> int:
    """
    Upsert pedido na tabela pedidos_mercadolivre.
    """
    if not meli_data or meli_data.get('error'):
        logger.error("[upsert_pedido_meli] Dados inválidos ou erro: %s", meli_data)
        raise ValueError(f"Dados do Mercado Livre inválidos: {meli_data.get('error') if meli_data else 'None'}")

    order = meli_data.get('order') or {}
    shipment = meli_data.get('shipment') or {}
    sla = (meli_data.get('sla') or [])[0] if isinstance(meli_data.get('sla'), list) and meli_data.get('sla') else {}
    
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
        'expected_date':     sla.get('expected_date'),
        'date_approved':     _extract_meli_date_approved(order),
        'buyer_nickname':    (order.get('buyer') or {}).get('nickname'),
        'raw_order':         order,
        'raw_shipment':      shipment,
        'raw_sla':           meli_data.get('sla'),
        'marketplace_integration_id': marketplace_integration_id,
        'updated_at':        get_now_iso(),
    }
    
    if not row.get('codigo_pedido'):
        raise ValueError("codigo_pedido (external_id) está null - não é possível upsert pedidos_mercadolivre")
    
    res = supabase_db.table('pedidos_mercadolivre') \
        .upsert(row, on_conflict='codigo_pedido').execute()
    return res.data[0]['id']

def _resolve_shipping_carrier(shopee_data, numero_loja):
    """
    Resolve o shipping_carrier preferindo o enrichment atual e caindo para o
    espelho persistido em pedidos_shopee quando necessário.
    """
    if shopee_data:
        carrier = shopee_data.get('shipping_carrier')
        if carrier:
            return carrier

        for package in shopee_data.get('package_list') or []:
            carrier = package.get('shipping_carrier')
            if carrier:
                return carrier

    if not numero_loja:
        return None

    try:
        rows = supabase_db.table('pedidos_shopee') \
            .select('shipping_carrier, package_list') \
            .eq('codigo_pedido', str(numero_loja)) \
            .limit(1) \
            .execute() \
            .data

        if rows:
            row = rows[0]
            if row.get('shipping_carrier'):
                return row['shipping_carrier']

            for package in row.get('package_list') or []:
                carrier = package.get('shipping_carrier')
                if carrier:
                    return carrier
    except Exception as e:
        logger.warning(
            "[ingest] falha ao resolver shipping_carrier fallback para order_sn=%s: %s",
            numero_loja, e, exc_info=True,
        )

    return None

def _upsert_pedido_bling(payload, bling_integration_id):
    bling_id = payload.get('id')
    if not bling_id:
        return None

    loja_id = _extract_bling_loja_id(payload)
    
    data = {
        'bling_id': bling_id,
        'numero_pedido': str(payload.get('numero', '')),
        'numero_loja': payload.get('numeroLoja'),
        'situacao_id': payload.get('situacao', {}).get('id'),
        'situacao_valor': payload.get('situacao', {}).get('valor'),
        'contato': payload.get('contato'),
        'itens': payload.get('itens'),
        'transporte': payload.get('transporte'),
        'intermediador_cnpj': payload.get('intermediador', {}).get('cnpj'),
        'raw_payload': payload,
        'bling_integration_id': bling_integration_id,
        'updated_at': get_now_iso()
    }

    if loja_id not in (None, ''):
        data['loja_id'] = loja_id

    existing = _find_existing_pedido_bling_for_update(
        bling_id=bling_id,
        bling_integration_id=bling_integration_id,
    )
    if existing:
        res = supabase_db.table('pedidos_bling').update(data).eq('id', existing['id']).execute()
        return res.data[0]['id'] if res.data else existing['id']
    
    res = supabase_db.table('pedidos_bling').upsert(
        data,
        on_conflict='bling_integration_id,bling_id',
    ).execute()
    return res.data[0]['id'] if res.data else None


def _find_existing_pedido_bling_for_update(bling_id, bling_integration_id):
    """
    Reaproveita espelhos legados antes do modelo multi-Bling.
    A busca por numero_pedido foi removida porque numero do Bling nao e unico
    entre contas diferentes.
    """
    filters = [
        ('bling_integration_id', bling_integration_id, 'bling_id', bling_id),
        ('bling_integration_id', None, 'bling_id', bling_id),
    ]

    for first_key, first_value, second_key, second_value in filters:
        query = supabase_db.table('pedidos_bling').select('id')
        if first_value is None:
            query = query.is_(first_key, 'null')
        else:
            query = query.eq(first_key, first_value)
        rows = query.eq(second_key, second_value).limit(1).execute().data
        if rows:
            return rows[0]

    return None

def _upsert_pedido_shopee(shopee_data: dict, marketplace_integration_id: int) -> int:
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
    
    if not row.get('codigo_pedido'):
        logger.error("[upsert_pedido_shopee] codigo_pedido está null - shopee_data: %s", shopee_data)
        raise ValueError("codigo_pedido (external_id) está null - não é possível upsert pedidos_shopee")
    
    res = supabase_db.table('pedidos_shopee') \
        .upsert(row, on_conflict='codigo_pedido').execute()
    return res.data[0]['id']

def _upsert_pedido_master(payload, *,
                         pedido_bling_id, pedido_shopee_id, pedido_mercadolivre_id=None,
                         bling_integration_id, marketplace_integration_id,
                         canal_venda_id,           # derivado de channel_connections
                         is_flex, is_fulfillment=False, modalidade,
                         shopee_data=None, meli_data=None,
                         ingest_source='bling',
                         ):
    """
    Upsert pedido na tabela pedidos (tabela unificada).
    Popula TODOS os campos que a tela precisa exibir.

    Mapeamento de campos:
    - Bling numeroLoja = Marketplace order code (ex: Shopee order_sn)
    - No banco: codigo_pedido_externo (equivale a numeroLoja/order_sn)
    - Bling numero = Número interno do pedido no Bling
    - No banco: numero_pedido
    """
    # Identificadores
    bling_id      = payload.get('id')                          # ID interno Bling
    bling_numero  = str(payload.get('numero') or '')           # número exibido
    numero_loja   = payload.get('numeroLoja')                  # ID marketplace
    bling_loja_id = _extract_bling_loja_id(payload)
    codigo_externo = str(numero_loja).strip() if numero_loja not in (None, '') else None

    # Cliente (sempre do Bling — fonte canônica)
    contato = payload.get('contato') or {}

    # Datas
    data_venda          = _clean_date(payload.get('data'))
    marketplace_times = _resolve_marketplace_timestamps(payload, shopee_data=shopee_data, meli_data=meli_data)
    
    # Resolver data limite de envio
    data_limite_envio = None
    if shopee_data:
        data_limite_envio = _clean_shopee_ship_by_date(shopee_data.get('ship_by_date'))
    elif meli_data:
        sla = (meli_data.get('sla') or [])[0] if isinstance(meli_data.get('sla'), list) and meli_data.get('sla') else {}
        data_limite_envio = sla.get('expected_date')
    
    if not data_limite_envio:
        data_limite_envio = _clean_date(payload.get('dataPrevista'))

    coleta_contexto = {}
    data_coleta = None
    regra_logistica_integracao_id = None
    if marketplace_integration_id:
        coleta_contexto = logistica_coleta_service.calcular_data_coleta(
            marketplace_integration_id=marketplace_integration_id,
            modalidade=modalidade,
            pagamento_dt=_parse_datetime(marketplace_times.get('data_pagamento_marketplace')),
            compra_dt=_parse_datetime(marketplace_times.get('data_compra_marketplace')),
        )
        data_coleta = coleta_contexto.get('data_coleta')
        regra_logistica_integracao_id = (coleta_contexto.get('regra') or {}).get('id')
        logger.info(
            "[bling-ingest] coleta calculada codigo_externo=%s modalidade=%s contexto=%s",
            codigo_externo,
            modalidade,
            {
                "data_coleta": data_coleta,
                "horario_corte": coleta_contexto.get("horario_corte"),
                "horario_coleta": coleta_contexto.get("horario_coleta"),
                "regra_id": regra_logistica_integracao_id,
            },
        )
    data_venda_iso = normalize_to_iso(data_venda)
    data_limite_envio_iso = normalize_to_iso(data_limite_envio)
    data_compra_marketplace_iso = normalize_to_iso(marketplace_times.get('data_compra_marketplace'))
    data_pagamento_marketplace_iso = normalize_to_iso(marketplace_times.get('data_pagamento_marketplace'))
    data_coleta_iso = normalize_to_iso(data_coleta)
    data_envio_marketplace_iso = normalize_to_iso(marketplace_times.get('data_envio_marketplace'))

    transporte = payload.get('transporte') or {}
    volumes    = transporte.get('volumes') or []
    servico    = volumes[0].get('servico') if volumes else None

    # Status interno
    situacao_pedido_id = _resolve_situacao_interna(
        bling_integration_id,
        payload.get('situacao', {}).get('id'),
    )

    marketplace_slug = None
    if shopee_data:
        marketplace_slug = 'shopee'
    elif meli_data:
        marketplace_slug = 'mercadolivre'

    marketplace_module_id = canonical_order_repository.resolve_module_id(
        marketplace_integration_id, marketplace_slug
    )
    # O vinculo e resolvido sempre, nao apenas quando falta o module_id: ele
    # tambem carrega o `ingest_origin_mode`, que decide se o Bling pode ditar
    # o ciclo de vida deste pedido.
    link = canonical_order_repository.resolve_erp_marketplace_link(
        bling_integration_id, bling_loja_id
    )
    if not marketplace_module_id and link:
        marketplace_module_id = link.get('marketplace_module_id')
        marketplace_integration_id = (
            marketplace_integration_id or link.get('marketplace_integration_id')
        )

    if not marketplace_module_id or not codigo_externo:
        canonical_order_repository.defer_unresolved_erp_order(
            erp_integration_id=bling_integration_id,
            erp_store_id=bling_loja_id,
            erp_order_id=bling_id,
            marketplace_order_id=codigo_externo,
            payload=payload,
        )
        raise OrderIdentityUnresolvedError(
            f"Pedido Bling {bling_id} aguardando resolução marketplace/numeroLoja"
        )

    # Autoridade por origem (secao 7.4 da spec de canonizacao). Onde o
    # marketplace integra direto, ele dita o ciclo de vida e o Bling complementa
    # apenas ERP/NF. O fato externo continua registrado em `status_original` e a
    # identidade fiscal continua sendo gravada; so a projecao e suprimida.
    #
    # Excecao deliberada: se o pedido ainda nao existe, o Bling chegou primeiro.
    # Nesse caso projetar e melhor que deixar o pedido sem situacao alguma — a
    # mesma regra que o RPC canonico aplica na primeira aparicao.
    ingest_origin_mode = (link or {}).get('ingest_origin_mode') or 'erp_bling'
    if not is_authoritative(ingest_origin_mode, 'erp', 'order'):
        if canonical_order_repository.order_exists(marketplace_module_id, codigo_externo):
            logger.info(
                "[ingest] Bling nao autoritativo para %s/%s (modo=%s): situacao "
                "preservada, apenas fatos de ERP aplicados",
                marketplace_module_id, codigo_externo, ingest_origin_mode,
            )
            situacao_pedido_id = None
        else:
            logger.info(
                "[ingest] Bling chegou antes do marketplace em %s/%s (modo=%s): "
                "projetando situacao inicial",
                marketplace_module_id, codigo_externo, ingest_origin_mode,
            )

    data = {
        'marketplace_module_id':      marketplace_module_id,
        'marketplace_order_id':       codigo_externo,
        'marketplace_integration_id': marketplace_integration_id,
        'ingest_source':              ingest_source,
        'erp_integration_id':         bling_integration_id,
        'erp_store_id':               str(bling_loja_id) if bling_loja_id not in (None, '') else None,
        'erp_order_id':               bling_id,
        'erp_order_number':           bling_numero,
        'pedido_bling_id':            pedido_bling_id,
        'pedido_shopee_id':           pedido_shopee_id,
        'pedido_mercadolivre_id':     pedido_mercadolivre_id,
        'canal_venda_id':             canal_venda_id,
        'situacao_pedido_id':         situacao_pedido_id,
        'status_original':            str(payload.get('situacao', {}).get('id') or ''),
        'cliente_nome':               contato.get('nome'),
        'cliente_documento':          contato.get('numeroDocumento'),
        'cliente_telefone':           contato.get('telefone') or contato.get('celular'),
        'cliente_email':              contato.get('email'),
        'customer':                   contato or {},
        'total_pedido':               _safe_float(payload.get('total')),
        'moeda':                      'BRL',
        'data_venda':                 data_venda_iso,
        'data_limite_envio':          data_limite_envio_iso,
        'data_compra_marketplace':    data_compra_marketplace_iso,
        'data_pagamento_marketplace': data_pagamento_marketplace_iso,
        'data_coleta':                data_coleta_iso,
        'data_envio_marketplace':     data_envio_marketplace_iso,
        'regra_logistica_integracao_id': regra_logistica_integracao_id,
        'servico_logistico':          servico,
        'is_flex':                    is_flex,
        'is_fulfillment':             is_fulfillment,
        'modalidade_logistica':       modalidade,
        'buyer_username':             (shopee_data or {}).get('buyer_username') or (meli_data.get('order', {}) if meli_data else {}).get('buyer', {}).get('nickname'),
        'shipping_carrier':           (shopee_data or {}).get('shipping_carrier') or (meli_data.get('shipment', {}) if meli_data else {}).get('mode'),
        'message_to_seller':          (shopee_data or {}).get('raw', {}).get('message_to_seller') or (meli_data.get('order', {}) if meli_data else {}).get('comment'),
    }
    data = {k: v for k, v in data.items() if v is not None}

    snapshot_items = [
            {
                'sku': item.get('codigo'),
                'name': item.get('descricao'),
                'quantity': _safe_float(item.get('quantidade'), 1.0),
                'unit_price': _safe_float(item.get('valor')),
                'subtotal': _safe_float(item.get('valor')) * _safe_float(item.get('quantidade'), 1.0),
                'raw': item,
            }
            for item in (payload.get('itens') or [])
        ]
    snapshot = {
        'identity': {
            'ingest_source': ingest_source,
            'marketplace': marketplace_module_id,
            'marketplace_order_id': codigo_externo,
            'marketplace_integration_id': marketplace_integration_id,
            'erp_integration_id': bling_integration_id,
            'erp_order_id': bling_id,
            'erp_order_number': bling_numero,
        },
        'customer': {
            'name': contato.get('nome'),
            'document': contato.get('numeroDocumento'),
            'phone': contato.get('telefone') or contato.get('celular'),
            'email': contato.get('email'),
            'raw': contato,
        },
        'items': snapshot_items,
        'logistics': {
            'service': servico,
            'shipping_carrier': data.get('shipping_carrier'),
            'is_flex': is_flex,
            'is_fulfillment': is_fulfillment,
            'modalidade': modalidade,
            'deadline': data_limite_envio_iso,
            'purchase_at': data_compra_marketplace_iso,
            'payment_at': data_pagamento_marketplace_iso,
            'collection_at': data_coleta_iso,
            'marketplace_shipped_at': data_envio_marketplace_iso,
            'cutoff_time': coleta_contexto.get('horario_corte'),
            'collection_time': coleta_contexto.get('horario_coleta'),
            'rule_id': regra_logistica_integracao_id,
            'payment_time_source': marketplace_times.get('payment_time_source'),
            'transport': transporte,
        },
        'financial': {'total': _safe_float(payload.get('total')), 'currency': 'BRL'},
        'platform_fields': {
            'buyer_username': data.get('buyer_username'),
            'message_to_seller': data.get('message_to_seller'),
            'shipping_carrier': data.get('shipping_carrier'),
            'shopee': shopee_data,
            'mercadolivre': meli_data,
        },
        'raw_refs': {
            'bling': payload,
            'pedido_bling_id': pedido_bling_id,
            'pedido_shopee_id': pedido_shopee_id,
            'pedido_mercadolivre_id': pedido_mercadolivre_id,
        },
        'source_history': [{'source': ingest_source, 'at': get_now_iso()}],
    }
    refs = [
        {
            'integration_id': marketplace_integration_id,
            'module_id': marketplace_module_id,
            'role': 'sales_origin',
            'external_order_id': codigo_externo,
            'external_status': data.get('status_original'),
        },
        {
            'integration_id': bling_integration_id,
            'module_id': 'bling',
            'role': 'erp',
            'external_order_id': str(bling_id or bling_numero),
            'external_record_id': str(pedido_bling_id) if pedido_bling_id else None,
            'metadata': {'store_id': data.get('erp_store_id')},
        },
    ]
    pedido_id = canonical_order_repository.upsert(data, snapshot=snapshot, refs=refs)
    logger.info(
        "[upsert_pedido_master] Pedido canônico atualizado: module=%s external=%s pedido_id=%s",
        marketplace_module_id, codigo_externo, pedido_id,
    )

    _upsert_itens_pedido(pedido_id, payload.get('itens', []))
    return pedido_id


def _clean_date(date_str):
    """Valida e limpa strings de data para evitar erros no Postgres."""
    if not date_str or not isinstance(date_str, str):
        return None
    if date_str.startswith('0000') or '0000-00-00' in date_str:
        return None
    return date_str


def _clean_shopee_ship_by_date(value):
    """
    Retorna ship_by_date da Shopee já convertido para ISO pelo driver.
    O driver Shopee já converte o timestamp Unix para ISO no timezone da aplicação.
    """
    return value


def _safe_float(value, default=0.0):
    """Converte valores de forma segura."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        for k in ['valor', 'total', 'quantidade']:
            if k in value:
                return _safe_float(value[k], default)
        return default
    try:
        return float(str(value).replace(',', '.'))
    except:
        return default


def _resolve_situacao_interna(bling_integration_id, bling_situacao_id):
    """Mapeia status do Bling para status interno via integration_status_mappings."""
    resolved = canonical_order_status_service.resolve_bling(
        bling_situacao_id,
        integration_id=bling_integration_id,
    )
    if resolved.internal_situacao_pedido_id:
        return resolved.internal_situacao_pedido_id

    if str(bling_situacao_id) == '15':
        logger.warning(
            "[ingest] sem mapeamento explicito para situacao Bling 15 inst=%s; usando fallback interno 2 (Em Andamento)",
            bling_integration_id,
        )
        return 2

    logger.warning(
        "[ingest] sem mapeamento de situacao Bling status=%s inst=%s; mantendo status_original e situacao_pedido_id=null",
        bling_situacao_id,
        bling_integration_id,
    )
    return None

def _volume_servico(payload):
    volumes = payload.get('transporte', {}).get('volumes', [])
    return volumes[0].get('servico') if volumes else None

def _upsert_itens_pedido(pedido_id, itens_bling):
    """
    Upsert itens do pedido na tabela itens_pedido.
    Usa vinculos_bling (o cadastro real de mapeamento) em vez de produtos.sku.
    """
    if not pedido_id or not itens_bling:
        return

    pedido_rows = (
        supabase_db.table('pedidos')
        .select('ingest_source')
        .eq('id', pedido_id)
        .limit(1)
        .execute().data or []
    )
    if pedido_rows and str(pedido_rows[0].get('ingest_source') or '').lower() in ('shopee', 'mercadolivre'):
        # Marketplace owns commercial item data. Bling may only enrich the
        # internal product mapping for an existing SKU.
        for item in itens_bling:
            codigo = item.get('codigo')
            produto_id = _resolve_produto_interno(codigo, (item.get('produto') or {}).get('id'))
            if codigo and produto_id:
                (supabase_db.table('itens_pedido').update({'produto_id': produto_id, 'updated_at': get_now_iso()})
                 .eq('pedido_id', pedido_id).eq('sku_externo', codigo).execute())
        return

    # Deletar itens existentes deste pedido para evitar duplicatas
    supabase_db.table('itens_pedido').delete().eq('pedido_id', pedido_id).execute()

    rows = []
    for it in itens_bling:
        codigo = it.get('codigo')                          # SKU vendido
        produto_bling_id = (it.get('produto') or {}).get('id')
        produto_id = _resolve_produto_interno(codigo, produto_bling_id)
        rows.append({
            'pedido_id':       pedido_id,
            'produto_id':      produto_id,
            'sku_externo':     codigo,
            'descricao':       it.get('descricao'),
            'quantidade':      _safe_float(it.get('quantidade'), 1.0),
            'preco_unitario':  _safe_float(it.get('valor')),
            'subtotal':        _safe_float(it.get('valor')) * _safe_float(it.get('quantidade'), 1.0),
            'updated_at':      get_now_iso(),
        })

    if rows:
        supabase_db.table('itens_pedido').insert(rows).execute()
        logger.info("[upsert_itens_pedido] %d itens inseridos para pedido_id=%s", len(rows), pedido_id)


def _resolve_produto_interno(codigo, produto_bling_id):
    """
    Resolve o produto interno usando vinculos_bling.
    Prioridade: 1) vinculos_bling por bling_id, 2) vinculos_bling por SKU, 3) produtos.sku
    """
    # 1ª tentativa: vinculos_bling por bling_id
    if produto_bling_id:
        v = (supabase_db.table('vinculos_bling')
             .select('produto_id')
             .eq('codigo_bling', str(produto_bling_id))
             .limit(1).execute().data)
        if v:
            return v[0]['produto_id']

    # 2ª tentativa: vinculos_bling por SKU
    if codigo:
        v = (supabase_db.table('vinculos_bling')
             .select('produto_id')
             .eq('codigo_bling', str(codigo))
             .limit(1).execute().data)
        if v:
            return v[0]['produto_id']

    # 3ª tentativa: produtos por SKU
    if codigo:
        p = (supabase_db.table('produtos')
             .select('id')
             .eq('sku', codigo)
             .limit(1).execute().data)
        if p:
            return p[0]['id']

    return None


def materialize_marketplace_direct_order(
    *,
    source: str,
    external_order_id: str,
    marketplace_inst: dict,
    marketplace_detail: dict,
    marketplace_mirror_id: int | None,
    bling_integration_id: int | None,
    bling_loja_id: str | None = None,
):
    if not bling_integration_id or not external_order_id:
        return {"status": "not_available", "reason": "missing_bling_reference"}

    from nistiprint_shared.services.bling.bling_client import (
        BlingClient,
        BlingRateLimitedError,
        BlingTransientHTTPError,
    )

    try:
        client = BlingClient.create_client_for_integration_id(int(bling_integration_id))
        matches = client.get_order_numbers_by_store_numbers([str(external_order_id)]) or []
    except BlingRateLimitedError as exc:
        logger.warning(
            "[marketplace-direct] rate limit ao localizar pedido Bling numeroLoja=%s inst=%s retry_after=%s",
            external_order_id,
            bling_integration_id,
            exc.retry_after,
        )
        return {
            "status": "error",
            "reason": "bling_rate_limited",
            "message": str(exc),
            "retry_after": exc.retry_after,
        }
    except BlingTransientHTTPError as exc:
        logger.warning(
            "[marketplace-direct] Bling temporariamente indisponivel numeroLoja=%s inst=%s retry_after=%s",
            external_order_id,
            bling_integration_id,
            exc.retry_after,
        )
        return {
            "status": "error",
            "reason": "bling_lookup_transient_error",
            "message": str(exc),
            "retry_after": exc.retry_after,
        }
    except Exception as exc:
        logger.warning(
            "[marketplace-direct] falha ao localizar pedido Bling numeroLoja=%s inst=%s: %s",
            external_order_id,
            bling_integration_id,
            exc,
            exc_info=True,
        )
        return {"status": "error", "reason": "bling_lookup_failed", "message": str(exc)}

    if not matches:
        return {"status": "not_found", "reason": "bling_order_not_found"}

    match = matches[0] or {}
    if not match.get("id") or not match.get("numero"):
        return {"status": "error", "reason": "bling_order_incomplete"}

    original_payload = {
        "id": match.get("id"),
        "numero": match.get("numero"),
        "numeroLoja": str(external_order_id),
        "loja": {"id": bling_loja_id} if bling_loja_id not in (None, "") else {},
    }
    detalhe = _preserve_original_bling_fields(
        _fetch_bling_order_detail({"id": bling_integration_id}, match.get("id")),
        original_payload,
    )
    if not detalhe.get("numero"):
        return {"status": "error", "reason": "bling_detail_incomplete"}

    pedido_bling_id = _upsert_pedido_bling(detalhe, bling_integration_id)

    loja_id = str(_extract_bling_loja_id(detalhe) or bling_loja_id or "")
    canal_venda_id = _resolve_canal_venda_id(
        marketplace_inst.get("id"),
        bling_integration_id,
        loja_id,
    )

    plataforma = marketplace_inst.get("plataforma_slug") or source
    shopee_data = marketplace_detail if plataforma == "shopee" else None
    meli_data = marketplace_detail if plataforma == "mercadolivre" else None

    fulfillment = _classify_fulfillment(
        shopee_data,
        meli_data,
        detalhe.get("numeroLoja"),
        plataforma,
        canal_venda_id=canal_venda_id,
        marketplace_integration_id=marketplace_inst.get("id"),
    )
    flex = _classify_flex(
        shopee_data,
        meli_data,
        detalhe.get("numeroLoja"),
        plataforma,
        is_fulfillment=fulfillment.is_fulfillment,
    )
    modalidade = fulfillment.modalidade if fulfillment.is_fulfillment else flex.modalidade

    pedido_id = _upsert_pedido_master(
        detalhe,
        pedido_bling_id=pedido_bling_id,
        pedido_shopee_id=marketplace_mirror_id if plataforma == "shopee" else None,
        pedido_mercadolivre_id=marketplace_mirror_id if plataforma == "mercadolivre" else None,
        bling_integration_id=bling_integration_id,
        marketplace_integration_id=marketplace_inst.get("id"),
        canal_venda_id=canal_venda_id,
        is_flex=flex.is_flex,
        is_fulfillment=fulfillment.is_fulfillment,
        modalidade=modalidade,
        shopee_data=shopee_data,
        meli_data=meli_data,
        ingest_source=source,
    )
    if not pedido_id:
        return {"status": "error", "reason": "bling_materialization_failed"}

    if pedido_id:
        _detect_and_mark_personalized(detalhe, pedido_id)

    return {
        "status": "success",
        "pedido_id": pedido_id,
        "pedido_bling_id": pedido_bling_id,
        "bling_order_id": detalhe.get("id"),
        "bling_order_number": detalhe.get("numero"),
        "canal_venda_id": canal_venda_id,
        "is_flex": flex.is_flex,
        "is_fulfillment": fulfillment.is_fulfillment,
        "modalidade": modalidade,
    }


def import_single_order_by_shop_id(shopee_order_sn: str):
    """
    Imports a single order from Bling based on the Shopee Order SN (numeroLoja).
    This is a manual import function that replicates the webhook processing logic.
    
    Args:
        shopee_order_sn: The Shopee order SN (numeroLoja) to import
        
    Returns:
        Tuple of (success: bool, message: str)
    """
    from nistiprint_shared.services.bling.bling_client import BlingClient
    from nistiprint_shared.services.integracao_canal_service import integracao_canal_service
    
    logger.info(f"[MANUAL_IMPORT] Starting import for order SN: {shopee_order_sn}")
    
    try:
        # 1. Get channel configuration by looking up the loja_id
        # First, we need to find which Bling integration has this order
        configs = integracao_canal_service.listar_configuracoes(include_inactive=False)
        
        if not configs:
            return False, "No active channel configurations found."
        
        # Try to find the order in each configured Bling integration
        found_order = None
        used_config = None
        
        for cfg in configs:
            bling_loja_id = cfg.get('bling_loja_id')
            if not bling_loja_id:
                continue
            
            try:
                bling_client = _bling_client_for_config(cfg)
                
                logger.info(f"[MANUAL_IMPORT] Checking config {cfg.get('id')} (bling_loja_id={bling_loja_id})")
                
                # Use get_orders_by_store_numbers to search by numeroLoja
                orders_found, orders_data, ids_with_numbers, not_found = bling_client.get_orders_by_store_numbers([shopee_order_sn])
                
                if orders_found > 0 and orders_data:
                    found_order = orders_data[0]  # Take the first match
                    used_config = cfg
                    logger.info(f"[MANUAL_IMPORT] Found order in config {cfg.get('id')}: bling_id={found_order.get('id')}")
                    break
                
            except Exception as e:
                logger.warning(f"[MANUAL_IMPORT] Error checking config {cfg.get('id')}: {e}")
                continue
        
        if not found_order:
            return False, f"Order {shopee_order_sn} not found in any configured Bling integration."
        
        # 2. Process the order through the standard pipeline
        result = process_webhook(found_order, bling_integration_hint=used_config.get('bling_integration_id'))
        
        pedido_id = result.get('pedido_id')
        if pedido_id:
            return True, f"Order {shopee_order_sn} imported successfully (pedido_id={pedido_id})"
        else:
            return False, f"Order {shopee_order_sn} processing failed."
            
    except Exception as e:
        logger.error(f"[MANUAL_IMPORT] Error importing order {shopee_order_sn}: {e}", exc_info=True)
        return False, f"Error importing order: {str(e)}"


def _bling_client_for_config(cfg):
    """Helper to create BlingClient from config (reused from pedidos_bling_import_service)"""
    from nistiprint_shared.services.bling.bling_client import BlingClient
    from nistiprint_shared.services.integracao_canal_service import integracao_canal_service
    
    bling_iid = cfg.get("bling_integration_id")
    if bling_iid:
        return BlingClient.create_client_for_integration_id(int(bling_iid))
    
    plataforma_nome = cfg.get("plataforma_nome")
    canal_venda_id = cfg.get("canal_venda_id")
    
    if plataforma_nome:
        return BlingClient.create_client_for_platform(
            plataforma_nome.lower(),
            channel_id=canal_venda_id,
            function_name="ORDER_IMPORT",
        )
    
    if canal_venda_id:
        canal_info = integracao_canal_service.get_integration_by_canal(canal_venda_id, expected_module='bling')
        if canal_info and canal_info.get("plataforma_nome"):
            return BlingClient.create_client_for_platform(
                canal_info["plataforma_nome"].lower(),
                channel_id=canal_venda_id,
                function_name="ORDER_IMPORT",
            )
    
    logger.warning("Config without platform defined - using fallback shopee")
    return BlingClient.create_client_for_platform(
        "shopee",
        channel_id=canal_venda_id,
        function_name="ORDER_IMPORT",
    )


