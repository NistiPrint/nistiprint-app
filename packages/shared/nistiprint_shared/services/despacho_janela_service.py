"""Fechamento automatico das janelas de despacho.

Contrato: docs/specs/02-domains/despacho/spec.md

## O que este servico e, e o que nao e

Ele **nao** e o que mantem a torre correta. `despacho_arvore` calcula corte e
coleta na leitura, sempre no futuro — foi assim que o bug dos horarios de
ontem foi resolvido, e essa continua sendo a defesa. Se este job atrasar,
falhar ou nao rodar, os numeros da tela seguem certos.

O que este job faz e o que calculo nenhum faz: agir no instante em que a
janela vira.

    CORTE   o lote fecha. Cria a demanda RASCUNHO com os pedidos daquele
            momento, para o operador receber o lote pronto para conferir.
    COLETA  a transportadora passou. Recalcula os compromissos, para os
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
  execucao, dentro da janela de catch-up.

Esse desenho e o que torna aceitavel a escolha de agendar uma entrada de cron
por horario configurado: se o schedule sair de sincronia com o cadastro, o
catch-up cobre a diferenca.
"""
from __future__ import annotations

import logging
from typing import Any

from celery import shared_task

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.utils.task_logging import log_task_execution

logger = logging.getLogger(__name__)

#: Ate onde olhar para tras atras de janela nao processada.
#:
#: 26h e mais que um ciclo diario completo: cobre o worker que passou a noite
#: fora sem reprocessar a semana inteira. Uma janela mais larga tornaria um
#: incidente longo em uma enxurrada de rascunhos retroativos.
CATCH_UP = "26 hours"


def _rows(response: Any) -> list[dict]:
    data = getattr(response, "data", None)
    if isinstance(data, list):
        return data
    return [data] if isinstance(data, dict) else []


@shared_task(name="nistiprint_shared.services.despacho_janela_service.fechar_janelas")
@log_task_execution(task_type="DESPACHO", task_name="fechar_janelas_despacho")
def fechar_janelas_despacho(catch_up: str = CATCH_UP) -> dict:
    """Fecha os cortes vencidos e recalcula os compromissos apos as coletas."""
    resultado = {"cortes_fechados": 0, "rascunhos": [], "compromissos_recalculados": 0}

    try:
        vencidas = _rows(
            supabase_db.rpc("janelas_despacho_vencidas", {"p_desde": catch_up}).execute()
        )
    except Exception:
        logger.error("[despacho-janela] falha ao consultar janelas vencidas", exc_info=True)
        return resultado

    if not vencidas:
        logger.info("[despacho-janela] nenhuma janela vencida pendente")
        return resultado

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
            except Exception:
                # Conflito aqui e corrida entre dois workers na mesma janela —
                # exatamente o que o unique existe para resolver.
                logger.debug("[despacho-janela] coleta ja registrada: %s", janela, exc_info=True)
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
            logger.error(
                "[despacho-janela] falha ao fechar corte integration=%s modalidade=%s janela=%s",
                janela.get("integration_id"), janela.get("modalidade_id"),
                janela.get("janela_em"), exc_info=True,
            )
            continue

        if not res:
            logger.info(
                "[despacho-janela] corte sem pedido pendente: integration=%s modalidade=%s",
                janela.get("integration_id"), janela.get("modalidade_id"),
            )
            continue

        criado = res[0]
        resultado["cortes_fechados"] += 1
        resultado["rascunhos"].append({
            "demanda_id": criado.get("out_demanda_id"),
            "codigo": criado.get("out_demanda_codigo"),
            "qtd_pedidos": criado.get("out_qtd_pedidos"),
        })
        logger.info(
            "[despacho-janela] rascunho criado %s com %s pedidos",
            criado.get("out_demanda_codigo"), criado.get("out_qtd_pedidos"),
        )

    # Recalcula uma vez por execucao, e nao por janela: a funcao varre todos os
    # pedidos FIXO pendentes de uma vez, entao chamar N vezes so repetiria o
    # mesmo trabalho.
    if houve_coleta or resultado["cortes_fechados"]:
        try:
            res = supabase_db.rpc("despacho_recalcular_compromissos", {}).execute()
            resultado["compromissos_recalculados"] = getattr(res, "data", 0) or 0
        except Exception:
            logger.warning("[despacho-janela] falha ao recalcular compromissos", exc_info=True)

    return resultado
