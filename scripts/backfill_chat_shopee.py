"""
Backfill das conversas do SellerChat com lacuna declarada.

Uso:
    python scripts/backfill_chat_shopee.py [--limite N] [--rps 2] [--dry-run]
                                           [--janela-dias 7] [--conversa ID]

Recupera as mensagens que a Shopee entregou apenas como referencia dentro de um
`bundle_message` e nunca foram buscadas. Le a fila de `conversas_chat_shopee`
mantida pelo ingest, entao pode ser interrompido e retomado: o que ja foi
resolvido sai da fila sozinho.

Expectativa realista: as conversas cuja ultima mensagem passou de 12h sem leitura
provavelmente nao voltam -- a Shopee as oculta do vendedor. O script nao finge
sucesso nesses casos: o que nao voltar fica registrado em `ids_nao_recuperados`
com status `expirada`, e aparece no resumo final.

Priorizacao: conversas com mensagem mais recente primeiro, porque sao as dos
pedidos que ainda precisam ser atendidos.
"""
import argparse
import logging
import time
from datetime import datetime, timedelta, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("backfill_chat_shopee")

COLUNAS = ("conversation_id,installed_integration_id,buyer_username,ids_nao_recuperados,"
           "status_completude,ultima_mensagem_em,mensagens_esperadas,mensagens_presentes")


def _conversas_pendentes(supabase_db, *, janela_dias, limite, conversa=None):
    query = (supabase_db.table("conversas_chat_shopee").select(COLUNAS)
             .order("ultima_mensagem_em", desc=True))
    if conversa:
        query = query.eq("conversation_id", int(conversa))
    else:
        corte = datetime.now(timezone.utc) - timedelta(days=janela_dias)
        query = (query.in_("status_completude", ["pendente", "erro"])
                 .gte("ultima_mensagem_em", corte.isoformat())
                 .limit(limite))
    return query.execute().data or []


def _rodar(args):
    from nistiprint_shared.database.supabase_db_service import supabase_db
    from nistiprint_shared.services.shopee_chat_service import shopee_chat_ingest_service

    conversas = _conversas_pendentes(
        supabase_db, janela_dias=args.janela_dias, limite=args.limite, conversa=args.conversa
    )
    logger.info("%s conversa(s) na fila (janela de %s dias)", len(conversas), args.janela_dias)
    if not conversas:
        return 0

    ausentes_antes = sum(len(linha.get("ids_nao_recuperados") or []) for linha in conversas)
    logger.info("%s mensagem(ns) ausente(s) declarada(s)", ausentes_antes)

    if args.dry_run:
        for linha in conversas[:20]:
            logger.info("  conversa=%s comprador=%s ausentes=%s ultima=%s",
                        linha.get("conversation_id"), linha.get("buyer_username"),
                        len(linha.get("ids_nao_recuperados") or []),
                        linha.get("ultima_mensagem_em"))
        logger.info("dry-run: nada foi buscado na Shopee")
        return 0

    # Token bucket simples. A Shopee limita por app, e o backfill nao pode
    # competir com o ingest ao vivo, que tem prazo de 12h para nao perder o
    # conteudo -- o historico pode esperar.
    intervalo = 1.0 / max(args.rps, 0.1)
    proximo = time.monotonic()

    resumo = {"resolvidas": 0, "expiradas": 0, "falhas": 0, "recuperadas": 0}
    for indice, linha in enumerate(conversas, start=1):
        agora = time.monotonic()
        if agora < proximo:
            time.sleep(proximo - agora)
        proximo = time.monotonic() + intervalo

        conversation_id = linha.get("conversation_id")
        integration = shopee_chat_ingest_service.carregar_integracao(
            linha.get("installed_integration_id")
        )
        if not integration:
            resumo["falhas"] += 1
            logger.warning("[%s/%s] conversa=%s sem integracao ativa",
                           indice, len(conversas), conversation_id)
            continue

        ausentes = linha.get("ids_nao_recuperados") or []
        if ausentes:
            resultado = shopee_chat_ingest_service.resolver_bundle(
                integration, conversation_id, ausentes
            )
        else:
            resultado = shopee_chat_ingest_service.reconcile_conversation(
                integration, str(conversation_id), janela_dias=args.janela_dias
            )

        if resultado.get("status") != "success":
            resumo["falhas"] += 1
            logger.warning("[%s/%s] conversa=%s falhou: %s (%s)", indice, len(conversas),
                           conversation_id, resultado.get("error_type"), resultado.get("message"))
            if resultado.get("error_type") == "rate_limit":
                espera = int(resultado.get("retry_after") or 30)
                logger.info("rate limit da Shopee: aguardando %ss", espera)
                time.sleep(espera)
            continue

        recuperadas = int(resultado.get("messages_upserted") or 0)
        resumo["recuperadas"] += recuperadas
        estado = str(resultado.get("status_completude") or "")
        if estado == "completa":
            resumo["resolvidas"] += 1
        elif estado == "expirada":
            resumo["expiradas"] += 1
        logger.info("[%s/%s] conversa=%s recuperadas=%s estado=%s nao_recuperadas=%s",
                    indice, len(conversas), conversation_id, recuperadas, estado,
                    len(resultado.get("ids_nao_recuperados") or []))

    logger.info("---")
    logger.info("conversas completadas ....... %s", resumo["resolvidas"])
    logger.info("conversas expiradas ......... %s (a Shopee ja havia ocultado)", resumo["expiradas"])
    logger.info("falhas ...................... %s", resumo["falhas"])
    logger.info("mensagens recuperadas ....... %s de %s declaradas ausentes",
                resumo["recuperadas"], ausentes_antes)
    return 0 if not resumo["falhas"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limite", type=int, default=200,
                        help="maximo de conversas por execucao (padrao 200)")
    parser.add_argument("--rps", type=float, default=2.0,
                        help="chamadas por segundo a Shopee (padrao 2)")
    parser.add_argument("--janela-dias", type=int, default=7,
                        help="janela de contexto em dias (padrao 7)")
    parser.add_argument("--conversa", type=int, default=None,
                        help="reconcilia uma unica conversation_id, ignorando os filtros")
    parser.add_argument("--dry-run", action="store_true",
                        help="lista a fila sem chamar a Shopee")
    return _rodar(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
