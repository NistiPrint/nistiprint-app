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
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, request
from nistiprint_shared.database.supabase_db_service import supabase_db
from routes.auth import get_current_user

import logging

logger = logging.getLogger("DespachoAPI")

despacho_bp = Blueprint("despacho", __name__)


#: O dia operacional e o do galpao. `date.today()` num container em UTC vira o
#: dia seguinte a partir das 21h de Sao Paulo — e foi assim que a torre passou a
#: tratar amanha como hoje e jogar os pedidos do dia no balde de atrasados.
FUSO_OPERACIONAL = ZoneInfo("America/Sao_Paulo")


def _hoje_operacional() -> str:
    return datetime.now(FUSO_OPERACIONAL).date().isoformat()


def _parse_data(raw: str | None) -> str:
    if not raw:
        return _hoje_operacional()
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return _hoje_operacional()


def _parse_int(raw: str | None) -> int | None:
    if raw in (None, "", "null"):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


# Espelha public.despacho_aba_do_bucket. A aba nunca tem contagem propria: ela
# agrupa os MESMOS buckets que a arvore ja devolve. Um segundo contador seria um
# segundo numero para a mesma pergunta, e mais cedo ou mais tarde os dois
# discordariam — que e o problema que a torre existe para eliminar.
#
# sem_prazo cai em "hoje" de proposito: prazo desconhecido e a hipotese mais
# urgente, nao a menos.
ABA_DO_BUCKET = {
    "atrasado": "hoje",
    "hoje": "hoje",
    "sem_prazo": "hoje",
    "amanha": "amanha",
    "depois": "proximos",
}


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
                "prazo_final_em": None,
                "compromisso_mais_proximo": None,
                "buckets": {},
                "coletas": {},
                "janelas": [],
            })

            if row["nivel"] == 1:
                mod["qtd_pedidos"] = row["qtd_pedidos"]
                mod["qtd_itens"] = row["qtd_itens"]
                mod["corte_em"] = row["corte_em"]
                mod["coleta_em"] = row["coleta_em"]
                mod["prazo_final_em"] = row["prazo_final_em"]
                mod["compromisso_mais_proximo"] = row["compromisso_mais_proximo"]
                continue

            # Níveis 2 e 3 são dois recortes do MESMO conjunto do nível 1, não
            # sub-níveis: prazo do marketplace (urgência) e coleta (qual
            # caminhão). Somar um com o outro conta cada pedido duas vezes.
            if row["nivel"] == 3:
                mod["coletas"][row["coleta_grupo"]] = {
                    "coleta_em": row["coleta_grupo"],
                    "qtd_pedidos": row["qtd_pedidos"],
                    "qtd_itens": row["qtd_itens"],
                }
                continue

            mod["buckets"][row["bucket_prazo"]] = {
                "bucket": row["bucket_prazo"],
                "qtd_pedidos": row["qtd_pedidos"],
                "qtd_itens": row["qtd_itens"],
            }

        # Entrega rapida e flag de cadastro (Shopee Flex/Turbo, ML Flex, Amazon
        # Same Day). Nao se deriva de tipo_prazo: Flex e FIXO e Turbo e
        # RELATIVO, e os dois sao rapidos.
        rapidas = {}
        try:
            cat = supabase_db.table("modalidades_logisticas").select("id,entrega_rapida").execute()
            rapidas = {m["id"]: bool(m.get("entrega_rapida")) for m in (cat.data or [])}
        except Exception:
            logger.warning("Falha ao carregar flag de entrega rapida", exc_info=True)

        # De que situacoes o total e feito. A tela de Pedidos filtrada por "Em
        # Andamento" mostra menos que a torre porque a torre tambem conta
        # Produzido e Pronto para Envio — ainda sao trabalho do galpao. Um
        # numero que precisa ser explicado toda vez e um numero que sera
        # desconfiado toda vez, entao a composicao vai junto.
        composicao = {}
        try:
            res_c = supabase_db.rpc("despacho_composicao_situacao", {"p_data": p_data}).execute()
            for c in (res_c.data or []):
                composicao.setdefault(c["integration_id"], []).append({
                    "situacao_id": c["situacao_id"],
                    "situacao": c["situacao_nome"],
                    "qtd_pedidos": c["qtd_pedidos"],
                })
        except Exception:
            logger.warning("Falha ao carregar composicao por situacao", exc_info=True)

        # Canais que compartilham a janela sao UM lote: saem no mesmo caminhao,
        # entao viram um card so e um lancamento so. Dois escopos para a mesma
        # coleta seriam dois lotes de producao para um caminhao.
        lote_por_modalidade = {}
        for mkt_id in {row["integration_id"] for row in rows}:
            if mkt_id is None:
                continue
            try:
                res_l = supabase_db.rpc("despacho_lotes", {"p_integration_id": mkt_id}).execute()
                for l in (res_l.data or []):
                    lote_por_modalidade[(mkt_id, l["modalidade_id"])] = l
            except Exception:
                logger.warning("Falha ao carregar lotes da integracao %s", mkt_id, exc_info=True)

        # Rascunho aberto por no. Nao subtrai da contagem — e marcador. A
        # invariante e que a soma dos filhos e igual ao pai e que nenhum pedido
        # e omitido.
        rascunhos = {}
        try:
            res_r = supabase_db.rpc("despacho_rascunhos_abertos", {"p_data": p_data}).execute()
            for r in (res_r.data or []):
                rascunhos[(r.get("integration_id"), r.get("modalidade_id"))] = r
        except Exception:
            logger.warning("Falha ao carregar rascunhos abertos", exc_info=True)

        # Saídas de despacho de cada lote: um mesmo corte pode ter coleta local
        # às 17h e entrega em ponto de coleta às 19h. É o que permite registrar
        # coleta parcial sem a demanda ficar atrasada — ainda há uma saída.
        for mkt in marketplaces.values():
            for mod in mkt["modalidades"].values():
                if not mod.get("modalidade_id") or not mod.get("coleta_em"):
                    continue
                try:
                    dia = str(mod["coleta_em"])[:10]
                    janelas = supabase_db.rpc("janelas_logisticas", {
                        "p_modalidade_id": mod["modalidade_id"],
                        "p_integration_id": mkt["integration_id"],
                        "p_dia": dia,
                    }).execute()
                    mod["janelas"] = janelas.data or []
                except Exception:
                    logger.warning("Falha ao obter janelas da modalidade %s", mod.get("modalidade_id"), exc_info=True)

        payload = []
        abas_totais = {"hoje": 0, "amanha": 0, "proximos": 0}
        for mkt in marketplaces.values():
            lotes = {}
            for mod in mkt["modalidades"].values():
                mod_id = mod.get("modalidade_id")
                info = lote_por_modalidade.get((mkt["integration_id"], mod_id))
                # Modalidade sem janela cadastrada e lote de si mesma: ela
                # precisa continuar visivel e lancavel, e o card sinaliza.
                chave = info["lote_chave"] if info else ("nc" if mod_id is None else str(mod_id))
                ids = info["modalidade_ids"] if info else ([] if mod_id is None else [mod_id])
                nome = info["lote_nome"] if info else mod.get("nome")
                rapida = info["entrega_rapida"] if info else rapidas.get(mod_id, False)

                lote = lotes.setdefault(chave, {
                    "lote_chave": chave,
                    "modalidade_ids": ids,
                    "modalidade_id": mod_id,
                    "nome": nome,
                    "codigo": mod.get("codigo"),
                    "tipo_prazo": mod.get("tipo_prazo"),
                    "entrega_rapida": bool(rapida),
                    "qtd_pedidos": 0,
                    "qtd_itens": 0,
                    "corte_em": mod.get("corte_em"),
                    "coleta_em": mod.get("coleta_em"),
                    "prazo_final_em": mod.get("prazo_final_em"),
                    "compromisso_mais_proximo": mod.get("compromisso_mais_proximo"),
                    "janelas": mod.get("janelas") or [],
                    "coletas": {},
                    "buckets": {},
                    "por_aba": {"hoje": 0, "amanha": 0, "proximos": 0},
                    "rascunho": None,
                })

                lote["qtd_pedidos"] += mod.get("qtd_pedidos") or 0
                lote["qtd_itens"] += mod.get("qtd_itens") or 0
                if not lote["janelas"] and mod.get("janelas"):
                    lote["janelas"] = mod["janelas"]

                for bucket in mod["buckets"].values():
                    aba = ABA_DO_BUCKET.get(bucket["bucket"], "proximos")
                    alvo = lote["buckets"].setdefault(bucket["bucket"], {
                        "bucket": bucket["bucket"], "aba": aba, "qtd_pedidos": 0, "qtd_itens": 0,
                    })
                    alvo["qtd_pedidos"] += bucket["qtd_pedidos"] or 0
                    alvo["qtd_itens"] += bucket["qtd_itens"] or 0
                    lote["por_aba"][aba] += bucket["qtd_pedidos"] or 0
                    abas_totais[aba] += bucket["qtd_pedidos"] or 0

                for coleta in mod["coletas"].values():
                    alvo = lote["coletas"].setdefault(coleta["coleta_em"], {
                        "coleta_em": coleta["coleta_em"], "qtd_pedidos": 0, "qtd_itens": 0,
                    })
                    alvo["qtd_pedidos"] += coleta["qtd_pedidos"] or 0
                    alvo["qtd_itens"] += coleta["qtd_itens"] or 0

                r = rascunhos.get((mkt["integration_id"], mod_id))
                if r and not lote["rascunho"]:
                    lote["rascunho"] = r

            mkt["modalidades"] = [
                {**l, "buckets": list(l["buckets"].values()),
                 "coletas": sorted(l["coletas"].values(), key=lambda c: c["coleta_em"] or "")}
                for l in lotes.values()
            ]
            mkt["composicao"] = composicao.get(mkt["integration_id"], [])
            payload.append(mkt)

        return jsonify({"success": True, "data": {
            "data": p_data,
            "marketplaces": payload,
            "abas": abas_totais,
        }})
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
        horizonte = request.args.getlist("horizonte") or ["atrasado", "hoje"]
        p_data = _parse_data(request.args.get("data"))

        # O no da torre e o LOTE: um ou mais canais que compartilham a janela.
        # `modalidade_id` continua aceito para quem chama a rota antiga.
        modalidade_ids = [_parse_int(v) for v in request.args.getlist("modalidade_ids")]
        modalidade_ids = [m for m in modalidade_ids if m is not None]
        if not modalidade_ids:
            unico = _parse_int(request.args.get("modalidade_id"))
            modalidade_ids = [unico] if unico is not None else None

        ids_result = supabase_db.rpc("despacho_escopo_lote", {
            "p_integration_id": integration_id,
            "p_modalidade_ids": modalidade_ids,
            "p_horizonte": horizonte,
            "p_data": p_data,
        }).execute()
        pedido_ids = [row if isinstance(row, int) else row.get("despacho_escopo_lote")
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
            alvo = set(modalidade_ids) if modalidade_ids else {None}
            for row in (arvore.data or []):
                if (row.get("nivel") == 2
                        and row.get("integration_id") == integration_id
                        and row.get("modalidade_id") in alvo):
                    b = row.get("bucket_prazo")
                    buckets[b] = (buckets.get(b) or 0) + (row.get("qtd_pedidos") or 0)
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
    """Monta um RASCUNHO de demanda a partir de um escopo da torre.

    Nao publica e nao carimba despachado_em: o pedido continua na torre ate a
    publicacao. Lancar de novo no mesmo escopo SOMA no rascunho aberto em vez
    de criar um segundo lote para a mesma coleta — e a regra de retardatario da
    spec, e e o que impede o mesmo pedido de existir em duas demandas.

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
        modalidade_ids = body.get("modalidade_ids")
        if not modalidade_ids:
            unico = body.get("modalidade_id")
            modalidade_ids = [unico] if unico is not None else None
        horizonte = body.get("horizonte") or ["atrasado", "hoje"]
        p_data = _parse_data(body.get("data"))
        nome = body.get("nome")
        observacoes = body.get("observacoes")
        user_id = str((user or {}).get("id") or (user or {}).get("nome") or "System")

        result = supabase_db.rpc("despacho_lancar_lote", {
            "p_integration_id": integration_id,
            "p_modalidade_ids": modalidade_ids,
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
                # somou num rascunho que ja existia em vez de criar outro
                "somou_em_rascunho": row.get("out_complementar"),
                "status": "RASCUNHO",
            },
        })
    except Exception as exc:
        message = str(exc)
        if "Escopo vazio" in message or "no_data_found" in message.lower():
            return jsonify({"success": False, "error": "Escopo vazio: nenhum pedido em aberto para esse no e horizonte."}), 409
        logger.error("Erro ao lancar escopo de despacho: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": message}), 500


@despacho_bp.route("/publicar", methods=["POST"])
def post_publicar():
    """Publica um rascunho: RASCUNHO -> AGUARDANDO.

    E aqui, e so aqui, que despachado_em e carimbado — o momento em que o
    galpao assume o lote e os pedidos saem da torre. Publicar duas vezes e
    recusado pela propria funcao de banco.

    Body JSON: {"demanda_id": int}
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({"success": False, "error": "Nao autorizado"}), 401

        body = request.get_json(silent=True) or {}
        demanda_id = _parse_int(body.get("demanda_id"))
        if demanda_id is None:
            return jsonify({"success": False, "error": "demanda_id e obrigatorio"}), 400

        user_id = str((user or {}).get("id") or (user or {}).get("nome") or "System")
        result = supabase_db.rpc("despacho_publicar_demanda", {
            "p_demanda_id": demanda_id,
            "p_user_id": user_id,
        }).execute()

        rows = result.data or []
        if not rows:
            return jsonify({"success": False, "error": "Demanda nao encontrada"}), 404

        row = rows[0]
        return jsonify({"success": True, "data": {
            "demanda_codigo": row.get("out_demanda_codigo"),
            "total_pedidos": row.get("out_total_pedidos"),
            "total_itens": row.get("out_total_itens"),
            "status": "AGUARDANDO",
        }})
    except Exception as exc:
        message = str(exc)
        # A funcao recusa republicacao com invalid_parameter_value. Isso e
        # conflito de estado, nao erro de servidor: 409 diz ao cliente que
        # repetir nao vai adiantar.
        if "so rascunho pode ser publicado" in message:
            return jsonify({"success": False, "error": "Esta demanda ja foi publicada."}), 409
        if "nao tem pedidos" in message:
            return jsonify({"success": False, "error": "Rascunho sem pedidos."}), 409
        logger.error("Erro ao publicar demanda: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": message}), 500


@despacho_bp.route("/rascunhos", methods=["GET"])
def get_rascunhos():
    """Rascunhos abertos do dia, por no da torre.

    `pedidos_ja_fora` conta os que sairam da pendencia DEPOIS de entrarem no
    lote — cancelados, devolvidos ou enviados por fora. E a checagem que o
    operador precisa ver antes de publicar um lote que promete produzir o que
    nao existe mais.
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({"success": False, "error": "Nao autorizado"}), 401

        p_data = _parse_data(request.args.get("data"))
        result = supabase_db.rpc("despacho_rascunhos_abertos", {"p_data": p_data}).execute()
        return jsonify({"success": True, "data": result.data or []})
    except Exception as exc:
        logger.error("Erro ao listar rascunhos abertos: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": str(exc)}), 500


@despacho_bp.route("/demanda/<int:demanda_id>/itens", methods=["GET"])
def get_itens_demanda(demanda_id):
    """Linhas de producao de uma demanda, na ordem de producao.

    Ordenadas por carga de miolo decrescente e, dentro do miolo, por quantidade
    decrescente — a mesma ordem da planilha do legado. `contabiliza_estoque`
    falso nao e pendencia: significa que a linha produz sem movimentar estoque,
    porque o SKU nao tem produto interno vinculado.
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({"success": False, "error": "Nao autorizado"}), 401

        itens = (
            supabase_db.table("itens_demanda")
            .select("id,ordem,sku_externo,descricao,variacao,quantidade,"
                    "miolo_nome,miolo_chave,miolo_origem,produto_id,"
                    "id_produto_miolo,contabiliza_estoque,dados_adicionais")
            .eq("demanda_id", demanda_id)
            .order("ordem")
            .execute()
        ).data or []

        demanda = (
            supabase_db.table("demandas_producao")
            .select("id,demanda_id,descricao,status,data_entrega,escopo_despacho,publicado_em")
            .eq("id", demanda_id).limit(1).execute()
        ).data or []

        return jsonify({"success": True, "data": {
            "demanda": demanda[0] if demanda else None,
            "itens": itens,
            "total_pecas": sum(float(i.get("quantidade") or 0) for i in itens),
            "sem_estoque": sum(1 for i in itens if not i.get("contabiliza_estoque")),
        }})
    except Exception as exc:
        logger.error("Erro ao obter itens da demanda %s: %s", demanda_id, exc, exc_info=True)
        return jsonify({"success": False, "error": str(exc)}), 500


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
