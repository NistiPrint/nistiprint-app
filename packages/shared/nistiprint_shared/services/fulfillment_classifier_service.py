"""
Aplica regras parametrizáveis em fulfillment_classification_rules.
Baseado na arquitetura do flex_classifier_service.
"""
import logging
import unicodedata
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("fulfillment_classifier")

def _normalize(s: Optional[str]) -> str:
    if not s:
        return ""
    # Remove acentos e converte para lowercase
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()

@dataclass
class FulfillmentResult:
    is_fulfillment: bool
    modalidade: str
    matched_rule_id: Optional[int]
    motivo: str   # explicação humana p/ log

def classify(
    db,  # SupabaseDBService
    fields: dict,                 # {'servico_logistico': ..., 'shipping_carrier': ..., 'fulfillment_flag': ...}
    marketplace_integration_id: Optional[int] = None,
    log_context: Optional[dict] = None,    # ex.: {'order_sn': '...', 'pedido_id': ...}
) -> FulfillmentResult:
    ctx = log_context or {}
    rules = db.table('fulfillment_classification_rules') \
        .select('*').eq('ativo', True) \
        .order('prioridade', desc=False).execute().data

    def matches(rule, value):
        if value is None:
            return False
        op, pat = rule['operador'], rule['padrao']
        if op == 'EQUALS':
            return value == pat
        if op == 'ILIKE':
            return pat == '%' or pat.replace('%', '').lower() in value.lower()
        if op == 'ILIKE_NORMALIZED':
            return _normalize(pat) in _normalize(value)
        return False

    # 1) Regras com escopo da instância marketplace
    if marketplace_integration_id is not None:
        for r in rules:
            if r.get('integracao_instancia_id') != marketplace_integration_id:
                continue
            val = fields.get(r['campo'])
            if matches(r, val):
                motivo = (f"{r['campo']}={val!r} casou regra #{r['id']} "
                          f"(scope=marketplace:{marketplace_integration_id})")
                logger.info("[fulfillment] %s %s → is_fulfillment=%s modalidade=%s",
                            ctx, motivo, r['is_fulfillment'], r.get('modalidade'))
                return FulfillmentResult(r['is_fulfillment'], r.get('modalidade') or 'STANDARD', r['id'], motivo)

    # 2) Regras globais (via canal_venda_id se disponível no log_context ou fields)
    canal_venda_id = fields.get('canal_venda_id')
    for r in rules:
        if r.get('integracao_instancia_id') is None:
            # Se a regra tiver canal_venda_id, verificamos match
            if r.get('canal_venda_id') and canal_venda_id and r.get('canal_venda_id') != canal_venda_id:
                continue
                
            val = fields.get(r['campo'])
            if matches(r, val):
                motivo = (f"{r['campo']}={val!r} casou regra global/canal #{r['id']}")
                logger.info("[fulfillment] %s %s → is_fulfillment=%s modalidade=%s",
                            ctx, motivo, r['is_fulfillment'], r.get('modalidade'))
                return FulfillmentResult(r['is_fulfillment'], r.get('modalidade') or 'STANDARD', r['id'], motivo)

    # 3) Default
    motivo = (f"nenhuma regra casou para fields={fields!r} → STANDARD por default")
    logger.info("[fulfillment] %s %s", ctx, motivo)
    return FulfillmentResult(False, 'STANDARD', None, motivo)
