import logging
import json
import unicodedata
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from nistiprint_shared.services.platform_api_service import platform_api_service
from nistiprint_shared.services.order_service import order_service
from nistiprint_shared.services.integracao_canal_service import integracao_canal_service
from nistiprint_shared.database.supabase_db_service import supabase_db

logger = logging.getLogger("OrderSyncService")

def normalize_text(text: str) -> str:
    """Remove acentos e converte para maiúsculas para facilitar comparação."""
    if not text:
        return ""
    text = str(text)
    nfkd_form = unicodedata.normalize('NFKD', text)
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)]).upper().strip()

def clean_date(date_str: Any) -> Optional[str]:
    """Valida e limpa strings de data para evitar erros no Postgres (ex: '0000-00-00')."""
    if not date_str or not isinstance(date_str, str):
        return None
    if date_str.startswith('0000') or '0000-00-00' in date_str:
        return None
    return date_str

def safe_float(value: Any, default: float = 0.0) -> float:
    """Converte valores de forma segura, tratando se vierem como dicionários da API."""
    if value is None: return default
    if isinstance(value, (int, float)): return float(value)
    if isinstance(value, dict):
        # Tenta pegar campos comuns de valor em objetos (Bling v3 style)
        for k in ['valor', 'total', 'quantidade']:
            if k in value: return safe_float(value[k], default)
        return default
    try:
        return float(str(value).replace(',', '.'))
    except:
        return default

class OrderSyncService:
    """
    Serviço centralizado para sincronizar e normalizar pedidos.
    Garante que dados relacionais (nome, telefone, flex, canal) sejam persistidos em colunas próprias.
    """

    def _get_canal_id_by_loja_id(self, loja_id: int) -> Optional[int]:
        """
        Mapeia o loja_id do Bling para o ID do canal_venda interno.
        Usa o novo serviço de configuração de vínculos.
        """
        if not loja_id:
            return None
        
        try:
            # Usar o novo serviço de configuração dinâmica
            config = integracao_canal_service.get_canal_by_bling_loja_id(loja_id)
            if config:
                return config['canal_venda_id']
            
            # Fallback: buscar na tabela canais_venda (legado)
            res = supabase_db.table('canais_venda').select('id').eq('conta_bling_id', str(loja_id)).execute()
            if res.data:
                return res.data[0]['id']
        except Exception as e:
            logger.warning(f"Erro ao resolver canal para loja_id {loja_id}: {e}")
        
        return None

    def sync_shopee_order(self, order_sn: str, instance_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Sincroniza pedido Shopee buscando detalhes na API da Shopee.
        """
        try:
            logger.info(f"Sincronizando pedido Shopee: {order_sn}")
            shopee_data = platform_api_service.get_order_detail([order_sn], instance_id, "shopee")
            
            if "error" in shopee_data and shopee_data["error"]:
                logger.error(f"Erro Shopee {order_sn}: {shopee_data['error']}")
                return shopee_data

            raw_order = shopee_data.get("raw", {})
            recipient = raw_order.get('recipient_address', {})
            
            # Extração Relacional
            cliente_nome = recipient.get('name') or raw_order.get('buyer_username')
            cliente_telefone = recipient.get('phone')
            
            # Data real de envio (ship_by_date)
            ship_by_date_raw = raw_order.get('ship_by_date')
            data_prevista = datetime.fromtimestamp(ship_by_date_raw, tz=timezone.utc).isoformat() if ship_by_date_raw else None
            data_prevista = clean_date(data_prevista)

            # Identificação FLEX (ESTRITA: 'entrega rápida')
            shipping_carrier = raw_order.get('shipping_carrier', '')
            norm_carrier = normalize_text(shipping_carrier)
            is_flex = "ENTREGA RAPIDA" in norm_carrier

            # Upsert
            # Para pedidos Shopee puros (sem Bling), usar order_sn como numero_pedido e codigo_pedido_externo
            # Se já existir vínculo Bling, o numero_pedido já estará correto (vindo do Bling)
            # Dados do cliente NÃO são enviados pois o Bling é a fonte prioritária
            order_core_dto = {
                'numero_pedido': order_sn,  # Será sobrescrito se existir Bling
                'codigo_pedido_externo': order_sn,
                'origem': 'SHOPEE',
                'is_flex': is_flex,
                'data_limite_envio': data_prevista,
                'servico_logistico': shipping_carrier,
                'data_venda': clean_date(shopee_data.get('date_created')),
                'total_pedido': safe_float(shopee_data.get('total')),
                'situacao_pedido_id': self._map_shopee_status(shopee_data.get('status_original')),
                'status_original': shopee_data.get('status_original'),
                'informacoes_cliente': {
                    'buyer_username': raw_order.get('buyer_username'),
                    'shipping_carrier': shipping_carrier,
                    'full_address': recipient.get('full_address')
                }
            }

            # Itens
            items_dto = []
            for item in raw_order.get('item_list', []):
                items_dto.append({
                    'sku_externo': item.get('item_sku') or item.get('model_sku'),
                    'descricao': item.get('item_name'),
                    'quantidade': item.get('model_quantity_purchased', 1),
                    'preco_unitario': item.get('model_original_price', 0),
                    'subtotal': float(item.get('model_original_price', 0)) * float(item.get('model_quantity_purchased', 1))
                })

            # Upsert
            # Resolver channel_id dinamicamente baseado na configuração
            # Fallback para ID 1 (Shopee) se não houver configuração
            channel_id = 1  # Default Shopee
            config = integracao_canal_service.get_canal_by_bling_loja_id(204047801)  # Shopee antiga como referência
            if config:
                channel_id = config['canal_venda_id']
            
            result = order_service.upsert_order(
                order_data=order_core_dto,
                platform='SHOPEE',
                platform_order_id=order_sn,
                raw_payload=raw_order,
                items=items_dto,
                channel_id=channel_id
            )
            
            # Legacy Sync
            self._save_to_shopee_table(order_sn, raw_order, data_prevista)
            return result
        except Exception as e:
            logger.error(f"Erro sync_shopee_order: {e}")
            return {"error": str(e)}

    def sync_bling_order(self, bling_order_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sincroniza pedido vindo do Bling (Webhook ou Importação).
        """
        try:
            bling_id = str(bling_order_data.get('id'))
            order_sn = bling_order_data.get('numeroLoja') 
            bling_numero = str(bling_order_data.get('numero'))
            external_id = order_sn if order_sn else f"BLING-{bling_numero}"
            
            # Extração Relacional
            contato = bling_order_data.get('contato', {})
            transporte = bling_order_data.get('transporte', {})
            volumes = transporte.get('volumes', [])
            servico_logistico = volumes[0].get('servico', '') if volumes else ""
            
            norm_servico = normalize_text(servico_logistico)
            is_flex = "ENTREGA RAPIDA" in norm_servico
            
            loja_id = bling_order_data.get('loja', {}).get('id')
            canal_id = self._get_canal_id_by_loja_id(loja_id)
            
            order_core_dto = {
                'numero_pedido': bling_numero,
                'codigo_pedido_externo': external_id,
                'origem': 'MARKETPLACE' if order_sn else 'BLING',
                'cliente_nome': contato.get('nome'),
                'cliente_telefone': contato.get('telefone') or contato.get('celular'),
                'cliente_email': contato.get('email'),
                'is_flex': is_flex,
                'data_limite_envio': clean_date(bling_order_data.get('dataPrevista')),
                'servico_logistico': servico_logistico,
                'data_venda': clean_date(bling_order_data.get('data')),
                'total_pedido': safe_float(bling_order_data.get('total')),
                'situacao_pedido_id': self._map_bling_status(bling_order_data.get('situacao', {}).get('id')),
                'status_original': str(bling_order_data.get('situacao', {}).get('id')),
                'informacoes_cliente': {
                    'servico_logistico': servico_logistico,
                    'contato_id': contato.get('id'),
                    'numero_loja': order_sn
                }
            }

            items_dto = []
            for item in bling_order_data.get('itens', []):
                items_dto.append({
                    'sku_externo': item.get('codigo'),
                    'descricao': item.get('descricao'),
                    'quantidade': safe_float(item.get('quantidade'), 1.0),
                    'preco_unitario': safe_float(item.get('valor')),
                    'subtotal': safe_float(item.get('valor')) * safe_float(item.get('quantidade'), 1.0)
                })

            result = order_service.upsert_order(
                order_data=order_core_dto,
                platform='BLING',
                platform_order_id=bling_id,
                raw_payload=bling_order_data,
                items=items_dto,
                channel_id=canal_id
            )
            return result
        except Exception as e:
            logger.error(f"Erro sync_bling_order: {e}")
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
                'informacoes_comprador': {'username': raw_order.get('buyer_username')},
                'updated_at': datetime.utcnow().isoformat()
            }
            res = supabase_db.table('pedidos_shopee').select('id').eq('codigo_pedido', order_sn).execute()
            if res.data:
                supabase_db.table('pedidos_shopee').update(payload).eq('id', res.data[0]['id']).execute()
            else:
                payload['created_at'] = datetime.utcnow().isoformat()
                supabase_db.table('pedidos_shopee').insert(payload).execute()
        except: pass

    def _map_bling_status(self, id: int) -> int:
        return {6: 1, 15: 2, 9: 5, 12: 7, 18: 5}.get(id, 1)

    def _map_shopee_status(self, status: str) -> int:
        return {
            'UNPAID': 1, 'READY_TO_SHIP': 2, 'PROCESSED': 3,
            'SHIPPED': 5, 'COMPLETED': 6, 'IN_CANCEL': 7,
            'CANCELLED': 7, 'INVOICED': 5
        }.get(status, 1)

order_sync_service = OrderSyncService()
