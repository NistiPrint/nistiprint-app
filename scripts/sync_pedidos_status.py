#!/usr/bin/env python3
"""
Script para sincronizar status dos pedidos no Bling e verificar Flex na Shopee.

Uso:
    python scripts/sync_pedidos_status.py [--days N] [--limit N] [--dry-run]

Opções:
    --days N       Buscar pedidos dos últimos N dias (default: 7)
    --limit N      Limitar a quantidade de pedidos (default: sem limite)
    --dry-run      Apenas simula, não atualiza o banco
    --flex-only    Processar apenas pedidos Shopee (para verificar Flex)
    --status-only  Processar apenas atualização de status (não verifica Flex)

Rate Limits:
    - Bling: 3 requisições/segundo (respeitado com sleep)
    - Shopee: 10 requisições/segundo (por integração)
"""

import os
import sys
import time
import logging
import argparse
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

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
        logging.FileHandler('sync_pedidos_status.log', encoding='utf-8')
    ]
)
logger = logging.getLogger('SyncPedidosStatus')

# Rate limits
BLING_RATE_LIMIT = 3  # requisições por segundo
SHOPEE_RATE_LIMIT = 10  # requisições por segundo


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


class PedidoSyncService:
    """Serviço para sincronizar status de pedidos."""
    
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.bling_limiter = RateLimiter(BLING_RATE_LIMIT)
        self.shopee_limiter = RateLimiter(SHOPEE_RATE_LIMIT)
        
        # Estatísticas
        self.stats = {
            'total': 0,
            'bling_updated': 0,
            'shopee_updated': 0,
            'errors': 0,
            'skipped': 0,
        }
    
    def get_pedidos_para_sync(self, days: int = 7, limit: Optional[int] = None, 
                               flex_only: bool = False) -> List[Dict[str, Any]]:
        """
        Busca pedidos que precisam de sincronização.
        
        Critérios:
        - Pedidos com integração Bling (tem codigo_pedido_externo numérico)
        - Pedidos dos últimos N dias
        - Opcional: apenas pedidos Shopee (para verificar Flex)
        """
        logger.info(f"Buscando pedidos dos últimos {days} dias para sincronizar...")
        
        data_inicio = (datetime.utcnow() - timedelta(days=days)).isoformat()
        
        # Query base
        query = supabase_db.table('pedidos').select('''
            id,
            numero_pedido,
            codigo_pedido_externo,
            situacao_pedido_id,
            is_flex,
            data_limite_envio,
            canal_venda_id,
            canal_venda:canais_venda(nome, slug),
            integracoes:vinculos_integracao_pedido(plataforma, id_na_plataforma, dados_brutos)
        ''').gte('created_at', data_inicio).order('created_at', desc=True)
        
        if flex_only:
            # Apenas pedidos Shopee
            query = query.eq('canal_venda_id', 1)  # Shopee
        
        if limit:
            query = query.limit(limit)
        
        result = query.execute()
        pedidos = result.data if result.data else []
        
        logger.info(f"Encontrados {len(pedidos)} pedidos para processar")
        return pedidos
    
    def _get_bling_order_id(self, pedido: Dict[str, Any]) -> Optional[int]:
        """Extrai o ID do pedido no Bling."""
        # Tenta pegar das integrações
        integracoes = pedido.get('integracoes', [])
        for integ in integracoes:
            if integ.get('plataforma') == 'BLING':
                return int(integ.get('id_na_plataforma'))
        
        # Fallback: codigo_pedido_externo pode ser o ID Bling
        codigo = pedido.get('codigo_pedido_externo', '')
        if codigo and codigo.isdigit():
            return int(codigo)
        
        return None
    
    def _is_shopee_pedido(self, pedido: Dict[str, Any]) -> bool:
        """Verifica se o pedido é da Shopee e deve ter dados buscados na API Shopee."""
        # Verificar pelo canal de venda
        canal = pedido.get('canal_venda', {})
        slug = (canal.get('slug') or '').lower()
        nome = (canal.get('nome') or '').lower()
        canal_venda_id = pedido.get('canal_venda_id')
        
        # Shopee tem canal_venda_id = 1 (ou slug/nome contendo 'shopee')
        is_shopee = (
            canal_venda_id == 1 or 
            'shopee' in slug or 
            'shopee' in nome
        )
        
        if not is_shopee:
            return False
        
        # Verificar se tem numeroLoja (código externo da Shopee)
        # O numero_pedido é o número humano do Bling, NÃO serve para API Shopee
        numero_pedido = pedido.get('numero_pedido', '')
        codigo_externo = pedido.get('codigo_pedido_externo', '')
        
        # Shopee order_sn tem formato específico (ex: 260329DGGVEK6S)
        # Não é apenas numérico como o Bling
        def is_shopee_order_sn(value: str) -> bool:
            if not value:
                return False
            # Shopee order_sn contém letras e números, geralmente 12-15 caracteres
            # Ex: 260329DGGVEK6S, 260329D31TF1K2
            return len(value) >= 10 and any(c.isalpha() for c in value)
        
        # Verificar nas integrações também
        integracoes = pedido.get('integracoes', [])
        has_shopee_integration = any(
            integ.get('plataforma') == 'SHOPEE' and integ.get('id_na_plataforma')
            for integ in integracoes
        )
        
        # É pedido Shopee válido se:
        # 1. É do canal Shopee E
        # 2. Tem numeroLoja/codigo_externo com formato de order_sn OU tem integração Shopee
        return (
            is_shopee and 
            (is_shopee_order_sn(numero_pedido) or 
             is_shopee_order_sn(codigo_externo) or 
             has_shopee_integration)
        )
    
    def _get_shopee_order_sn(self, pedido: Dict[str, Any]) -> Optional[str]:
        """Obtém o numeroLoja (Shopee Order SN) do pedido."""
        # 1. Tentar das integrações Shopee (mais confiável)
        integracoes = pedido.get('integracoes', [])
        for integ in integracoes:
            if integ.get('plataforma') == 'SHOPEE':
                order_sn = integ.get('id_na_plataforma')
                if order_sn:
                    logger.debug(f"Shopee: Order SN da integração: {order_sn}")
                    return order_sn
        
        # 2. Tentar codigo_pedido_externo (pode ser o order_sn)
        codigo_externo = pedido.get('codigo_pedido_externo', '')
        if self._is_valid_shopee_order_sn(codigo_externo):
            logger.debug(f"Shopee: Order SN do codigo_externo: {codigo_externo}")
            return codigo_externo
        
        # 3. Tentar numero_pedido (apenas se tiver formato de order_sn)
        numero_pedido = pedido.get('numero_pedido', '')
        if self._is_valid_shopee_order_sn(numero_pedido):
            logger.debug(f"Shopee: Order SN do numero_pedido: {numero_pedido}")
            return numero_pedido
        
        logger.debug(f"Shopee: Pedido {pedido.get('id')} não tem order_sn válido")
        return None
    
    def _is_valid_shopee_order_sn(self, value: str) -> bool:
        """Verifica se um valor tem formato de Shopee Order SN."""
        if not value:
            return False
        # Shopee order_sn: 10-15 caracteres, contém letras e números
        # Ex: 260329DGGVEK6S, 260329D31TF1K2
        # NÃO é apenas numérico (isso seria número Bling)
        value = str(value).strip()
        if len(value) < 10 or len(value) > 20:
            return False
        # Deve conter pelo menos uma letra
        return any(c.isalpha() for c in value)
    
    def sync_bling_status(self, pedido: Dict[str, Any], bling_client: BlingClient) -> bool:
        """
        Sincroniza status do pedido no Bling.
        
        Returns:
            True se atualizou com sucesso, False se falhou
        """
        bling_id = self._get_bling_order_id(pedido)
        if not bling_id:
            logger.debug(f"Pedido {pedido['id']}: Sem ID Bling, pulando")
            return False
        
        try:
            # Respeitar rate limit
            self.bling_limiter.wait_if_needed()
            
            # Buscar dados atualizados do Bling
            logger.info(f"Bling: Buscando pedido {bling_id}...")
            bling_order = bling_client.get_order(bling_id)
            
            if not bling_order:
                logger.warning(f"Bling: Pedido {bling_id} não encontrado")
                return False
            
            # Extrair status do Bling
            bling_status_id = bling_order.get('situacao', {}).get('id')
            if not bling_status_id:
                logger.warning(f"Bling: Status não encontrado para pedido {bling_id}")
                return False
            
            # Mapear status Bling -> Interno
            status_interno = order_sync_service._map_bling_status(bling_status_id)
            status_atual = pedido.get('situacao_pedido_id')
            
            logger.info(
                f"Bling: Pedido {bling_id} - Status Bling: {bling_status_id} -> "
                f"Status Interno: {status_interno} (atual: {status_atual})"
            )
            
            # Atualizar se mudou
            if status_atual != status_interno:
                if self.dry_run:
                    logger.info(f"[DRY RUN] Atualizaria status de {status_atual} para {status_interno}")
                else:
                    supabase_db.table('pedidos').update({
                        'situacao_pedido_id': status_interno,
                        'updated_at': datetime.utcnow().isoformat()
                    }).eq('id', pedido['id']).execute()
                    
                    # Registrar evento
                    self._register_event(pedido['id'], 'STATUS_SYNC', 
                                        f"Status atualizado via Bling: {bling_status_id} -> {status_interno}")
                
                logger.info(f"Bling: Status atualizado para {status_interno}")
            else:
                logger.debug(f"Bling: Status já está atualizado ({status_interno})")
            
            return True
            
        except Exception as e:
            logger.error(f"Bling: Erro ao sincronizar pedido {bling_id}: {e}")
            return False
    
    def sync_shopee_flex(self, pedido: Dict[str, Any], instance_id: str, order_sn: str) -> bool:
        """
        Sincroniza dados Flex da Shopee.
        
        Args:
            pedido: Dados do pedido
            instance_id: ID da instância de integração Shopee
            order_sn: Shopee Order SN (numeroLoja)
        
        Returns:
            True se atualizou com sucesso, False se falhou
        """
        # order_sn já é passado como parâmetro, não precisa extrair
        if not order_sn:
            logger.debug(f"Shopee: order_sn não fornecido, pulando")
            return False
        
        try:
            # Respeitar rate limit
            self.shopee_limiter.wait_if_needed()
            
            # Buscar dados da Shopee USANDO O DRIVER DIRETAMENTE
            logger.info(f"Shopee: Buscando pedido {order_sn}...")
            
            # Importar driver da Shopee diretamente
            from nistiprint_shared.services.platform_drivers.shopee import get_order_detail as shopee_get_order_detail
            from nistiprint_shared.services.installed_integration_service import installed_integration_service
            
            # Obter integração completa
            integration_obj = installed_integration_service.get_installed_by_id(instance_id)
            if not integration_obj:
                logger.warning(f"Shopee: Integração {instance_id} não encontrada")
                return False
            
            integration = integration_obj.to_dict()
            integration['id'] = instance_id
            
            # Chamar driver da Shopee diretamente
            shopee_data = shopee_get_order_detail(integration, [order_sn])
            
            if shopee_data.get("error"):
                logger.warning(f"Shopee: Erro ao buscar {order_sn}: {shopee_data['error']}")
                return False
            
            raw_order = shopee_data.get("raw", {})
            
            # Verificar se é Flex
            shipping_carrier = raw_order.get('shipping_carrier', '')
            carrier_lower = shipping_carrier.lower()
            
            # Nova regra: se shipping_carrier contém 'entrega rapida' ou 'entrega rápida', é flex
            is_flex = 'entrega rapida' in carrier_lower or 'entrega rápida' in carrier_lower
            
            logger.info(f"Shopee: Pedido {order_sn} - shipping_carrier: {shipping_carrier}")
            logger.info(f"Shopee: Pedido {order_sn} - Flex classification: {is_flex}")
            
            # Extrair ship_by_date
            ship_by_date_raw = raw_order.get('ship_by_date')
            data_limite_envio = None
            if ship_by_date_raw:
                from datetime import timezone
                data_limite_envio = datetime.fromtimestamp(
                    ship_by_date_raw, tz=timezone.utc
                ).isoformat()
            
            is_flex_atual = pedido.get('is_flex', False)
            
            logger.info(
                f"Shopee: Pedido {order_sn} - Flex: {is_flex} (atual: {is_flex_atual})"
            )
            
            # Atualizar se mudou
            if is_flex != is_flex_atual or (data_limite_envio and not pedido.get('data_limite_envio')):
                update_data = {}
                
                if is_flex != is_flex_atual:
                    update_data['is_flex'] = is_flex
                
                if data_limite_envio and not pedido.get('data_limite_envio'):
                    update_data['data_limite_envio'] = data_limite_envio
                
                update_data['updated_at'] = datetime.utcnow().isoformat()
                
                if self.dry_run:
                    logger.info(f"[DRY RUN] Atualizaria: {update_data}")
                else:
                    supabase_db.table('pedidos').update(update_data)\
                        .eq('id', pedido['id']).execute()
                    
                    if is_flex:
                        self._register_event(pedido['id'], 'FLEX_SYNC', 
                                            f"Pedido Flex detectado via Shopee: {shipping_carrier}")
                
                logger.info(f"Shopee: Dados atualizados (Flex: {is_flex})")
            else:
                logger.debug(f"Shopee: Dados já estão atualizados")
            
            return True
            
        except Exception as e:
            logger.error(f"Shopee: Erro ao sincronizar {order_sn}: {e}")
            return False
    
    def _register_event(self, pedido_id: int, tipo: str, descricao: str):
        """Registra evento na timeline do pedido."""
        try:
            supabase_db.table('eventos_pedido').insert({
                'pedido_id': pedido_id,
                'tipo_evento': tipo,
                'descricao': descricao,
                'created_at': datetime.utcnow().isoformat()
            }).execute()
        except Exception as e:
            logger.warning(f"Erro ao registrar evento: {e}")
    
    def get_bling_client_for_pedido(self, pedido: Dict[str, Any]) -> Optional[BlingClient]:
        """Obtém cliente Bling configurado para o pedido."""
        try:
            canal_id = pedido.get('canal_venda_id')
            if not canal_id:
                return None

            # Buscar configuração de integração Bling
            config = integracao_canal_service.get_integration_by_canal(canal_id, expected_module='bling')
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
    
    def get_shopee_instance_id(self, pedido: Dict[str, Any]) -> Optional[str]:
        """Obtém o ID da instância Shopee para o pedido."""
        try:
            canal_id = pedido.get('canal_venda_id')
            if not canal_id:
                logger.debug(f"Pedido {pedido.get('id')}: Sem canal_venda_id")
                return None

            # Usar novo método com validação explícita do módulo Shopee
            config = integracao_canal_service.get_integration_by_canal(
                canal_id, 
                expected_module='shopee'
            )
            
            if config and config.get('integration_id'):
                logger.info(f"Shopee: Usando integração ID {config['integration_id']} (via vínculo do canal)")
                return str(config['integration_id'])

            # Fallback: buscar por module_id (caso não haja vínculo configurado)
            from nistiprint_shared.services.installed_integration_service import installed_integration_service

            shopee_integrations = installed_integration_service.get_installed_by_module('shopee')
            if shopee_integrations:
                for shopee_integ in shopee_integrations:
                    if shopee_integ.is_active and shopee_integ.config:
                        config_dict = shopee_integ.config if isinstance(shopee_integ.config, dict) else {}
                        if config_dict.get('shop_id') or config_dict.get('partner_id'):
                            logger.info(f"Shopee: Usando integração ID {shopee_integ.id} (fallback por módulo)")
                            return str(shopee_integ.id)

            logger.debug(f"Pedido {pedido.get('id')}: Sem integração Shopee encontrada")
            return None

        except Exception as e:
            logger.error(f"Erro ao obter instância Shopee: {e}")
            return None
    
    def _validate_shopee_integration(self, instance_id: str) -> bool:
        """
        Valida se a integração Shopee está configurada corretamente.

        Returns:
            True se estiver válida, False caso contrário
        """
        import json

        try:
            from nistiprint_shared.services.installed_integration_service import installed_integration_service

            integration_obj = installed_integration_service.get_installed_by_id(instance_id)
            if not integration_obj:
                logger.warning(f"Shopee: Integração {instance_id} não encontrada no banco")
                return False

            integration = integration_obj.to_dict()

            # Parse config: pode vir como string JSON ou dict
            config_raw = integration.get('config', {})
            if isinstance(config_raw, str):
                try:
                    config = json.loads(config_raw)
                except (json.JSONDecodeError, TypeError):
                    logger.error(f"Shopee: Config é string mas não é JSON válido")
                    config = {}
            else:
                config = config_raw if isinstance(config_raw, dict) else {}

            credentials = integration.get('credentials', {})

            # Shopee: partner_id, partner_key, shop_id estão em config (JSON)
            # access_token é coluna explícita (não está em credentials)
            partner_id = config.get('partner_id')
            partner_key = config.get('partner_key')
            shop_id = config.get('shop_id')
            access_token = integration.get('access_token')  # Coluna explícita, não em credentials

            missing = []
            if not partner_id:
                missing.append('partner_id (em config)')
            if not partner_key:
                missing.append('partner_key (em config)')
            if not shop_id:
                missing.append('shop_id (em config)')
            if not access_token:
                missing.append('access_token (coluna explícita)')

            if missing:
                logger.error(
                    f"Shopee: Integração {instance_id} incompleta. Faltam: {', '.join(missing)}"
                )
                logger.error(
                    f"Shopee: Para corrigir, acesse /admin/integracoes e re-autorize a integração Shopee"
                )
                return False

            logger.info(f"Shopee: Integração {instance_id} válida (shop_id={shop_id})")
            return True

        except Exception as e:
            logger.error(f"Erro ao validar integração Shopee: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _get_module_id_for_pedido(self, pedido: Dict[str, Any]) -> str:
        """Determina o module_id correto para o pedido."""
        canal = pedido.get('canal_venda', {})
        slug = (canal.get('slug') or '').lower()
        nome = (canal.get('nome') or '').lower()
        
        # Mapear para module_id suportado
        if 'shopee' in slug or 'shopee' in nome:
            return 'shopee'
        elif 'mercadolivre' in slug or 'mercado livre' in nome:
            return 'mercadolivre'
        elif 'amazon' in slug:
            return 'amazon'
        elif 'shein' in slug:
            return 'shein'
        elif 'tiktok' in slug:
            return 'tiktok'
        
        # Default: shopee
        return 'shopee'
    
    def run(self, days: int = 7, limit: Optional[int] = None,
            flex_only: bool = False, status_only: bool = False):
        """
        Executa a sincronização.
        """
        logger.info("=" * 60)
        logger.info("INICIANDO SINCRONIZAÇÃO DE PEDIDOS")
        logger.info("=" * 60)
        logger.info(f"Configuração: days={days}, limit={limit}, dry_run={self.dry_run}")
        logger.info(f"flex_only={flex_only}, status_only={status_only}")
        logger.info("")
        
        # Buscar pedidos
        pedidos = self.get_pedidos_para_sync(days=days, limit=limit, flex_only=flex_only)
        
        if not pedidos:
            logger.info("Nenhum pedido para processar")
            return
        
        self.stats['total'] = len(pedidos)
        
        # Processar cada pedido
        for i, pedido in enumerate(pedidos, 1):
            logger.info(f"\n[{i}/{len(pedidos)}] Processando pedido {pedido['id']}...")
            
            try:
                # 1. Sincronizar status do Bling (todos os pedidos com Bling)
                if not status_only:
                    bling_client = self.get_bling_client_for_pedido(pedido)
                    if bling_client:
                        if self.sync_bling_status(pedido, bling_client):
                            self.stats['bling_updated'] += 1
                    else:
                        self.stats['skipped'] += 1
                        logger.debug("Pulando Bling (sem cliente)")
                
                # 2. Sincronizar Flex da Shopee (APENAS se for pedido Shopee válido)
                if not flex_only:
                    # Verificar se é pedido Shopee válido antes de tentar buscar
                    if self._is_shopee_pedido(pedido):
                        # Obter order_sn válido
                        order_sn = self._get_shopee_order_sn(pedido)
                        
                        if order_sn:
                            instance_id = self.get_shopee_instance_id(pedido)
                            if instance_id:
                                # Validar integração antes de tentar buscar
                                if self._validate_shopee_integration(instance_id):
                                    logger.info(f"Shopee: Processando order_sn {order_sn}...")
                                    if self.sync_shopee_flex(pedido, instance_id, order_sn):
                                        self.stats['shopee_updated'] += 1
                                else:
                                    logger.warning(
                                        f"Shopee: Pulando order_sn {order_sn} - integração {instance_id} "
                                        f"incompleta. Verifique em /admin/integracoes"
                                    )
                                    self.stats['errors'] += 1
                            else:
                                logger.debug(f"Shopee: Sem instance_id para pedido {pedido['id']}")
                        else:
                            logger.info(f"Shopee: Pulando pedido {pedido['id']} - não tem order_sn válido (não é pedido Shopee ou não tem numeroLoja)")
                    else:
                        logger.debug(f"Shopee: Pulando pedido {pedido['id']} - não é pedido Shopee")
                
            except Exception as e:
                self.stats['errors'] += 1
                logger.error(f"Erro ao processar pedido {pedido['id']}: {e}", exc_info=True)
            
            # Progresso
            if i % 10 == 0:
                logger.info(f"Progresso: {i}/{len(pedidos)} pedidos processados")
        
        # Relatório final
        logger.info("")
        logger.info("=" * 60)
        logger.info("RELATÓRIO FINAL")
        logger.info("=" * 60)
        logger.info(f"Total de pedidos:     {self.stats['total']}")
        logger.info(f"Bling atualizados:    {self.stats['bling_updated']}")
        logger.info(f"Shopee atualizados:   {self.stats['shopee_updated']}")
        logger.info(f"Erros:                {self.stats['errors']}")
        logger.info(f"Pulados:              {self.stats['skipped']}")
        
        if self.dry_run:
            logger.info("")
            logger.info("⚠️  DRY RUN - Nenhuma alteração foi feita no banco")


def main():
    parser = argparse.ArgumentParser(
        description='Sincronizar status de pedidos no Bling e Flex na Shopee'
    )
    parser.add_argument(
        '--days', '-d',
        type=int,
        default=7,
        help='Buscar pedidos dos últimos N dias (default: 7)'
    )
    parser.add_argument(
        '--limit', '-l',
        type=int,
        default=None,
        help='Limitar quantidade de pedidos (default: sem limite)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Apenas simula, não atualiza o banco'
    )
    parser.add_argument(
        '--flex-only',
        action='store_true',
        help='Processar apenas pedidos Shopee (para verificar Flex)'
    )
    parser.add_argument(
        '--status-only',
        action='store_true',
        help='Apenas atualizar status (não verifica Flex)'
    )
    
    args = parser.parse_args()
    
    # Executar sync
    sync_service = PedidoSyncService(dry_run=args.dry_run)
    sync_service.run(
        days=args.days,
        limit=args.limit,
        flex_only=args.flex_only,
        status_only=args.status_only
    )


if __name__ == '__main__':
    main()
