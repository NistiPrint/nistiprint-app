import logging
from typing import List, Dict, Any, Optional
from nistiprint_shared.services.platform_api_service import platform_api_service
from nistiprint_shared.services.order_service import order_service

logger = logging.getLogger("OrderSyncService")

class OrderSyncService:
    """
    Serviço para sincronizar pedidos entre as plataformas externas e o banco unificado.
    """

    def sync_shopee_order(self, order_sn: str, instance_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Busca detalhes de um pedido na Shopee e salva no modelo unificado.
        """
        try:
            logger.info(f"Sincronizando pedido Shopee: {order_sn}")
            
            # 1. Buscar detalhes na API da Shopee via PlatformApiService
            # O driver da Shopee retorna um DTO normalizado com o campo 'raw'
            shopee_data = platform_api_service.get_order_detail([order_sn], instance_id, "shopee")
            
            if "error" in shopee_data:
                logger.error(f"Erro ao buscar pedido {order_sn} na Shopee: {shopee_data['error']}")
                return shopee_data

            # 2. Preparar dados para o OrderService
            # Mapeamento do DTO da Shopee para o OrderCore
            raw_order = shopee_data.get("raw", {})
            customer = shopee_data.get("customer", {})
            
            order_core_dto = {
                'numero_pedido': order_sn,
                'codigo_pedido_externo': order_sn,
                'origem': 'SHOPEE',
                'cliente_nome': customer.get('name'),
                'data_venda': shopee_data.get('date_created'),
                'total_pedido': shopee_data.get('total'),
                'status_unificado': self._map_shopee_status(shopee_data.get('status_original')),
                'status_original': shopee_data.get('status_original'),
                'informacoes_cliente': customer
            }

            # 3. Preparar Itens
            items_dto = []
            item_list = raw_order.get('item_list', [])
            for item in item_list:
                items_dto.append({
                    'sku_externo': item.get('item_sku'),
                    'descricao': item.get('item_name'),
                    'quantidade': item.get('model_quantity_purchased', 1),
                    'preco_unitario': item.get('model_original_price', 0),
                    'subtotal': float(item.get('model_original_price', 0)) * float(item.get('model_quantity_purchased', 1))
                })

            # 4. Salvar via OrderService
            result = order_service.upsert_order(
                order_data=order_core_dto,
                platform='SHOPEE',
                platform_order_id=order_sn,
                raw_payload=raw_order,
                items=items_dto
            )

            logger.info(f"Pedido {order_sn} sincronizado com sucesso. ID Core: {result.get('id')}")
            return result

        except Exception as e:
            logger.error(f"Falha crítica na sincronização do pedido {order_sn}: {str(e)}")
            return {"error": str(e)}

    def sync_bling_order(self, bling_order_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Salva dados vindos do Bling no modelo unificado.
        bling_order_data: Payload detalhado do pedido na API V3 do Bling.
        """
        try:
            bling_id = str(bling_order_data.get('id'))
            order_sn = bling_order_data.get('numeroLoja') # ID do Marketplace (Âncora)
            bling_numero = str(bling_order_data.get('numero')) # Número legível do Bling
            
            # Se não tem numeroLoja, usamos um prefixo no ID do Bling para o Core
            external_id = order_sn if order_sn else f"BLING-{bling_numero}"
            
            logger.info(f"Sincronizando pedido Bling: {bling_numero} (Chave: {external_id})")

            # 1. Preparar dados para o OrderService
            contact = bling_order_data.get('contato', {})
            
            order_core_dto = {
                'numero_pedido': external_id,
                'codigo_pedido_externo': external_id,
                'origem': 'BLING' if not order_sn else 'MARKETPLACE',
                'cliente_nome': contact.get('nome'),
                'data_venda': bling_order_data.get('data'),
                'total_pedido': float(bling_order_data.get('total', 0)),
                'status_unificado': self._map_bling_status(bling_order_data.get('situacao', {}).get('id')),
                'status_original': str(bling_order_data.get('situacao', {}).get('id')),
                'informacoes_cliente': contact
            }

            # 2. Preparar Itens
            items_dto = []
            for item in bling_order_data.get('itens', []):
                items_dto.append({
                    'sku_externo': item.get('codigo'),
                    'descricao': item.get('descricao'),
                    'quantidade': float(item.get('quantidade', 1)),
                    'preco_unitario': float(item.get('valor', 0)),
                    'subtotal': float(item.get('valor', 0)) * float(item.get('quantidade', 1))
                })

            # 3. Salvar via OrderService
            result = order_service.upsert_order(
                order_data=order_core_dto,
                platform='BLING',
                platform_order_id=bling_id,
                raw_payload=bling_order_data,
                items=items_dto
            )

            return result

        except Exception as e:
            logger.error(f"Erro ao sincronizar pedido Bling {bling_id}: {str(e)}")
            return {"error": str(e)}

    def _map_bling_status(self, bling_status_id: int) -> str:
        """
        Mapeia ID de situação do Bling para status unificado.
        IDs baseados no padrão Bling (pode variar por conta, mas o 15 é Em Aberto/Andamento)
        """
        mapping = {
            6: 'AGUARDANDO_PAGAMENTO', # Em aberto
            15: 'PAGO',                # Em andamento (nosso gatilho de produção)
            9: 'ENVIADO',              # Atendido
            12: 'CANCELADO',           # Cancelado
            18: 'FATURADO'             # Verificado
        }
        return mapping.get(bling_status_id, 'PENDENTE')

    def _map_shopee_status(self, shopee_status: str) -> str:
        """
        Mapeia status da Shopee para o status unificado do sistema.
        """
        mapping = {
            'UNPAID': 'AGUARDANDO_PAGAMENTO',
            'READY_TO_SHIP': 'PAGO',
            'PROCESSED': 'EM_SEPARACAO',
            'SHIPPED': 'ENVIADO',
            'COMPLETED': 'ENTREGUE',
            'IN_CANCEL': 'CANCELADO',
            'CANCELLED': 'CANCELADO',
            'INVOICED': 'FATURADO'
        }
        return mapping.get(shopee_status, 'PENDENTE')

order_sync_service = OrderSyncService()

