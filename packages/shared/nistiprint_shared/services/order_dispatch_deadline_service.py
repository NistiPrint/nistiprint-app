"""Reconciliacao do prazo de postagem (`pedidos.data_limite_envio`).

## Por que existe

O prazo nao vem no primeiro evento do pedido. A Shopee devolve
`ship_by_date = 0` enquanto o pedido esta em `LOGISTICS_NOT_START`; o Mercado
Livre nem sempre tem SLA quando o pedido aparece. Medido em 09/09/2026, por
faixa de idade do pedido Shopee:

    0-1h  17/19 sem prazo   |  2-3h  10/19   |  4-5h  1/19   |  5h+  0

Em todos os casos o campo estava vazio exatamente quando o provider devolveu
zero — nunca perdemos um valor que ele tenha informado. O defeito nao era de
gravacao: era que **so descobriamos o prazo quando chegava um evento novo
daquele pedido**. Pedido parado no mesmo status nao gera evento, e ficava sem
prazo indefinidamente.

A varredura que existia (`ressincronizar_pendentes`) percorre a base inteira
por cursor a 100 pedidos/hora, contra ~300 pedidos novos/hora. Ela nao poderia
alcancar o problema nem em teoria — e nao e culpa do intervalo: e o instrumento
errado. Varredura por cursor responde "ja passei por todo mundo?"; a pergunta
aqui e "quem esta sem prazo agora?".

## A estrategia

Perguntar pelo que falta, nao varrer o que existe. O conjunto de trabalho e uma
consulta direta: pedido sem `data_limite_envio`, em situacao nao-final, de canal
que tem driver de prazo, dentro do horizonte.

Nada e escrito direto em `pedidos`: o pedido volta pela pipeline de ingest
normal (`ressincronizar_pendentes`), a mesma que o webhook usa. Um caminho de
escrita so — se a canonizacao logistica mudar, muda para os dois.

## Por que o estado de tentativa mora em `pedidos`, e nao numa fila

Uma fila e uma copia da verdade e pode discordar dela. Foi assim que a
reconciliacao de ERP travou em 09/09/2026: 53 linhas `pending` de pedidos que
ja tinham referencia ocuparam o lote de 50 para sempre, e a task passou o dia
reportando `applied: 50` sem aplicar nada.

Aqui a fila e o indice parcial `ix_pedidos_prazo_postagem_pendente`, sobre
`data_limite_envio IS NULL`. O conjunto e derivado da verdade: no instante em
que o prazo e gravado, o pedido sai do indice. Nao existe linha para virar
zumbi nem estado para divergir. As colunas `prazo_postagem_*` guardam so o que
a verdade nao sabe dizer — quantas vezes ja perguntamos e quando vale perguntar
de novo.

## O que a task mede

`preenchidos` — pedidos que ganharam prazo nesta rodada — e nao `reingeridos`.
A licao de 09/09 e que uma metrica que conta acoes em vez de resultados torna
uma task parada indistinguivel de uma task saudavel. Se `reingeridos` for alto
e `preenchidos` for zero por varias rodadas, o numero denuncia sozinho.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from celery import shared_task

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.utils.date_utils import get_now_iso
from nistiprint_shared.utils.task_logging import log_task_execution

logger = logging.getLogger(__name__)

#: Canais com driver de prazo em `logistics_canonicalization.OBSERVERS`.
#:
#: Fora desta lista nao existe campo de onde ler o prazo, entao reconsultar so
#: gastaria quota para reencontrar o mesmo vazio. E o caso de `amazonfba_classic`,
#: 100% sem `data_limite_envio` desde sempre — ausencia por falta de driver, nao
#: por falha de sincronizacao. Quando um canal ganhar observer, entra aqui.
CANAIS_COM_DRIVER = ("shopee", "mercadolivre")

#: Situacoes em que ainda faz sentido perguntar. Espelha
#: `ressincronizacao_service.SITUACOES_NAO_FINALIZADAS`: pedido entregue,
#: cancelado ou devolvido nao vai ser postado, e prazo de postagem para ele nao
#: e dado faltando — e dado que nao existe.
SITUACOES_ELEGIVEIS = (1, 2, 3, 4, 5)

#: Espera antes da proxima consulta, por numero de tentativas ja feitas.
#:
#: Calibrado pela curva observada em 09/09: quase todo pedido ganha prazo dentro
#: de 4h, e a maior parte bem antes. Perguntar de 5 em 5 minutos nas primeiras
#: rodadas cobre o caso comum; espacar depois evita gastar quota com o pedido
#: que esta parado justamente porque nao andou.
BACKOFF_MINUTOS = (5, 5, 10, 15, 30, 60, 120)

#: Idade maxima do pedido para continuar perguntando.
#:
#: Prazo de postagem descoberto tarde demais nao serve para nada: a operacao
#: precisa dele antes de despachar. Passado o horizonte, o pedido para de
#: consumir quota e passa a ser reportado como problema — que e o que ele e.
HORIZONTE_HORAS = int(os.getenv("DISPATCH_DEADLINE_HORIZON_HOURS", "48"))

#: Pedidos por rodada. Cada reingest custa chamadas de detalhe, envio e SLA no
#: marketplace — medido em ~5s por pedido. Com a trava abaixo, um lote que passe
#: do intervalo do beat atrasa a proxima rodada em vez de rodar em paralelo com
#: ela, entao o teto existe para o lote caber no intervalo, nao para proteger a
#: concorrencia.
LOTE_PADRAO = int(os.getenv("DISPATCH_DEADLINE_BATCH", "40"))

#: Trava contra sobreposicao. O beat dispara por relogio proprio e nao sabe se a
#: rodada anterior terminou; sem isto, um lote lento gera rodadas empilhadas
#: relendo os mesmos pedidos e consumindo quota em dobro. Mesmo motivo e mesmo
#: idioma da trava do backfill de lifecycle.
LOCK_KEY = "nistiprint:prazo-postagem:reconciliacao"
LOCK_TTL_SECONDS = int(os.getenv("DISPATCH_DEADLINE_LOCK_TTL", "900"))

CAMPOS = "id,marketplace_order_id,marketplace_module_id,situacao_pedido_id,prazo_postagem_tentativas,created_at"


def _adquirir_trava() -> str | None:
    from nistiprint_shared.services.redis_queue_tasks import get_redis_client

    token = str(uuid.uuid4())
    try:
        adquirida = get_redis_client().set(LOCK_KEY, token, nx=True, ex=LOCK_TTL_SECONDS)
    except Exception as exc:
        # Redis fora do ar nao pode impedir a reconciliacao de rodar; ela so
        # perde a protecao contra sobreposicao.
        logger.warning("Reconciliacao de prazo sem trava (Redis indisponivel): %s", exc)
        return token
    return token if adquirida else None


def _liberar_trava(token: str | None) -> None:
    if not token:
        return
    from nistiprint_shared.services.redis_queue_tasks import get_redis_client

    try:
        get_redis_client().eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] "
            "then return redis.call('del', KEYS[1]) else return 0 end",
            1,
            LOCK_KEY,
            token,
        )
    except Exception as exc:
        logger.warning("Erro ao liberar trava da reconciliacao de prazo: %s", exc)


def _horizonte_iso() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=HORIZONTE_HORAS)).isoformat()


def _proxima_tentativa_iso(tentativas: int) -> str:
    indice = min(max(tentativas - 1, 0), len(BACKOFF_MINUTOS) - 1)
    minutos = BACKOFF_MINUTOS[indice]
    return (datetime.now(timezone.utc) + timedelta(minutes=minutos)).isoformat()


def _candidatos(limite: int) -> list[dict]:
    """Pedidos sem prazo que ainda vale perguntar.

    Mais antigo primeiro: quem esta ha mais tempo sem prazo e quem esta mais
    perto de ser despachado sem ele.
    """
    agora = get_now_iso()
    return (
        supabase_db.table("pedidos")
        .select(CAMPOS)
        .is_("data_limite_envio", "null")
        .in_("situacao_pedido_id", list(SITUACOES_ELEGIVEIS))
        .in_("marketplace_module_id", list(CANAIS_COM_DRIVER))
        .gte("created_at", _horizonte_iso())
        .or_(f"prazo_postagem_proxima_tentativa.is.null,prazo_postagem_proxima_tentativa.lte.{agora}")
        .order("created_at")
        .limit(limite)
        .execute()
        .data
        or []
    )


def _abandonados() -> list[int]:
    """Pedidos que passaram do horizonte e seguem sem prazo.

    Nao sao mais reconsultados, entao precisam sair no log em voz alta: sao
    pedidos que a producao vai despachar as cegas.
    """
    rows = (
        supabase_db.table("pedidos")
        .select("id")
        .is_("data_limite_envio", "null")
        .in_("situacao_pedido_id", list(SITUACOES_ELEGIVEIS))
        .in_("marketplace_module_id", list(CANAIS_COM_DRIVER))
        .lt("created_at", _horizonte_iso())
        .limit(200)
        .execute()
        .data
        or []
    )
    return [row["id"] for row in rows]


def reconcile_dispatch_deadlines(limite: int | None = None) -> dict:
    limite = int(limite or LOTE_PADRAO)
    candidatos = _candidatos(limite)
    abandonados = _abandonados()

    if not candidatos:
        if abandonados:
            _alertar_abandonados(abandonados)
        return {
            "status": "success",
            "candidatos": 0,
            "reingeridos": 0,
            "preenchidos": 0,
            "sem_resposta": 0,
            "abandonados": len(abandonados),
        }

    ids = [int(row["id"]) for row in candidatos]
    tentativas_antes = {int(row["id"]): int(row.get("prazo_postagem_tentativas") or 0) for row in candidatos}

    from nistiprint_shared.services.ressincronizacao_service import ressincronizar_pendentes

    reingest = ressincronizar_pendentes(
        pedido_ids=ids,
        limite=len(ids),
        usar_cursor=False,
        pausa_segundos=0.0,
    )

    # A pergunta que importa nao e "reingeri?", e "o prazo chegou?". Reler o
    # estado depois do reingest e o unico jeito honesto de responder.
    depois = (
        supabase_db.table("pedidos")
        .select("id,data_limite_envio")
        .in_("id", ids)
        .execute()
        .data
        or []
    )
    preenchidos = [int(r["id"]) for r in depois if r.get("data_limite_envio")]
    sem_resposta = [pedido_id for pedido_id in ids if pedido_id not in preenchidos]

    if preenchidos:
        # Zera o estado de tentativa junto com o sucesso: se o prazo algum dia
        # for limpo, o pedido volta a ser perguntado do inicio e nao herda um
        # backoff longo de uma disputa antiga.
        (
            supabase_db.table("pedidos")
            .update({
                "prazo_postagem_tentativas": 0,
                "prazo_postagem_proxima_tentativa": None,
                "prazo_postagem_motivo": None,
            })
            .in_("id", preenchidos)
            .execute()
        )

    for pedido_id in sem_resposta:
        tentativas = tentativas_antes.get(pedido_id, 0) + 1
        (
            supabase_db.table("pedidos")
            .update({
                "prazo_postagem_tentativas": tentativas,
                "prazo_postagem_proxima_tentativa": _proxima_tentativa_iso(tentativas),
                "prazo_postagem_motivo": "provider ainda nao informou prazo de postagem",
            })
            .eq("id", pedido_id)
            .execute()
        )

    if abandonados:
        _alertar_abandonados(abandonados)

    logger.info(
        "[prazo-postagem] candidatos=%s reingeridos=%s preenchidos=%s sem_resposta=%s "
        "erros=%s abandonados=%s",
        len(ids),
        reingest.get("processados"),
        len(preenchidos),
        len(sem_resposta),
        reingest.get("total_erros"),
        len(abandonados),
    )

    return {
        "status": "success",
        "candidatos": len(ids),
        "reingeridos": reingest.get("processados", 0),
        "preenchidos": len(preenchidos),
        "sem_resposta": len(sem_resposta),
        "erros": reingest.get("total_erros", 0),
        "abandonados": len(abandonados),
        "correlation_id": reingest.get("correlation_id"),
    }


def _alertar_abandonados(ids: list[int]) -> None:
    logger.error(
        "[prazo-postagem] %s pedidos passaram de %sh sem prazo de postagem e nao serao "
        "mais reconsultados (pedido_id: %s) — despacho sem prazo ate intervencao manual",
        len(ids),
        HORIZONTE_HORAS,
        ", ".join(str(i) for i in ids[:50]),
    )


@shared_task(
    name="nistiprint_shared.services.order_dispatch_deadline_service.reconcile_dispatch_deadlines"
)
@log_task_execution(task_type="PEDIDO", task_name="reconcile_dispatch_deadlines")
def reconcile_dispatch_deadlines_task(limite: int | None = None):
    token = _adquirir_trava()
    if not token:
        # Rodada anterior ainda viva. Pular e o comportamento certo: empilhar
        # rodadas releria os mesmos pedidos e gastaria quota em dobro.
        logger.info("[prazo-postagem] rodada anterior ainda em execucao; pulando")
        return {"status": "skipped", "motivo": "rodada anterior em execucao"}
    try:
        return reconcile_dispatch_deadlines(limite=limite)
    finally:
        _liberar_trava(token)
