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
import json
import os
import tempfile
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, request
from werkzeug.utils import secure_filename
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.order_erp_reference_service import (
    order_erp_reference_service,
)
from routes.auth import get_current_user

import logging

logger = logging.getLogger("DespachoAPI")

despacho_bp = Blueprint("despacho", __name__)


def _json_request_value(value, default=None):
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _conferencia(conferencia_id: int) -> dict | None:
    rows = (supabase_db.table("conferencias_arquivo").select("*")
            .eq("id", conferencia_id).limit(1).execute().data or [])
    return dict(rows[0]) if rows else None


def _conferencia_payload(row: dict) -> dict:
    """O que a tela do escopo precisa saber sobre a planilha que a originou.

    Derivado inteiramente das colunas gravadas, e nao das contagens que a
    leitura devolveu em memoria: assim a conferencia recem-criada e a mesma
    conferencia relida depois do ingest respondem com o mesmo shape. Enquanto
    isso nao era verdade, recarregar a conferencia apagava o funil da tela — e
    com ele o botao que levava a consolidacao.

    O funil conta o DESCARTE por etapa, nao o restante. O operador nao precisa
    saber quantas linhas sobreviveram a cada filtro; ele precisa descobrir que
    escolheu o filtro errado, e isso aparece no tamanho do que foi jogado fora.
    """
    descartes = row.get("descartes") or []
    por_etapa: dict[str, int] = {}
    for item in descartes:
        etapa = (item or {}).get("etapa") or "filtro"
        por_etapa[etapa] = por_etapa.get(etapa, 0) + 1

    pedido_ids = [int(value) for value in (row.get("pedido_ids") or []) if value]
    nao_encontrados = row.get("nao_encontrados") or []
    fora_da_torre = row.get("fora_da_torre") or []

    return {
        "conferencia_id": row.get("id"),
        "arquivo_nome": row.get("arquivo_nome"),
        "module_id": row.get("module_id"),
        "filtro": row.get("filtro") or {},
        "demanda_id": row.get("demanda_id"),
        "funil": {
            "linhas": row.get("total_linhas") or 0,
            "refs": row.get("total_refs") or 0,
            "descartados": sorted(
                ({"etapa": etapa, "qtd": qtd} for etapa, qtd in por_etapa.items()),
                key=lambda item: -item["qtd"],
            ),
            "casados": len(pedido_ids) + len(fora_da_torre),
            "na_torre": len(pedido_ids),
            "nao_encontrados": len(nao_encontrados),
            "fora_da_torre": len(fora_da_torre),
        },
        "nao_encontrados": nao_encontrados,
        "fora_da_torre": fora_da_torre,
        "ingest_resultado": row.get("ingest_resultado"),
        "erp_resultado": row.get("erp_resultado"),
    }


def _pedido_ids_da_conferencia(conferencia_id: int) -> list[int]:
    conferencia = _conferencia(conferencia_id)
    if not conferencia:
        return []
    ids = [int(value) for value in (conferencia.get("pedido_ids") or []) if value]
    if not ids:
        return []
    # O recorte salvo e a fonte de verdade, mas o pedido pode ter saido da
    # torre entre a conferencia e a acao. Revalidar evita lancar cancelados ou
    # pedidos ja publicados.
    try:
        rows = (supabase_db.table("vw_pedidos_pendentes_despacho")
                .select("id").in_("id", ids).execute().data or [])
    except Exception:
        rows = (supabase_db.table("pedidos").select("id")
                .in_("id", ids).is_("despachado_em", None)
                .in_("situacao_pedido_id", [2, 3, 4]).execute().data or [])
    validos = {int(row["id"]) for row in rows if row.get("id") is not None}
    return [pedido_id for pedido_id in ids if pedido_id in validos]


def _casar_refs(refs: list[str]) -> list[dict]:
    if not refs:
        return []
    return supabase_db.rpc("consolidar_casar_refs", {"p_refs": refs}).execute().data or []


def _serializar_linhas(linhas):
    def safe(value):
        if isinstance(value, dict):
            return {str(key): safe(item) for key, item in value.items()}
        if isinstance(value, list):
            return [safe(item) for item in value]
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return value
    return safe(linhas)


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
        conferencia_id = _parse_int(request.args.get("conferencia_id"))
        horizonte = request.args.getlist("horizonte") or ["atrasado", "hoje"]
        p_data = _parse_data(request.args.get("data"))

        # O no da torre e o LOTE: um ou mais canais que compartilham a janela.
        # `modalidade_id` continua aceito para quem chama a rota antiga.
        modalidade_ids = [_parse_int(v) for v in request.args.getlist("modalidade_ids")]
        modalidade_ids = [m for m in modalidade_ids if m is not None]
        if not modalidade_ids:
            unico = _parse_int(request.args.get("modalidade_id"))
            modalidade_ids = [unico] if unico is not None else None

        if conferencia_id is not None:
            pedido_ids = _pedido_ids_da_conferencia(conferencia_id)
        else:
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
            return jsonify({"success": True, "data": {"total": 0, "pedidos": [], "conferencia_id": conferencia_id}})

        pedidos_result = (
            supabase_db.table("pedidos")
            .select(
                "id,numero_pedido,codigo_pedido_externo,cliente_nome,total_pedido,"
                "data_venda,data_limite_envio,compromisso_logistico_em,"
                "metodo_envio_chave,metodo_envio_rotulo,modalidade_logistica_id,pack_id,"
                # O numero do ERP e util para o galpao, mas o numero que o
                # operador confere contra o painel do marketplace e este.
                # Sem ele a lista da torre nao casa com a tela de origem.
                "marketplace_order_id,marketplace_module_id,"
                "erp_integration_id,erp_order_id,erp_order_number"
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
                "conferencia_id": conferencia_id,
                "conferencia": _conferencia(conferencia_id) if conferencia_id else None,
            },
        })
    except Exception as exc:
        logger.error("Erro ao obter escopo de despacho: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": str(exc)}), 500


@despacho_bp.route("/arquivo/conferir", methods=["POST"])
def conferir_arquivo():
    """Le, filtra e casa uma planilha sem criar demanda."""
    user = get_current_user()
    if not user:
        return jsonify({"success": False, "error": "Nao autorizado"}), 401

    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify({"success": False, "error": "Arquivo obrigatorio"}), 400
    original_name = upload.filename
    safe_name = secure_filename(original_name)
    suffix = os.path.splitext(safe_name)[1].lower()
    if suffix not in {".xlsx", ".xls", ".csv"}:
        return jsonify({"success": False, "error": "Apenas arquivos XLSX, XLS ou CSV sao aceitos"}), 400

    from services.mapeamento_planilha import MAPEAMENTOS, conferir_linhas, ler_linhas, normalizar_module_id

    module_id = normalizar_module_id(request.form.get("module_id") or request.form.get("platform"))
    mapping = MAPEAMENTOS.get(module_id) if module_id else None
    filtro = _json_request_value(request.form.get("filtro"), {}) or {}
    integration_id = _parse_int(request.form.get("marketplace_integration_id") or request.form.get("integration_id"))
    fd, path = tempfile.mkstemp(prefix="despacho-arquivo-", suffix=suffix)
    os.close(fd)
    try:
        upload.save(path)
        linhas, mapping = ler_linhas(path, mapping, module_id)
        resultado = conferir_linhas(linhas, mapping, filtro)
        refs = resultado.refs
        casamentos = _casar_refs(refs)
        por_ref = {str(row.get("ref")): row for row in casamentos}
        pedido_ids = list(dict.fromkeys(
            int(row["pedido_id"]) for row in casamentos
            if row.get("pedido_id") and row.get("na_torre")
        ))
        nao_encontrados = [ref for ref in refs if not por_ref.get(ref, {}).get("pedido_id")]
        fora = []
        for row in casamentos:
            if row.get("pedido_id") and not row.get("na_torre"):
                fora.append({
                    **row,
                    "motivo": "Pedido ja despachado ou fora das situacoes pendentes da torre",
                })
        row = (supabase_db.table("conferencias_arquivo").insert({
            "arquivo_nome": safe_name or "arquivo",
            "module_id": mapping.module_id,
            "marketplace_integration_id": integration_id,
            "filtro": filtro,
            "total_linhas": len(linhas),
            "total_refs": len(refs),
            "descartes": _serializar_linhas(resultado.descartes),
            "linhas": _serializar_linhas([line.as_dict() for line in resultado.linhas]),
            "pedido_ids": pedido_ids,
            "nao_encontrados": nao_encontrados,
            "fora_da_torre": _serializar_linhas(fora),
            "criado_por": str((user or {}).get("id") or (user or {}).get("nome") or "System"),
        }).execute().data or [None])[0]
        if not row:
            raise RuntimeError("Nao foi possivel gravar a conferencia")
        # Mesmo shape de GET /arquivo/<id>: a tela do escopo le os dois pelo
        # mesmo caminho, entao a conferencia recem-criada e a relida depois do
        # ingest nao podem diferir.
        data = {
            **_conferencia_payload(row),
            "filtros": [f.serialize() for f in mapping.filtros],
        }
        return jsonify({"success": True, "data": data})
    except Exception as exc:
        logger.error("Erro ao conferir arquivo de despacho: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": str(exc)}), 400
    finally:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


@despacho_bp.route("/arquivo/<int:conferencia_id>", methods=["GET"])
def get_conferencia_arquivo(conferencia_id):
    if not get_current_user():
        return jsonify({"success": False, "error": "Nao autorizado"}), 401
    row = _conferencia(conferencia_id)
    if not row:
        return jsonify({"success": False, "error": "Conferencia nao encontrada"}), 404
    return jsonify({"success": True, "data": _conferencia_payload(row)})


@despacho_bp.route("/arquivo/<int:conferencia_id>/ingerir", methods=["POST"])
def ingerir_conferencia_arquivo(conferencia_id):
    """Cria pedidos ausentes pelo pipeline canonico, incluindo itens."""
    if not get_current_user():
        return jsonify({"success": False, "error": "Nao autorizado"}), 401
    conferencia = _conferencia(conferencia_id)
    if not conferencia:
        return jsonify({"success": False, "error": "Conferencia nao encontrada"}), 404

    from nistiprint_shared.services.canonical_order_repository import canonical_order_repository
    from nistiprint_shared.services.canonical_order_snapshot_service import canonical_order_snapshot_service

    linhas = conferencia.get("linhas") or []
    nao_encontrados = set(str(item) for item in (conferencia.get("nao_encontrados") or []))
    grupos: dict[str, list[dict]] = {}
    for linha in linhas:
        pedido = linha.get("pedido") or {}
        item = linha.get("item") or {}
        ref = str(pedido.get("marketplace_order_id") or "").strip()
        if ref and ref in nao_encontrados and item.get("sku_externo"):
            grupos.setdefault(ref, []).append(linha)

    resultado = {"criados": [], "existentes": [], "erros": []}
    for ref, itens_linha in grupos.items():
        first = itens_linha[0]
        pedido = first.get("pedido") or {}
        itens = []
        for linha in itens_linha:
            item = linha.get("item") or {}
            itens.append({
                "sku": item.get("sku_externo"),
                "name": item.get("titulo_anuncio"),
                "quantity": item.get("quantidade") or 1,
                "unit_price": item.get("preco_unitario") or 0,
                "variacao": item.get("variacao_externa"),
            })
        order = {
            "marketplace_module_id": conferencia.get("module_id"),
            "marketplace_order_id": ref,
            "marketplace_integration_id": conferencia.get("marketplace_integration_id"),
            "ingest_source": "planilha",
            "situacao_pedido_id": 2,
            "cliente_nome": pedido.get("cliente_nome"),
            "cliente_documento": pedido.get("cliente_documento"),
            "total_pedido": pedido.get("total_pedido"),
            "data_limite_envio": pedido.get("data_limite_envio"),
            "metodo_envio_rotulo": pedido.get("metodo_envio_rotulo"),
            "modalidade_logistica": pedido.get("modalidade_logistica"),
        }
        snapshot = {
            "identity": {"marketplace_order_id": ref},
            "customer": {"name": pedido.get("cliente_nome"), "document": pedido.get("cliente_documento"), "username": pedido.get("buyer_username")},
            "items": itens,
            "logistics": {"deadline": pedido.get("data_limite_envio"), "service": pedido.get("metodo_envio_rotulo"), "collection_at": pedido.get("data_coleta")},
            "financial": {"total": pedido.get("total_pedido"), "currency": "BRL"},
            "platform_fields": {"planilha": {"arquivo": conferencia.get("arquivo_nome"), "conferencia_id": conferencia_id, "linhas": [line.get("numero_linha") for line in itens_linha], "bruto": [line.get("bruto") for line in itens_linha]}},
        }
        refs = [{"role": "sales_origin", "module_id": conferencia.get("module_id"), "external_order_id": ref, "integration_id": conferencia.get("marketplace_integration_id")}]
        try:
            pedido_id = canonical_order_repository.upsert(order, snapshot, refs)
            canonical_order_snapshot_service.upsert_snapshot(
                pedido_id=pedido_id, ingest_source="planilha", marketplace=conferencia.get("module_id"),
                marketplace_order_id=ref, marketplace_integration_id=conferencia.get("marketplace_integration_id"),
                customer=snapshot["customer"], items=itens, logistics=snapshot["logistics"], financial=snapshot["financial"],
                platform_fields=snapshot["platform_fields"], raw_refs={"sales_origin": ref}, upsert_items=True,
            )
            resultado["criados"].append({"pedido_id": pedido_id, "ref": ref})
        except Exception as exc:
            logger.warning("Falha ao ingerir pedido da conferencia %s (%s): %s", conferencia_id, ref, exc, exc_info=True)
            resultado["erros"].append({"ref": ref, "erro": "Falha ao ingerir pedido"})

    refs = [str((line.get("pedido") or {}).get("marketplace_order_id")) for line in linhas if (line.get("pedido") or {}).get("marketplace_order_id")]
    casamentos = _casar_refs(list(dict.fromkeys(refs)))
    pedido_ids = list(dict.fromkeys(int(item["pedido_id"]) for item in casamentos if item.get("pedido_id") and item.get("na_torre")))
    update = {"pedido_ids": pedido_ids, "nao_encontrados": [item["ref"] for item in casamentos if not item.get("pedido_id")], "ingest_resultado": resultado}
    supabase_db.table("conferencias_arquivo").update(update).eq("id", conferencia_id).execute()

    # Resolve automaticamente o que acabou de nascer; o endpoint abaixo fica
    # disponivel como retry quando o pedido ainda nao chegou ao Bling.
    erp_resultado = {"ready": [], "blocked": []}
    if resultado["criados"]:
        erp_resultado = order_erp_reference_service.resolve_many([item["pedido_id"] for item in resultado["criados"]])
        supabase_db.table("conferencias_arquivo").update({"erp_resultado": erp_resultado}).eq("id", conferencia_id).execute()
    return jsonify({"success": True, "data": {"conferencia_id": conferencia_id, "ingest": resultado, "erp": erp_resultado, "pedido_ids": pedido_ids}})


@despacho_bp.route("/arquivo/<int:conferencia_id>/resolver-erp", methods=["POST"])
def resolver_erp_conferencia(conferencia_id):
    if not get_current_user():
        return jsonify({"success": False, "error": "Nao autorizado"}), 401
    conferencia = _conferencia(conferencia_id)
    if not conferencia:
        return jsonify({"success": False, "error": "Conferencia nao encontrada"}), 404
    resultado = order_erp_reference_service.resolve_many([int(value) for value in (conferencia.get("pedido_ids") or []) if value])
    supabase_db.table("conferencias_arquivo").update({"erp_resultado": resultado}).eq("id", conferencia_id).execute()
    return jsonify({"success": True, "data": {"conferencia_id": conferencia_id, "erp": resultado}})


def _linha_consolidada(row: dict) -> dict:
    """Contrato unico da linha de producao, venha da previa ou da demanda.

    A previa sai de `despacho_consolidar_pedidos` e a demanda ja materializada
    sai de `itens_demanda`. As duas descrevem exatamente a mesma linha — e
    precisam, porque a previa existe para prometer o que o lancamento vai
    produzir — mas nomeiam dois campos de forma diferente: `titulo_anuncio` vs.
    `descricao` e `miolo` vs. `miolo_nome`.

    Traduzir aqui, uma vez, e o que permite a tela renderizar as duas com o
    mesmo componente. Enquanto a traducao nao existia, a previa do arquivo lia
    `descricao` e `pedido_ids` — nomes que a RPC nao devolve — e toda linha
    aparecia como "Sem descricao" com zero pedidos.
    """
    quantidade = float(row.get("quantidade") or 0)
    return {
        "ordem": row.get("ordem"),
        "sku_externo": row.get("sku_externo"),
        # `titulo` fecha a chave da linha. A consolidacao agrupa por
        # (titulo, sku, variacao, miolo_chave): o mesmo SKU anunciado com dois
        # titulos diferentes vira DUAS linhas, e um ajuste sem o titulo acerta
        # uma delas em silencio.
        "titulo": row.get("descricao") or row.get("titulo_anuncio"),
        "descricao": row.get("descricao") or row.get("titulo_anuncio"),
        "variacao": row.get("variacao"),
        "quantidade": quantidade,
        "produto_id": row.get("produto_id"),
        "produto_nome": row.get("produto_nome"),
        "miolo_nome": row.get("miolo_nome") or row.get("miolo"),
        "miolo_chave": row.get("miolo_chave"),
        "miolo_origem": row.get("miolo_origem"),
        "id_produto_miolo": row.get("id_produto_miolo"),
        "contabiliza_estoque": bool(row.get("contabiliza_estoque")),
        "pedidos_origem": row.get("pedidos_origem") or [],
        "eh_kit": bool(row.get("eh_kit")),
    }


def _marcar_kits(itens: list[dict]) -> list[dict]:
    """Diz quais linhas sao kit, em uma consulta para o lote inteiro.

    A consolidacao nao explode kit — quem decide isso e o operador (ver
    `20260901100000`). Para decidir, ele precisa VER que aquela linha e um kit,
    e e so isso que este passo acrescenta.
    """
    ids = sorted({item["produto_id"] for item in itens if item.get("produto_id")})
    if not ids:
        return itens
    try:
        resp = supabase_db.table("produtos").select("id,formato").in_("id", ids).execute()
        kits = {row["id"] for row in (resp.data or []) if row.get("formato") == "kit"}
    except Exception:
        logger.warning("Nao foi possivel marcar os kits da previa", exc_info=True)
        return itens
    for item in itens:
        item["eh_kit"] = item.get("produto_id") in kits
    return itens


def _resumo_consolidacao(itens: list[dict]) -> dict:
    """Os tres numeros que a tela mostra acima da tabela."""
    return {
        "total_linhas": len(itens),
        "total_pecas": sum(item["quantidade"] for item in itens),
        "sem_estoque": sum(1 for item in itens if not item["contabiliza_estoque"]),
        "total_miolos": len({item.get("miolo_chave") for item in itens}),
    }


@despacho_bp.route("/previsao", methods=["GET"])
def previsao_consolidacao():
    """A consolidacao do lote ANTES de fechar: produto, miolo e ordem de producao.

    Chama a mesma RPC que o lancamento usa para materializar os itens
    (`despacho_materializar_itens` -> `despacho_consolidar_pedidos`), so que sem
    gravar nada. E por isso que a previa e a demanda publicada mostram as mesmas
    linhas: nao existe uma segunda consolidacao para divergir da primeira.

    Aceita as tres origens de lote (demanda_id, escopo da torre, conferencia de
    arquivo) — a previa vale para todas, e nao so para o arquivo: no fluxo da
    torre o operador tambem so via a consolidacao depois de ja ter criado o
    rascunho no banco.
    """
    try:
        if not get_current_user():
            return jsonify({"success": False, "error": "Nao autorizado"}), 401

        ids, chave = _pedido_ids_do_lote(request.args)
        if not ids:
            return jsonify({"success": True, "data": {
                "total_pedidos": 0, "itens": [], "chave": chave,
                **_resumo_consolidacao([]),
            }})

        rows = supabase_db.rpc(
            "despacho_consolidar_pedidos", {"p_pedido_ids": ids}
        ).execute().data or []
        itens = _marcar_kits([_linha_consolidada(row) for row in rows])

        return jsonify({"success": True, "data": {
            "total_pedidos": len(ids),
            "itens": itens,
            "chave": chave,
            **_resumo_consolidacao(itens),
        }})
    except Exception as exc:
        # Sem retaguarda que "degrade" para itens crus: uma lista sem miolo e
        # sem produto resolvido nao e uma previa pior, e uma previa errada — e
        # ela seria lida como a promessa do que vai para producao.
        logger.error("Erro ao montar previa da consolidacao: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": str(exc)}), 500


# Ajustes da previa -----------------------------------------------------------
#
# O operador edita a lista ANTES de publicar: remove uma linha, corrige uma
# quantidade, ou explode um kit nos produtos que o compoem. O contrato e
# pequeno de proposito — o que chega ao banco e uma lista de operacoes
# auditavel, gravada em `escopo_despacho.ajustes`, e nao uma segunda
# consolidacao feita no cliente.

_OPS_AJUSTE = {"remover", "quantidade", "explodir"}


def _ajustes_validos(bruto) -> list[dict]:
    """Filtra e valida os ajustes vindos da tela.

    Recusar aqui, com mensagem, e melhor do que deixar o `RAISE EXCEPTION` do
    Postgres chegar cru na tela — e evita gravar um rascunho para so depois
    descobrir que o ajuste era invalido.
    """
    if not bruto:
        return []
    if not isinstance(bruto, list):
        raise ValueError("ajustes deve ser uma lista")

    limpos: list[dict] = []
    for item in bruto:
        if not isinstance(item, dict):
            raise ValueError("cada ajuste deve ser um objeto")
        op = str(item.get("op") or "").strip().lower()
        if op not in _OPS_AJUSTE:
            raise ValueError(f"operacao de ajuste desconhecida: {op or '(vazia)'}")
        sku = str(item.get("sku") or "").strip()
        if not sku:
            raise ValueError("ajuste sem sku")
        limpo = {
            "op": op,
            "sku": sku,
            "variacao": str(item.get("variacao") or "-").strip() or "-",
            "miolo_chave": item.get("miolo_chave"),
        }
        titulo = str(item.get("titulo") or "").strip()
        if titulo:
            limpo["titulo"] = titulo
        if op == "quantidade":
            try:
                valor = float(item.get("valor"))
            except (TypeError, ValueError):
                raise ValueError(f"quantidade invalida para {sku}")
            if valor <= 0:
                raise ValueError(f"quantidade deve ser maior que zero ({sku})")
            limpo["valor"] = valor
        limpos.append(limpo)
    return limpos


def _aplicar_ajustes(demanda_id: int, ajustes: list[dict], user_id: str) -> float | None:
    """Refaz os itens do rascunho com os ajustes. Devolve o novo total."""
    if not ajustes:
        return None
    resultado = supabase_db.rpc("despacho_reaplicar_itens", {
        "p_demanda_id": int(demanda_id),
        "p_ajustes": ajustes,
        "p_user_id": user_id,
    }).execute()
    return resultado.data


@despacho_bp.route("/kit/<int:produto_id>/componentes", methods=["GET"])
def get_kit_componentes(produto_id: int):
    """Em que produtos um kit se desdobra, com o miolo de cada um.

    A tela usa isto para mostrar o resultado da explosao antes de o operador
    confirmar — explodir sem ver no que vai dar e o tipo de acao que se desfaz
    tarde demais.
    """
    try:
        if not get_current_user():
            return jsonify({"success": False, "error": "Nao autorizado"}), 401
        rows = supabase_db.rpc("despacho_kit_componentes", {
            "p_produto_id": produto_id
        }).execute().data or []
        return jsonify({"success": True, "data": {"componentes": rows}})
    except Exception as exc:
        logger.error("Erro ao buscar componentes do kit %s: %s", produto_id, exc, exc_info=True)
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

        try:
            ajustes = _ajustes_validos(body.get("ajustes"))
        except ValueError as erro:
            return jsonify({"success": False, "error": str(erro)}), 400

        conferencia_id = _parse_int(body.get("conferencia_id"))
        if conferencia_id is not None:
            conferencia = _conferencia(conferencia_id)
            if not conferencia:
                return jsonify({"success": False, "error": "Conferencia nao encontrada"}), 404
            pedido_ids = _pedido_ids_da_conferencia(conferencia_id)
            if not pedido_ids:
                return jsonify({"success": False, "error": "Conferencia sem pedidos pendentes"}), 409
            result = supabase_db.rpc("despacho_lancar_pedidos", {
                "p_pedido_ids": pedido_ids,
                "p_nome": nome,
                "p_user_id": user_id,
                "p_observacoes": observacoes,
                "p_escopo": {
                    "conferencia_id": conferencia_id,
                    "arquivo_nome": conferencia.get("arquivo_nome"),
                    "module_id": conferencia.get("module_id"),
                    "filtro": conferencia.get("filtro") or {},
                    "nome": nome,
                },
            }).execute()
            rows = result.data or []
            if not rows:
                return jsonify({"success": False, "error": "Escopo vazio"}), 409
            row = rows[0]
            demanda_id = row.get("out_demanda_id")
            supabase_db.table("conferencias_arquivo").update({"demanda_id": demanda_id}).eq("id", conferencia_id).execute()
            total_ajustado = _aplicar_ajustes(demanda_id, ajustes, user_id)
            return jsonify({"success": True, "data": {
                "demanda_id": demanda_id,
                "demanda_codigo": row.get("out_demanda_codigo"),
                "total_pedidos": row.get("out_total_pedidos"),
                "total_itens": total_ajustado if total_ajustado is not None else row.get("out_total_itens"),
                "ajustes_aplicados": len(ajustes),
                "ja_em_rascunho": row.get("out_ja_em_rascunho") or [],
                "status": "RASCUNHO",
            }})

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
        total_ajustado = _aplicar_ajustes(row.get("out_demanda_id"), ajustes, user_id)
        return jsonify({
            "success": True,
            "data": {
                "demanda_id": row.get("out_demanda_id"),
                "demanda_codigo": row.get("out_demanda_codigo"),
                "total_pedidos": row.get("out_total_pedidos"),
                "total_itens": total_ajustado if total_ajustado is not None else row.get("out_total_itens"),
                "ajustes_aplicados": len(ajustes),
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

        linhas = (
            supabase_db.table("itens_demanda")
            .select("id,ordem,sku_externo,descricao,variacao,quantidade,"
                    "miolo_nome,miolo_chave,miolo_origem,produto_id,"
                    "id_produto_miolo,contabiliza_estoque,dados_adicionais")
            .eq("demanda_id", demanda_id)
            .order("ordem")
            .execute()
        ).data or []

        # Mesmo contrato da previa: a tela usa um componente so para as duas.
        itens = []
        for linha in linhas:
            item = _linha_consolidada(linha)
            item["id"] = linha.get("id")
            item["produto_nome"] = (linha.get("dados_adicionais") or {}).get("produto_nome")
            itens.append(item)

        demanda = (
            supabase_db.table("demandas_producao")
            .select("id,demanda_id,descricao,status,data_entrega,escopo_despacho,publicado_em")
            .eq("id", demanda_id).limit(1).execute()
        ).data or []

        return jsonify({"success": True, "data": {
            "demanda": demanda[0] if demanda else None,
            "itens": itens,
            **_resumo_consolidacao(itens),
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


# ---------------------------------------------------------------------------
# Acoes sobre o lote: papeis, notas e IDs de origem
# ---------------------------------------------------------------------------
#
# O lote e o mesmo objeto em dois momentos da vida dele:
#
#   antes de publicar  -> (integration_id, modalidade_ids, horizonte, data)
#   depois de publicar -> demanda_id
#
# As quatro acoes do fluxo de fabrica (gerar demanda, emitir nota, copiar IDs,
# imprimir papeis) valem nos dois momentos, entao as rotas abaixo aceitam
# qualquer uma das duas chaves e resolvem para a mesma lista de pedidos. A
# alternativa seria o frontend mandar a lista de ids na URL: ela diverge do que
# a tela mostra assim que qualquer coisa muda no banco, e estoura o limite de
# URL num lote grande. Aqui quem resolve o conjunto e sempre o servidor.

#: O legado copia os codigos de origem em blocos porque a busca do Bling nao
#: Deve coincidir com o limite usado pelo cliente Bling para numeros da loja.
TAMANHO_BLOCO_IDS = 100


def _pedido_ids_do_lote(origem) -> tuple[list[int], str]:
    """Resolve o conjunto de pedidos a partir de demanda_id ou do escopo.

    `origem` e o request.args (GET) ou o dict do corpo (POST). Retorna
    (pedido_ids, chave) onde chave descreve de onde vieram, para log.
    """
    demanda_id = _parse_int(origem.get("demanda_id"))
    if demanda_id is not None:
        pivot = (
            supabase_db.table("demandas_pedidos")
            .select("pedido_id, created_at")
            .eq("demanda_id", demanda_id)
            .order("created_at")
            .execute()
        )
        ids = [row.get("pedido_id") for row in (pivot.data or []) if row.get("pedido_id")]
        return ids, f"demanda:{demanda_id}"

    conferencia_id = _parse_int(origem.get("conferencia_id"))
    if conferencia_id is not None:
        return _pedido_ids_da_conferencia(conferencia_id), f"conferencia:{conferencia_id}"

    integration_id = _parse_int(origem.get("integration_id"))
    if hasattr(origem, "getlist"):
        horizonte = origem.getlist("horizonte") or ["atrasado", "hoje"]
        modalidade_ids = [_parse_int(v) for v in origem.getlist("modalidade_ids")]
    else:
        horizonte = origem.get("horizonte") or ["atrasado", "hoje"]
        modalidade_ids = [_parse_int(v) for v in (origem.get("modalidade_ids") or [])]
    modalidade_ids = [m for m in modalidade_ids if m is not None]
    if not modalidade_ids:
        unico = _parse_int(origem.get("modalidade_id"))
        modalidade_ids = [unico] if unico is not None else None

    p_data = _parse_data(origem.get("data"))
    result = supabase_db.rpc("despacho_escopo_lote", {
        "p_integration_id": integration_id,
        "p_modalidade_ids": modalidade_ids,
        "p_horizonte": horizonte,
        "p_data": p_data,
    }).execute()
    ids = [row if isinstance(row, int) else row.get("despacho_escopo_lote")
           for row in (result.data or [])]
    ids = [pid for pid in ids if pid is not None]
    return ids, f"escopo:{integration_id}/{modalidade_ids}"


def _pedidos_para_acoes(pedido_ids: list[int]) -> list[dict]:
    """Le de uma vez tudo que as tres acoes precisam saber de cada pedido.

    `order_erp_reference_service.resolve_many` faz uma consulta por pedido; num
    lote de 150 sao 150 idas ao banco antes de a tela desenhar. A referencia de
    ERP ja esta no proprio pedido na esmagadora maioria dos casos, entao aqui a
    leitura e uma so e o servico remoto fica reservado para quem realmente
    ainda nao tem referencia.
    """
    if not pedido_ids:
        return []
    pedidos: list[dict] = []
    # PostgREST monta a lista de ids na URL: em lote grande isso estoura.
    for inicio in range(0, len(pedido_ids), 200):
        fatia = pedido_ids[inicio:inicio + 200]
        resultado = (
            supabase_db.table("pedidos")
            .select(
                "id,numero_pedido,codigo_pedido_externo,marketplace_order_id,"
                "marketplace_module_id,marketplace_integration_id,cliente_nome,"
                "erp_integration_id,erp_store_id,erp_order_id,erp_order_number"
            )
            .in_("id", fatia)
            .execute()
        )
        pedidos.extend(resultado.data or [])

    por_id = {p["id"]: p for p in pedidos}
    # Preserva a ordem que o escopo devolveu — ela ja vem por prazo.
    return [por_id[pid] for pid in pedido_ids if pid in por_id]


def _id_de_origem(pedido: dict) -> str:
    """O identificador do pedido no marketplace.

    `codigo_pedido_externo` e o fallback historico; `marketplace_order_id` e o
    campo canonico. Hoje coincidem, mas o que o operador cola na busca do
    marketplace e o segundo.
    """
    valor = pedido.get("marketplace_order_id") or pedido.get("codigo_pedido_externo")
    return str(valor).strip() if valor else ""


def _rotulos_de_contas(integration_ids: list) -> dict:
    ids = sorted({int(i) for i in integration_ids if i is not None})
    if not ids:
        return {}
    try:
        resultado = (
            supabase_db.table("installed_integrations")
            .select("id, instance_name")
            .in_("id", ids)
            .execute()
        )
        return {
            int(row["id"]): row.get("instance_name") or f"Conta {row['id']}"
            for row in (resultado.data or [])
            if row.get("id") is not None
        }
    except Exception:
        logger.warning("Falha ao ler rotulos das contas de ERP", exc_info=True)
        return {}


@despacho_bp.route("/acoes", methods=["GET"])
def get_acoes():
    """Insumos das acoes de um lote: IDs de origem em blocos e contas de ERP.

    Aceita `demanda_id` OU o seletor do escopo (integration_id, modalidade_ids,
    horizonte, data).
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({"success": False, "error": "Nao autorizado"}), 401

        pedido_ids, chave = _pedido_ids_do_lote(request.args)
        pedidos = _pedidos_para_acoes(pedido_ids)

        codigos = [c for c in (_id_de_origem(p) for p in pedidos) if c]
        blocos = [
            {
                "indice": indice + 1,
                "quantidade": len(codigos[i:i + TAMANHO_BLOCO_IDS]),
                "texto": ";".join(codigos[i:i + TAMANHO_BLOCO_IDS]),
            }
            for indice, i in enumerate(range(0, len(codigos), TAMANHO_BLOCO_IDS))
        ]

        rotulos = _rotulos_de_contas([p.get("erp_integration_id") for p in pedidos])

        grupos: dict = {}
        sem_erp: list[dict] = []
        for pedido in pedidos:
            integracao = pedido.get("erp_integration_id")
            pronto = bool(integracao and pedido.get("erp_order_id") and pedido.get("erp_order_number"))
            if not pronto:
                sem_erp.append({
                    "pedido_id": pedido["id"],
                    "id_origem": _id_de_origem(pedido),
                    "numero_pedido": pedido.get("numero_pedido"),
                    "motivo": "Pedido ainda sem numero no ERP - a nota nao pode ser emitida por aqui.",
                })
                continue
            chave_grupo = int(integracao)
            grupo = grupos.setdefault(chave_grupo, {
                "erp_integration_id": chave_grupo,
                "conta": rotulos.get(chave_grupo) or f"Conta {chave_grupo}",
                "total": 0,
                "pedido_ids": [],
            })
            grupo["total"] += 1
            grupo["pedido_ids"].append(pedido["id"])

        logger.info("Acoes do lote %s: %s pedidos, %s blocos", chave, len(pedidos), len(blocos))

        return jsonify({"success": True, "data": {
            "total": len(pedidos),
            "pedido_ids": [p["id"] for p in pedidos],
            "blocos_ids": blocos,
            "tamanho_bloco": TAMANHO_BLOCO_IDS,
            "contas_erp": sorted(grupos.values(), key=lambda g: -g["total"]),
            "sem_erp": sem_erp,
        }})
    except Exception as exc:
        logger.error("Erro ao montar acoes do lote: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": str(exc)}), 500


@despacho_bp.route("/nfe", methods=["GET"])
def get_nfe_do_lote():
    """Emite as notas do lote, transmitindo o resultado pedido a pedido (SSE).

    Sem `erp_integration_id` cada pedido vai pela conta da propria origem; com
    ele, o lote inteiro vai pela conta escolhida a mao - que e o escape para
    quando a origem esta mal vinculada.

    O contrato de eventos e o mesmo de /demanda_producao/<id>/nfe, de proposito:
    a tela de despacho e a de demanda leem o mesmo componente.
    """
    from flask import Response, stream_with_context
    import json as _json

    try:
        user = get_current_user()
        if not user:
            return jsonify({"success": False, "error": "Nao autorizado"}), 401

        conta_escolhida = _parse_int(request.args.get("erp_integration_id"))
        pedido_ids, chave = _pedido_ids_do_lote(request.args)
        pedidos = _pedidos_para_acoes(pedido_ids)
        if not pedidos:
            return jsonify({"success": False, "error": "Nenhum pedido neste lote."}), 400

        rotulos = _rotulos_de_contas([p.get("erp_integration_id") for p in pedidos])

        grupos: dict = {}
        bloqueados: list[dict] = []
        fora_da_conta: list[dict] = []
        for pedido in pedidos:
            integracao = pedido.get("erp_integration_id")
            ordem_erp = pedido.get("erp_order_id")
            numero_erp = pedido.get("erp_order_number")

            if not (integracao and ordem_erp and numero_erp):
                # So aqui vale pagar a resolucao remota: e o unico caso em que
                # o pedido pode ganhar referencia agora.
                resolucao = order_erp_reference_service.resolve_order(
                    pedido["id"], allow_remote=True
                )
                if resolucao.get("status") != "ready":
                    bloqueados.append({
                        "pedido_id": pedido["id"],
                        "numeroLoja": _id_de_origem(pedido),
                        "error": resolucao.get("message") or resolucao.get("status"),
                    })
                    continue
                integracao = resolucao.get("erp_integration_id")
                ordem_erp = resolucao.get("erp_order_id")
                numero_erp = resolucao.get("erp_order_number")

            if conta_escolhida is not None and int(integracao) != conta_escolhida:
                # Escolha manual = recorte, nao reatribuicao. `erp_order_id` so
                # existe dentro da conta que criou o pedido; mandar esse id para
                # outra conta emitiria nota do pedido errado, ou de nenhum. Quem
                # nao e da conta escolhida fica de fora, e a tela diz quantos.
                fora_da_conta.append({
                    "pedido_id": pedido["id"],
                    "numeroLoja": _id_de_origem(pedido),
                    "erp_integration_id": int(integracao),
                })
                continue

            grupos.setdefault(int(integracao), []).append({
                "pedido_id": pedido["id"],
                "id": ordem_erp,
                "numero": str(numero_erp),
                "numeroLoja": _id_de_origem(pedido),
                "contato": {"nome": pedido.get("cliente_nome")},
            })

        logger.info(
            "NF do lote %s: %s pedidos em %s conta(s), %s bloqueados, %s fora da conta escolhida",
            chave, len(pedidos), len(grupos), len(bloqueados), len(fora_da_conta),
        )

        if not grupos and not bloqueados:
            return jsonify({
                "success": False,
                "error": "Nenhum pedido deste lote pertence a conta de ERP escolhida.",
            }), 400

        def stream():
            from nistiprint_shared.services.bling.bling_client_updated import BlingClient
            from nistiprint_shared.services.installed_integration_service import (
                installed_integration_service,
            )

            for bloqueado in bloqueados:
                yield "data: " + _json.dumps({
                    "status": "error", "success": False,
                    "order": bloqueado, "error": bloqueado["error"],
                }) + "\n\n"

            for integracao_id, ordens in grupos.items():
                rotulo = rotulos.get(integracao_id) or f"Conta {integracao_id}"
                integracao = installed_integration_service.get_installed_by_id(str(integracao_id))
                if not integracao:
                    for ordem in ordens:
                        yield "data: " + _json.dumps({
                            "status": "error", "success": False, "order": ordem,
                            "erp_integration_id": integracao_id, "account_label": rotulo,
                            "error": f"Conta de ERP {integracao_id} nao encontrada.",
                        }) + "\n\n"
                    continue

                dados_conta = integracao.to_dict()
                dados_conta["id"] = integracao.id
                if getattr(integracao, "access_token", None):
                    dados_conta["access_token"] = integracao.access_token
                if getattr(integracao, "refresh_token", None):
                    dados_conta["refresh_token"] = integracao.refresh_token
                cliente = BlingClient(dados_conta)

                for ordem in ordens:
                    try:
                        resultado = cliente.generate_nfe(ordem)
                        evento = {
                            "status": "processing",
                            "order": {
                                "id": ordem["id"],
                                "numero": ordem["numero"],
                                "numeroLoja": ordem["numeroLoja"],
                                "nfe_id": resultado.get("nfe_id"),
                            },
                            "erp_integration_id": integracao_id,
                            "account_label": rotulo,
                            "success": not resultado.get("error"),
                        }
                        if resultado.get("error"):
                            evento["error"] = resultado.get("error_message") or "Erro desconhecido ao gerar NFe"
                            if resultado.get("error_details"):
                                evento["error_details"] = resultado.get("error_details")
                        yield "data: " + _json.dumps(evento) + "\n\n"
                    except Exception as erro:
                        yield "data: " + _json.dumps({
                            "status": "error", "success": False, "order": ordem,
                            "erp_integration_id": integracao_id, "account_label": rotulo,
                            "error": str(erro),
                        }) + "\n\n"

            yield "data: " + _json.dumps({
                "status": "complete",
                "fora_da_conta": len(fora_da_conta),
            }) + "\n\n"

        return Response(stream_with_context(stream()), mimetype="text/event-stream")
    except Exception as exc:
        logger.error("Erro ao emitir notas do lote: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": str(exc)}), 500
