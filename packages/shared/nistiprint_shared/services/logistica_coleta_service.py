from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from nistiprint_shared.database.supabase_db_service import supabase_db


DEFAULT_TZ = "America/Sao_Paulo"


@dataclass
class JanelaColeta:
    horario_limite: str
    tipo_envio: str
    ponto_coleta_id: Optional[int]
    ponto_coleta_nome: Optional[str]
    prioridade_uso: int
    dias_semana: List[int]


class LogisticaColetaService:
    """Fonte canonica de regras logisticas por marketplace_integration_id."""

    def __init__(self):
        self._table = supabase_db.table("regras_logisticas_integracao")

    @staticmethod
    def _normalize_weekday(dt: datetime) -> int:
        # Python: Monday=0..Sunday=6 -> DB: Monday=1..Sunday=7
        return dt.weekday() + 1

    @staticmethod
    def _parse_time_hhmm(value: str) -> tuple[int, int]:
        text = (value or "").strip()
        if not text:
            return 23, 59
        parts = text.split(":")
        if len(parts) < 2:
            return 23, 59
        return int(parts[0]), int(parts[1])

    @staticmethod
    def _normalize_dias_semana(raw: Any) -> List[int]:
        if not raw:
            return [1, 2, 3, 4, 5, 6, 7]
        out: List[int] = []
        for val in raw:
            try:
                day = int(val)
            except (TypeError, ValueError):
                continue
            if 1 <= day <= 7:
                out.append(day)
        return out or [1, 2, 3, 4, 5, 6, 7]

    def _load_rules(self, marketplace_integration_id: int, modalidade: str) -> List[JanelaColeta]:
        response = (
            self._table
            .select("horario_limite,tipo_envio,ponto_coleta_id,prioridade_uso,dias_semana,pontos_coleta(nome)")
            .eq("marketplace_integration_id", marketplace_integration_id)
            .eq("modalidade", modalidade)
            .eq("ativo", True)
            .order("horario_limite", desc=False)
            .order("prioridade_uso", desc=True)
            .execute()
        )

        rows = response.data or []
        rules: List[JanelaColeta] = []
        for row in rows:
            ponto = row.get("pontos_coleta") or {}
            rules.append(
                JanelaColeta(
                    horario_limite=str(row.get("horario_limite") or "23:59")[:5],
                    tipo_envio=row.get("tipo_envio") or "COLETA_LOCAL",
                    ponto_coleta_id=row.get("ponto_coleta_id"),
                    ponto_coleta_nome=ponto.get("nome"),
                    prioridade_uso=int(row.get("prioridade_uso") or 1),
                    dias_semana=self._normalize_dias_semana(row.get("dias_semana")),
                )
            )
        return rules

    def calcular_contexto_coleta(
        self,
        marketplace_integration_id: Optional[int],
        modalidade: Optional[str],
        reference_dt: Optional[datetime] = None,
        timezone_name: str = DEFAULT_TZ,
    ) -> Dict[str, Any]:
        if not marketplace_integration_id:
            return {
                "tem_regra": False,
                "janela_status": "SEM_REGRA",
            }

        modalidade_key = (modalidade or "STANDARD").upper()
        tz = ZoneInfo(timezone_name)
        now = reference_dt.astimezone(tz) if reference_dt else datetime.now(tz)
        rules = self._load_rules(marketplace_integration_id, modalidade_key)
        if not rules:
            return {
                "tem_regra": False,
                "janela_status": "SEM_REGRA",
                "marketplace_integration_id": marketplace_integration_id,
                "modalidade": modalidade_key,
            }

        next_window_dt: Optional[datetime] = None
        next_window_rule: Optional[JanelaColeta] = None
        deadline_today_dt: Optional[datetime] = None

        for day_offset in range(0, 8):
            candidate_day = now + timedelta(days=day_offset)
            weekday = self._normalize_weekday(candidate_day)
            candidate_rules = [r for r in rules if weekday in r.dias_semana]
            if not candidate_rules:
                continue
            for rule in candidate_rules:
                hh, mm = self._parse_time_hhmm(rule.horario_limite)
                dt_candidate = candidate_day.replace(hour=hh, minute=mm, second=0, microsecond=0)
                if day_offset == 0:
                    if deadline_today_dt is None or dt_candidate > deadline_today_dt:
                        deadline_today_dt = dt_candidate
                if dt_candidate >= now and (next_window_dt is None or dt_candidate < next_window_dt):
                    next_window_dt = dt_candidate
                    next_window_rule = rule
            if next_window_dt is not None and day_offset == 0:
                break
            if next_window_dt is not None and day_offset > 0:
                break

        if next_window_dt is None or next_window_rule is None:
            return {
                "tem_regra": True,
                "janela_status": "VENCIDA",
                "marketplace_integration_id": marketplace_integration_id,
                "modalidade": modalidade_key,
            }

        deadline_horario = None
        if deadline_today_dt:
            deadline_horario = deadline_today_dt.strftime("%H:%M")
        else:
            # fallback: maior horario da modalidade
            deadline_horario = max((r.horario_limite for r in rules), default=next_window_rule.horario_limite)

        next_horario = next_window_dt.strftime("%H:%M")
        minutes_left = int((next_window_dt - now).total_seconds() // 60)
        if deadline_horario == next_horario and next_window_dt.date() == now.date():
            status = "ULTIMA_CHANCE"
        elif next_window_dt.date() > now.date():
            status = "PROXIMA"
        else:
            status = "BACKUP" if next_horario != min((r.horario_limite for r in rules), default=next_horario) else "PROXIMA"

        return {
            "tem_regra": True,
            "marketplace_integration_id": marketplace_integration_id,
            "modalidade": modalidade_key,
            "proxima_coleta_at": next_window_dt.isoformat(),
            "proxima_coleta_horario": next_horario,
            "proxima_coleta_tipo_envio": next_window_rule.tipo_envio,
            "proxima_coleta_ponto_id": next_window_rule.ponto_coleta_id,
            "proxima_coleta_ponto_nome": next_window_rule.ponto_coleta_nome,
            "deadline_final_horario": deadline_horario,
            "janela_status": status,
            "minutos_ate_proxima_coleta": max(0, minutes_left),
        }

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

