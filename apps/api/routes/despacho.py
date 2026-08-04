"""
Rotas API do dominio Despacho.

Contrato: docs/specs/02-domains/despacho/spec.md e data-model.md

Toda logica de agrupamento, invariantes de totalizadores e transacao de
lancamento vivem no banco (RPCs `despacho_arvore`, `despacho_escopo_pedidos`,
`despacho_lancar_escopo`). Este arquivo so traduz HTTP <-> RPC: se uma decisao
de negocio aparecer aqui em Python, ela provavelmente deveria estar na
migration, para que a arvore, a esteira e o lancamento nunca divirjam entre
si por caminhos diferentes de codigo.
"""

from datetime import date, datetime

from flask import Blueprint, jsonify, request
from nistiprint_shared.database.supabase_db_service import supabase_db
from routes.auth import get_current_user

import logging

logger = logging.getLogger("DespachoAPI")

despacho_bp = Blueprint("despacho", __name__)


def _parse_data(raw: str | None) -> str:
    if not raw:
        return date.today().isoformat()
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return date.today().isoformat()


def _parse_int(raw: str | None) -> int | None:
    if raw in (None, "", "null"):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


@despacho_bp.route("/arvore", methods=["GET"])
def get_arvore():
    """Totalizadores em tres niveis: marketplace, modalidade, prazo.

    Query params:
    - data: YYYY-MM-DD (default hoje)
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({"success": False, "error": "Nao autorizado"}), 401

        p_data = _parse_data(request.args.get("data"))
        result = supabase_db.rpc("despacho_arvore", {"p_data": p_data}).execute()
        rows = result.data or []

        # Monta a arvore no shape que o frontend consome, sem repetir a
        # invariante de soma no cliente: cada linha ja veio agregada pelo
        # GROUPING SETS no banco.
        marketplaces = {}
        for row in rows:
            mkt_key = row["integration_id"]
            mkt = marketplaces.setdefault(mkt_key, {
                "integration_id": mkt_key,
                "nome": row["marketplace_nome"],
                "qtd_pedidos": 0,
                "qtd_itens": 0,
                "corte_em": None,
                "coleta_em": None,
                "compromisso_mais_proximo": None,
                "modalidades": {},
            })

            if row["nivel"] == 0:
                mkt["qtd_pedidos"] = row["qtd_pedidos"]
                mkt["qtd_itens"] = row["qtd_itens"]
                mkt["corte_em"] = row["corte_em"]
                mkt["coleta_em"] = row["coleta_em"]
                mkt["compromisso_mais_proximo"] = row["compromisso_mais_proximo"]
                continue

            mod_key = row["modalidade_id"]
            mod = mkt["modalidades"].setdefault(mod_key, {
                "modalidade_id": mod_key,
                "codigo": row["modalidade_codigo"],
                "nome": row["modalidade_nome"],
                "tipo_prazo": row["tipo_prazo"],
                "qtd_pedidos": 0,
                "qtd_itens": 0,
                "corte_em": None,
                "coleta_em": None,
                "compromisso_mais_proximo": None,
                "buckets": {},
            })

            if row["nivel"] == 1:
                mod["qtd_pedidos"] = row["qtd_pedidos"]
                mod["qtd_itens"] = row["qtd_itens"]
                mod["corte_em"] = row["corte_em"]
                mod["coleta_em"] = row["coleta_em"]
                mod["compromisso_mais_proximo"] = row["compromisso_mais_proximo"]
                continue

            mod["buckets"][row["bucket_prazo"]] = {
                "bucket": row["bucket_prazo"],
                "qtd_pedidos": row["qtd_pedidos"],
                "qtd_itens": row["qtd_itens"],
            }

        payload = []
        for mkt in marketplaces.values():
            mkt["modalidades"] = [
                {**mod, "buckets": list(mod["buckets"].values())}
                for mod in mkt["modalidades"].values()
            ]
            payload.append(mkt)

        return jsonify({"success": True, "data": {"data": p_data, "marketplaces": payload}})
    except Exception as exc:
        logger.error("Erro ao montar arvore de despacho: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": str(exc)}), 500


@despacho_bp.route("/escopo", methods=["GET"])
def get_escopo():
    """Pedidos de um no (integration_id, modalidade_id) dentro de um horizonte.

    Query params:
    - integration_id: int ou omitido/"null" para o no "Origem nao resolvida"
    - modalidade_id: int ou omitido/"null" para "Modalidade nao classificada"
    - horizonte: lista repetida, ex. ?horizonte=atrasado&horizonte=hoje
    - data: YYYY-MM-DD (default hoje)
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({"success": False, "error": "Nao autorizado"}), 401

        integration_id = _parse_int(request.args.get("integration_id"))
        modalidade_id = _parse_int(request.args.get("modalidade_id"))
        horizonte = request.args.getlist("horizonte") or ["atrasado", "hoje"]
        p_data = _parse_data(request.args.get("data"))

        ids_result = supabase_db.rpc("despacho_escopo_pedidos", {
            "p_integration_id": integration_id,
            "p_modalidade_id": modalidade_id,
            "p_horizonte": horizonte,
            "p_data": p_data,
        }).execute()
        pedido_ids = [row if isinstance(row, int) else row.get("despacho_escopo_pedidos")
                      for row in (ids_result.data or [])]
        pedido_ids = [pid for pid in pedido_ids if pid is not None]

        if not pedido_ids:
            return jsonify({"success": True, "data": {"total": 0, "pedidos": []}})

        pedidos_result = (
            supabase_db.table("pedidos")
            .select(
                "id,numero_pedido,codigo_pedido_externo,cliente_nome,total_pedido,"
                "data_venda,data_limite_envio,compromisso_logistico_em,"
                "metodo_envio_chave,metodo_envio_rotulo,modalidade_logistica_id,pack_id"
            )
            .in_("id", pedido_ids)
            .order("compromisso_logistico_em", desc=False)
            .execute()
        )
        pedidos = pedidos_result.data or []

        # Irmaos de pacote: esta e a tela onde a confusao custa caro. Dois
        # pedidos do mesmo pacote aparecem com o mesmo `numero_pedido` (o do
        # ERP), e e daqui que sai a demanda de producao. Sem o marcador, a
        # leitura natural e "duplicata" — e a reacao natural a duplicata,
        # momentos antes de lancar, e remover uma das linhas.
        pacotes = {}
        try:
            pack_result = supabase_db.rpc(
                "pedidos_pacotes", {"p_pedido_ids": [p["id"] for p in pedidos]}
            ).execute()
            pacotes = {row["pedido_id"]: row for row in (pack_result.data or [])}
        except Exception:
            logger.warning("Falha ao resolver pacotes do escopo", exc_info=True)

        for pedido in pedidos:
            pacote = pacotes.get(pedido["id"])
            pedido["pack_irmaos"] = (pacote or {}).get("irmaos") or 0
            pedido["pack_irmaos_ids"] = (pacote or {}).get("irmaos_ids") or []

        # Quebra por prazo do no inteiro, nao so do horizonte selecionado.
        # O card da torre mostra o total do no; a tela abre com horizonte
        # "atrasado + hoje" e mostra menos. Sem os buckets, a diferenca parece
        # pedido sumido — e a duvida certa ("cade os outros?") vira desconfianca
        # no contador, que e justamente o numero que existe para ser conferido
        # contra o painel do marketplace.
        buckets = {}
        try:
            arvore = supabase_db.rpc("despacho_arvore", {"p_data": p_data}).execute()
            for row in (arvore.data or []):
                if (row.get("nivel") == 2
                        and row.get("integration_id") == integration_id
                        and row.get("modalidade_id") == modalidade_id):
                    buckets[row.get("bucket_prazo")] = row.get("qtd_pedidos") or 0
        except Exception:
            logger.warning("Falha ao obter buckets do no", exc_info=True)

        return jsonify({
            "success": True,
            "data": {
                "total": len(pedido_ids),
                "pedidos": pedidos,
                "buckets": buckets,
                "total_no": sum(buckets.values()) if buckets else len(pedido_ids),
            },
        })
    except Exception as exc:
        logger.error("Erro ao obter escopo de despacho: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": str(exc)}), 500


@despacho_bp.route("/lancar", methods=["POST"])
def post_lancar():
    """Cria (ou complementa) uma demanda a partir de um escopo.

    Body JSON:
    {
      "integration_id": int|null,
      "modalidade_id": int|null,
      "horizonte": ["atrasado", "hoje"],
      "data": "YYYY-MM-DD",
      "nome": "opcional",
      "observacoes": "opcional"
    }
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({"success": False, "error": "Nao autorizado"}), 401

        body = request.get_json(silent=True) or {}
        integration_id = body.get("integration_id")
        modalidade_id = body.get("modalidade_id")
        horizonte = body.get("horizonte") or ["atrasado", "hoje"]
        p_data = _parse_data(body.get("data"))
        nome = body.get("nome")
        observacoes = body.get("observacoes")
        user_id = str((user or {}).get("id") or (user or {}).get("nome") or "System")

        result = supabase_db.rpc("despacho_lancar_escopo", {
            "p_integration_id": integration_id,
            "p_modalidade_id": modalidade_id,
            "p_horizonte": horizonte,
            "p_data": p_data,
            "p_nome": nome,
            "p_user_id": user_id,
            "p_observacoes": observacoes,
        }).execute()

        rows = result.data or []
        if not rows:
            return jsonify({"success": False, "error": "Escopo vazio"}), 409

        row = rows[0]
        return jsonify({
            "success": True,
            "data": {
                "demanda_id": row.get("out_demanda_id"),
                "demanda_codigo": row.get("out_demanda_codigo"),
                "total_pedidos": row.get("out_total_pedidos"),
                "total_itens": row.get("out_total_itens"),
                "complementar": row.get("out_complementar"),
            },
        })
    except Exception as exc:
        message = str(exc)
        if "Escopo vazio" in message or "no_data_found" in message.lower():
            return jsonify({"success": False, "error": "Escopo vazio: nenhum pedido em aberto para esse no e horizonte."}), 409
        logger.error("Erro ao lancar escopo de despacho: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": message}), 500


@despacho_bp.route("/esteira", methods=["GET"])
def get_esteira():
    """Fila de modalidades RELATIVO (ex.: Shopee Turbo), FIFO por prazo de
    etiqueta. Sem conceito de janela diaria: cada pedido tem relogio proprio.
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({"success": False, "error": "Nao autorizado"}), 401

        # Duas consultas simples em vez de embedded-resource-filter: menos
        # dependencia de sintaxe especifica de versao do client PostgREST.
        modalidades_relativo = (
            supabase_db.table("modalidades_logisticas")
            .select("id,codigo,nome,tipo_prazo,offset_etiqueta_min,offset_coleta_min,nivel_interrupcao")
            .eq("tipo_prazo", "RELATIVO")
            .execute()
        ).data or []
        modalidade_ids = [m["id"] for m in modalidades_relativo]
        modalidade_by_id = {m["id"]: m for m in modalidades_relativo}

        if not modalidade_ids:
            return jsonify({"success": True, "data": {"pedidos": []}})

        result = (
            supabase_db.table("pedidos")
            .select(
                "id,numero_pedido,codigo_pedido_externo,cliente_nome,"
                "marketplace_integration_id,compromisso_logistico_em,"
                "metodo_envio_rotulo,modalidade_logistica_id"
            )
            .is_("despachado_em", None)
            .in_("modalidade_logistica_id", modalidade_ids)
            .order("compromisso_logistico_em", desc=False)
            .limit(200)
            .execute()
        )

        pedidos = result.data or []
        for pedido in pedidos:
            pedido["modalidade"] = modalidade_by_id.get(pedido.get("modalidade_logistica_id"))

        return jsonify({"success": True, "data": {"pedidos": pedidos}})
    except Exception as exc:
        logger.error("Erro ao obter esteira de despacho: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": str(exc)}), 500


@despacho_bp.route("/admin/metodos-envio", methods=["GET"])
def get_metodos_envio():
    """Metodos de envio observados no ingest. status=novo lista os que ainda
    nao tem regra de classificacao — o gatilho de manutencao para cadastrar
    uma modalidade nova (ex.: Shopee Turbo) assim que ela aparece em producao.
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({"success": False, "error": "Nao autorizado"}), 401

        status = (request.args.get("status") or "").upper()
        query = supabase_db.table("metodos_envio_observados").select("*")
        if status in ("NOVO", "CLASSIFICADO", "IGNORADO"):
            query = query.eq("status", status)
        result = query.order("ultima_ocorrencia_em", desc=True).limit(200).execute()

        return jsonify({"success": True, "data": result.data or []})
    except Exception as exc:
        logger.error("Erro ao listar metodos de envio observados: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": str(exc)}), 500


@despacho_bp.route("/admin/modalidades", methods=["GET"])
def get_modalidades():
    """Catalogo de modalidades logisticas, para telas de cadastro."""
    try:
        user = get_current_user()
        if not user:
            return jsonify({"success": False, "error": "Nao autorizado"}), 401

        module_id = request.args.get("module_id")
        query = supabase_db.table("modalidades_logisticas").select("*")
        if module_id:
            query = query.eq("module_id", module_id)
        result = query.order("module_id").order("ordem_exibicao").execute()

        return jsonify({"success": True, "data": result.data or []})
    except Exception as exc:
        logger.error("Erro ao listar modalidades logisticas: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": str(exc)}), 500
