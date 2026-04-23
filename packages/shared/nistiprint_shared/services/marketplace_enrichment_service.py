from typing import Optional, Dict, Any
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.platform_api_service import platform_api_service
import logging

logger = logging.getLogger(__name__)

class MarketplaceEnrichmentService:
    """
    Serviço para enriquecer pedidos com dados de marketplaces.
    Busca dados adicionais do marketplace (Shopee, Amazon, etc) e os salva em vinculos_integracao_pedido.
    """

    def __init__(self):
        self.erp_links_table = supabase_db.table('erp_marketplace_links')
        self.vinculos_table = supabase_db.table('vinculos_integracao_pedido')
        self.installed_integrations_table = supabase_db.table('installed_integrations')
        self.pedidos_table = supabase_db.table('pedidos')

    def get_marketplace_link(self, erp_integration_id: int, erp_store_id: str) -> Optional[Dict[str, Any]]:
        """
        Busca vínculo entre integração ERP e marketplace.
        
        Args:
            erp_integration_id: ID da integração Bling
            erp_store_id: ID da loja no Bling (ex: 204047801)
        
        Returns:
            Dados do vínculo ou None se não encontrado
        """
        try:
            response = self.erp_links_table.select("*") \
                .eq('erp_integration_id', erp_integration_id) \
                .eq('erp_store_id', erp_store_id) \
                .execute()
            
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            logger.error(f"Erro ao buscar marketplace link: {e}")
            return None

    def get_marketplace_integration(self, marketplace_integration_id: int) -> Optional[Dict[str, Any]]:
        """
        Busca detalhes da integração do marketplace.
        
        Args:
            marketplace_integration_id: ID da integração do marketplace
        
        Returns:
            Dados da integração ou None se não encontrado
        """
        try:
            response = self.installed_integrations_table.select("*") \
                .eq('id', marketplace_integration_id) \
                .execute()
            
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            logger.error(f"Erro ao buscar marketplace integration: {e}")
            return None

    def enrich_order_from_marketplace(
        self, 
        pedido_id: int, 
        codigo_pedido_externo: str,
        erp_integration_id: int,
        erp_store_id: str
    ) -> bool:
        """
        Enriquece um pedido com dados do marketplace.
        
        Fluxo:
        1. Busca vínculo ERP-Marketplace via erp_marketplace_links
        2. Se marketplace_integration_id existe, busca dados do marketplace
        3. Salva dados em vinculos_integracao_pedido com plataforma correta
        
        Args:
            pedido_id: ID do pedido na tabela pedidos
            codigo_pedido_externo: Código do pedido externo (order_sn, etc)
            erp_integration_id: ID da integração Bling
            erp_store_id: ID da loja no Bling
        
        Returns:
            True se enriquecimento foi bem-sucedido, False caso contrário
        """
        try:
            # 1. Buscar vínculo ERP-Marketplace
            link = self.get_marketplace_link(erp_integration_id, erp_store_id)
            
            if not link:
                logger.warning(f"Nenhum marketplace link encontrado para erp_integration_id={erp_integration_id}, erp_store_id={erp_store_id}")
                return False
            
            marketplace_integration_id = link.get('marketplace_integration_id')
            
            if not marketplace_integration_id:
                logger.info(f"Marketplace não instalado para erp_store_id={erp_store_id}. Pulando enriquecimento.")
                return False
            
            # 2. Buscar detalhes da integração do marketplace
            marketplace_integration = self.get_marketplace_integration(marketplace_integration_id)
            
            if not marketplace_integration:
                logger.warning(f"Integração do marketplace {marketplace_integration_id} não encontrada")
                return False
            
            platform_name = marketplace_integration.get('module_id', '').upper()
            
            # 3. Buscar dados do marketplace (por enquanto, apenas Shopee)
            if platform_name == 'SHOPEE':
                return self._enrich_from_shopee(
                    pedido_id, 
                    codigo_pedido_externo,
                    marketplace_integration_id,
                    marketplace_integration
                )
            else:
                logger.info(f"Enriquecimento para plataforma {platform_name} ainda não implementado")
                return False
                
        except Exception as e:
            logger.error(f"Erro ao enriquecer pedido {pedido_id} do marketplace: {e}")
            return False

    def _enrich_from_shopee(
        self,
        pedido_id: int,
        codigo_pedido_externo: str,
        marketplace_integration_id: int,
        marketplace_integration: Dict[str, Any]
    ) -> bool:
        """
        Enriquece pedido com dados da Shopee chamando a API diretamente.

        Args:
            pedido_id: ID do pedido
            codigo_pedido_externo: Order SN da Shopee
            marketplace_integration_id: ID da integração Shopee
            marketplace_integration: Dados da integração Shopee

        Returns:
            True se bem-sucedido
        """
        try:
            # Chamar API Shopee diretamente para buscar dados atualizados
            # Use 'id' from installed_integrations as instance_id
            instance_id = marketplace_integration.get('id')
            if not instance_id:
                logger.warning(f"Instance ID não encontrado para integração {marketplace_integration_id}")
                return False

            logger.info(f"Buscando dados da API Shopee para pedido {codigo_pedido_externo} (instance_id={instance_id})")
            shopee_data = platform_api_service.get_order_detail([codigo_pedido_externo], instance_id, "shopee")

            if "error" in shopee_data and shopee_data["error"]:
                logger.error(f"Erro na API Shopee para {codigo_pedido_externo}: {shopee_data['error']}")
                return False

            raw_order = shopee_data.get("raw", {})
            buyer_username = raw_order.get('buyer_username')
            shipping_carrier = raw_order.get('shipping_carrier')
            message_to_seller = raw_order.get('message_to_seller')

            logger.info(f"Dados da API Shopee recebidos: buyer_username={buyer_username}, shipping_carrier={shipping_carrier}, message_to_seller={message_to_seller}")

            # Preparar dados brutos para vinculos_integracao_pedido
            raw_payload = {
                'buyer_username': buyer_username,
                'shipping_carrier': shipping_carrier,
                'message_to_seller': message_to_seller,
                'recipient_address': raw_order.get('recipient_address', {}),
                'status_pedido': shopee_data.get('status_original'),
                'raw_order': raw_order
            }

            # Salvar em vinculos_integracao_pedido
            vinculo = {
                'pedido_id': pedido_id,
                'plataforma': 'SHOPEE',
                'id_na_plataforma': codigo_pedido_externo,
                'status_na_plataforma': shopee_data.get('status_original'),
                'integration_id': marketplace_integration_id,
                'dados_brutos': raw_payload,
                'last_synced_at': None
            }

            # Upsert no vinculos_integracao_pedido
            self.vinculos_table.upsert(vinculo, on_conflict='pedido_id,plataforma').execute()

            # Atualizar colunas explícitas na tabela pedidos
            update_pedido = {
                'buyer_username': buyer_username,
                'marketplace_order_id': codigo_pedido_externo,
                'shipping_carrier': shipping_carrier,
                'message_to_seller': message_to_seller,
                'contact_marketplace_id': None
            }
            self.pedidos_table.update(update_pedido).eq('id', pedido_id).execute()

            logger.info(f"Pedido {pedido_id} enriquecido com dados da API Shopee: buyer_username={buyer_username}")
            return True

        except Exception as e:
            logger.error(f"Erro ao enriquecer pedido {pedido_id} da Shopee: {e}")
            return False

# Instância global
marketplace_enrichment_service = MarketplaceEnrichmentService()
