import logging
import json
import unicodedata
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from nistiprint_shared.services.platform_api_service import platform_api_service
from nistiprint_shared.services.order_service import order_service
from nistiprint_shared.database.supabase_db_service import supabase_db

logger = logging.getLogger("OrderSyncService")

def normalize_text(text: str) -> str:
    """Remove acentos e converte para maiúsculas para facilitar comparação."""
    if not text:
        return ""
    text = str(text)
    nfkd_form = unicodedata.normalize('NFKD', text)
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)]).upper().strip()

class OrderSyncService:
    """
    Serviço para sincronizar pedidos entre as plataformas externas e o banco unificado.
    Normaliza dados relacionais para facilitar consultas e dashboards.
    """

    def sync_shopee_order(self, order_sn: str, instance_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Busca detalhes de um pedido na Shopee e salva no modelo unificado.
        """
        try:
            logger.info(f"Sincronizando pedido Shopee: {order_sn}")
            
            shopee_data = platform_api_service.get_order_detail([order_sn], instance_id, "shopee")
            
            if "error" in shopee_data:
                logger.error(f"Erro ao buscar pedido {order_sn} na Shopee: {shopee_data['error']}")
                return shopee_data

            # 1. Extração Inteligente Shopee
            raw_order = shopee_data.get("raw", {})
            recipient = raw_order.get('recipient_address', {})
            
            # Nome do cliente: Prioridade para o nome de entrega (Real)
            cliente_nome = recipient.get('name') or raw_order.get('buyer_username')
            cliente_telefone = recipient.get('phone')
            
            # Data real de envio (ship_by_date)
            ship_by_date_raw = raw_order.get('ship_by_date')
            data_prevista_entrega = None
            if ship_by_date_raw:
                data_prevista_entrega = datetime.fromtimestamp(ship_by_date_raw, tz=timezone.utc).isoformat()
            
            # Identificação FLEX (Foco: Entrega Direta / SPX Express)
            shipping_carrier = raw_order.get('shipping_carrier', '')
            norm_carrier = normalize_text(shipping_carrier)
            # Shopee Flex costuma ser "SPX Entrega Rápida" ou similar
            is_flex = any(x in norm_carrier for x in ["ENTREGA RAPIDA", "DIRETA", "FLEX", "SPX EXPRESS"])
            
            order_core_dto = {
                'numero_pedido': order_sn,
                'codigo_pedido_externo': order_sn,
                'origem': 'SHOPEE',
                'cliente_nome': cliente_nome,
                'cliente_telefone': cliente_telefone,
                'is_flex': is_flex,
                'data_prevista_entrega': data_prevista_entrega,
                'servico_logistico': shipping_carrier,
                'data_venda': shopee_data.get('date_created'),
                'total_pedido': shopee_data.get('total'),
                'situacao_pedido_id': self._map_shopee_status(shopee_data.get('status_original')),
                'status_original': shopee_data.get('status_original'),
                'informacoes_cliente': {
                    'buyer_username': raw_order.get('buyer_username'),
                    'shipping_carrier': shipping_carrier,
                    'is_flex': is_flex
                }
            }

            # 2. Preparar Itens
            items_dto = []
            for item in raw_order.get('item_list', []):
                items_dto.append({
                    'sku_externo': item.get('item_sku') or item.get('model_sku'),
                    'descricao': item.get('item_name'),
                    'quantidade': item.get('model_quantity_purchased', 1),
                    'preco_unitario': item.get('model_original_price', 0),
                    'subtotal': float(item.get('model_original_price', 0)) * float(item.get('model_quantity_purchased', 1))
                })

            # 3. Salvar
            result = order_service.upsert_order(
                order_data=order_core_dto,
                platform='SHOPEE',
                platform_order_id=order_sn,
                raw_payload=raw_order,
                items=items_dto
            )

            # Manter compatibilidade com tabela legado se existir
            self._save_to_shopee_table(order_sn, raw_order, data_prevista_entrega)

            return result

        except Exception as e:
            logger.error(f"Falha na sincronização Shopee {order_sn}: {str(e)}")
            return {"error": str(e)}

    def sync_bling_order(self, bling_order_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Salva dados detalhados vindos do Bling no modelo unificado.
        """
        try:
            bling_id = str(bling_order_data.get('id'))
            order_sn = bling_order_data.get('numeroLoja') 
            bling_numero = str(bling_order_data.get('numero'))
            external_id = order_sn if order_sn else f"BLING-{bling_numero}"
            
            # 1. Extração Inteligente Bling
            contato = bling_order_data.get('contato', {})
            cliente_nome = contato.get('nome')
            
            # Transporte e Flex
            transporte = bling_order_data.get('transporte', {})
            volumes = transporte.get('volumes', [])
            servico_logistico = ""
            if volumes and len(volumes) > 0:
                servico_logistico = volumes[0].get('servico', '')
            
            norm_servico = normalize_text(servico_logistico)
            # Bling Flex (Foco pedido pelo usuário: Entrega Direta)
            is_flex = any(x in norm_servico for x in ["ENTREGA DIRETA", "DIRETA", "LOGGI", "RAPIDA", "FLEX"])
            
            data_prevista = bling_order_data.get('dataPrevista')
            
            order_core_dto = {
                'numero_pedido': bling_numero,
                'codigo_pedido_externo': external_id,
                'origem': 'BLING' if not order_sn else 'MARKETPLACE',
                'cliente_nome': cliente_nome,
                'cliente_telefone': contato.get('telefone') or contato.get('celular'),
                'cliente_email': contato.get('email'),
                'is_flex': is_flex,
                'data_prevista_entrega': data_prevista,
                'servico_logistico': servico_logistico,
                'data_venda': bling_order_data.get('data'),
                'total_pedido': float(bling_order_data.get('total', 0)),
                'situacao_pedido_id': self._map_bling_status(bling_order_data.get('situacao', {}).get('id')),
                'status_original': str(bling_order_data.get('situacao', {}).get('id')),
                'informacoes_cliente': {
                    'servico_logistico': servico_logistico,
                    'is_flex': is_flex,
                    'contato_id': contato.get('id')
                }
            }

            items_dto = []
            for item in bling_order_data.get('itens', []):
                items_dto.append({
                    'sku_externo': item.get('codigo'),
                    'descricao': item.get('descricao'),
                    'quantidade': float(item.get('quantidade', 1)),
                    'preco_unitario': float(item.get('valor', 0)),
                    'subtotal': float(item.get('valor', 0)) * float(item.get('quantidade', 1))
                })

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

    def _save_to_shopee_table(self, order_sn: str, raw_order: dict, data_envio: str):
        try:
            payload = {
                'codigo_pedido': order_sn,
                'status_pedido': raw_order.get('order_status'),
                'valor_total': float(raw_order.get('total_amount', 0)),
                'data_criacao': datetime.fromtimestamp(raw_order.get('create_time'), tz=timezone.utc).isoformat() if raw_order.get('create_time') else None,
                'data_envio': data_envio,
                'endereco_entrega': raw_order.get('recipient_address'),
                'itens_pedido': raw_order.get('item_list'),
                'informacoes_comprador': {
                    'user_id': raw_order.get('buyer_user_id'),
                    'username': raw_order.get('buyer_username')
                },
                'updated_at': datetime.utcnow().isoformat()
            }
            res = supabase_db.table('pedidos_shopee').select('id').eq('codigo_pedido', order_sn).execute()
            if res.data:
                supabase_db.table('pedidos_shopee').update(payload).eq('id', res.data[0]['id']).execute()
            else:
                payload['created_at'] = datetime.utcnow().isoformat()
                supabase_db.table('pedidos_shopee').insert(payload).execute()
        except: pass

    def _map_bling_status(self, bling_status_id: int) -> int:
        mapping = {6: 1, 15: 2, 9: 5, 12: 7, 18: 5}
        return mapping.get(bling_status_id, 1)

    def _map_shopee_status(self, shopee_status: str) -> int:
        mapping = {
            'UNPAID': 1, 'READY_TO_SHIP': 2, 'PROCESSED': 3,
            'SHIPPED': 5, 'COMPLETED': 6, 'IN_CANCEL': 7,
            'CANCELLED': 7, 'INVOICED': 5
        }
        return mapping.get(shopee_status, 1)

order_sync_service = OrderSyncService()
