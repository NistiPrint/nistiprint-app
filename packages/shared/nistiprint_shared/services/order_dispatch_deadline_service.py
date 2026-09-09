"""Reconciliacao do prazo de postagem (`pedidos.data_limite_envio`).

## Por que existe

O prazo nao existe na origem no momento em que o pedido chega. A Shopee so
publica `ship_by_date` depois que a solicitacao de envio e criada; antes disso
o campo vem literalmente `0`, ainda que `days_to_ship` ja venha preenchido.
Medido em 09/09/2026 sobre 7 dias de pedidos Shopee, o prazo acompanha o
estagio logistico do pacote e nada mais:

    LOGISTICS_REQUEST_CREATED / PICKUP_DONE / DELIVERY_DONE   1346/1346 com prazo
    LOGISTICS_READY                                             34/68   com prazo
    LOGISTICS_NOT_START                                          0/39   com prazo

Isso foi verificado ate o fim, e nao por inferencia: o pedido e reconsultado na
origem a cada rodada (o `enriched_at` do espelho anda), `ship_by_date` esta na
lista de `response_optional_fields` do driver, e nos mesmos payloads em que ele
volta zerado o `days_to_ship` volta com valor. Nunca perdemos um prazo que a
Shopee tenha informado: em 14 dias, zero pedidos com valor util no espelho e
`data_limite_envio` nulo em `pedidos`.

**E nao da para derivar.** Entre os pedidos com `days_to_ship = 2`, a distancia
entre pagamento e `ship_by_date` vai de 0 a 5 dias corridos — o prazo e ancorado
no momento da solicitacao de envio, nao no pagamento. Calcular daria numero para
todo mundo e numero errado para a maioria, que e pior que ausencia porque parece
dado.

O que era defeito nosso, e foi corrigido, e outra coisa: **so descobriamos o
prazo quando chegava um evento novo daquele pedido**. Pedido parado no mesmo
status nao gera evento, e ficava sem prazo indefinidamente.

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

## Quando parar de perguntar

Nao por idade — por situacao. O prazo deixa de ser perguntavel quando o pedido
sai do atendimento: foi despachado (`Enviado`, `Entregue`) ou morreu
(`Cancelado`, `Devolvido`). Enquanto ele ainda vai sair daqui, a pergunta
continua valendo, e desistir por relogio era jogar fora justamente o dado de que
a operacao precisa.

Os dados sustentam o corte. Nos ultimos 10 dias, dos 334 pedidos que chegaram a
`Pronto para Envio`, ZERO estava sem prazo. O prazo sempre chega antes do pedido
evoluir — entao pedido que evoluiu ou ja tem o dado, ou nunca teria.

`Em Aberto` fica de fora por outro motivo: sem pagamento nao existe prazo de
postagem para o provider informar (32 de 32 medidos, sem excecao), e esses
pedidos ocupavam metade do lote perguntando o que ninguem tem como responder.
Eles voltam a fila sozinhos no instante em que o pagamento os move para
`Em Andamento`.

Nao desistir so e sustentavel se nao desistir for barato: o backoff cresce ate
uma consulta por dia, entao o pedido esquecido pelo comprador vira ruido de
fundo em vez de fila perdida.

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

#: Situacoes em que o prazo ainda e util e ainda pode chegar: o pedido esta pago
#: e ainda nao saiu daqui. `Enviado` e `Entregue` ja foram despachados — prazo de
#: postagem para eles nao muda mais nada. `Em Aberto` ainda nao tem pagamento, e
#: sem pagamento o provider nao tem prazo para informar.
SITUACOES_ELEGIVEIS = (2, 3, 4)  # Em Andamento, Produzido, Pronto para Envio

#: Situacoes que, quando o pedido chega nelas sem prazo, encerram o assunto.
#: Existem para o log dizer *por que* o pedido saiu da fila, e nao so que saiu.
SITUACOES_QUE_ENCERRAM = (5, 6, 7, 8)  # Enviado, Entregue, Cancelado, Devolvido

#: Espera antes da proxima consulta, por numero de tentativas ja feitas.
#:
#: Calibrado pela curva observada em 09/09: quase todo pedido ganha prazo dentro
#: de 4h, e a maior parte bem antes. Perguntar de 5 em 5 minutos nas primeiras
#: rodadas cobre o caso comum; espacar depois evita gastar quota com o pedido
#: que esta parado justamente porque nao andou.
#:
#: A cauda longa (4h, 8h, 24h) substitui o horizonte de idade que existia antes.
#: Desistir de um pedido que ainda vai ser despachado e pior que perguntar
#: devagar: uma consulta por dia e um custo que a operacao nem sente, e o pedido
#: continua elegivel ate a situacao dele resolver a questao.
BACKOFF_MINUTOS = (5, 5, 10, 15, 30, 60, 120, 240, 480, 1440)

#: A partir de quando um pedido pago e sem prazo vira alerta.
#:
#: E limite de PACIENCIA, nao de desistencia: o pedido continua na fila. Serve
#: para a operacao saber que vai despachar as cegas enquanto ainda da tempo de
#: buscar o prazo na mao. Calibrado pela curva medida: praticamente todo pedido
#: ganha prazo em ate 4h, entao passar de 6h e sinal, nao ruido.
ALERTA_HORAS = int(os.getenv("DISPATCH_DEADLINE_ALERT_HOURS", "6"))

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


def _limite_de_paciencia_iso() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=ALERTA_HORAS)).isoformat()


def _proxima_tentativa_iso(tentativas: int) -> str:
    indice = min(max(tentativas - 1, 0), len(BACKOFF_MINUTOS) - 1)
    minutos = BACKOFF_MINUTOS[indice]
    return (datetime.now(timezone.utc) + timedelta(minutes=minutos)).isoformat()


def _candidatos(limite: int) -> list[dict]:
    """Pedidos sem prazo que ainda vale perguntar.

    Sem recorte de idade: quem decide se ainda vale perguntar e a situacao do
    pedido, nao o relogio.

    Nunca-perguntados primeiro (`prazo_postagem_proxima_tentativa` nulo), depois
    os mais antigos. Pedido recem-chegado e onde o prazo tem mais chance de estar
    disponivel e mais valor para a operacao; pedido velho ja esta espacado pelo
    backoff e nao precisa disputar a frente do lote.
    """
    def _base():
        return (
            supabase_db.table("pedidos")
            .select(CAMPOS)
            .is_("data_limite_envio", "null")
            .in_("situacao_pedido_id", list(SITUACOES_ELEGIVEIS))
            .in_("marketplace_module_id", list(CANAIS_COM_DRIVER))
        )

    # Duas consultas em vez de um `ORDER BY ... NULLS FIRST`: o nome do argumento
    # de nulos mudou entre versoes do postgrest-py e `supabase` esta sem pin no
    # requirements. Um TypeError aqui derrubaria a rodada inteira para economizar
    # uma consulta de 20ms.
    novos = (
        _base()
        .is_("prazo_postagem_proxima_tentativa", "null")
        .order("created_at")
        .limit(limite)
        .execute()
        .data
        or []
    )
    if len(novos) >= limite:
        return novos

    reincidentes = (
        _base()
        .lte("prazo_postagem_proxima_tentativa", get_now_iso())
        .order("prazo_postagem_proxima_tentativa")
        .limit(limite - len(novos))
        .execute()
        .data
        or []
    )
    return novos + reincidentes


def _atrasados() -> list[int]:
    """Pedidos pagos, ainda nao despachados, sem prazo ha tempo demais.

    Continuam na fila — isto e alerta, nao desistencia. Sao pedidos que a
    producao vai despachar as cegas se ninguem buscar o prazo na mao, e o unico
    jeito de alguem saber disso a tempo e o log dizer em voz alta.
    """
    rows = (
        supabase_db.table("pedidos")
        .select("id")
        .is_("data_limite_envio", "null")
        .in_("situacao_pedido_id", list(SITUACOES_ELEGIVEIS))
        .in_("marketplace_module_id", list(CANAIS_COM_DRIVER))
        .lt("created_at", _limite_de_paciencia_iso())
        .limit(200)
        .execute()
        .data
        or []
    )
    return [row["id"] for row in rows]


def _motivos(pedidos: list[dict], ids: list[int]) -> dict[int, str]:
    """Por que cada pedido continua sem prazo, na lingua do provider.

    Medido em 09/09/2026 sobre 7 dias de pedidos Shopee, o prazo acompanha
    exatamente o estagio logistico do pacote:

        LOGISTICS_REQUEST_CREATED / PICKUP_DONE / DELIVERY_DONE  1346/1346 com prazo
        LOGISTICS_READY                                            34/68   com prazo
        LOGISTICS_NOT_START                                         0/39   com prazo

    Ou seja: a Shopee so publica `ship_by_date` quando a solicitacao de envio
    existe. Antes disso o campo vem zerado — nao e falha de sincronizacao nossa,
    e ausencia na origem, e nenhuma quantidade de reconsulta muda isso.

    Registrar o estagio aqui e o que impede a proxima investigacao de comecar do
    zero: "sem prazo" vira "esperando a Shopee criar a solicitacao de envio",
    legivel na propria linha do pedido.
    """
    por_id = {int(row["id"]): row for row in pedidos if row.get("id") is not None}
    alvo = [pedido_id for pedido_id in ids if pedido_id in por_id]
    motivos: dict[int, str] = {}

    externos_shopee = {
        str(por_id[pedido_id].get("marketplace_order_id")): pedido_id
        for pedido_id in alvo
        if por_id[pedido_id].get("marketplace_module_id") == "shopee"
        and por_id[pedido_id].get("marketplace_order_id")
    }
    if externos_shopee:
        espelhos = (
            supabase_db.table("pedidos_shopee")
            .select("order_sn,raw_payload")
            .in_("order_sn", list(externos_shopee))
            .execute()
            .data
            or []
        )
        for espelho in espelhos:
            pedido_id = externos_shopee.get(str(espelho.get("order_sn")))
            if not pedido_id:
                continue
            pacotes = (espelho.get("raw_payload") or {}).get("package_list") or []
            estagios = sorted({
                str(pacote.get("logistics_status") or "").strip()
                for pacote in pacotes
                if pacote.get("logistics_status")
            })
            if not estagios:
                motivos[pedido_id] = "Shopee: pedido ainda sem pacote; prazo so existe apos a solicitacao de envio"
            elif estagios == ["LOGISTICS_NOT_START"]:
                motivos[pedido_id] = "Shopee: LOGISTICS_NOT_START; prazo so existe apos a solicitacao de envio"
            else:
                motivos[pedido_id] = f"Shopee: {'+'.join(estagios)} sem ship_by_date"

    for pedido_id in alvo:
        motivos.setdefault(pedido_id, "provider ainda nao informou prazo de postagem")
    return motivos


def reconcile_dispatch_deadlines(limite: int | None = None) -> dict:
    limite = int(limite or LOTE_PADRAO)
    candidatos = _candidatos(limite)
    atrasados = _atrasados()

    if not candidatos:
        if atrasados:
            _alertar_atrasados(atrasados)
        return {
            "status": "success",
            "candidatos": 0,
            "reingeridos": 0,
            "preenchidos": 0,
            "sem_resposta": 0,
            "atrasados": len(atrasados),
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
        .select("id,data_limite_envio,situacao_pedido_id")
        .in_("id", ids)
        .execute()
        .data
        or []
    )
    preenchidos: list[int] = []
    encerrados: list[int] = []
    sem_resposta: list[int] = []
    for row in depois:
        pedido_id = int(row["id"])
        if row.get("data_limite_envio"):
            preenchidos.append(pedido_id)
        elif row.get("situacao_pedido_id") in SITUACOES_QUE_ENCERRAM:
            # O reingest trouxe situacao nova e o pedido saiu do atendimento:
            # foi despachado ou morreu. Nao e falta de resposta, e assunto
            # encerrado — contar junto com `sem_resposta` faria a fila parecer
            # travada quando ela so andou.
            encerrados.append(pedido_id)
        else:
            sem_resposta.append(pedido_id)

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

    if encerrados:
        (
            supabase_db.table("pedidos")
            .update({
                "prazo_postagem_proxima_tentativa": None,
                "prazo_postagem_motivo": "pedido saiu do atendimento sem prazo informado",
            })
            .in_("id", encerrados)
            .execute()
        )

    motivos = _motivos(candidatos, sem_resposta) if sem_resposta else {}
    for pedido_id in sem_resposta:
        tentativas = tentativas_antes.get(pedido_id, 0) + 1
        (
            supabase_db.table("pedidos")
            .update({
                "prazo_postagem_tentativas": tentativas,
                "prazo_postagem_proxima_tentativa": _proxima_tentativa_iso(tentativas),
                "prazo_postagem_motivo": motivos.get(
                    pedido_id, "provider ainda nao informou prazo de postagem"
                ),
            })
            .eq("id", pedido_id)
            .execute()
        )

    if atrasados:
        _alertar_atrasados(atrasados)

    logger.info(
        "[prazo-postagem] candidatos=%s reingeridos=%s preenchidos=%s encerrados=%s "
        "sem_resposta=%s erros=%s atrasados=%s",
        len(ids),
        reingest.get("processados"),
        len(preenchidos),
        len(encerrados),
        len(sem_resposta),
        reingest.get("total_erros"),
        len(atrasados),
    )

    return {
        "status": "success",
        "candidatos": len(ids),
        "reingeridos": reingest.get("processados", 0),
        "preenchidos": len(preenchidos),
        "encerrados": len(encerrados),
        "sem_resposta": len(sem_resposta),
        "erros": reingest.get("total_erros", 0),
        "atrasados": len(atrasados),
        "correlation_id": reingest.get("correlation_id"),
    }


def _alertar_atrasados(ids: list[int]) -> None:
    logger.error(
        "[prazo-postagem] %s pedidos pagos estao ha mais de %sh sem prazo de postagem "
        "(pedido_id: %s) — seguem na fila, mas serao despachados as cegas se o prazo "
        "nao for buscado na mao",
        len(ids),
        ALERTA_HORAS,
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
