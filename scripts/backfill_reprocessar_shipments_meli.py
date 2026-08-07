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

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
# Quando o pacote nao esta instalado (`pip install -e packages/shared`),
# apontamos o sys.path direto para os fontes.
for _candidate in (_PROJECT_ROOT, os.path.join(_PROJECT_ROOT, 'packages', 'shared')):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger('backfill-shipments-meli')


def _localizar_env() -> str | None:
    for candidato in (os.path.join(os.getcwd(), '.env'), os.path.join(_PROJECT_ROOT, '.env')):
        if os.path.exists(candidato):
            return candidato
    return None


def _parse_env_manual(caminho: str) -> int:
    """Parser minimo de .env, usado quando python-dotenv nao esta disponivel.

    Cobre `CHAVE=valor`, comentarios, `export ` e aspas simples/duplas.
    Nao expande variaveis nem trata valores multilinha - se o .env usar isso,
    rode com o interpretador do .venv, que tem o python-dotenv.
    """
    carregadas = 0
    with open(caminho, 'r', encoding='utf-8') as arquivo:
        for linha in arquivo:
            linha = linha.strip()
            if not linha or linha.startswith('#') or '=' not in linha:
                continue
            if linha.startswith('export '):
                linha = linha[len('export '):]
            chave, _, valor = linha.partition('=')
            chave = chave.strip()
            valor = valor.strip()
            if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in ('"', "'"):
                valor = valor[1:-1]
            if chave and chave not in os.environ:
                os.environ[chave] = valor
                carregadas += 1
    return carregadas


def _carregar_env() -> None:
    """Carrega o .env antes de qualquer import que instancie o cliente Supabase."""
    caminho = _localizar_env()
    if not caminho:
        logger.warning('Arquivo .env nao localizado a partir de %s', os.getcwd())
        return

    try:
        from dotenv import load_dotenv
    except ModuleNotFoundError:
        # Interpretador sem as dependencias do projeto (ex.: python3 do sistema
        # em vez do .venv). Fazemos o parse na mao para pelo menos conseguir
        # reportar o proximo problema com clareza.
        total = _parse_env_manual(caminho)
        logger.info('Ambiente carregado de %s (%s variaveis, parser interno)', caminho, total)
        return

    load_dotenv(dotenv_path=caminho)
    logger.info('Ambiente carregado de %s', caminho)


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


def _mascarar(valor: str | None) -> str:
    if not valor:
        return '<vazio>'
    if len(valor) <= 12:
        return f'<{len(valor)} chars>'
    return f'{valor[:8]}...{valor[-4:]} ({len(valor)} chars)'


def main():
    args = _parse_args()

    logger.info('python=%s cwd=%s', sys.executable, os.getcwd())

    _carregar_env()

    for nome in ('SUPABASE_URL', 'SUPABASE_SERVICE_KEY', 'INGEST_REDIS_URL'):
        logger.info('env %s = %s', nome, _mascarar(os.environ.get(nome)))

    faltando = [
        nome for nome in ('SUPABASE_URL', 'SUPABASE_SERVICE_KEY')
        if not os.environ.get(nome)
    ]
    if faltando:
        logger.error(
            'Variaveis de ambiente ausentes: %s. Rode a partir da raiz do projeto '
            '(onde esta o .env) ou exporte-as antes.',
            ', '.join(faltando),
        )
        return 2

    if not args.dry_run and not os.environ.get('INGEST_REDIS_URL'):
        # O default da fila de ingestao confiavel e `redis://redis:6379/0`,
        # hostname que so existia no docker-compose. Rodando como servico,
        # o publish falha se a variavel nao estiver no .env.
        logger.warning(
            'INGEST_REDIS_URL nao definida; a fila usara o default '
            'redis://redis:6379/0. Se o Redis nao atende nesse host, defina '
            'INGEST_REDIS_URL no .env (ex.: redis://localhost:6379/0).'
        )

    try:
        from nistiprint_shared.services.marketplace_payment_reprocess_service import (
            marketplace_shipment_reprocess_service,
        )
    except ModuleNotFoundError as exc:
        logger.error(
            'Nao foi possivel importar as dependencias (%s). Use o interpretador '
            'do projeto, que tem os pacotes instalados: '
            '.venv/bin/python scripts/%s',
            exc, os.path.basename(__file__),
        )
        return 2

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
