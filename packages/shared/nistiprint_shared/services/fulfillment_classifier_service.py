"""
Apply configurable rules from fulfillment_classification_rules.
Compatibility:
- Prefer marketplace_integration_id (new contract)
- Fallback to integracao_instancia_id (legacy contract)
"""
import logging
import unicodedata
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("fulfillment_classifier")


def _normalize(value: Optional[str]) -> str:
    if not value:
        return ""
    nfkd = unicodedata.normalize("NFKD", value)
    return "".join(char for char in nfkd if not unicodedata.combining(char)).lower().strip()


@dataclass
class FulfillmentResult:
    is_fulfillment: bool
    modalidade: str
    matched_rule_id: Optional[int]
    motivo: str


def classify(
    db,
    fields: dict,
    marketplace_integration_id: Optional[int] = None,
    log_context: Optional[dict] = None,
) -> FulfillmentResult:
    ctx = log_context or {}
    rules = (
        db.table("fulfillment_classification_rules")
        .select("*")
        .eq("ativo", True)
        .order("prioridade", desc=False)
        .execute()
        .data
    )

    def matches(rule, value):
        if value is None:
            return False
        op, pat = rule["operador"], rule["padrao"]
        if op == "EQUALS":
            return value == pat
        if op == "ILIKE":
            return pat == "%" or pat.replace("%", "").lower() in value.lower()
        if op == "ILIKE_NORMALIZED":
            return _normalize(pat) in _normalize(value)
        return False

    def scoped_marketplace_id(rule):
        # New column first, then legacy fallback.
        if rule.get("marketplace_integration_id") is not None:
            return rule.get("marketplace_integration_id")
        return rule.get("integracao_instancia_id")

    # 1) Instance-scoped rules
    if marketplace_integration_id is not None:
        for rule in rules:
            if scoped_marketplace_id(rule) != marketplace_integration_id:
                continue
            value = fields.get(rule["campo"])
            if matches(rule, value):
                reason = (
                    f"{rule['campo']}={value!r} matched rule #{rule['id']} "
                    f"(scope=marketplace:{marketplace_integration_id})"
                )
                logger.info(
                    "[fulfillment] %s %s -> is_fulfillment=%s modalidade=%s",
                    ctx,
                    reason,
                    rule["is_fulfillment"],
                    rule.get("modalidade"),
                )
                return FulfillmentResult(
                    rule["is_fulfillment"],
                    rule.get("modalidade") or "STANDARD",
                    rule["id"],
                    reason,
                )

    # 2) Global or channel-scoped rules
    channel_id = fields.get("canal_venda_id")
    for rule in rules:
        if scoped_marketplace_id(rule) is not None:
            continue
        rule_channel_id = rule.get("canal_venda_id")
        if rule_channel_id is not None:
            if channel_id is None or rule_channel_id != channel_id:
                continue

        value = fields.get(rule["campo"])
        if matches(rule, value):
            reason = f"{rule['campo']}={value!r} matched global/channel rule #{rule['id']}"
            logger.info(
                "[fulfillment] %s %s -> is_fulfillment=%s modalidade=%s",
                ctx,
                reason,
                rule["is_fulfillment"],
                rule.get("modalidade"),
            )
            return FulfillmentResult(
                rule["is_fulfillment"],
                rule.get("modalidade") or "STANDARD",
                rule["id"],
                reason,
            )

    # 3) Default
    reason = f"no rule matched for fields={fields!r} -> STANDARD by default"
    logger.info("[fulfillment] %s %s", ctx, reason)
    return FulfillmentResult(False, "STANDARD", None, reason)
