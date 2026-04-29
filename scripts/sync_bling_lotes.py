#!/usr/bin/env python3
"""
Script para sincronizar status dos pedidos com o Bling em lotes de 50.

Este script busca pedidos com situação "Em Andamento" (situacao_pedido_id = 2)
e atualiza o status de acordo com o que retorna da API do Bling.

LIMITAÇÃO DA API BLING:
- O endpoint GET /pedidos/vendas aceita apenas filtro por numerosLojas[] (ID da loja virtual)
- Não é possível buscar em lote pelos IDs internos do Bling
- Pedidos sem numeroLoja configurado na loja virtual não serão encontrados

Uso:
    python scripts/sync_bling_lotes.py [--batch N] [--limit N] [--dry-run]

Opções:
    --batch N      Tamanho do lote para busca no Bling (default: 50, max: 100)
    --limit N      Limitar quantidade total de pedidos para processar (default: sem limite)
    --dry-run      Apenas simula, não atualiza o banco
    --verbose      Log detalhado

Rate Limits:
    - Bling: 3 requisições/segundo (respeitado com sleep)
"""

import os
import sys
import time
import logging
import argparse
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple, Set

# Adicionar apps/api ao path para imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'apps', 'api'))

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.bling.bling_client import BlingClient
from nistiprint_shared.services.order_sync_service import order_sync_service
from nistiprint_shared.services.integracao_canal_service import integracao_canal_service

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('sync_bling_lotes.log', encoding='utf-8')
    ]
)
logger = logging.getLogger('SyncBlingLotes')

# Rate limits
BLING_RATE_LIMIT = 3  # requisições por segundo
BATCH_SIZE_DEFAULT = 50
BATCH_SIZE_MAX = 100  # Limite da API do Bling


class RateLimiter:
    """Controla rate limiting para APIs."""

    def __init__(self, requests_per_second: int):
        self.min_interval = 1.0 / requests_per_second
        self.last_request_time = 0

    def wait_if_needed(self):
        """Espera se necessário para respeitar o rate limit."""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.min_interval:
            sleep_time = self.min_interval - elapsed
            time.sleep(sleep_time)
        self.last_request_time = time.time()


class BlingBatchSync:
    """Serviço para sincronizar status de pedidos em lotes com o Bling."""

    def __init__(self, dry_run: bool = False, batch_size: int = BATCH_SIZE_DEFAULT):
        self.dry_run = dry_run
        self.batch_size = min(batch_size, BATCH_SIZE_MAX)
        self.bling_limiter = RateLimiter(BLING_RATE_LIMIT)

        # Estatísticas
        self.stats = {
            'total_pedidos': 0,
            'total_lotes': 0,
            'pedidos_encontrados_bling': 0,
            'pedidos_nao_encontrados_bling': 0,
            'status_atualizados': 0,
            'status_iguais': 0,
            'erros': 0,
        }

    def get_pedidos_em_andamento(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Busca pedidos com situação "Em Andamento" (ID 2) que possuem codigo_pedido_externo.

        Args:
            limit: Limite opcional de pedidos para retornar

        Returns:
            Lista de pedidos com dados necessários para sincronização
        """
        logger.info("Buscando pedidos 'Em Andamento' para sincronizar...")

        # Query para buscar pedidos com situacao_pedido_id = 2 (Em Andamento)
        query = supabase_db.table('pedidos').select('''
            id,
            numero_pedido,
            codigo_pedido_externo,
            situacao_pedido_id,
            canal_venda_id,
            updated_at
        ''').eq('situacao_pedido_id', 2).order('updated_at', desc=True)

        if limit:
            query = query.limit(limit)

        result = query.execute()
        pedidos = result.data if result.data else []

        # Filtrar apenas pedidos com codigo_pedido_externo preenchido
        pedidos_validos = []
        for pedido in pedidos:
            codigo = str(pedido.get('codigo_pedido_externo', '')).strip()
            if codigo:
                pedidos_validos.append(pedido)
            else:
                logger.debug(f"Pedido {pedido['id']} ignorado: codigo_pedido_externo vazio")

        logger.info(f"Encontrados {len(pedidos_validos)} pedidos 'Em Andamento' válidos para sincronizar")
        return pedidos_validos

    def get_bling_client_for_pedido(self, pedido: Dict[str, Any]) -> Optional[BlingClient]:
        """
        Obtém cliente Bling configurado para o pedido.

        Args:
            pedido: Dados do pedido

        Returns:
            BlingClient configurado ou None se não encontrar integração
        """
        try:
            canal_id = pedido.get('canal_venda_id')
            if not canal_id:
                logger.debug(f"Pedido {pedido.get('id')}: Sem canal_venda_id")
                return None

            # Buscar configuração de integração Bling
            config = integracao_canal_service.get_integration_by_canal(canal_id, expected_module='bling')
            if not config:
                logger.debug(f"Canal {canal_id}: Sem configuração de integração Bling")
                return None

            bling_iid = config.get('bling_integration_id')
            if bling_iid:
                return BlingClient.create_client_for_integration_id(int(bling_iid))

            # Fallback: criar cliente por plataforma
            plataforma = config.get('plataforma_nome', 'shopee')
            return BlingClient.create_client_for_platform(
                plataforma.lower(),
                channel_id=canal_id,
                function_name="ORDER_SYNC"
            )

        except Exception as e:
            logger.error(f"Erro ao criar BlingClient: {e}")
            return None

    def buscar_pedidos_no_bling_em_lote(
        self,
        bling_client: BlingClient,
        codigos_externos: List[str]
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """
        Busca pedidos no Bling usando o endpoint GET /pedidos/vendas com numerosLojas[].

        Args:
            bling_client: Cliente Bling autenticado
            codigos_externos: Lista de codigo_pedido_externo para buscar

        Returns:
            Tupla com (pedidos_encontrados, codigos_nao_encontrados)
        """
        if not codigos_externos:
            return [], []

        # Respeitar rate limit
        self.bling_limiter.wait_if_needed()

        # Construir parâmetros da URL usando numerosLojas[]
        # A API do Bling aceita múltiplos valores com o mesmo nome de parâmetro
        params = [('numerosLojas[]', str(codigo)) for codigo in codigos_externos]

        logger.debug(f"Bling: Buscando {len(codigos_externos)} pedidos...")
        response = bling_client._request('GET', 'pedidos/vendas', params=params)

        if not response:
            logger.error("Bling: Erro na resposta da API")
            return [], codigos_externos.copy()

        pedidos_bling = response.get('data', [])
        logger.debug(f"Bling: Encontrados {len(pedidos_bling)} pedidos")

        # Criar conjunto de IDs encontrados para calcular os não encontrados
        ids_encontrados = {str(p.get('numeroLoja')) for p in pedidos_bling if p.get('numeroLoja')}
        codigos_nao_encontrados = [c for c in codigos_externos if c not in ids_encontrados]

        return pedidos_bling, codigos_nao_encontrados

    def processar_lote(
        self,
        bling_client: BlingClient,
        pedidos_internos: List[Dict[str, Any]]
    ) -> None:
        """
        Processa um lote de pedidos internos, buscando no Bling e atualizando status.

        Args:
            bling_client: Cliente Bling autenticado
            pedidos_internos: Lista de pedidos internos para processar
        """
        if not pedidos_internos:
            return

        # Extrair codigos_externos para busca no Bling (valores de codigo_pedido_externo)
        codigos_externos = [str(p['codigo_pedido_externo']) for p in pedidos_internos]

        # Buscar no Bling usando endpoint GET /pedidos/vendas com numerosLojas[]
        pedidos_bling, codigos_nao_encontrados = self.buscar_pedidos_no_bling_em_lote(
            bling_client, codigos_externos
        )

        # Atualizar estatísticas
        self.stats['pedidos_encontrados_bling'] += len(pedidos_bling)
        self.stats['pedidos_nao_encontrados_bling'] += len(codigos_nao_encontrados)

        # Logar pedidos não encontrados
        if codigos_nao_encontrados:
            logger.warning(f"Bling: {len(codigos_nao_encontrados)} pedidos não encontrados: {codigos_nao_encontrados[:10]}{'...' if len(codigos_nao_encontrados) > 10 else ''}")

        # Criar mapa de pedidos Bling por numeroLoja para acesso rápido
        bling_map = {str(p.get('numeroLoja')): p for p in pedidos_bling if p.get('numeroLoja')}

        # Processar cada pedido interno
        for pedido_interno in pedidos_internos:
            codigo_externo = str(pedido_interno['codigo_pedido_externo'])
            bling_order = bling_map.get(codigo_externo)

            if not bling_order:
                logger.debug(f"Pedido {pedido_interno['id']}: Não encontrado no Bling (codigo: {codigo_externo})")
                continue

            # Extrair status do Bling
            bling_status_id = bling_order.get('situacao', {}).get('id')
            if not bling_status_id:
                logger.warning(f"Pedido {pedido_interno['id']}: Status não encontrado no Bling")
                continue

            # Mapear status Bling -> Interno
            status_interno = order_sync_service._map_bling_status(bling_status_id)
            status_atual = pedido_interno.get('situacao_pedido_id')

            logger.debug(
                f"Pedido {pedido_interno['id']} (Bling {codigo_externo}): "
                f"Status Bling: {bling_status_id} -> Status Interno: {status_interno} (atual: {status_atual})"
            )

            # Verificar se precisa atualizar
            if status_atual != status_interno:
                self.atualizar_status_pedido(pedido_interno, status_interno, bling_status_id)
            else:
                self.stats['status_iguais'] += 1
                logger.debug(f"Pedido {pedido_interno['id']}: Status já está atualizado ({status_interno})")

    def atualizar_status_pedido(
        self,
        pedido: Dict[str, Any],
        novo_status_id: int,
        bling_status_id: int
    ) -> None:
        """
        Atualiza o status de um pedido no banco de dados.

        Args:
            pedido: Dados do pedido
            novo_status_id: Novo status interno
            bling_status_id: Status original do Bling (para logging)
        """
        status_anterior = pedido.get('situacao_pedido_id')

        if self.dry_run:
            logger.info(
                f"[DRY RUN] Pedido {pedido['id']}: Atualizaria status de {status_anterior} para {novo_status_id} "
                f"(Bling: {bling_status_id})"
            )
        else:
            try:
                # Atualizar no banco
                supabase_db.table('pedidos').update({
                    'situacao_pedido_id': novo_status_id,
                    'updated_at': datetime.utcnow().isoformat()
                }).eq('id', pedido['id']).execute()

                # Registrar evento na timeline
                self.registrar_evento(pedido['id'], 'STATUS_SYNC',
                                     f"Status atualizado via Bling: {status_anterior} -> {novo_status_id} (Bling ID: {bling_status_id})")

                logger.info(
                    f"Pedido {pedido['id']}: Status atualizado de {status_anterior} para {novo_status_id} "
                    f"(Bling: {bling_status_id})"
                )
                self.stats['status_atualizados'] += 1

            except Exception as e:
                logger.error(f"Pedido {pedido['id']}: Erro ao atualizar status: {e}")
                self.stats['erros'] += 1

    def registrar_evento(self, pedido_id: int, tipo: str, descricao: str) -> None:
        """
        Registra evento na timeline do pedido.

        Args:
            pedido_id: ID do pedido
            tipo: Tipo do evento (ex: STATUS_SYNC)
            descricao: Descrição do evento
        """
        try:
            supabase_db.table('eventos_pedido').insert({
                'pedido_id': pedido_id,
                'tipo_evento': tipo,
                'descricao': descricao,
                'created_at': datetime.utcnow().isoformat()
            }).execute()
        except Exception as e:
            logger.warning(f"Erro ao registrar evento para pedido {pedido_id}: {e}")

    def run(self, limit: Optional[int] = None) -> None:
        """
        Executa a sincronização em lotes.

        Args:
            limit: Limite opcional de pedidos para processar
        """
        logger.info("=" * 70)
        logger.info("INICIANDO SINCRONIZAÇÃO DE STATUS COM BLING (EM LOTES)")
        logger.info("=" * 70)
        logger.info(f"Configuração: batch_size={self.batch_size}, limit={limit}, dry_run={self.dry_run}")
        logger.info("")

        # Buscar pedidos para sincronizar
        pedidos = self.get_pedidos_em_andamento(limit=limit)

        if not pedidos:
            logger.info("Nenhum pedido 'Em Andamento' para processar")
            return

        self.stats['total_pedidos'] = len(pedidos)

        # Agrupar pedidos por canal_venda_id para usar o BlingClient correto
        pedidos_por_canal: Dict[int, List[Dict[str, Any]]] = {}
        pedidos_sem_canal: List[Dict[str, Any]] = []
        
        for pedido in pedidos:
            canal_id = pedido.get('canal_venda_id')
            if canal_id:
                if canal_id not in pedidos_por_canal:
                    pedidos_por_canal[canal_id] = []
                pedidos_por_canal[canal_id].append(pedido)
            else:
                pedidos_sem_canal.append(pedido)

        logger.info(f"Pedidos agrupados em {len(pedidos_por_canal)} canal(is) de venda")
        if pedidos_sem_canal:
            logger.warning(f"{len(pedidos_sem_canal)} pedidos sem canal_venda_id serão ignorados")
        logger.info("")

        # Processar cada canal
        for canal_id, pedidos_canal in pedidos_por_canal.items():
            logger.info(f"Processando canal {canal_id} ({len(pedidos_canal)} pedidos)...")

            # Obter BlingClient para este canal
            # Usar o primeiro pedido como referência
            bling_client = self.get_bling_client_for_pedido(pedidos_canal[0])
            if not bling_client:
                logger.warning(f"Canal {canal_id}: Não foi possível obter BlingClient, pulando {len(pedidos_canal)} pedidos")
                self.stats['erros'] += len(pedidos_canal)
                continue

            logger.info(f"Canal {canal_id}: BlingClient obtido com sucesso")

            # Dividir em lotes
            lotes = [
                pedidos_canal[i:i + self.batch_size]
                for i in range(0, len(pedidos_canal), self.batch_size)
            ]

            logger.info(f"Canal {canal_id}: {len(lotes)} lote(s) de até {self.batch_size} pedidos")

            # Processar cada lote
            for idx_lote, lote in enumerate(lotes, 1):
                logger.info(f"  Lote {idx_lote}/{len(lotes)}: {len(lote)} pedidos")
                self.stats['total_lotes'] += 1

                try:
                    self.processar_lote(bling_client, lote)
                except Exception as e:
                    logger.error(f"  Erro ao processar lote {idx_lote}: {e}")
                    self.stats['erros'] += len(lote)

            logger.info(f"Canal {canal_id}: Processamento concluído")
            logger.info("")

        # Relatório final
        self.imprimir_relatorio()

    def imprimir_relatorio(self) -> None:
        """Imprime relatório final da sincronização."""
        total = self.stats['total_pedidos']
        encontrados = self.stats['pedidos_encontrados_bling']
        taxa_encontro = (encontrados / total * 100) if total > 0 else 0

        logger.info("=" * 70)
        logger.info("RELATÓRIO FINAL")
        logger.info("=" * 70)
        logger.info(f"Total de pedidos:            {self.stats['total_pedidos']}")
        logger.info(f"Total de lotes processados:  {self.stats['total_lotes']}")
        logger.info(f"Pedidos encontrados no Bling: {self.stats['pedidos_encontrados_bling']} ({taxa_encontro:.1f}%)")
        logger.info(f"Pedidos não encontrados:     {self.stats['pedidos_nao_encontrados_bling']}")
        logger.info(f"Status atualizados:          {self.stats['status_atualizados']}")
        logger.info(f"Status já atualizados:       {self.stats['status_iguais']}")
        logger.info(f"Erros:                       {self.stats['erros']}")

        if self.dry_run:
            logger.info("")
            logger.info("⚠️  DRY RUN - Nenhuma alteração foi feita no banco")


def main():
    parser = argparse.ArgumentParser(
        description='Sincronizar status de pedidos "Em Andamento" com o Bling em lotes'
    )
    parser.add_argument(
        '--batch', '-b',
        type=int,
        default=BATCH_SIZE_DEFAULT,
        help=f'Tamanho do lote para busca no Bling (default: {BATCH_SIZE_DEFAULT}, max: {BATCH_SIZE_MAX})'
    )
    parser.add_argument(
        '--limit', '-l',
        type=int,
        default=None,
        help='Limitar quantidade total de pedidos (default: sem limite)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Apenas simula, não atualiza o banco'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Habilitar log detalhado (debug)'
    )

    args = parser.parse_args()

    # Configurar nível de log
    if args.verbose:
        logging.getLogger('SyncBlingLotes').setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)

    # Validar batch size
    if args.batch > BATCH_SIZE_MAX:
        logger.warning(f"Batch size {args.batch} excede o limite da API ({BATCH_SIZE_MAX}). Usando {BATCH_SIZE_MAX}.")
        args.batch = BATCH_SIZE_MAX

    # Executar sync
    sync_service = BlingBatchSync(dry_run=args.dry_run, batch_size=args.batch)
    sync_service.run(limit=args.limit)


if __name__ == '__main__':
    main()
