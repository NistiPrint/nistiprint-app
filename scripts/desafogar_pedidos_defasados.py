"""Desafoga pedidos cujo status parou de evoluir ha dias.

Motivacao: quando um webhook do marketplace se perde, o pedido congela numa
situacao intermediaria e ninguem fica sabendo — a base nao tem como distinguir
"nada aconteceu com este pedido" de "nao fomos avisados do que aconteceu".

Este script identifica os congelados por `marketplace_status_updated_at` e os
devolve para a pipeline normal de ingest via `ressincronizar_pendentes`. Nao
escreve em `pedidos`: quem decide o novo status continua sendo a mesma pipeline
que processa o webhook, entao nao existe caminho de escrita paralelo aqui.

Uso:
    python scripts/desafogar_pedidos_defasados.py --dias 7 --dry-run
    python scripts/desafogar_pedidos_defasados.py --dias 7

O padrao e `--dry-run`: relistar e barato, chamar a API do marketplace 59 vezes
por engano nao e.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.append(os.path.join(os.getcwd(), 'packages', 'shared'))

from nistiprint_shared.database.supabase_db_service import supabase_db  # noqa: E402
from nistiprint_shared.services.ressincronizacao_service import (  # noqa: E402
    SITUACOES_NAO_FINALIZADAS,
    ressincronizar_pendentes,
)


def listar_defasados(dias: int, limite: int) -> list[dict]:
    corte = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
    return (
        supabase_db.table('pedidos')
        .select('id,numero_pedido,marketplace_order_id,origem,'
                'situacao_pedido_id,marketplace_status_updated_at')
        .in_('situacao_pedido_id', SITUACOES_NAO_FINALIZADAS)
        .lt('marketplace_status_updated_at', corte)
        .order('marketplace_status_updated_at')
        .limit(limite)
        .execute()
        .data
        or []
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dias', type=int, default=7,
                        help='pedidos sem atualizacao de status ha mais de N dias')
    parser.add_argument('--limite', type=int, default=200,
                        help='teto de pedidos por execucao (quota de API)')
    parser.add_argument('--pausa', type=float, default=0.2,
                        help='segundos entre chamadas a origem')
    parser.add_argument('--dry-run', action='store_true', default=None,
                        help='so lista (padrao)')
    parser.add_argument('--executar', dest='dry_run', action='store_false',
                        help='executa de fato')
    args = parser.parse_args()
    dry_run = True if args.dry_run is None else args.dry_run

    pedidos = listar_defasados(args.dias, args.limite)
    if not pedidos:
        print(f'Nenhum pedido parado ha mais de {args.dias} dias.')
        return 0

    print(f'{len(pedidos)} pedidos sem atualizacao ha mais de {args.dias} dias:\n')
    for p in pedidos[:20]:
        print(f"  #{p['id']:<7} {p['origem']:<18} bling={p.get('numero_pedido'):<10} "
              f"mkt={p.get('marketplace_order_id')} "
              f"parado desde {str(p.get('marketplace_status_updated_at'))[:10]}")
    if len(pedidos) > 20:
        print(f'  ... e mais {len(pedidos) - 20}')

    if dry_run:
        print('\n[dry-run] nada foi chamado. Use --executar para desafogar.')
        return 0

    print('\nRelendo na origem...\n')
    resultado = ressincronizar_pendentes(
        pedido_ids=[p['id'] for p in pedidos],
        limite=args.limite,
        pausa_segundos=args.pausa,
    )
    print(json.dumps(resultado, indent=2, ensure_ascii=False, default=str))
    return 0 if resultado.get('total_erros', 0) == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
