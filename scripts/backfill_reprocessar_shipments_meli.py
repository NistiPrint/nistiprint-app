"""
Reenfileira os webhooks de `shipments` do Mercado Livre que morreram como
`failed_terminal` com o erro `shipment_without_order_reference`.

Contexto
--------
O commit b870300 passou a enviar o header `x-format-new: true` em
`GET /shipments/{id}`. Nesse formato o Mercado Livre deixou de expor
`order_id` e `pack_id` no root da resposta, entao o adapter nao conseguia
mais correlacionar o shipment ao pedido e encerrava o evento como terminal.
Resultado: nenhum pedido do ML avancava de "Em Andamento" para "Enviado" /
"Entregue" a partir de 31/07/2026.

A correcao adiciona o fallback via `GET /shipments/{id}/items`. Este script
faz o replay dos eventos que falharam nesse intervalo, para que os pedidos
travados recebam o status atual do marketplace. Ele apenas envolve o
`marketplace_shipment_reprocess_service`, que ja faz reserva atomica do
evento e publica no envelope de ingestao confiavel.

IMPORTANTE: rode este script somente APOS o deploy da correcao, senao os
eventos vao falhar de novo pelo mesmo motivo.

Uso:
    python scripts/backfill_reprocessar_shipments_meli.py --dry-run
    python scripts/backfill_reprocessar_shipments_meli.py --limite 100
    python scripts/backfill_reprocessar_shipments_meli.py --limite 500 --lotes 3
"""
import argparse
import logging
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger('backfill-shipments-meli')


def _parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--limite',
        type=int,
        default=100,
        help='Eventos por lote (o servico limita a 500). Padrao: 100.',
    )
    parser.add_argument(
        '--lotes',
        type=int,
        default=1,
        help='Quantos lotes rodar em sequencia. Padrao: 1.',
    )
    parser.add_argument(
        '--intervalo',
        type=float,
        default=5.0,
        help='Pausa em segundos entre lotes, para nao estourar o rate limit do ML.',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Apenas lista o que seria reprocessado, sem enfileirar nada.',
    )
    return parser.parse_args()


def main():
    args = _parse_args()

    from nistiprint_shared.services.marketplace_payment_reprocess_service import (
        marketplace_shipment_reprocess_service,
    )

    total_enfileirados, total_falhas = 0, 0

    for lote in range(1, max(1, args.lotes) + 1):
        resultado = marketplace_shipment_reprocess_service.reprocess(
            dry_run=args.dry_run,
            limit=args.limite,
        )
        candidatos = resultado.get('candidate_count', 0)

        if args.dry_run:
            for row in resultado.get('candidates', []):
                logger.info(
                    '[dry-run] id=%s resource=%s/%s status=%s erro=%s',
                    row.get('webhook_event_id'), row.get('resource_type'),
                    row.get('resource_id'), row.get('last_status'),
                    row.get('last_error_type'),
                )
            logger.info('[dry-run] %s eventos seriam reenfileirados.', candidatos)
            return 0

        enfileirados = len(resultado.get('queued', []))
        falhas = resultado.get('failed', [])
        total_enfileirados += enfileirados
        total_falhas += len(falhas)

        logger.info(
            'Lote %s/%s: candidatos=%s enfileirados=%s falhas=%s',
            lote, args.lotes, candidatos, enfileirados, len(falhas),
        )
        for falha in falhas:
            logger.warning(
                'Falha id=%s erro=%s',
                falha.get('webhook_event_id'), falha.get('error_type'),
            )

        if candidatos == 0:
            logger.info('Sem candidatos restantes; encerrando antes do fim dos lotes.')
            break
        if lote < args.lotes and args.intervalo > 0:
            time.sleep(args.intervalo)

    logger.info(
        'Concluido. enfileirados=%s falhas=%s',
        total_enfileirados, total_falhas,
    )
    return 0 if total_falhas == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
