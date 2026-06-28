from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.demanda_producao_service import demanda_producao_service
from nistiprint_shared.utils.date_utils import get_now_iso


TERMINAL_ORDER_STATUS_IDS = {5, 6, 7}
TERMINAL_DEMAND_STATUSES = {"CONCLUIDO", "COLETADO", "CANCELADO", "FINALIZADO"}
LEGACY_DRAFT_DEMAND_STATUSES = {"AGUARDANDO", "RASCUNHO"}


class ProductionLotSuggestionsService:
    def normalize_modalidade(
        self,
        modalidade: Optional[str],
        *,
        is_flex: bool = False,
        is_fulfillment: bool = False,
    ) -> str:
        raw = (modalidade or "").strip().upper()
        if raw in {"FLEX", "EXPRESS"} or is_flex:
            return "EXPRESS"
        if raw == "FULFILLMENT" or is_fulfillment:
            return "FULFILLMENT"
        if raw == "RETIRADA":
            return "RETIRADA"
        return "STANDARD"

    def get_modalidade_label(self, modalidade: Optional[str]) -> str:
        normalized = self.normalize_modalidade(modalidade)
        labels = {
            "STANDARD": "Normal",
            "EXPRESS": "Flex",
            "FULFILLMENT": "Fulfillment",
            "RETIRADA": "Retirada",
        }
        return labels.get(normalized, normalized.title())

    def build_suggestion_key(
        self,
        *,
        marketplace_integration_id: int,
        modalidade: str,
        regra_logistica_integracao_id: int,
        data_coleta: str,
    ) -> str:
        return (
            f"mp={int(marketplace_integration_id)}|"
            f"mod={self.normalize_modalidade(modalidade)}|"
            f"rule={int(regra_logistica_integracao_id)}|"
            f"collect={data_coleta}"
        )

    def parse_suggestion_key(self, suggestion_key: str) -> Dict[str, Any]:
        parts: Dict[str, str] = {}
        for chunk in str(suggestion_key or "").split("|"):
            if "=" not in chunk:
                continue
            key, value = chunk.split("=", 1)
            parts[key] = value

        required = {"mp", "mod", "rule", "collect"}
        if not required.issubset(parts):
            raise ValueError("Sugestao invalida.")

        return {
            "marketplace_integration_id": int(parts["mp"]),
            "modalidade": self.normalize_modalidade(parts["mod"]),
            "regra_logistica_integracao_id": int(parts["rule"]),
            "data_coleta": parts["collect"],
        }

    def _safe_parse_dt(self, value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None

    def _serialize_dt(self, value: Optional[str]) -> Optional[str]:
        parsed = self._safe_parse_dt(value)
        return parsed.isoformat() if parsed else value

    def _format_collection_label(self, value: Optional[str]) -> str:
        parsed = self._safe_parse_dt(value)
        if not parsed:
            return "Coleta indefinida"
        return parsed.strftime("%d/%m %H:%M")

    def _build_order_suggestion_key(self, order: Dict[str, Any]) -> Optional[str]:
        marketplace_integration_id = order.get("marketplace_integration_id")
        rule_id = order.get("regra_logistica_integracao_id")
        data_coleta = self._serialize_dt(order.get("data_coleta"))
        if marketplace_integration_id is None or rule_id is None or not data_coleta:
            return None
        try:
            return self.build_suggestion_key(
                marketplace_integration_id=int(marketplace_integration_id),
                modalidade=self.normalize_modalidade(
                    order.get("modalidade_logistica"),
                    is_flex=bool(order.get("is_flex")),
                    is_fulfillment=bool(order.get("is_fulfillment")),
                ),
                regra_logistica_integracao_id=int(rule_id),
                data_coleta=data_coleta,
            )
        except (TypeError, ValueError):
            return None

    def _fetch_order_rows(self, order_ids: Optional[Sequence[int]] = None) -> List[Dict[str, Any]]:
        query = (
            supabase_db.table("pedidos")
            .select(
                "id,numero_pedido,codigo_pedido_externo,cliente_nome,canal_venda_id,"
                "marketplace_integration_id,situacao_pedido_id,is_flex,is_fulfillment,"
                "modalidade_logistica,data_coleta,data_limite_envio,data_pagamento_marketplace,"
                "data_compra_marketplace,regra_logistica_integracao_id,personalizado,created_at"
            )
            .order("data_coleta", desc=False)
            .order("created_at", desc=False)
        )
        if order_ids:
            query = query.in_("id", list(order_ids))
        else:
            query = query.limit(2000)
        response = supabase_db.execute_with_retry(query)
        return response.data or []

    def _fetch_order_items(self, order_ids: Sequence[int]) -> Dict[int, List[Dict[str, Any]]]:
        if not order_ids:
            return {}
        response = supabase_db.execute_with_retry(
            supabase_db.table("itens_pedido")
            .select("pedido_id,produto_id,sku_externo,descricao,quantidade")
            .in_("pedido_id", list(order_ids))
        )
        grouped: Dict[int, List[Dict[str, Any]]] = {}
        for row in response.data or []:
            grouped.setdefault(int(row["pedido_id"]), []).append(row)
        return grouped

    def _fetch_demand_links(self, order_ids: Sequence[int]) -> Dict[int, List[Dict[str, Any]]]:
        if not order_ids:
            return {}
        response = supabase_db.execute_with_retry(
            supabase_db.table("demandas_pedidos")
            .select("pedido_id,demanda_id")
            .in_("pedido_id", list(order_ids))
        )
        grouped: Dict[int, List[Dict[str, Any]]] = {}
        for row in response.data or []:
            grouped.setdefault(int(row["pedido_id"]), []).append(row)
        return grouped

    def _fetch_demand_rows(self, demand_ids: Iterable[int]) -> Dict[int, Dict[str, Any]]:
        ids = sorted({int(did) for did in demand_ids if did is not None})
        if not ids:
            return {}
        response = supabase_db.execute_with_retry(
            supabase_db.table("demandas_producao")
            .select("id,demanda_id,descricao,status,data_coleta,modalidade_logistica,dados_adicionais")
            .in_("id", ids)
        )
        return {int(row["id"]): row for row in (response.data or []) if row.get("id") is not None}

    def _fetch_marketplace_map(self, marketplace_ids: Iterable[int]) -> Dict[int, Dict[str, Any]]:
        ids = sorted({int(mid) for mid in marketplace_ids if mid is not None})
        if not ids:
            return {}
        response = supabase_db.execute_with_retry(
            supabase_db.table("installed_integrations")
            .select("id,instance_name,module_id")
            .in_("id", ids)
        )
        rows = response.data or []
        module_ids = sorted({row.get("module_id") for row in rows if row.get("module_id")})
        module_map: Dict[str, Dict[str, Any]] = {}
        if module_ids:
            module_res = supabase_db.execute_with_retry(
                supabase_db.table("integration_modules").select("id,slug").in_("id", module_ids)
            )
            module_map = {
                row["id"]: row
                for row in (module_res.data or [])
                if row.get("id") is not None
            }

        output: Dict[int, Dict[str, Any]] = {}
        for row in rows:
            module = module_map.get(row.get("module_id")) or {}
            output[int(row["id"])] = {
                "id": int(row["id"]),
                "instance_name": row.get("instance_name") or f"Marketplace #{row['id']}",
                "module_id": row.get("module_id"),
                "slug": module.get("slug"),
            }
        return output

    def _fetch_rule_map(self, rule_ids: Iterable[int]) -> Dict[int, Dict[str, Any]]:
        ids = sorted({int(rid) for rid in rule_ids if rid is not None})
        if not ids:
            return {}
        response = supabase_db.execute_with_retry(
            supabase_db.table("regras_logisticas_integracao")
            .select("id,horario_corte,horario_coleta,tipo_envio,ponto_coleta_id,descricao")
            .in_("id", ids)
        )
        rows = response.data or []
        point_ids = sorted({row.get("ponto_coleta_id") for row in rows if row.get("ponto_coleta_id") is not None})
        point_map: Dict[int, Dict[str, Any]] = {}
        if point_ids:
            point_res = supabase_db.execute_with_retry(
                supabase_db.table("pontos_coleta").select("id,nome").in_("id", point_ids)
            )
            point_map = {
                int(row["id"]): row
                for row in (point_res.data or [])
                if row.get("id") is not None
            }

        output: Dict[int, Dict[str, Any]] = {}
        for row in rows:
            point = point_map.get(int(row["ponto_coleta_id"])) if row.get("ponto_coleta_id") is not None else None
            output[int(row["id"])] = {
                **row,
                "ponto_coleta_nome": (point or {}).get("nome"),
            }
        return output

    def _extract_marketplace_from_demand(self, demand_row: Dict[str, Any]) -> Optional[int]:
        dados = demand_row.get("dados_adicionais") or {}
        if isinstance(dados, dict):
            value = dados.get("marketplace_integration_id")
            if value is not None:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return None
        return None

    def _extract_rule_id_from_demand(self, demand_row: Dict[str, Any]) -> Optional[int]:
        dados = demand_row.get("dados_adicionais") or {}
        if not isinstance(dados, dict):
            return None
        direct = dados.get("regra_logistica_integracao_id")
        if direct is not None:
            try:
                return int(direct)
            except (TypeError, ValueError):
                return None
        coleta_contexto = dados.get("coleta_contexto") or {}
        regra = coleta_contexto.get("regra") or {}
        if regra.get("id") is None:
            return None
        try:
            return int(regra["id"])
        except (TypeError, ValueError):
            return None

    def _build_active_demand_lookup(self) -> Dict[str, Dict[str, Any]]:
        response = supabase_db.execute_with_retry(
            supabase_db.table("demandas_producao")
            .select("id,demanda_id,descricao,status,data_coleta,modalidade_logistica,dados_adicionais")
        )
        lookup: Dict[str, Dict[str, Any]] = {}
        for row in response.data or []:
            status = str(row.get("status") or "").upper()
            if status in TERMINAL_DEMAND_STATUSES or status in LEGACY_DRAFT_DEMAND_STATUSES:
                continue
            marketplace_integration_id = self._extract_marketplace_from_demand(row)
            rule_id = self._extract_rule_id_from_demand(row)
            data_coleta = self._serialize_dt(row.get("data_coleta"))
            if not marketplace_integration_id or not rule_id or not data_coleta:
                continue
            key = self.build_suggestion_key(
                marketplace_integration_id=marketplace_integration_id,
                modalidade=row.get("modalidade_logistica"),
                regra_logistica_integracao_id=rule_id,
                data_coleta=data_coleta,
            )
            lookup[key] = {
                "id": row.get("id"),
                "demanda_id": row.get("demanda_id"),
                "descricao": row.get("descricao"),
                "status": row.get("status"),
            }
        return lookup

    def _consolidate_items(
        self,
        orders: Sequence[Dict[str, Any]],
        items_by_order: Dict[int, List[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        grouped: Dict[Tuple[Any, str], Dict[str, Any]] = {}
        for order in orders:
            for item in items_by_order.get(int(order["id"]), []):
                key = (item.get("produto_id"), item.get("sku_externo") or "")
                if key not in grouped:
                    grouped[key] = {
                        "produto_id": item.get("produto_id"),
                        "sku": item.get("sku_externo"),
                        "descricao": item.get("descricao") or "Item sem descricao",
                        "quantidade": 0,
                        "pedido_ids": [],
                        "quantidades_por_pedido": {},
                    }
                item_quantidade = int(item.get("quantidade") or 0)
                grouped[key]["quantidade"] += item_quantidade
                grouped[key]["pedido_ids"].append(int(order["id"]))
                grouped[key]["quantidades_por_pedido"][str(int(order["id"]))] = (
                    grouped[key]["quantidades_por_pedido"].get(str(int(order["id"])), 0) + item_quantidade
                )
        return sorted(grouped.values(), key=lambda item: ((item.get("descricao") or "").lower(), item.get("sku") or ""))

    def _summarize_orders(
        self,
        orders: Sequence[Dict[str, Any]],
        items_by_order: Dict[int, List[Dict[str, Any]]],
        marketplace_map: Dict[int, Dict[str, Any]],
        rule_map: Dict[int, Dict[str, Any]],
        active_lookup: Dict[str, Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        suggestions: Dict[str, Dict[str, Any]] = {}
        exceptions: List[Dict[str, Any]] = []

        for order in orders:
            order_id = int(order["id"])
            items = items_by_order.get(order_id, [])
            if int(order.get("situacao_pedido_id") or 0) in TERMINAL_ORDER_STATUS_IDS:
                continue

            modalidade = self.normalize_modalidade(
                order.get("modalidade_logistica"),
                is_flex=bool(order.get("is_flex")),
                is_fulfillment=bool(order.get("is_fulfillment")),
            )
            marketplace_integration_id = order.get("marketplace_integration_id")
            rule_id = order.get("regra_logistica_integracao_id")
            data_coleta = self._serialize_dt(order.get("data_coleta"))

            exception_reason = None
            if not items:
                exception_reason = "Sem itens no pedido"
            elif not marketplace_integration_id:
                exception_reason = "Pedido sem origem canonica"
            elif not rule_id:
                exception_reason = "Pedido sem regra logistica vinculada"
            elif not data_coleta:
                exception_reason = "Pedido sem data de coleta calculada"

            if exception_reason:
                exceptions.append(
                    {
                        "pedido_id": order_id,
                        "numero_pedido": order.get("numero_pedido"),
                        "codigo_pedido_externo": order.get("codigo_pedido_externo"),
                        "cliente_nome": order.get("cliente_nome"),
                        "marketplace_integration_id": marketplace_integration_id,
                        "modalidade": modalidade,
                        "motivo": exception_reason,
                    }
                )
                continue

            suggestion_key = self.build_suggestion_key(
                marketplace_integration_id=int(marketplace_integration_id),
                modalidade=modalidade,
                regra_logistica_integracao_id=int(rule_id),
                data_coleta=data_coleta,
            )
            suggestion = suggestions.get(suggestion_key)
            if suggestion is None:
                marketplace = marketplace_map.get(int(marketplace_integration_id)) or {}
                rule = rule_map.get(int(rule_id)) or {}
                suggestion = {
                    "suggestion_key": suggestion_key,
                    "marketplace_integration_id": int(marketplace_integration_id),
                    "marketplace_nome": marketplace.get("instance_name") or f"Marketplace #{marketplace_integration_id}",
                    "marketplace_slug": marketplace.get("slug"),
                    "modalidade": modalidade,
                    "modalidade_label": self.get_modalidade_label(modalidade),
                    "regra_logistica_integracao_id": int(rule_id),
                    "horario_corte": rule.get("horario_corte"),
                    "horario_coleta": rule.get("horario_coleta"),
                    "tipo_envio": rule.get("tipo_envio"),
                    "ponto_coleta_nome": rule.get("ponto_coleta_nome"),
                    "descricao_regra": rule.get("descricao"),
                    "data_coleta": data_coleta,
                    "data_coleta_label": self._format_collection_label(data_coleta),
                    "pedido_ids": [],
                    "canal_venda_ids": [],
                    "itens_total": 0,
                    "skus_unicos": set(),
                    "warnings": [],
                }
                active_demand = active_lookup.get(suggestion_key)
                if active_demand:
                    suggestion["complemento_demanda"] = active_demand
                suggestions[suggestion_key] = suggestion

            suggestion["pedido_ids"].append(order_id)
            if order.get("canal_venda_id") is not None:
                suggestion["canal_venda_ids"].append(int(order["canal_venda_id"]))
            suggestion["itens_total"] += sum(int(item.get("quantidade") or 0) for item in items)
            suggestion["skus_unicos"].update(
                (item.get("sku_externo") or f"produto:{item.get('produto_id')}")
                for item in items
            )
            if order.get("personalizado"):
                suggestion["warnings"].append(f"Pedido {order.get('numero_pedido') or order_id} personalizado")

        suggestion_list: List[Dict[str, Any]] = []
        for suggestion in suggestions.values():
            channel_counter = Counter(suggestion.pop("canal_venda_ids", []))
            suggestion["canal_venda_id"] = channel_counter.most_common(1)[0][0] if channel_counter else None
            suggestion["total_pedidos"] = len(suggestion["pedido_ids"])
            suggestion["total_itens"] = suggestion.pop("itens_total")
            suggestion["total_skus"] = len(suggestion.pop("skus_unicos"))
            suggestion["warnings"] = sorted(set(suggestion["warnings"]))
            if len(channel_counter) > 1:
                suggestion["warnings"].append("Pedidos de mais de um canal interno; o lote usara o canal dominante.")
            suggestion_list.append(suggestion)

        suggestion_list.sort(key=lambda item: (item.get("data_coleta") or "9999-12-31T23:59:59", item.get("marketplace_nome") or ""))
        exceptions.sort(key=lambda item: ((item.get("marketplace_integration_id") or 0), item.get("numero_pedido") or ""))
        return suggestion_list, exceptions

    def _eligible_orders_with_context(
        self,
        order_ids: Optional[Sequence[int]] = None,
    ) -> Dict[str, Any]:
        orders = self._fetch_order_rows(order_ids)
        if not orders:
            return {"orders": [], "items_by_order": {}, "links_by_order": {}, "demands_by_id": {}}

        items_by_order = self._fetch_order_items([int(order["id"]) for order in orders])
        links_by_order = self._fetch_demand_links([int(order["id"]) for order in orders])
        demand_ids = [
            int(link["demanda_id"])
            for links in links_by_order.values()
            for link in links
            if link.get("demanda_id") is not None
        ]
        demands_by_id = self._fetch_demand_rows(demand_ids)

        eligible_orders: List[Dict[str, Any]] = []
        for order in orders:
            linked_demand_rows = [
                demands_by_id.get(int(link["demanda_id"]))
                for link in links_by_order.get(int(order["id"]), [])
                if link.get("demanda_id") is not None
            ]
            non_terminal_links = [
                demand
                for demand in linked_demand_rows
                if demand and str(demand.get("status") or "").upper() not in TERMINAL_DEMAND_STATUSES
            ]
            order["linked_demandas"] = [d for d in linked_demand_rows if d]
            if non_terminal_links:
                order["blocked_by_demanda"] = non_terminal_links[0]
                continue
            eligible_orders.append(order)

        return {
            "orders": eligible_orders,
            "items_by_order": items_by_order,
            "links_by_order": links_by_order,
            "demands_by_id": demands_by_id,
        }

    def list_suggestions(self, search_term: Optional[str] = None) -> Dict[str, Any]:
        context = self._eligible_orders_with_context()
        orders = context["orders"]
        if search_term:
            term = str(search_term).strip().lower()
            orders = [
                order
                for order in orders
                if term in str(order.get("numero_pedido") or "").lower()
                or term in str(order.get("codigo_pedido_externo") or "").lower()
                or term in str(order.get("cliente_nome") or "").lower()
            ]

        marketplace_ids = [int(order["marketplace_integration_id"]) for order in orders if order.get("marketplace_integration_id") is not None]
        rule_ids = [int(order["regra_logistica_integracao_id"]) for order in orders if order.get("regra_logistica_integracao_id") is not None]
        marketplace_map = self._fetch_marketplace_map(marketplace_ids)
        rule_map = self._fetch_rule_map(rule_ids)
        active_lookup = self._build_active_demand_lookup()
        suggestions, exceptions = self._summarize_orders(
            orders,
            context["items_by_order"],
            marketplace_map,
            rule_map,
            active_lookup,
        )

        return {
            "updated_at": get_now_iso(),
            "suggestions": suggestions,
            "exceptions": exceptions,
            "legacy_drafts_count": self._count_legacy_drafts(),
        }

    def _count_legacy_drafts(self) -> int:
        response = supabase_db.execute_with_retry(
            supabase_db.table("demandas_producao").select("id", count="exact").eq("status", "AGUARDANDO")
        )
        return int(getattr(response, "count", 0) or 0)

    def get_suggestion_detail(self, suggestion_key: str) -> Dict[str, Any]:
        parsed = self.parse_suggestion_key(suggestion_key)
        context = self._eligible_orders_with_context()
        marketplace_ids = [int(order["marketplace_integration_id"]) for order in context["orders"] if order.get("marketplace_integration_id") is not None]
        rule_ids = [int(order["regra_logistica_integracao_id"]) for order in context["orders"] if order.get("regra_logistica_integracao_id") is not None]
        marketplace_map = self._fetch_marketplace_map(marketplace_ids)
        rule_map = self._fetch_rule_map(rule_ids)
        active_lookup = self._build_active_demand_lookup()
        suggestions, exceptions = self._summarize_orders(
            context["orders"],
            context["items_by_order"],
            marketplace_map,
            rule_map,
            active_lookup,
        )
        suggestion = next((item for item in suggestions if item["suggestion_key"] == suggestion_key), None)
        if not suggestion:
            raise ValueError("Sugestao indisponivel ou desatualizada.")

        grouped_orders = [
            order
            for order in context["orders"]
            if self._build_order_suggestion_key(order) == suggestion_key
        ]
        consolidated_items = self._consolidate_items(grouped_orders, context["items_by_order"])

        return {
            **suggestion,
            "grouping": parsed,
            "orders": [
                {
                    "id": int(order["id"]),
                    "numero_pedido": order.get("numero_pedido"),
                    "codigo_pedido_externo": order.get("codigo_pedido_externo"),
                    "cliente_nome": order.get("cliente_nome"),
                    "canal_venda_id": order.get("canal_venda_id"),
                    "data_pagamento_marketplace": self._serialize_dt(order.get("data_pagamento_marketplace")),
                    "data_compra_marketplace": self._serialize_dt(order.get("data_compra_marketplace")),
                    "data_limite_envio": self._serialize_dt(order.get("data_limite_envio")),
                    "total_itens": sum(int(item.get("quantidade") or 0) for item in context["items_by_order"].get(int(order["id"]), [])),
                    "is_personalizado": bool(order.get("personalizado")),
                }
                for order in grouped_orders
            ],
            "items": consolidated_items,
            "exceptions": [
                item
                for item in exceptions
                if int(item.get("marketplace_integration_id") or 0) == parsed["marketplace_integration_id"]
                and item.get("modalidade") == parsed["modalidade"]
            ],
        }

    def _build_demanda_name(self, detail: Dict[str, Any], override_name: Optional[str] = None) -> str:
        if override_name:
            return override_name
        complemento = detail.get("complemento_demanda")
        if complemento:
            code = complemento.get("demanda_id") or complemento.get("id")
            return f"Complemento da demanda {code}"
        return (
            f"Lote {detail.get('marketplace_nome')} - "
            f"{detail.get('modalidade_label')} - "
            f"{detail.get('data_coleta_label')}"
        )

    def confirm_suggestion(
        self,
        suggestion_key: str,
        included_order_ids: Sequence[int],
        *,
        user_id: str,
        nome_demanda: Optional[str] = None,
        observacoes: Optional[str] = None,
    ) -> Dict[str, Any]:
        detail = self.get_suggestion_detail(suggestion_key)
        selected_ids = sorted({int(order_id) for order_id in included_order_ids})
        if not selected_ids:
            raise ValueError("Selecione pelo menos um pedido compativel.")

        compatible_ids = {int(order["id"]) for order in detail["orders"]}
        if not set(selected_ids).issubset(compatible_ids):
            raise ValueError("Ha pedidos selecionados que nao pertencem mais a este lote.")

        context = self._eligible_orders_with_context(selected_ids)
        current_orders = context["orders"]
        current_ids = {int(order["id"]) for order in current_orders}
        if current_ids != set(selected_ids):
            raise RuntimeError("Sugestao desatualizada. Atualize a tela antes de confirmar.")

        selected_orders = []
        for order in current_orders:
            rebuilt_key = self._build_order_suggestion_key(order)
            if rebuilt_key != suggestion_key:
                raise RuntimeError("Sugestao desatualizada. Os pedidos mudaram de janela logistica.")
            selected_orders.append(order)

        consolidated_items = self._consolidate_items(selected_orders, context["items_by_order"])
        if not consolidated_items:
            raise ValueError("Nao ha itens validos para consolidar.")

        demanda = demanda_producao_service.criar_demanda_direta(
            nome_demanda=self._build_demanda_name(detail, nome_demanda),
            canal_venda_id=detail.get("canal_venda_id"),
            data_entrega_str=(self._safe_parse_dt(detail.get("data_coleta")) or datetime.now()).date().isoformat(),
            lista_de_itens=consolidated_items,
            horario_coleta_especifico=detail.get("horario_coleta"),
            observacoes=observacoes,
            user_id=user_id,
            tipo_demanda="PLATAFORMA",
            status="EM_PRODUCAO",
            data_coleta=detail.get("data_coleta"),
            marketplace_integration_id=detail.get("marketplace_integration_id"),
            modalidade_logistica=detail.get("modalidade"),
            regra_logistica_integracao_id=detail.get("regra_logistica_integracao_id"),
        )
        if not demanda:
            raise RuntimeError("Falha ao criar demanda.")

        demanda_id = int(demanda["id"])
        link_payload = [{"demanda_id": demanda_id, "pedido_id": order_id} for order_id in selected_ids]
        supabase_db.execute_with_retry(
            supabase_db.table("demandas_pedidos").upsert(link_payload, on_conflict="demanda_id,pedido_id")
        )

        return {
            "demanda_id": demanda_id,
            "demanda_uuid": demanda.get("demanda_id"),
            "total_pedidos": len(selected_ids),
            "total_itens": len(consolidated_items),
            "nome_demanda": demanda.get("nome") or demanda.get("descricao"),
            "complemento_demanda": detail.get("complemento_demanda"),
        }


production_lot_suggestions_service = ProductionLotSuggestionsService()



