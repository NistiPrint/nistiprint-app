"""After deploying the projection worker, requeue missing geography in small batches."""

import argparse
import os

import psycopg2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--account-id', type=int, required=True)
    parser.add_argument('--after', type=int, default=0, help='Último ID da execução anterior')
    parser.add_argument('--max-batches', type=int, default=10)
    args = parser.parse_args()
    if args.account_id <= 0 or args.after < 0 or not 1 <= args.max_batches <= 100:
        parser.error('Informe conta positiva, cursor não negativo e até 100 lotes por execução.')
    dsn = os.environ.get('NISTIPRINT_GESTAO_REPAIR_DSN')
    if not dsn:
        parser.error('Defina NISTIPRINT_GESTAO_REPAIR_DSN')
    after, total = args.after, 0
    with psycopg2.connect(dsn) as connection:
        for _ in range(args.max_batches):
            with connection.cursor() as cursor:
                cursor.execute('SELECT gestao_requeue_geography(%s,%s,100)', (args.account_id, after))
                result = cursor.fetchone()[0]
            connection.commit()
            after, count = result['last_id'], result['queued']
            total += count
            if not count:
                break
    print(f'Pedidos enfileirados: {total}; último ID: {after}.')


if __name__ == '__main__':
    main()
