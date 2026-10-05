"""Fechamento automatico das janelas de despacho.

Contrato: docs/specs/02-domains/despacho/spec.md

## O que este servico e, e o que nao e

Ele **nao** e o que mantem a torre correta. `despacho_arvore` calcula corte e
coleta na leitura, sempre no futuro — foi assim que o bug dos horarios de
ontem foi resolvido, e essa continua sendo a defesa. Se este job atrasar,
falhar ou nao rodar, os numeros da tela seguem certos.

O que este job faz e o que calculo nenhum faz: agir no instante em que a
janela vira.

    CORTE   registra o fechamento do lote. A demanda nasce da acao do operador.
    COLETA  a janela prevista venceu. Recalcula os compromissos, para os
            consumidores que leem `pedidos.compromisso_logistico_em` direto
            (painel de producao, ordenacao de demandas) nao ficarem com o
            valor do ciclo anterior.

## Idempotencia e catch-up

Toda janela processada e registrada em `janelas_despacho_execucoes`, com
unique em (integracao, modalidade, tipo, janela). O job pergunta ao banco
"que janela venceu e ainda nao foi processada?" em vez de assumir que rodou na
hora certa. Consequencias praticas:

- rodar duas vezes na mesma janela nao cria dois lotes;
- beat reiniciado, worker fora do ar ou horario editado na aba Logistica nao
  fazem o lote ser pulado em silencio — a janela e recuperada na proxima
  execucao, desde a ultima consulta concluida no banco.

A verificacao ocorre a cada minuto e le a agenda efetiva no SQL. Novos horarios
nao exigem reiniciar o beat. A janela prevista nao confirma uma saida fisica;
essa confirmacao vem do estado consultado no marketplace.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from celery import shared_task

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.utils.task_logging import log_task_execution

logger = logging.getLogger(__name__)

#: Ate onde olhar para tras atras de janela nao processada.
#:
#: O SQL amplia este minimo ate a ultima consulta concluida, registrada no banco,
#: recuperando tambem interrupcoes maiores sem criar demandas retroativas.
CATCH_UP = "26 hours"


def _rows(response: Any) -> list[dict]:
    data = getattr(response, "data", None)
    if isinstance(data, list):
        return data
    return [data] if isinstance(data, dict) else []


@shared_task(name="nistiprint_shared.services.despacho_janela_service.fechar_janelas")
@log_task_execution(task_type="DESPACHO", task_name="fechar_janelas_despacho")
def fechar_janelas_despacho(catch_up: str = CATCH_UP) -> dict:
    """Registra os cortes vencidos e recalcula os compromissos apos as coletas.

    Nao cria demanda. O corte e regra de PERTENCIMENTO — ele responde quais
    pedidos entram nesta coleta — e essa resposta continua sendo calculada na
    leitura por `coleta_do_pedido`. Materializar um lote a cada janela so
    enchia a lista de demandas com rascunho que ninguem abria.
    """
    resultado = {"cortes_registrados": 0, "cortes": [], "compromissos_recalculados": 0}
    consulta_em = datetime.now(timezone.utc).isoformat()
    houve_erro = False

    try:
        vencidas = _rows(
            supabase_db.rpc("janelas_despacho_vencidas", {"p_desde": catch_up}).execute()
        )
    except Exception:
        logger.error("[despacho-janela] falha ao consultar janelas vencidas", exc_info=True)
        return resultado

    if not vencidas:
        logger.info("[despacho-janela] nenhuma janela vencida pendente")

    houve_coleta = False

    for janela in vencidas:
        tipo = janela.get("tipo")

        if tipo == "COLETA":
            # Coleta nao gera lote: ela encerra o ciclo. O efeito e o recalculo
            # dos compromissos, feito uma vez ao final.
            houve_coleta = True
            try:
                supabase_db.table("janelas_despacho_execucoes").insert({
                    "integration_id": janela["integration_id"],
                    "modalidade_id": janela["modalidade_id"],
                    "tipo": "COLETA",
                    "janela_em": janela["janela_em"],
                    "observacao": "Coleta registrada; compromissos recalculados",
                }).execute()
            except Exception as exc:
                # Conflito aqui e corrida entre dois workers na mesma janela —
                # exatamente o que o unique existe para resolver.
                logger.debug("[despacho-janela] coleta ja registrada: %s", janela, exc_info=True)
                if str(getattr(exc, 'code', '')) != '23505':
                    houve_erro = True
            continue

        # Isolado por janela: um corte problematico nao pode impedir os outros
        # de fechar. Cada card tem seu proprio caminhao.
        try:
            res = _rows(supabase_db.rpc("despacho_fechar_corte", {
                "p_integration_id": janela["integration_id"],
                "p_modalidade_id": janela["modalidade_id"],
                "p_janela_em": janela["janela_em"],
                "p_user_id": "Sistema",
            }).execute())
        except Exception:
            houve_erro = True
            logger.error(
                "[despacho-janela] falha ao fechar corte integration=%s modalidade=%s janela=%s",
                janela.get("integration_id"), janela.get("modalidade_id"),
                janela.get("janela_em"), exc_info=True,
            )
            continue

        if not res:
            logger.info(
                "[despacho-janela] corte ja registrado: integration=%s modalidade=%s janela=%s",
                janela.get("integration_id"), janela.get("modalidade_id"),
                janela.get("janela_em"),
            )
            continue

        # O corte NAO cria mais demanda. Ele registra que a janela venceu e
        # quantos pedidos havia no lote naquele instante — o numero que permite
        # responder depois "quantos pedidos havia no corte das 13h" sem ter
        # materializado um lote que ninguem pediu.
        #
        # Entre 04/08 e 26/08 o fechamento automatico criou 81 rascunhos e
        # nenhum foi publicado: ele produzia e ninguem consumia, e cada lote
        # aberto prendia pedidos que o proprio job depois ignorava. O rascunho
        # passou a nascer do clique do operador na Torre.
        registrado = res[0]
        resultado["cortes_registrados"] += 1
        resultado["cortes"].append({
            "integration_id": janela.get("integration_id"),
            "modalidade_id": janela.get("modalidade_id"),
            "janela_em": janela.get("janela_em"),
            "qtd_pedidos": registrado.get("out_qtd_pedidos"),
        })
        logger.info(
            "[despacho-janela] corte registrado integration=%s modalidade=%s com %s pedidos no lote",
            janela.get("integration_id"), janela.get("modalidade_id"),
            registrado.get("out_qtd_pedidos"),
        )

    # Recalcula uma vez por execucao, e nao por janela: a funcao varre todos os
    # pedidos FIXO pendentes de uma vez, entao chamar N vezes so repetiria o
    # mesmo trabalho.
    # Repetir o recalculo tambem recupera a queda entre registrar uma janela e
    # recalcular seus pedidos; o registro idempotente ja pode estar concluido.
    if houve_coleta or resultado["cortes_registrados"] or not vencidas:
        try:
            res = supabase_db.rpc("despacho_recalcular_compromissos", {}).execute()
            resultado["compromissos_recalculados"] = getattr(res, "data", 0) or 0
        except Exception:
            houve_erro = True
            logger.warning("[despacho-janela] falha ao recalcular compromissos", exc_info=True)

    if not houve_erro:
        try:
            supabase_db.table('logistica_sync_cursores').update({'ultima_consulta_em': consulta_em}) \
                .eq('nome', 'janelas-despacho').execute()
        except Exception:
            logger.warning('[despacho-janela] checkpoint nao registrado; janelas serao recuperadas', exc_info=True)

    return resultado
