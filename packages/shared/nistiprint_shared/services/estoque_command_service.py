"""Comandos idempotentes de estoque sobre o núcleo transacional do Supabase."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Mapping, Optional

from nistiprint_shared.database.supabase_db_service import supabase_db


class EstoqueCommandError(RuntimeError):
    """Erro ao validar ou executar um comando de estoque."""


class EstoqueCommandConflict(EstoqueCommandError):
    """O mesmo identificador já foi usado com outro conteúdo."""


class EstoqueCommandOutcomeUnknown(EstoqueCommandError):
    """A chamada falhou sem confirmar se o banco concluiu o comando."""

    def __init__(self, operation_id: str, message: str):
        super().__init__(message)
        self.operation_id = operation_id


_MOVEMENT_FIELDS = {
    "produto_id",
    "deposito_id",
    "tipo_movimentacao",
    "quantidade",
    "motivo",
    "documento_referencia",
    "origem_tipo",
    "item_demanda_id",
    "estagio",
    "correlation_id",
    "expected_saldo",
}


def new_operation_id() -> str:
    """Cria uma identidade que o chamador deve persistir antes da primeira tentativa."""
    return str(uuid.uuid4())


def _normalize_movement(value: Mapping[str, Any], actor_id: Optional[int], command_type: str) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("Cada movimento precisa ser um objeto.")
    unknown = set(value) - _MOVEMENT_FIELDS
    if unknown:
        raise ValueError(f"Campos de movimento não permitidos: {', '.join(sorted(unknown))}.")

    try:
        product_id = int(value["produto_id"])
        deposit_id = int(value["deposito_id"])
        quantity = Decimal(str(value["quantidade"]))
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise ValueError("produto_id, deposito_id e quantidade são obrigatórios e válidos.") from exc
    if product_id <= 0 or deposit_id <= 0 or not quantity.is_finite():
        raise ValueError("IDs devem ser positivos e a quantidade deve ser finita.")
    if quantity == 0 and command_type != "BALANCO":
        raise ValueError("A quantidade deve ser diferente de zero, exceto no balanço para saldo zero.")
    if quantity.normalize().as_tuple().exponent < -4:
        raise ValueError("A quantidade admite no máximo quatro casas decimais.")

    movement = {
        "produto_id": product_id,
        "deposito_id": deposit_id,
        "tipo_movimentacao": str(value.get("tipo_movimentacao") or "").strip(),
        "quantidade": format(quantity.normalize(), "f"),
        "motivo": str(value.get("motivo") or ""),
        "documento_referencia": value.get("documento_referencia"),
        "origem_tipo": value.get("origem_tipo"),
        "item_demanda_id": value.get("item_demanda_id"),
        "estagio": value.get("estagio"),
        "correlation_id": value.get("correlation_id"),
    }
    if movement["correlation_id"] is not None:
        try:
            movement["correlation_id"] = str(uuid.UUID(str(movement["correlation_id"])))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("correlation_id deve ser um UUID válido.") from exc
    if value.get("expected_saldo") is not None:
        try:
            expected = Decimal(str(value["expected_saldo"]))
        except (TypeError, ValueError, InvalidOperation) as exc:
            raise ValueError("expected_saldo deve ser numérico.") from exc
        if not expected.is_finite():
            raise ValueError("expected_saldo deve ser finito.")
        if expected.normalize().as_tuple().exponent < -4:
            raise ValueError("expected_saldo admite no máximo quatro casas decimais.")
        movement["expected_saldo"] = format(expected.normalize(), "f")
    if not movement["tipo_movimentacao"]:
        raise ValueError("tipo_movimentacao é obrigatório.")
    return movement


class EstoqueCommandService:
    """Valida o comando, calcula sua identidade semântica e chama uma única RPC."""

    @staticmethod
    def is_enabled() -> bool:
        return os.getenv("ESTOQUE_COMANDOS_V2_ATIVO", "false").strip().lower() in {
            "1", "true", "yes", "on"
        }

    def execute_command(
        self,
        command: Mapping[str, Any],
        actor_context: Optional[Mapping[str, Any]] = None,
        *,
        allow_when_disabled: bool = False,
    ) -> Dict[str, Any]:
        if not self.is_enabled() and not allow_when_disabled:
            raise EstoqueCommandError("Comandos de estoque v2 estão desabilitados neste ambiente.")
        if not isinstance(command, Mapping):
            raise ValueError("O comando precisa ser um objeto.")
        try:
            operation_id = str(uuid.UUID(str(command["operation_id"])))
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            raise ValueError("operation_id deve ser um UUID estável.") from exc

        command_type = str(command.get("command_type") or "").strip().upper()
        raw_movements = command.get("movimentos")
        if not command_type or not isinstance(raw_movements, list) or not raw_movements:
            raise ValueError("command_type e uma lista não vazia de movimentos são obrigatórios.")

        actor_id = None
        if actor_context and actor_context.get("id") is not None:
            actor_id = int(actor_context["id"])
        movements = [_normalize_movement(m, actor_id, command_type) for m in raw_movements]
        movements.sort(key=lambda m: (m["produto_id"], m["deposito_id"], m["tipo_movimentacao"], m["quantidade"]))

        semantic = {
            "command_type": command_type,
            "source": command.get("source") or {},
            "actor_id": actor_id,
            "movimentos": movements,
        }
        canonical = json.dumps(semantic, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        content_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        params = {
            "p_operation_id": operation_id,
            "p_command_type": command_type,
            "p_content_hash": content_hash,
            "p_source": semantic["source"],
            "p_actor_id": actor_id,
            "p_movimentos": movements,
        }

        try:
            response = supabase_db.rpc("executar_comando_estoque", params).execute()
        except Exception as exc:
            detail = str(exc)
            if "23505" in detail or "40001" in detail or "conteúdo diferente" in detail:
                raise EstoqueCommandConflict(detail) from exc
            raise EstoqueCommandOutcomeUnknown(operation_id, detail) from exc
        if not response or not response.data:
            raise EstoqueCommandOutcomeUnknown(
                operation_id,
                "A operação não retornou confirmação; consulte ou repita usando o mesmo operation_id.",
            )
        result = response.data[0] if isinstance(response.data, list) else response.data
        return dict(result) if isinstance(result, Mapping) else {"result": result}

    def get_operation(self, operation_id: str, actor_context: Optional[Mapping[str, Any]] = None) -> Optional[Dict[str, Any]]:
        try:
            normalized_id = str(uuid.UUID(str(operation_id)))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("operation_id deve ser um UUID válido.") from exc
        response = (
            supabase_db.table("estoque_operacoes")
            .select("operation_id,command_type,source,actor_id,status,result,created_at,confirmed_at")
            .eq("operation_id", normalized_id)
            .limit(1)
            .execute()
        )
        if not response.data:
            return None
        operation = dict(response.data[0])
        if actor_context and not actor_context.get("is_admin"):
            actor_id = actor_context.get("id")
            if actor_id is None or str(actor_id) != str(operation.get("actor_id")):
                raise PermissionError("Acesso negado a esta operação de estoque.")
        return operation


estoque_command_service = EstoqueCommandService()
