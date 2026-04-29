#!/usr/bin/env python3
"""
Standalone script para atualizar o status dos pedidos de acordo com o Bling.

Busca pedidos no banco de dados e atualiza seus status consultando a API do Bling.

Uso:
    python scripts/update_bling_order_status.py --days 7
    python scripts/update_bling_order_status.py --days 30 --limit 100
    python scripts/update_bling_order_status.py --days 7 --dry-run

Opções:
    --days N       Buscar pedidos dos últimos N dias (obrigatório)
    --limit N      Limitar a quantidade de pedidos (opcional)
    --dry-run      Apenas simula, não atualiza o banco
    --canal-id N   Filtrar apenas por canal de venda específico (opcional)

Rate Limit:
    - Bling: 3 requisições/segundo (respeitado com sleep)
"""

import os
import sys
import time
import logging
import argparse
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

# Adicionar parent directory ao path para imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.bling.bling_client import BlingClient
from nistiprint_shared.services.integracao_canal_service import integracao_canal_service
from nistiprint_shared.services.order_sync_service import order_sync_service

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('update_bling_order_status.log', encoding='utf-8')
    ]
)
logger = logging.getLogger('UpdateBlingOrderStatus')

# Rate limit
BLING_RATE_LIMIT = 3  # requisições por segundo


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


class BlingStatusUpdater:
    """Serviço para atualizar status de pedidos via Bling."""
    
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.limiter = RateLimiter(BLING_RATE_LIMIT)
        
        # Estatísticas
        self.stats = {
            'total': 0,
            'updated': 0,
            'unchanged': 0,
            'errors': 0,
            'not_found': 0,
        }
    
    def get_pedidos(self, days: int, limit: Optional[int] = None, 
                    canal_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Busca pedidos para atualização.
        
        Args:
            days: Número de dias anteriores para buscar
            limit: Limite opcional de pedidos
            canal_id: ID do canal de venda para filtrar (opcional)
        
        Returns:
            Lista de pedidos
        """
        logger.info(f"Buscando pedidos dos últimos {days} dias...")
        
        data_inicio = (datetime.utcnow() - timedelta(days=days)).isoformat()
        
        # Query base
        query = supabase_db.table('pedidos').select('''
            id,
            numero_pedido,
            codigo_pedido_externo,
            situacao_pedido_id,
            canal_venda_id,
            canal_venda:canais_venda(nome, slug),
            integracoes:vinculos_integracao_pedido(plataforma, id_na_plataforma)
        ''').gte('created_at', data_inicio).order('created_at', desc=True)
        
        if canal_id:
            query = query.eq('canal_venda_id', canal_id)
            logger.info(f"Filtrando por canal_venda_id: {canal_id}")
        
        if limit:
            query = query.limit(limit)
        
        result = query.execute()
        pedidos = result.data if result.data else []
        
        logger.info(f"Encontrados {len(pedidos)} pedidos para processar")
        return pedidos
    
    def get_bling_order_id(self, pedido: Dict[str, Any]) -> Optional[int]:
        """
        Extrai o ID do pedido no Bling.
        
        Tenta obter das integrações primeiro, depois do codigo_pedido_externo.
        """
        # Tenta pegar das integrações
        integracoes = pedido.get('integracoes', [])
        for integ in integracoes:
            if integ.get('plataforma') == 'BLING':
                bling_id = integ.get('id_na_plataforma')
                if bling_id:
                    try:
                        return int(bling_id)
                    except (ValueError, TypeError):
                        pass
        
        # Fallback: codigo_pedido_externo pode ser o ID Bling
        codigo = pedido.get('codigo_pedido_externo', '')
        if codigo and codigo.isdigit():
            return int(codigo)
        
        return None
    
    def get_bling_client(self, pedido: Dict[str, Any]) -> Optional[BlingClient]:
        """
        Obtém cliente Bling configurado para o pedido.
        """
        try:
            canal_id = pedido.get('canal_venda_id')
            if not canal_id:
                logger.warning(f"Pedido {pedido['id']}: Sem canal_venda_id")
                return None

            # Buscar configuração de integração Bling
            config = integracao_canal_service.get_integration_by_canal(
                canal_id, 
                expected_module='bling'
            )
            if not config:
                logger.warning(f"Sem configuração de integração Bling para canal {canal_id}")
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
    
    def update_pedido_status(self, pedido: Dict[str, Any], bling_client: BlingClient) -> bool:
        """
        Atualiza o status de um pedido consultando o Bling.
        
        Returns:
            True se atualizou com sucesso, False se falhou
        """
        bling_id = self.get_bling_order_id(pedido)
        if not bling_id:
            logger.debug(f"Pedido {pedido['id']}: Sem ID Bling, pulando")
            return False
        
        pedido_id = pedido['id']
        status_atual = pedido.get('situacao_pedido_id')
        
        try:
            # Respeitar rate limit
            self.limiter.wait_if_needed()
            
            # Buscar dados atualizados do Bling
            logger.info(f"[{pedido_id}] Buscando pedido {bling_id} no Bling...")
            bling_order = bling_client.get_order(bling_id)
            
            if not bling_order:
                logger.warning(f"[{pedido_id}] Pedido {bling_id} não encontrado no Bling")
                self.stats['not_found'] += 1
                return False
            
            # Extrair status do Bling
            bling_status_id = bling_order.get('situacao', {}).get('id')
            if not bling_status_id:
                logger.warning(f"[{pedido_id}] Status não encontrado no Bling para pedido {bling_id}")
                return False
            
            # Mapear status Bling -> Interno
            status_interno = order_sync_service._map_bling_status(bling_status_id)
            
            logger.info(
                f"[{pedido_id}] Status Bling: {bling_status_id} -> "
                f"Status Interno: {status_interno} (atual: {status_atual})"
            )
            
            # Atualizar se mudou
            if status_atual != status_interno:
                if self.dry_run:
                    logger.info(f"[{pedido_id}] [DRY RUN] Atualizaria status de {status_atual} para {status_interno}")
                else:
                    supabase_db.table('pedidos').update({
                        'situacao_pedido_id': status_interno,
                        'updated_at': datetime.utcnow().isoformat()
                    }).eq('id', pedido_id).execute()
                    
                    # Registrar evento
                    self._register_event(
                        pedido_id, 
                        'STATUS_SYNC', 
                        f"Status atualizado via Bling: {bling_status_id} -> {status_interno}"
                    )
                
                logger.info(f"[{pedido_id}] Status atualizado para {status_interno}")
                self.stats['updated'] += 1
            else:
                logger.debug(f"[{pedido_id}] Status já está atualizado ({status_interno})")
                self.stats['unchanged'] += 1
            
            return True
            
        except Exception as e:
            logger.error(f"[{pedido_id}] Erro ao atualizar status: {e}")
            self.stats['errors'] += 1
            return False
    
    def _register_event(self, pedido_id: int, tipo: str, descricao: str):
        """Registra evento na timeline do pedido."""
        if self.dry_run:
            return
        try:
            supabase_db.table('eventos_pedido').insert({
                'pedido_id': pedido_id,
                'tipo_evento': tipo,
                'descricao': descricao,
                'created_at': datetime.utcnow().isoformat()
            }).execute()
        except Exception as e:
            logger.warning(f"Erro ao registrar evento: {e}")
    
    def run(self, days: int, limit: Optional[int] = None, 
            canal_id: Optional[int] = None):
        """
        Executa a atualização de status.
        """
        logger.info("=" * 60)
        logger.info("INICIANDO ATUALIZAÇÃO DE STATUS VIA BLING")
        logger.info("=" * 60)
        logger.info(f"Configuração: days={days}, limit={limit}, canal_id={canal_id}")
        logger.info(f"dry_run={self.dry_run}")
        logger.info("")
        
        # Buscar pedidos
        pedidos = self.get_pedidos(days=days, limit=limit, canal_id=canal_id)
        
        if not pedidos:
            logger.info("Nenhum pedido para processar")
            return
        
        self.stats['total'] = len(pedidos)
        
        # Processar cada pedido
        for i, pedido in enumerate(pedidos, 1):
            logger.info(f"\n[{i}/{len(pedidos)}] Processando pedido {pedido['id']}...")
            
            # Obter cliente Bling
            bling_client = self.get_bling_client(pedido)
            if not bling_client:
                logger.debug(f"Pedido {pedido['id']}: Sem cliente Bling, pulando")
                self.stats['errors'] += 1
                continue
            
            # Atualizar status
            self.update_pedido_status(pedido, bling_client)
            
            # Progresso
            if i % 10 == 0:
                logger.info(f"Progresso: {i}/{len(pedidos)} pedidos processados")
        
        # Relatório final
        logger.info("")
        logger.info("=" * 60)
        logger.info("RELATÓRIO FINAL")
        logger.info("=" * 60)
        logger.info(f"Total de pedidos:     {self.stats['total']}")
        logger.info(f"Atualizados:          {self.stats['updated']}")
        logger.info(f"Inalterados:           {self.stats['unchanged']}")
        logger.info(f"Não encontrados:      {self.stats['not_found']}")
        logger.info(f"Erros:                {self.stats['errors']}")
        
        if self.dry_run:
            logger.info("")
            logger.info("⚠️  DRY RUN - Nenhuma alteração foi feita no banco")


def main():
    parser = argparse.ArgumentParser(
        description='Atualizar status de pedidos via Bling'
    )
    parser.add_argument(
        '--days', '-d',
        type=int,
        required=True,
        help='Buscar pedidos dos últimos N dias (obrigatório)'
    )
    parser.add_argument(
        '--limit', '-l',
        type=int,
        default=None,
        help='Limitar quantidade de pedidos (opcional)'
    )
    parser.add_argument(
        '--canal-id',
        type=int,
        default=None,
        help='Filtrar apenas por canal de venda específico (opcional)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Apenas simula, não atualiza o banco'
    )
    
    args = parser.parse_args()
    
    # Executar atualização
    updater = BlingStatusUpdater(dry_run=args.dry_run)
    updater.run(
        days=args.days,
        limit=args.limit,
        canal_id=args.canal_id
    )


if __name__ == '__main__':
    main()
