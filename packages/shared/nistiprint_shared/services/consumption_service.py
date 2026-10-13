from decimal import Decimal, InvalidOperation
from typing import Any, Dict

from nistiprint_shared.database.supabase_db_service import supabase_db


class ConsumptionService:
    """Consumption metrics derived from confirmed stock ledger movements."""

    CONSUMPTION_TYPES = {
        "CONS_MP", "CONS_INT", "SAIDA_INSUMO_PRODUCAO", "SAIDA_RESERVADA",
    }
    COMPENSATION_TYPES = {
        "COMPENSACAO_CONSUMO", "COMPENSACAO_CONS_MP", "COMPENSACAO_CONS_INT",
        "ESTORNO_CONS_MP", "ESTORNO_CONS_INT",
    }

    def __init__(self):
        self.movements_table = supabase_db.table("movimentacoes_estoque")

    @classmethod
    def _signed_consumption(cls, movement: dict[str, Any]) -> Decimal:
        movement_type = str(movement.get("tipo_movimentacao") or "").upper()
        if movement_type not in cls.CONSUMPTION_TYPES | cls.COMPENSATION_TYPES:
            return Decimal("0")
        try:
            quantity = abs(Decimal(str(movement.get("quantidade") or 0)))
        except (InvalidOperation, TypeError, ValueError):
            return Decimal("0")
        return -quantity if movement_type in cls.COMPENSATION_TYPES else quantity

    def get_daily_consumption(self, days: int = 30) -> Dict[int, Dict[str, Any]]:
        """Return average daily net material consumption from physical movements."""
        days = int(days)
        if days <= 0:
            raise ValueError("days deve ser maior que zero")
        response = supabase_db.rpc("consumo_medio_diario", {"p_dias": days}).execute()
        result = {}
        for row in response.data or []:
            product_id = int(row["produto_id"])
            result[product_id] = {
                "total_periodo": float(row["total_periodo"]),
                "media_diaria": float(row["media_diaria"]),
                "periodo_dias": int(row["periodo_dias"]),
                "nome_insumo": row.get("nome_insumo"),
            }
        return result


consumption_service = ConsumptionService()
