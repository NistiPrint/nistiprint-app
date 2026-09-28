"""Planejamento persistente e rastreabilidade da impressão de capas."""

import hashlib
import json
import logging
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.app_config_service import app_config_service
from nistiprint_shared.services.bom_service import bom_service
from nistiprint_shared.services.product_service import product_service
from routes.auth import get_current_user

logger = logging.getLogger("ImpressaoCapasAPI")
impressao_capas_bp = Blueprint("impressao_capas", __name__, url_prefix="/api/v2/impressao-capas")


def _ids_validos(values):
    if not isinstance(values, list):
        raise ValueError("pedido_ids deve ser uma lista")
    ids = []
    for value in values:
        if isinstance(value, bool) or not str(value).isdigit() or int(value) <= 0:
            raise ValueError("pedido_ids deve conter IDs inteiros positivos")
        ids.append(int(value))
    return sorted(set(ids))


def _key(sku, variation):
    return (str(sku or "").strip().casefold(), str(variation or "").strip().casefold())


def _cover_components(product_id, category_id=None):
    """Resolve capas imprimíveis da ficha técnica, inclusive artes recursivas."""
    found = {}

    # O cadastro de arte local já tem um resolvedor recursivo que acompanha
    # categorias marcadas com permite_arte e devolve o SKU usado pelo agente.
    # Preferi-lo mantém o plano alinhado ao cadastro exibido no produto.
    try:
        from nistiprint_shared.services.recursive_artwork_service import recursive_artwork_service
        for artwork in recursive_artwork_service.list_for_product(str(product_id)):
            label = " ".join(str(artwork.get(field) or "") for field in ("name", "sku", "category_name")).casefold()
            category_matches = bool(category_id) and str(artwork.get("category_id")) == str(category_id)
            name_identifies_printed_cover = "capa" in label and "impress" in label
            if not category_matches and not name_identifies_printed_cover:
                continue
            component_id = int(artwork.get("product_id"))
            found[component_id] = {
                "produto_capa_id": component_id,
                "sku_capa": artwork.get("sku"),
                "capa_nome": artwork.get("name") or artwork.get("sku"),
                "quantidade_por_unidade": float(artwork.get("quantity") or 1),
            }
        if found:
            return list(found.values())
    except Exception:
        logger.warning("Não foi possível resolver artes recursivas para o produto %s", product_id, exc_info=True)

    def walk(parent_id, multiplier, path):
        if not parent_id or str(parent_id) in path or len(path) >= 20:
            return
        for component in bom_service.get_bom_for_produto(int(parent_id)):
            component_id = int(component.componente_id)
            if str(component_id) in path:
                continue
            product = product_service.get_by_id(str(component_id)) or {}
            quantity = multiplier * float(component.quantidade or 1)
            category_name = ""
            if product.get("categoria_id"):
                try:
                    from nistiprint_shared.services.category_service import category_service
                    category = category_service.get_by_id(str(product["categoria_id"])) or {}
                    category_name = str(category.get("nome") or category.get("name") or "")
                except Exception:
                    logger.debug("Não foi possível obter a categoria do produto %s", component_id, exc_info=True)
            label = " ".join((
                str(product.get("nome") or product.get("name") or ""),
                str(product.get("sku") or ""), category_name,
            )).casefold()
            is_printed_cover = (
                (bool(category_id) and str(product.get("categoria_id")) == str(category_id))
                or ("capa" in label and "impress" in label)
            )
            if is_printed_cover:
                row = found.setdefault(component_id, {
                    "produto_capa_id": component_id,
                    "sku_capa": product.get("sku"),
                    "capa_nome": product.get("nome") or product.get("name") or product.get("sku"),
                    "quantidade_por_unidade": 0,
                })
                row["quantidade_por_unidade"] += quantity
            else:
                walk(component_id, quantity, path | {str(component_id)})

    walk(product_id, 1, {str(product_id)})
    return list(found.values())


def _serialize_plan(plan_id):
    plan = (supabase_db.table("impressao_capas_planos").select("*")
            .eq("id", plan_id).limit(1).execute().data or [])
    if not plan:
        return None
    plan = plan[0]
    items = (supabase_db.table("impressao_capas_itens").select("*")
             .eq("plano_id", plan_id).order("capa_nome").order("id").execute().data or [])
    sends = (supabase_db.table("impressao_capas_envios").select("*")
             .eq("plano_id", plan_id).order("created_at", desc=True).execute().data or [])
    groups = (supabase_db.table("impressao_capas_grupos").select("*")
              .eq("plano_id", plan_id).execute().data or [])
    plan["itens"] = items
    plan["envios"] = sends
    plan["grupos"] = groups
    return plan


@impressao_capas_bp.route("/planos", methods=["POST"])
def criar_ou_atualizar_plano():
    user = get_current_user()
    if not user:
        return jsonify({"success": False, "error": "Não autorizado"}), 401
    try:
        body = request.get_json(silent=True) or {}
        pedido_ids = _ids_validos(body.get("pedido_ids"))
        linhas = body.get("linhas") if isinstance(body.get("linhas"), list) else []
        preview_informada = isinstance(body.get("linhas"), list)
        if not pedido_ids:
            return jsonify({"success": False, "error": "O escopo não contém pedidos"}), 400
        if not isinstance(linhas, list):
            return jsonify({"success": False, "error": "linhas deve ser uma lista"}), 400

        pedido_rows = (supabase_db.table("pedidos").select("id,codigo_pedido_externo,origem")
                       .in_("id", pedido_ids).execute().data or [])
        existing_ids = {int(row["id"]) for row in pedido_rows}
        pedido_ids = [value for value in pedido_ids if value in existing_ids]
        if not pedido_ids:
            return jsonify({"success": False, "error": "Nenhum pedido do escopo ainda está disponível"}), 409

        scope_key = hashlib.sha256(json.dumps(pedido_ids).encode("utf-8")).hexdigest()
        plan_rows = (supabase_db.table("impressao_capas_planos").select("id")
                     .eq("chave_escopo", scope_key).limit(1).execute().data or [])
        now_user = str(user.get("id") or user.get("email") or user.get("nome") or "System")
        if plan_rows:
            plan_id = plan_rows[0]["id"]
            supabase_db.table("impressao_capas_planos").update({
                "pedido_ids": pedido_ids,
                "previsao_versao": body.get("previsao_versao"),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", plan_id).execute()
        else:
            inserted = supabase_db.table("impressao_capas_planos").insert({
                "chave_escopo": scope_key,
                "pedido_ids": pedido_ids,
                "previsao_versao": body.get("previsao_versao"),
                "criado_por": now_user,
            }).execute().data or []
            plan_id = inserted[0]["id"]

        item_rows = (supabase_db.table("itens_pedido").select("*")
                     .in_("pedido_id", pedido_ids).order("pedido_id").order("id").execute().data or [])
        item_ids = [int(item["id"]) for item in item_rows if item.get("id")]
        item_to_order = {int(item["id"]): int(item["pedido_id"]) for item in item_rows if item.get("id") and item.get("pedido_id")}
        order_code_by_id = {int(row["id"]): row.get("codigo_pedido_externo") for row in pedido_rows}
        order_origin_by_id = {int(row["id"]): row.get("origem") for row in pedido_rows}
        custom_rows = []
        if item_ids:
            custom_rows = (supabase_db.table("personalizacoes_pedido").select("*")
                           .in_("item_pedido_id", item_ids).execute().data or [])
        # Vinculação legada por pedido externo + descrição, apenas para registros
        # que ainda não receberam item_pedido_id.
        external_codes = list({str(order_code_by_id.get(pid)) for pid in pedido_ids if order_code_by_id.get(pid)})
        if external_codes:
            legacy = (supabase_db.table("personalizacoes_pedido").select("*")
                      .in_("shopee_order_sn", external_codes).execute().data or [])
            seen = {row.get("id") for row in custom_rows}
            custom_rows.extend(row for row in legacy if row.get("id") not in seen and not row.get("item_pedido_id"))
        custom_by_item = {}
        for personalization in custom_rows:
            item_id = personalization.get("item_pedido_id")
            if item_id is None:
                description = str(personalization.get("item_description") or "").strip().casefold()
                code = str(personalization.get("shopee_order_sn") or "")
                candidates = [item for item in item_rows
                              if order_code_by_id.get(int(item.get("pedido_id") or 0)) == code
                              and str(item.get("descricao") or "").strip().casefold() == description]
                if len(candidates) == 1:
                    item_id = candidates[0].get("id")
            if item_id is not None:
                custom_by_item.setdefault(int(item_id), []).append(personalization)

        # Keep the same default used by the production dashboard while also
        # recognizing printed-cover components by their catalog labels below.
        cover_category = app_config_service.get_config("producao_capas_impressas_category_id") or "13"
        line_targets = {}
        line_targets_by_sku = {}
        line_products_by_key = {}
        line_products_by_sku = {}
        for line in linhas:
            sku = line.get("sku") or line.get("sku_externo")
            variation = line.get("variacao")
            try:
                quantity = Decimal(str(line.get("quantidade") or 0))
            except InvalidOperation:
                continue
            target_key = _key(sku, variation)
            line_targets[target_key] = line_targets.get(target_key, Decimal(0)) + max(Decimal(0), quantity)
            sku_key = target_key[0]
            line_targets_by_sku[sku_key] = line_targets_by_sku.get(sku_key, Decimal(0)) + max(Decimal(0), quantity)
            if line.get("produto_id"):
                line_products_by_key[target_key] = line.get("produto_id")
                line_products_by_sku[sku_key] = line.get("produto_id")

        source_totals = {}
        source_totals_by_sku = {}
        resolved_product_ids = {}
        for item in item_rows:
            sku = item.get("sku_externo") or ""
            variation = item.get("variacao_externa") or item.get("variacao") or ""
            key = _key(sku, variation)
            source_totals[key] = source_totals.get(key, Decimal(0)) + Decimal(str(item.get("quantidade") or 0))
            source_totals_by_sku[key[0]] = source_totals_by_sku.get(key[0], Decimal(0)) + Decimal(str(item.get("quantidade") or 0))

        payload = {}
        for item in item_rows:
            item_id = int(item["id"])
            order_id = item_to_order[item_id]
            item_sku = item.get("sku_externo") or ""
            variation = item.get("variacao_externa") or item.get("variacao") or ""
            key = _key(item_sku, variation)
            base_product_id = item.get("produto_id") or line_products_by_key.get(key) or line_products_by_sku.get(key[0])
            if not base_product_id and item.get("sku_externo"):
                order_origin = order_origin_by_id.get(order_id)
                cache_key = (item_sku.strip().casefold(), str(order_origin or "").casefold())
                if cache_key not in resolved_product_ids:
                    identity = product_service.resolver_identificacao_completa(item_sku, order_origin)
                    resolved_product_ids[cache_key] = (identity or {}).get("produto_id")
                base_product_id = resolved_product_ids[cache_key]
            if not base_product_id and item_sku:
                product = product_service.get_by_sku(item_sku)
                base_product_id = (product or {}).get("id")
            item_quantity = Decimal(str(item.get("quantidade") or 0))
            sku_key = key[0]
            target = line_targets.get(key, line_targets_by_sku.get(sku_key, Decimal(0)))
            if not preview_informada and key not in line_targets and sku_key not in line_targets_by_sku:
                target = source_totals.get(key, source_totals_by_sku.get(sku_key, Decimal(0)))
            denominator = source_totals.get(key) or source_totals_by_sku.get(sku_key) or Decimal(0)
            scale = target / denominator if denominator else Decimal(0)
            covers = _cover_components(base_product_id, cover_category) if base_product_id else []
            is_custom = bool(item.get("personalizado"))
            names = custom_by_item.get(item_id, []) if is_custom else []
            if not covers:
                source_key = f"sem_capa:{item_id}"
                payload[source_key] = {
                    "plano_id": plan_id,
                    "chave_origem": source_key,
                    "chave_grupo": f"sem_capa|{key[0]}|{key[1]}",
                    "item_pedido_id": item_id,
                    "variacao": variation,
                    "tipo": "pendente",
                    "quantidade_planejada": float(item_quantity * scale),
                    "pendencia": (
                        "Produto base não resolvido; confira a identificação do produto na linha e a ficha de materiais"
                        if not base_product_id else
                        "Nenhuma capa de impressão foi identificada na ficha de materiais; confira os componentes e a categoria da capa impressa"
                    ),
                }
            for cover in covers:
                names_total = 0
                group = f"{cover['produto_capa_id']}|personalizada|{key[1]}" if is_custom else f"{cover['produto_capa_id']}|estatica"
                if is_custom:
                    target_for_item = (target * item_quantity / denominator * Decimal(str(cover["quantidade_por_unidade"]))) if denominator else Decimal(0)
                    valid_names = [
                        personalization for personalization in names
                        if personalization.get("status") in (None, "SUCCESS")
                        and isinstance(personalization.get("customization_name"), str)
                        and personalization.get("customization_name", "").strip()
                    ]
                    identified_total = sum(
                        Decimal(str((personalization.get("detalhes_personalizacao") or {}).get("quantity_to_personalize")
                                    or (personalization.get("metadata") or {}).get("quantity_to_personalize") or 1))
                        * Decimal(str(cover["quantidade_por_unidade"]))
                        for personalization in valid_names
                    )
                    excessive_names = identified_total > target_for_item
                    for personalization in valid_names:
                        name = personalization.get("customization_name")
                        details = personalization.get("detalhes_personalizacao") or {}
                        metadata = personalization.get("metadata") or {}
                        quantity = int(details.get("quantity_to_personalize") or metadata.get("quantity_to_personalize") or 1)
                        quantity *= int(cover["quantidade_por_unidade"])
                        names_total += quantity
                        source_key = f"personalizacao:{personalization.get('id')}|capa:{cover['produto_capa_id']}"
                        payload[source_key] = {
                            "plano_id": plan_id,
                            "chave_origem": source_key,
                            "chave_grupo": group,
                            "item_pedido_id": item_id,
                            "personalizacao_id": personalization.get("id"),
                            "produto_capa_id": cover["produto_capa_id"],
                            "sku_capa": cover.get("sku_capa"),
                            "capa_nome": cover.get("capa_nome"),
                            "variacao": variation,
                            "tipo": "personalizada",
                            "nome_personalizado": name.strip(),
                            "quantidade_planejada": quantity,
                            "pendencia": "Quantidade editada menor que os nomes identificados; revise antes de confirmar" if excessive_names else None,
                        }
                    planned_names = Decimal(names_total)
                    missing = max(Decimal(0), target_for_item - planned_names)
                    if missing:
                        source_key = f"pendente:{item_id}|capa:{cover['produto_capa_id']}"
                        payload[source_key] = {
                            "plano_id": plan_id,
                            "chave_origem": source_key,
                            "chave_grupo": group,
                            "item_pedido_id": item_id,
                            "produto_capa_id": cover["produto_capa_id"],
                            "sku_capa": cover.get("sku_capa"),
                            "capa_nome": cover.get("capa_nome"),
                            "variacao": variation,
                            "tipo": "pendente",
                            "nome_personalizado": None,
                            "quantidade_planejada": float(missing),
                            "pendencia": f"{missing:g} unidade(s) sem nome identificado pela IA",
                        }
                    excess = max(Decimal(0), planned_names - target_for_item)
                    if excess:
                        source_key = f"divergencia:{item_id}|capa:{cover['produto_capa_id']}"
                        payload[source_key] = {
                            "plano_id": plan_id,
                            "chave_origem": source_key,
                            "chave_grupo": group,
                            "item_pedido_id": item_id,
                            "produto_capa_id": cover["produto_capa_id"],
                            "sku_capa": cover.get("sku_capa"),
                            "capa_nome": cover.get("capa_nome"),
                            "variacao": variation,
                            "tipo": "pendente",
                            "quantidade_planejada": float(excess),
                            "pendencia": f"A IA identificou {excess:g} unidade(s) acima da quantidade editada",
                        }
                else:
                    quantity = item_quantity * scale * Decimal(str(cover["quantidade_por_unidade"]))
                    source_key = f"item:{item_id}|capa:{cover['produto_capa_id']}"
                    payload[source_key] = {
                        "plano_id": plan_id,
                        "chave_origem": source_key,
                        "chave_grupo": group,
                        "item_pedido_id": item_id,
                        "produto_capa_id": cover["produto_capa_id"],
                        "sku_capa": cover.get("sku_capa"),
                        "capa_nome": cover.get("capa_nome"),
                        "variacao": variation,
                        "tipo": "estatica",
                        "nome_personalizado": None,
                        "quantidade_planejada": float(quantity),
                        "pendencia": None,
                    }

        # Uma edição pode criar uma linha ainda sem vínculo com pedido. Ela
        # aparece como pendência para revisão, sem perder a quantidade da prévia.
        known_skus = {key[0] for key in source_totals}
        for index, line in enumerate(linhas):
            sku = line.get("sku") or line.get("sku_externo")
            variation = line.get("variacao") or ""
            key = _key(sku, variation)
            if not sku or key[0] in known_skus:
                continue
            product = {"id": line.get("produto_id")} if line.get("produto_id") else (product_service.get_by_sku(sku) or {})
            covers = _cover_components(product.get("id"), cover_category) if product.get("id") else []
            quantity = Decimal(str(line.get("quantidade") or 0))
            for cover in covers:
                source_key = f"manual:{index}|capa:{cover['produto_capa_id']}"
                payload[source_key] = {
                    "plano_id": plan_id,
                    "chave_origem": source_key,
                    "chave_grupo": f"{cover['produto_capa_id']}|estatica",
                    "produto_capa_id": cover["produto_capa_id"],
                    "sku_capa": cover.get("sku_capa"),
                    "capa_nome": cover.get("capa_nome"),
                    "variacao": variation,
                    "tipo": "pendente",
                    "quantidade_planejada": float(quantity * Decimal(str(cover["quantidade_por_unidade"]))),
                    "pendencia": "Linha editada sem pedido de origem; revise antes de confirmar",
                }

        if payload:
            existing_items = (supabase_db.table("impressao_capas_itens")
                              .select("id,chave_origem,quantidade_confirmada")
                              .eq("plano_id", plan_id).execute().data or [])
            existing_by_key = {row.get("chave_origem"): row for row in existing_items}
            for row in payload.values():
                previous = existing_by_key.get(row["chave_origem"])
                row["quantidade_confirmada"] = (previous or {}).get("quantidade_confirmada", 0)
                row["updated_at"] = datetime.now(timezone.utc).isoformat()
            supabase_db.table("impressao_capas_itens").upsert(
                list(payload.values()), on_conflict="plano_id,chave_origem"
            ).execute()
            active_keys = set(payload)
            stale_ids = [row["id"] for row in existing_items if row.get("chave_origem") not in active_keys]
            for stale_id in stale_ids:
                supabase_db.table("impressao_capas_itens").update({
                    "quantidade_planejada": 0,
                    "pendencia": "Item removido ou alterado na prévia atual",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", stale_id).execute()
        else:
            stale_items = (supabase_db.table("impressao_capas_itens").select("id")
                           .eq("plano_id", plan_id).execute().data or [])
            for stale in stale_items:
                supabase_db.table("impressao_capas_itens").update({
                    "quantidade_planejada": 0,
                    "pendencia": "Item removido ou alterado na prévia atual",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", stale["id"]).execute()
        serialized = _serialize_plan(plan_id)
        return jsonify({"success": True, "data": serialized})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.error("Erro ao montar plano de capas: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": "Não foi possível montar o plano de impressão"}), 500


@impressao_capas_bp.route("/planos", methods=["GET"])
def consultar_plano():
    if not get_current_user():
        return jsonify({"success": False, "error": "Não autorizado"}), 401
    plan_id = request.args.get("plano_id")
    demanda_id = request.args.get("demanda_id")
    try:
        query = supabase_db.table("impressao_capas_planos").select("id")
        if plan_id:
            query = query.eq("id", plan_id)
        elif demanda_id:
            query = query.eq("demanda_id", int(demanda_id))
        else:
            rows = (supabase_db.table("impressao_capas_planos").select("id")
                    .order("updated_at", desc=True).limit(100).execute().data or [])
            return jsonify({"success": True, "data": [_serialize_plan(row["id"]) for row in rows]})
        rows = query.order("updated_at", desc=True).limit(1).execute().data or []
        if not rows:
            return jsonify({"success": True, "data": None})
        return jsonify({"success": True, "data": _serialize_plan(rows[0]["id"])})
    except Exception as exc:
        logger.error("Erro ao consultar plano de capas: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": "Não foi possível consultar o plano"}), 500


@impressao_capas_bp.route("/planos/<plan_id>/envios", methods=["POST"])
def registrar_envio(plan_id):
    user = get_current_user()
    if not user:
        return jsonify({"success": False, "error": "Não autorizado"}), 401
    body = request.get_json(silent=True) or {}
    try:
        record = {
            "plano_id": plan_id,
            "request_id": body["request_id"],
            "chave_grupo": body.get("chave_grupo"),
            "sku_capa": str(body.get("sku_capa") or "").strip(),
            "tipo": body.get("tipo"),
            "quantidade": int(body.get("quantidade") or 0),
            "printer_name": body.get("printer_name"),
            "agent_job_id": body.get("agent_job_id"),
            "status": body.get("status") or "sem_rastreio",
            "mensagem": body.get("mensagem"),
            "enviado_por": str(user.get("id") or user.get("email") or "System"),
        }
        if record["tipo"] not in ("estatica", "abrir_editor"):
            return jsonify({"success": False, "error": "Tipo de envio inválido"}), 400
        existing = (supabase_db.table("impressao_capas_envios").select("id")
                    .eq("request_id", record["request_id"]).limit(1).execute().data or [])
        if not existing:
            supabase_db.table("impressao_capas_envios").insert(record).execute()
        return jsonify({"success": True, "data": _serialize_plan(plan_id)})
    except Exception as exc:
        logger.error("Erro ao registrar envio de capa: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": "Não foi possível registrar o envio"}), 500


@impressao_capas_bp.route("/planos/<plan_id>/envios/<request_id>", methods=["PATCH"])
def atualizar_estado_envio(plan_id, request_id):
    if not get_current_user():
        return jsonify({"success": False, "error": "Não autorizado"}), 401
    body = request.get_json(silent=True) or {}
    try:
        supabase_db.table("impressao_capas_envios").update({
            "status": str(body.get("status") or "sem_rastreio"),
            "mensagem": body.get("mensagem"),
        }).eq("plano_id", plan_id).eq("request_id", request_id).execute()
        return jsonify({"success": True, "data": _serialize_plan(plan_id)})
    except Exception as exc:
        logger.error("Erro ao atualizar estado de envio: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": "Não foi possível atualizar a fila"}), 500


@impressao_capas_bp.route("/planos/<plan_id>/itens/<item_id>/confirmar", methods=["POST"])
def confirmar_item(plan_id, item_id):
    if not get_current_user():
        return jsonify({"success": False, "error": "Não autorizado"}), 401
    body = request.get_json(silent=True) or {}
    try:
        quantity = Decimal(str(body.get("quantidade") or 0))
        rows = (supabase_db.table("impressao_capas_itens").select("quantidade_planejada,tipo,pendencia")
                .eq("id", item_id).eq("plano_id", plan_id).limit(1).execute().data or [])
        if not rows:
            return jsonify({"success": False, "error": "Item do plano não encontrado"}), 404
        if rows[0].get("tipo") != "personalizada" or rows[0].get("pendencia"):
            return jsonify({"success": False, "error": "Revise os dados deste nome antes de confirmá-lo"}), 409
        if quantity < 0 or quantity > Decimal(str(rows[0].get("quantidade_planejada") or 0)):
            return jsonify({"success": False, "error": "A quantidade confirmada deve estar entre zero e a quantidade planejada"}), 400
        supabase_db.table("impressao_capas_itens").update({
            "quantidade_confirmada": float(quantity), "updated_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", item_id).eq("plano_id", plan_id).execute()
        return jsonify({"success": True, "data": _serialize_plan(plan_id)})
    except (InvalidOperation, ValueError):
        return jsonify({"success": False, "error": "Quantidade inválida"}), 400
    except Exception as exc:
        logger.error("Erro ao confirmar impressão de capa: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": "Não foi possível confirmar a impressão"}), 500


@impressao_capas_bp.route("/planos/<plan_id>/grupos/<path:group_key>/confirmar", methods=["POST"])
def confirmar_grupo(plan_id, group_key):
    if not get_current_user():
        return jsonify({"success": False, "error": "Não autorizado"}), 401
    body = request.get_json(silent=True) or {}
    try:
        quantity = Decimal(str(body.get("quantidade") or 0))
        rows = (supabase_db.table("impressao_capas_itens").select("quantidade_planejada")
                .eq("plano_id", plan_id).eq("chave_grupo", group_key).eq("tipo", "estatica").execute().data or [])
        planned = sum(Decimal(str(row.get("quantidade_planejada") or 0)) for row in rows)
        if not rows:
            return jsonify({"success": False, "error": "Grupo estático não encontrado"}), 404
        if quantity < 0 or quantity > planned:
            return jsonify({"success": False, "error": "A quantidade confirmada deve estar entre zero e a quantidade planejada"}), 400
        sends = (supabase_db.table("impressao_capas_envios").select("quantidade,agent_job_id,status")
                 .eq("plano_id", plan_id).eq("chave_grupo", group_key).eq("tipo", "estatica").execute().data or [])
        sent = sum(
            Decimal(str(row.get("quantidade") or 0)) for row in sends
            if row.get("status") != "erro" or row.get("agent_job_id")
        )
        if quantity > sent:
            return jsonify({"success": False, "error": "Confirme no máximo a quantidade enviada"}), 400
        now = datetime.now(timezone.utc).isoformat()
        supabase_db.table("impressao_capas_grupos").upsert({
            "plano_id": plan_id,
            "chave_grupo": group_key,
            "quantidade_confirmada": float(quantity),
            "updated_at": now,
        }, on_conflict="plano_id,chave_grupo").execute()
        return jsonify({"success": True, "data": _serialize_plan(plan_id)})
    except (InvalidOperation, ValueError):
        return jsonify({"success": False, "error": "Quantidade inválida"}), 400
    except Exception as exc:
        logger.error("Erro ao confirmar lote de capas: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": "Não foi possível confirmar as capas"}), 500
