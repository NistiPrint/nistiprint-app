from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.logistica_manutencao_service import rpc_data

DEFAULT_TZ = "America/Sao_Paulo"


class LogisticaColetaService:
    """Toda agenda, excecao e corte usa o mesmo resolvedor da torre e worker."""

    @staticmethod
    def _iso(value, tz):
        return (value.replace(tzinfo=tz) if value.tzinfo is None else value).isoformat() if value else None

    def calcular_data_coleta(self, marketplace_integration_id, modalidade,
                             pagamento_dt=None, compra_dt=None, timezone_name=DEFAULT_TZ):
        if not marketplace_integration_id:
            return {"tem_regra": False, "janela_status": "SEM_REGRA"}
        tz = ZoneInfo(timezone_name)
        result = rpc_data("logistica_contexto_coleta", {
            "p_integration_id": marketplace_integration_id,
            "p_modalidade": modalidade or "STANDARD",
            "p_referencia": self._iso(pagamento_dt or compra_dt, tz),
        }) or {}
        result["payment_time_source"] = "payment_at" if pagamento_dt else "purchase_at" if compra_dt else "now"
        return result

    def calcular_contexto_coleta(self, marketplace_integration_id, modalidade,
                                reference_dt=None, timezone_name=DEFAULT_TZ):
        if not marketplace_integration_id:
            return {"tem_regra": False, "janela_status": "SEM_REGRA"}
        params = {"p_integration_id": marketplace_integration_id, "p_modalidade": modalidade or "STANDARD"}
        if reference_dt:
            params["p_agora"] = self._iso(reference_dt, ZoneInfo(timezone_name))
        return rpc_data("logistica_contexto_coleta", params) or {}

    def resolver_por_canal(
        self,
        canal_venda_id: Optional[int],
        modalidade: Optional[str],
        reference_dt: Optional[datetime] = None,
        timezone_name: str = DEFAULT_TZ,
    ) -> Dict[str, Any]:
        if not canal_venda_id:
            return {"tem_regra": False, "janela_status": "SEM_REGRA"}

        cc = (
            supabase_db.table("channel_connections")
            .select("marketplace_integration_id")
            .eq("channel_id", canal_venda_id)
            .eq("is_active", True)
            .not_.is_("marketplace_integration_id", "null")
            .limit(1)
            .execute()
        )
        row = (cc.data or [{}])[0]
        marketplace_integration_id = row.get("marketplace_integration_id")
        return self.calcular_contexto_coleta(
            marketplace_integration_id=marketplace_integration_id,
            modalidade=modalidade,
            reference_dt=reference_dt,
            timezone_name=timezone_name,
        )


logistica_coleta_service = LogisticaColetaService()
