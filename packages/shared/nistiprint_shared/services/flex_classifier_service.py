"""
Aplica regras parametrizáveis em flex_classification_rules.
Ordem de resolução (prioridade crescente):
  1) regras por marketplace_integration_id (match exato)
  2) regras globais (sem escopo de instância)
  3) fallback (primeira regra com padrão '%')

Operadores:
  - EQUALS               : campo == padrao
  - ILIKE                : campo ILIKE padrao
  - ILIKE_NORMALIZED     : normalize(campo) ILIKE normalize(padrao)
                           onde normalize = lower + strip_accents
"""
import logging
import unicodedata
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("flex_classifier")

def _normalize(s: Optional[str]) -> str:
    if not s:
        return ""
    # Remove acentos e converte para lowercase
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()

@dataclass
class FlexResult:
    is_flex: bool
    modalidade: str
    matched_rule_id: Optional[int]
    motivo: str   # explicação humana p/ log

def classify(
    db,  # SupabaseDBService
    fields: dict,                 # {'servico_logistico': ..., 'shipping_carrier': ..., 'fulfillment_flag': ...}
    marketplace_integration_id: Optional[int] = None,
    log_context: Optional[dict] = None,    # ex.: {'order_sn': '...', 'pedido_id': ...}
) -> FlexResult:
    ctx = log_context or {}
    rules = db.table('flex_classification_rules') \
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
            if r.get('marketplace_integration_id') != marketplace_integration_id:
                continue
            val = fields.get(r['campo'])
            if matches(r, val):
                motivo = (f"{r['campo']}={val!r} casou regra #{r['id']} "
                          f"(scope=marketplace:{marketplace_integration_id})")
                logger.info("[flex] %s %s → is_flex=%s modalidade=%s",
                            ctx, motivo, r['is_flex'], r.get('modalidade'))
                return FlexResult(r['is_flex'], r.get('modalidade') or 'STANDARD', r['id'], motivo)

    # 2) Regras globais
    for r in rules:
        if r.get('marketplace_integration_id') is None:
            val = fields.get(r['campo'])
            if matches(r, val):
                motivo = (f"{r['campo']}={val!r} casou regra global #{r['id']}")
                logger.info("[flex] %s %s → is_flex=%s modalidade=%s",
                            ctx, motivo, r['is_flex'], r.get('modalidade'))
                return FlexResult(r['is_flex'], r.get('modalidade') or 'STANDARD', r['id'], motivo)

    # 3) Default
    motivo = (f"nenhuma regra casou para fields={fields!r} → STANDARD por default")
    logger.info("[flex] %s %s", ctx, motivo)
    return FlexResult(False, 'STANDARD', None, motivo)
