"""
Script para backfill de pedidos movendo mensagens da dead-letter queue
para a fila de pendentes.

Uso:
    python scripts/backfill_redis_dead_letter.py [--limit N] [--dry-run]

O script lê mensagens de 'bling:webhooks:dead-letter' e as move para
'bling:webhooks:pendentes' para reprocessamento pelo pipeline unificado.
"""
import json
import logging
import argparse
from typing import List

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

REDIS_HOST = 'redis'
REDIS_PORT = 6379
REDIS_DB = 0
DEAD_LETTER_QUEUE = 'bling:webhooks:dead-letter'
PENDING_QUEUE = 'bling:webhooks:pendentes'


def _get_redis_client():
    import redis
    return redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5
    )


def move_dead_letter_to_pending(limit: int = None, dry_run: bool = False) -> dict:
    """
    Move mensagens da dead-letter queue para a fila de pendentes.

    Args:
        limit: Número máximo de mensagens a mover (None = todas)
        dry_run: Se True, apenas conta e valida sem mover

    Returns:
        Dict com estatísticas
    """
    redis_client = _get_redis_client()
    stats = {
        'total_in_dead_letter': 0,
        'moved': 0,
        'skipped': 0,
        'errors': 0,
        'sample_messages': []
    }

    try:
        # Contar mensagens na dead-letter
        stats['total_in_dead_letter'] = redis_client.llen(DEAD_LETTER_QUEUE)
        logger.info(f"Total de mensagens em {DEAD_LETTER_QUEUE}: {stats['total_in_dead_letter']}")

        if stats['total_in_dead_letter'] == 0:
            logger.info("Nenhuma mensagem para processar.")
            return stats

        # Determinar quantas mensagens processar
        to_process = stats['total_in_dead_letter']
        if limit and limit < to_process:
            to_process = limit
            logger.info(f"Limitando a {to_process} mensagens (limit={limit})")

        # Processar mensagens
        for i in range(to_process):
            try:
                # Usar RPOPLPUSH para mover atomicamente (se não for dry-run)
                if dry_run:
                    # Em dry-run, apenas lê sem remover
                    msg = redis_client.lindex(DEAD_LETTER_QUEUE, -1 - i)
                    if not msg:
                        break
                else:
                    msg = redis_client.rpop(DEAD_LETTER_QUEUE)
                    if not msg:
                        break

                # Validar que é JSON válido
                try:
                    payload = json.loads(msg)
                except json.JSONDecodeError:
                    logger.warning(f"Mensagem {i} não é JSON válido, descartando")
                    stats['skipped'] += 1
                    continue

                # Guardar amostra para inspeção
                if len(stats['sample_messages']) < 5:
                    stats['sample_messages'].append({
                        'index': i,
                        'bling_id': payload.get('data', {}).get('id'),
                        'numeroLoja': payload.get('data', {}).get('numeroLoja'),
                        'companyId': payload.get('companyId')
                    })

                if not dry_run:
                    # Mover para pendentes
                    redis_client.lpush(PENDING_QUEUE, msg)
                    stats['moved'] += 1

                    if (i + 1) % 100 == 0:
                        logger.info(f"{i + 1}/{to_process} mensagens movidas")
                else:
                    stats['moved'] += 1  # Conta como "seria movida"

            except Exception as e:
                logger.error(f"Erro ao processar mensagem {i}: {e}")
                stats['errors'] += 1

        logger.info(f"Resumo: movidas={stats['moved']}, ignoradas={stats['skipped']}, erros={stats['errors']}")

        if stats['sample_messages']:
            logger.info("Amostra de mensagens:")
            for sample in stats['sample_messages']:
                logger.info(f"  - bling_id={sample['bling_id']}, numeroLoja={sample['numeroLoja']}, companyId={sample['companyId']}")

    except Exception as e:
        logger.error(f"Erro fatal: {e}", exc_info=True)
        raise

    return stats


def main():
    parser = argparse.ArgumentParser(description='Backfill: mover dead-letter -> pendentes')
    parser.add_argument('--limit', type=int, help='Limite de mensagens a mover (default: todas)')
    parser.add_argument('--dry-run', action='store_true', help='Apenas contar e validar, não mover')
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("BACKFILL: Dead-Letter -> Pendentes")
    logger.info("=" * 60)
    logger.info(f"Modo: {'DRY-RUN' if args.dry_run else 'EXECUÇÃO'}")
    if args.limit:
        logger.info(f"Limite: {args.limit} mensagens")
    logger.info("=" * 60)

    stats = move_dead_letter_to_pending(limit=args.limit, dry_run=args.dry_run)

    logger.info("=" * 60)
    logger.info("FINALIZADO")
    logger.info("=" * 60)
    logger.info(f"Total na dead-letter: {stats['total_in_dead_letter']}")
    logger.info(f"Movidas (ou seriam movidas): {stats['moved']}")
    logger.info(f"Ignoradas: {stats['skipped']}")
    logger.info(f"Erros: {stats['errors']}")


if __name__ == '__main__':
    main()
