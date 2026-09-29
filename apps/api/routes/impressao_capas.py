"""Planejamento persistente e rastreabilidade da impressão de capas."""

import hashlib
import json
import logging
import uuid
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.app_config_service import app_config_service
from nistiprint_shared.services.bom_service import bom_service
from nistiprint_shared.services.product_service import product_service
from nistiprint_shared.services.print_artwork_logic import build_print_groups, legacy_credit
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


def _bom_candidates(product_id):
    """Return reachable components and their quantities per finished product."""
    found = {}
    category_allows_artwork = {}

    def walk(parent_id, multiplier, path):
        if len(path) >= 20:
            return
        for component in bom_service.get_bom_for_produto(int(parent_id)):
            component_id = int(component.componente_id)
            if component_id in path:
                continue
            product = product_service.get_by_id(str(component_id)) or {}
            amount = multiplier * Decimal(str(component.quantidade or 1))
            label = str(product.get("nome") or product.get("name") or product.get("sku") or "")
            lowered = label.casefold()
            category_id = product.get("categoria_id")
            if category_id not in category_allows_artwork:
                from nistiprint_shared.services.category_service import category_service
                category = category_service.get_by_id(str(category_id)) if category_id else None
                category_allows_artwork[category_id] = bool(category and category.get("permite_arte"))
            allows_artwork = category_allows_artwork[category_id]
            role = ("contra" if "contra" in lowered else
                    "capa" if "capa" in lowered else
                    "miolo" if "miolo" in lowered else None) if allows_artwork else None
            row = found.setdefault(component_id, {
                "componente_id": component_id, "nome": label, "sku": product.get("sku"),
                "categoria_id": category_id,
                "papel_sugerido": role, "permite_arte": allows_artwork,
                "quantidade": Decimal(0),
            })
            row["quantidade"] += amount
            walk(component_id, amount, path | {component_id})

    walk(product_id, Decimal(1), {int(product_id)})
    return found


def _product_artworks(product_id):
    arts = (supabase_db.table("impressao_artes").select("*")
            .eq("produto_final_id", int(product_id)).eq("ativo", True).execute().data or [])
    if not arts:
        return []
    links = (supabase_db.table("impressao_arte_componentes").select("*")
             .eq("produto_final_id", int(product_id)).execute().data or [])
    for art in arts:
        art["componentes"] = [link for link in links if link["arte_id"] == art["id"]]
    return arts


def _print_groups(product_id, cover_category):
    arts = _product_artworks(product_id)
    if not arts:
        return [{**component, "produto_final_id": int(product_id)}
                for component in _cover_components(product_id, cover_category)]
    components = _bom_candidates(product_id)
    return build_print_groups(product_id, arts, components, [])


@impressao_capas_bp.route("/produtos/<int:product_id>/artes", methods=["GET", "POST"])
def artes_do_produto(product_id):
    if not get_current_user():
        return jsonify({"success": False, "error": "Não autorizado"}), 401
    if request.method == "GET":
        try:
            components = _bom_candidates(product_id)
            return jsonify({"success": True, "data": {
                "artes": _product_artworks(product_id),
                "componentes": [{**row, "quantidade": float(row["quantidade"])} for row in components.values()],
            }})
        except Exception:
            logger.exception("Falha ao consultar artes do produto %s", product_id)
            return jsonify({"success": False, "error": "Não foi possível consultar as artes"}), 500
    return _save_artwork(product_id)


@impressao_capas_bp.route("/produtos/<int:product_id>/artes/<art_id>", methods=["PUT", "DELETE"])
def arte_do_produto(product_id, art_id):
    if not get_current_user():
        return jsonify({"success": False, "error": "Não autorizado"}), 401
    try:
        uuid.UUID(art_id)
    except ValueError:
        return jsonify({"success": False, "error": "Identificador da arte inválido"}), 400
    existing = (supabase_db.table("impressao_artes").select("id")
                .eq("id", art_id).eq("produto_final_id", product_id).limit(1).execute().data or [])
    if not existing:
        return jsonify({"success": False, "error": "Arte não encontrada"}), 404
    if request.method == "DELETE":
        supabase_db.rpc("arquivar_arte_impressao", {
            "p_produto_final_id": product_id, "p_arte_id": art_id,
        }).execute()
        return jsonify({"success": True, "data": None})
    return _save_artwork(product_id, art_id)


def _save_artwork(product_id, art_id=None):
    body = request.get_json(silent=True) or {}
    product = product_service.get_by_id(str(product_id)) or {}
    if not product:
        return jsonify({"success": False, "error": "Produto não encontrado"}), 404
    if (product.get("material_type") or product.get("tipo_material")) != "produto_acabado":
        return jsonify({"success": False, "error": "Vincule esta arte ao produto final"}), 400
    name = str(body.get("nome") or "").strip()
    links = body.get("componentes")
    if not name or len(name) > 160 or not isinstance(links, list) or not links:
        return jsonify({"success": False, "error": "Informe nome e componentes da arte"}), 400
    try:
        reachable = _bom_candidates(product_id)
        ids = [int(link["componente_id"]) for link in links]
        if len(ids) != len(set(ids)) or any(component_id not in reachable for component_id in ids):
            raise ValueError("Selecione componentes distintos da ficha de materiais")
        if any(not reachable[component_id]["permite_arte"] for component_id in ids):
            raise ValueError("A arte só pode ser vinculada a componentes da categoria que permite arte")
        if any(link.get("papel") not in ("capa", "contra", "miolo") for link in links):
            raise ValueError("Papel de componente inválido")
        occupied = (supabase_db.table("impressao_arte_componentes").select("arte_id,componente_id")
                    .eq("produto_final_id", product_id).in_("componente_id", ids).execute().data or [])
        if any(row["arte_id"] != art_id for row in occupied):
            raise ValueError("Um componente já pertence a outra arte deste produto")
        result = supabase_db.rpc("salvar_arte_impressao", {
            "p_produto_final_id": product_id, "p_arte_id": art_id, "p_nome": name,
            "p_componentes": [{"componente_id": int(link["componente_id"]), "papel": link["papel"]}
                            for link in links],
        }).execute()
        return jsonify({"success": True, "data": {"id": result.data}})
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception:
        logger.exception("Falha ao salvar arte do produto %s", product_id)
        return jsonify({"success": False, "error": "Não foi possível salvar a arte"}), 500


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
        next_path = path | {str(parent_id)}
        for component in bom_service.get_bom_for_produto(int(parent_id)):
            component_id = int(component.componente_id)
            if str(component_id) in next_path:
                continue
            product = product_service.get_by_id(str(component_id)) or {}
            quantity = multiplier * float(component.quantidade or 1)
            category_name = ""
            category_allows_artwork = False
            if product.get("categoria_id"):
                try:
                    from nistiprint_shared.services.category_service import category_service
                    category = category_service.get_by_id(str(product["categoria_id"])) or {}
                    category_name = str(category.get("nome") or category.get("name") or "")
                    category_allows_artwork = bool(category.get("permite_arte"))
                except Exception:
                    logger.debug("Não foi possível obter a categoria do produto %s", component_id, exc_info=True)
            label = " ".join((
                str(product.get("nome") or product.get("name") or ""),
                str(product.get("sku") or ""), category_name,
            )).casefold()
            is_printed_cover = category_allows_artwork and (
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
                walk(component_id, quantity, next_path)

    walk(product_id, 1, set())
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
    product_ids = sorted({item["produto_final_id"] for item in items if item.get("produto_final_id")})
    products = (supabase_db.table("produtos").select("id,nome").in_("id", product_ids).execute().data or []) if product_ids else []
    plan["produtos"] = {str(product["id"]): product["nome"] for product in products}
    return plan


def _reconcile_legacy_groups(plan_id, payload):
    """Credit old confirmations only when every covered component maps to one art."""
    by_art = {}
    owners = {}
    for row in payload.values():
        if row.get("tipo") != "estatica":
            continue
        if row.get("arte_id"):
            group = by_art.setdefault(row["chave_grupo"], {"art": row["arte_id"], "ids": row["componentes_ids"], "planned": Decimal(0)})
            group["planned"] += Decimal(str(row["quantidade_planejada"]))
            for component_id in row["componentes_ids"]:
                owners.setdefault(component_id, set()).add(row["arte_id"])
        elif row.get("produto_capa_id"):
            owners.setdefault(row["produto_capa_id"], set()).add(None)
    if not by_art:
        return
    existing = (supabase_db.table("impressao_capas_grupos").select("chave_grupo,quantidade_confirmada")
                .eq("plano_id", plan_id).execute().data or [])
    groups = {row["chave_grupo"]: row for row in existing}
    sends = (supabase_db.table("impressao_capas_envios").select("chave_grupo,tipo")
             .eq("plano_id", plan_id).execute().data or [])
    legacy_activity = {row["chave_grupo"] for row in sends if row.get("tipo") == "estatica"}
    for group_key, info in by_art.items():
        if group_key in groups:
            continue
        amount, review = legacy_credit(
            info["ids"], info["art"], info["planned"], owners,
            {key: row.get("quantidade_confirmada") for key, row in groups.items()}, legacy_activity,
        )
        if not amount and not review:
            continue
        supabase_db.table("impressao_capas_grupos").insert({
            "plano_id": plan_id, "chave_grupo": group_key,
            "quantidade_confirmada": float(amount), "quantidade_legada": float(amount),
            "revisao_pendente": review,
        }).execute()


@impressao_capas_bp.route("/planos", methods=["POST"])
def criar_ou_atualizar_plano():
    user = get_current_user()
    if not user:
        return jsonify({"success": False, "error": "Não autorizado"}), 401
    try:
        body = request.get_json(silent=True) or {}
        demanda_id = body.get("demanda_id")
        if demanda_id is not None:
            demanda_id = int(demanda_id)
            if demanda_id <= 0:
                raise ValueError("demanda_id inválido")
            demand = (supabase_db.table("demandas_producao").select("id")
                      .eq("id", demanda_id).limit(1).execute().data or [])
            if not demand:
                return jsonify({"success": False, "error": "Demanda não encontrada"}), 404
            links = (supabase_db.table("demandas_pedidos").select("pedido_id")
                     .eq("demanda_id", demanda_id).execute().data or [])
            pedido_ids = _ids_validos([link["pedido_id"] for link in links])
        else:
            pedido_ids = _ids_validos(body.get("pedido_ids"))
        linhas = body.get("linhas") if isinstance(body.get("linhas"), list) else []
        preview_informada = isinstance(body.get("linhas"), list)
        if demanda_id and not preview_informada:
            demand_items = (supabase_db.table("itens_demanda")
                            .select("sku,variacao,quantidade,produto_id")
                            .eq("demanda_id", demanda_id).execute().data or [])
            linhas = [row for row in demand_items if row.get("sku")]
            preview_informada = bool(linhas)
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

        scope_key = (f"demanda:{demanda_id}" if demanda_id else
                     hashlib.sha256(json.dumps(pedido_ids).encode("utf-8")).hexdigest())
        plan_query = supabase_db.table("impressao_capas_planos").select("id,demanda_id")
        plan_rows = ((plan_query.eq("demanda_id", demanda_id) if demanda_id else
                      plan_query.eq("chave_escopo", scope_key)).limit(1).execute().data or [])
        if not demanda_id and plan_rows and plan_rows[0].get("demanda_id"):
            return jsonify({"success": False, "error": "Este escopo já foi publicado; abra a demanda para imprimir"}), 409
        now_user = str(user.get("id") or user.get("email") or user.get("nome") or "System")
        if plan_rows:
            plan_id = plan_rows[0]["id"]
            update = {
                "pedido_ids": pedido_ids,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            if "previsao_versao" in body:
                update["previsao_versao"] = body["previsao_versao"]
            supabase_db.table("impressao_capas_planos").update(update).eq("id", plan_id).execute()
        else:
            inserted = supabase_db.table("impressao_capas_planos").insert({
                "chave_escopo": scope_key,
                "demanda_id": demanda_id,
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
        items_by_external_description = {}
        for item in item_rows:
            external_code = order_code_by_id.get(int(item.get("pedido_id") or 0))
            description = str(item.get("descricao") or "").strip().casefold()
            items_by_external_description.setdefault((str(external_code or ""), description), []).append(item.get("id"))
        custom_by_item = {}
        for personalization in custom_rows:
            item_id = personalization.get("item_pedido_id")
            if item_id is None:
                description = str(personalization.get("item_description") or "").strip().casefold()
                code = str(personalization.get("shopee_order_sn") or "")
                candidates = items_by_external_description.get((code, description), [])
                if len(candidates) == 1:
                    item_id = candidates[0]
            if item_id is not None:
                custom_by_item.setdefault(int(item_id), []).append(personalization)

        # Keep the same default used by the production dashboard while also
        # recognizing printed-cover components by their catalog labels below.
        cover_category = app_config_service.get_config("producao_capas_impressas_category_id") or "13"
        line_targets = {}
        line_targets_by_sku = {}
        line_targets_by_product = {}
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
                product_key = int(line["produto_id"])
                line_targets_by_product[product_key] = line_targets_by_product.get(product_key, Decimal(0)) + max(Decimal(0), quantity)

        source_totals = {}
        source_totals_by_sku = {}
        source_totals_by_product = {}
        resolved_product_ids = {}
        products_by_sku = {}
        product_by_item = {}
        for item in item_rows:
            sku = item.get("sku_externo") or ""
            variation = item.get("variacao_externa") or item.get("variacao") or ""
            key = _key(sku, variation)
            source_totals[key] = source_totals.get(key, Decimal(0)) + Decimal(str(item.get("quantidade") or 0))
            source_totals_by_sku[key[0]] = source_totals_by_sku.get(key[0], Decimal(0)) + Decimal(str(item.get("quantidade") or 0))
            base_product_id = item.get("produto_id") or line_products_by_key.get(key) or line_products_by_sku.get(key[0])
            if not base_product_id and sku:
                origin = order_origin_by_id.get(int(item.get("pedido_id") or 0))
                cache_key = (sku.strip().casefold(), str(origin or "").casefold())
                if cache_key not in resolved_product_ids:
                    identity = product_service.resolver_identificacao_completa(sku, origin)
                    resolved_product_ids[cache_key] = (identity or {}).get("produto_id")
                base_product_id = resolved_product_ids[cache_key]
            if not base_product_id and sku:
                sku_key = sku.strip().casefold()
                if sku_key not in products_by_sku:
                    products_by_sku[sku_key] = (product_service.get_by_sku(sku) or {}).get("id")
                base_product_id = products_by_sku[sku_key]
            base_product_id = int(base_product_id) if base_product_id else None
            product_by_item[int(item["id"])] = base_product_id
            if base_product_id:
                product_key = int(base_product_id)
                source_totals_by_product[product_key] = source_totals_by_product.get(product_key, Decimal(0)) + Decimal(str(item.get("quantidade") or 0))

        payload = {}
        cover_meta = {}
        manual_meta = {}
        print_group_cache = {}
        for item in item_rows:
            item_id = int(item["id"])
            order_id = item_to_order[item_id]
            item_sku = item.get("sku_externo") or ""
            variation = item.get("variacao_externa") or item.get("variacao") or ""
            key = _key(item_sku, variation)
            base_product_id = product_by_item.get(item_id)
            item_quantity = Decimal(str(item.get("quantidade") or 0))
            sku_key = key[0]
            target = line_targets.get(key, line_targets_by_sku.get(sku_key, Decimal(0)))
            if not preview_informada and key not in line_targets and sku_key not in line_targets_by_sku:
                target = source_totals.get(key, source_totals_by_sku.get(sku_key, Decimal(0)))
            denominator = source_totals.get(key) or source_totals_by_sku.get(sku_key) or Decimal(0)
            if demanda_id and base_product_id and int(base_product_id) in line_targets_by_product:
                product_key = int(base_product_id)
                target = line_targets_by_product[product_key]
                denominator = source_totals_by_product.get(product_key, Decimal(0))
            scale = target / denominator if denominator else Decimal(0)
            if base_product_id and base_product_id not in print_group_cache:
                print_group_cache[base_product_id] = _print_groups(base_product_id, cover_category)
            covers = print_group_cache.get(base_product_id, [])
            is_custom = bool(item.get("personalizado"))
            names = custom_by_item.get(item_id, []) if is_custom else []
            if not covers:
                source_key = f"sem_capa:{item_id}"
                payload[source_key] = {
                    "plano_id": plan_id,
                    "chave_origem": source_key,
                    "chave_grupo": f"sem_capa|{key[0]}|{key[1]}",
                    "item_pedido_id": item_id,
                    "produto_final_id": int(base_product_id) if base_product_id else None,
                    "sku_capa": item_sku,
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
                cover_meta[(item_id, cover["produto_capa_id"])] = cover
                names_total = 0
                source_id = cover.get("arte_id") or cover["produto_capa_id"]
                group = f"{source_id}|personalizada|{key[1]}" if is_custom else f"{source_id}|estatica"
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
                        source_key = f"personalizacao:{personalization.get('id')}|capa:{source_id}"
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
                        source_key = f"pendente:{item_id}|capa:{source_id}"
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
                        source_key = f"divergencia:{item_id}|capa:{source_id}"
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
                    source_key = f"item:{item_id}|capa:{source_id}"
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
            if (not sku or key[0] in known_skus
                    or (demanda_id and line.get("produto_id")
                        and int(line["produto_id"]) in source_totals_by_product)):
                continue
            if line.get("produto_id"):
                product_id = int(line["produto_id"])
            else:
                sku_key = sku.strip().casefold()
                if sku_key not in products_by_sku:
                    products_by_sku[sku_key] = (product_service.get_by_sku(sku) or {}).get("id")
                product_id = int(products_by_sku[sku_key]) if products_by_sku[sku_key] else None
            if product_id and product_id not in print_group_cache:
                print_group_cache[product_id] = _print_groups(product_id, cover_category)
            covers = print_group_cache.get(product_id, [])
            quantity = Decimal(str(line.get("quantidade") or 0))
            for cover in covers:
                source_id = cover.get("arte_id") or cover["produto_capa_id"]
                source_key = f"manual:{index}|capa:{source_id}"
                manual_meta[source_key] = cover
                payload[source_key] = {
                    "plano_id": plan_id,
                    "chave_origem": source_key,
                    "chave_grupo": f"{source_id}|estatica",
                    "produto_capa_id": cover["produto_capa_id"],
                    "sku_capa": cover.get("sku_capa"),
                    "capa_nome": cover.get("capa_nome"),
                    "variacao": variation,
                    "tipo": "pendente",
                    "quantidade_planejada": float(quantity * Decimal(str(cover["quantidade_por_unidade"]))),
                    "pendencia": "Linha editada sem pedido de origem; revise antes de confirmar",
                }

        for source_key, row in payload.items():
            item_id = row.get("item_pedido_id")
            cover = (cover_meta.get((item_id, row.get("produto_capa_id")))
                     if item_id else manual_meta.get(source_key))
            row["pedido_id"] = item_to_order.get(item_id)
            row["pedido_codigo"] = order_code_by_id.get(row["pedido_id"])
            row["arte_id"] = cover.get("arte_id") if cover else None
            row["produto_final_id"] = cover.get("produto_final_id") if cover else row.get("produto_final_id")
            row["componentes_ids"] = cover.get("componentes_ids", []) if cover else []
            row["papeis"] = cover.get("papeis", []) if cover else []
            row["quantidade_por_unidade"] = cover.get("quantidade_por_unidade") if cover else None
            if cover and cover.get("pendencia_arte"):
                row["pendencia"] = cover["pendencia_arte"]

        if payload:
            existing_items = (supabase_db.table("impressao_capas_itens")
                              .select("id,chave_origem,quantidade_confirmada,personalizacao_id,produto_capa_id,tipo,arte_id,revisao_pendente")
                              .eq("plano_id", plan_id).execute().data or [])
            existing_by_key = {row.get("chave_origem"): row for row in existing_items}
            legacy_by_personalization = {}
            for existing in existing_items:
                if not existing.get("arte_id") and existing.get("tipo") == "personalizada":
                    legacy_by_personalization.setdefault(existing.get("personalizacao_id"), []).append(existing)
            for row in payload.values():
                previous = existing_by_key.get(row["chave_origem"])
                row["quantidade_confirmada"] = (previous or {}).get("quantidade_confirmada", 0)
                row["revisao_pendente"] = bool((previous or {}).get("revisao_pendente"))
                if row["revisao_pendente"]:
                    row["pendencia"] = "Confirmações antigas divergentes; concilie este nome antes de reimprimir"
                if (not previous and row.get("arte_id") and row.get("tipo") == "personalizada"
                        and row.get("personalizacao_id") and not row.get("pendencia")):
                    old = [item for item in legacy_by_personalization.get(row["personalizacao_id"], [])
                           if item.get("produto_capa_id") in row["componentes_ids"]]
                    old_ids = {item.get("produto_capa_id") for item in old}
                    values = [Decimal(str(item.get("quantidade_confirmada") or 0)) for item in old]
                    if old_ids == set(row["componentes_ids"]) and len(set(values)) == 1 and values[0] <= Decimal(str(row["quantidade_planejada"])):
                        row["quantidade_confirmada"] = float(values[0])
                    elif any(value > 0 for value in values):
                        row["revisao_pendente"] = True
                        row["pendencia"] = "Confirmações antigas divergentes; concilie este nome antes de reimprimir"
                row["updated_at"] = datetime.now(timezone.utc).isoformat()
            supabase_db.table("impressao_capas_itens").upsert(
                list(payload.values()), on_conflict="plano_id,chave_origem"
            ).execute()
            active_keys = set(payload)
            stale_ids = [row["id"] for row in existing_items if row.get("chave_origem") not in active_keys]
            if stale_ids:
                supabase_db.table("impressao_capas_itens").update({
                    "quantidade_planejada": 0,
                    "pendencia": "Item removido ou alterado na prévia atual",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }).in_("id", stale_ids).execute()
            _reconcile_legacy_groups(plan_id, payload)
        else:
            stale_items = (supabase_db.table("impressao_capas_itens").select("id")
                           .eq("plano_id", plan_id).execute().data or [])
            if stale_items:
                supabase_db.table("impressao_capas_itens").update({
                    "quantidade_planejada": 0,
                    "pendencia": "Item removido ou alterado na prévia atual",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }).in_("id", [stale["id"] for stale in stale_items]).execute()
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
            "arte_id": body.get("arte_id"),
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
        if record["arte_id"]:
            matching = (supabase_db.table("impressao_capas_itens").select("id,pendencia,tipo")
                        .eq("plano_id", plan_id).eq("chave_grupo", record["chave_grupo"])
                        .eq("arte_id", record["arte_id"]).execute().data or [])
            if not matching:
                return jsonify({"success": False, "error": "Arte não pertence a este plano"}), 409
            if record["tipo"] == "estatica" and record["status"] != "erro":
                review = (supabase_db.table("impressao_capas_grupos").select("revisao_pendente")
                          .eq("plano_id", plan_id).eq("chave_grupo", record["chave_grupo"]).limit(1).execute().data or [])
                if any(row.get("pendencia") for row in matching) or (review and review[0]["revisao_pendente"]):
                    return jsonify({"success": False, "error": "Revise as pendências antes de imprimir"}), 409
        existing = (supabase_db.table("impressao_capas_envios").select("id")
                    .eq("request_id", record["request_id"]).limit(1).execute().data or [])
        if not existing:
            supabase_db.table("impressao_capas_envios").insert(record).execute()
        return jsonify({"success": True, "data": _serialize_plan(plan_id)})
    except Exception as exc:
        logger.error("Erro ao registrar envio de capa: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": "Não foi possível registrar o envio"}), 500


@impressao_capas_bp.route("/planos/<plan_id>/grupos/<path:group_key>/preparar", methods=["POST"])
def preparar_grupo(plan_id, group_key):
    if not get_current_user():
        return jsonify({"success": False, "error": "Não autorizado"}), 401
    try:
        rows = (supabase_db.table("impressao_capas_itens")
                .select("arte_id,produto_final_id,componentes_ids,quantidade_por_unidade,quantidade_planejada,pendencia")
                .eq("plano_id", plan_id).eq("chave_grupo", group_key).eq("tipo", "estatica").execute().data or [])
        if not rows:
            return jsonify({"success": False, "error": "Arquivo não encontrado no plano"}), 404
        if any(row.get("pendencia") for row in rows):
            return jsonify({"success": False, "error": "Revise os componentes e pendências deste arquivo"}), 409
        art_id = rows[0].get("arte_id")
        if art_id:
            product_id = rows[0].get("produto_final_id")
            current = next((art for art in _product_artworks(product_id) if art["id"] == art_id), None)
            current_ids = {int(link["componente_id"]) for link in (current or {}).get("componentes", [])
                           if link["papel"] in ("capa", "contra")}
            if not current or any(set(row.get("componentes_ids") or []) != current_ids for row in rows):
                return jsonify({"success": False, "error": "O vínculo da arte mudou; atualize o plano"}), 409
            cover_category = app_config_service.get_config("producao_capas_impressas_category_id") or "13"
            current_group = next((entry for entry in _print_groups(product_id, cover_category)
                                  if entry.get("arte_id") == art_id), None)
            if (not current_group or current_group.get("pendencia_arte")
                    or any(Decimal(str(row.get("quantidade_por_unidade") or 0))
                           != Decimal(str(current_group["quantidade_por_unidade"])) for row in rows)):
                return jsonify({"success": False, "error": "A ficha de materiais mudou; atualize o plano"}), 409
        group = (supabase_db.table("impressao_capas_grupos").select("quantidade_legada,revisao_pendente")
                 .eq("plano_id", plan_id).eq("chave_grupo", group_key).limit(1).execute().data or [])
        if group and group[0].get("revisao_pendente"):
            return jsonify({"success": False, "error": "Concilie o histórico antes de imprimir"}), 409
        planned = sum(Decimal(str(row["quantidade_planejada"])) for row in rows)
        sends = (supabase_db.table("impressao_capas_envios").select("quantidade,status,agent_job_id")
                 .eq("plano_id", plan_id).eq("chave_grupo", group_key).eq("tipo", "estatica").execute().data or [])
        sent = Decimal(str((group[0] if group else {}).get("quantidade_legada") or 0)) + sum(
            Decimal(str(row.get("quantidade") or 0)) for row in sends
            if row.get("status") != "erro" or row.get("agent_job_id")
        )
        remaining = max(Decimal(0), planned - sent)
        if remaining != remaining.to_integral_value():
            return jsonify({"success": False, "error": "Quantidade de cópias não inteira; revise a ficha"}), 409
        return jsonify({"success": True, "data": {"quantidade_pendente": int(remaining)}})
    except Exception:
        logger.exception("Falha ao preparar grupo de impressão %s", group_key)
        return jsonify({"success": False, "error": "Não foi possível conferir o arquivo"}), 500


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
        rows = (supabase_db.table("impressao_capas_itens").select("quantidade_planejada,tipo,pendencia,revisao_pendente")
                .eq("id", item_id).eq("plano_id", plan_id).limit(1).execute().data or [])
        if not rows:
            return jsonify({"success": False, "error": "Item do plano não encontrado"}), 404
        if rows[0].get("tipo") != "personalizada" or rows[0].get("pendencia") or rows[0].get("revisao_pendente"):
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


@impressao_capas_bp.route("/planos/<plan_id>/itens/<item_id>/reconciliar", methods=["POST"])
def reconciliar_item(plan_id, item_id):
    if not get_current_user():
        return jsonify({"success": False, "error": "Não autorizado"}), 401
    try:
        rows = (supabase_db.table("impressao_capas_itens")
                .select("quantidade_planejada,revisao_pendente,tipo")
                .eq("id", item_id).eq("plano_id", plan_id).limit(1).execute().data or [])
        if not rows or rows[0].get("tipo") != "personalizada" or not rows[0].get("revisao_pendente"):
            return jsonify({"success": False, "error": "Nome sem conciliação pendente"}), 409
        quantity = Decimal(str((request.get_json(silent=True) or {}).get("quantidade_ja_impressa")))
        if quantity < 0 or quantity > Decimal(str(rows[0]["quantidade_planejada"])):
            raise ValueError("Quantidade fora do plano")
        supabase_db.table("impressao_capas_itens").update({
            "quantidade_confirmada": float(quantity), "revisao_pendente": False,
            "pendencia": None, "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", item_id).eq("plano_id", plan_id).execute()
        return jsonify({"success": True, "data": _serialize_plan(plan_id)})
    except (InvalidOperation, TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception:
        logger.exception("Falha ao conciliar item de impressão %s", item_id)
        return jsonify({"success": False, "error": "Não foi possível conciliar o nome"}), 500


@impressao_capas_bp.route("/planos/<plan_id>/grupos/<path:group_key>/confirmar", methods=["POST"])
def confirmar_grupo(plan_id, group_key):
    if not get_current_user():
        return jsonify({"success": False, "error": "Não autorizado"}), 401
    body = request.get_json(silent=True) or {}
    try:
        quantity = Decimal(str(body.get("quantidade") or 0))
        rows = (supabase_db.table("impressao_capas_itens").select("quantidade_planejada,pendencia")
                .eq("plano_id", plan_id).eq("chave_grupo", group_key).eq("tipo", "estatica").execute().data or [])
        planned = sum(Decimal(str(row.get("quantidade_planejada") or 0)) for row in rows)
        if not rows:
            return jsonify({"success": False, "error": "Grupo estático não encontrado"}), 404
        if any(row.get("pendencia") for row in rows):
            return jsonify({"success": False, "error": "Revise as pendências deste arquivo"}), 409
        if quantity < 0 or quantity > planned:
            return jsonify({"success": False, "error": "A quantidade confirmada deve estar entre zero e a quantidade planejada"}), 400
        group_rows = (supabase_db.table("impressao_capas_grupos").select("quantidade_legada,revisao_pendente")
                      .eq("plano_id", plan_id).eq("chave_grupo", group_key).limit(1).execute().data or [])
        if group_rows and group_rows[0].get("revisao_pendente"):
            return jsonify({"success": False, "error": "Concilie o histórico antes de confirmar"}), 409
        sends = (supabase_db.table("impressao_capas_envios").select("quantidade,agent_job_id,status")
                 .eq("plano_id", plan_id).eq("chave_grupo", group_key).eq("tipo", "estatica").execute().data or [])
        sent = Decimal(str((group_rows[0] if group_rows else {}).get("quantidade_legada") or 0)) + sum(
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


@impressao_capas_bp.route("/planos/<plan_id>/grupos/<path:group_key>/reconciliar", methods=["POST"])
def reconciliar_grupo(plan_id, group_key):
    if not get_current_user():
        return jsonify({"success": False, "error": "Não autorizado"}), 401
    try:
        rows = (supabase_db.table("impressao_capas_grupos").select("revisao_pendente")
                .eq("plano_id", plan_id).eq("chave_grupo", group_key).limit(1).execute().data or [])
        if not rows or not rows[0].get("revisao_pendente"):
            return jsonify({"success": False, "error": "Grupo sem conciliação pendente"}), 409
        items = (supabase_db.table("impressao_capas_itens").select("quantidade_planejada")
                 .eq("plano_id", plan_id).eq("chave_grupo", group_key).eq("tipo", "estatica").execute().data or [])
        planned = sum(Decimal(str(item["quantidade_planejada"])) for item in items)
        quantity = Decimal(str((request.get_json(silent=True) or {}).get("quantidade_ja_impressa")))
        if quantity < 0 or quantity > planned:
            raise ValueError("Quantidade fora do plano")
        supabase_db.table("impressao_capas_grupos").update({
            "quantidade_legada": float(quantity), "quantidade_confirmada": float(quantity),
            "revisao_pendente": False, "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("plano_id", plan_id).eq("chave_grupo", group_key).execute()
        return jsonify({"success": True, "data": _serialize_plan(plan_id)})
    except (InvalidOperation, TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception:
        logger.exception("Falha ao conciliar impressão do grupo %s", group_key)
        return jsonify({"success": False, "error": "Não foi possível conciliar o histórico"}), 500
