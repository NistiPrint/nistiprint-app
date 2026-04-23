import requests
import json
import logging
from datetime import datetime, timezone
from nistiprint_shared.services.conta_bling_service import conta_bling_service
from nistiprint_shared.database.database import db
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.database.supabase_db_service import get_db_session
from nistiprint_shared.database.supabase_db_service import get_current_database_mode
from nistiprint_shared.models.bling_pedidos import BlingPedidos
from nistiprint_shared.models.bling_pedido_itens import BlingPedidoItens
from nistiprint_shared.services.demanda_producao_service import demanda_producao_service
from nistiprint_shared.services import flex_classifier_service
from nistiprint_shared.services.platform_drivers import shopee as shopee_driver

logger = logging.getLogger(__name__)

class BlingOrderProcessingService:
    """
    Service to process Bling order webhooks, applying business logic
    and saving valid orders to the database using the new refactored model.
    """

    def __init__(self):
        self.supabase = supabase_db
        # Lazy load accounts to avoid circular dependencies
        self._bling_antiga_account = None
        self._bling_nova_account = None

    @property
    def bling_antiga_account(self):
        if self._bling_antiga_account is None:
            # CNPJ for the account that receives the webhooks
            self._bling_antiga_account = conta_bling_service.get_by_cnpj("13597")
        return self._bling_antiga_account

    @property
    def bling_nova_account(self):
        if self._bling_nova_account is None:
            # CNPJ for the cross-check account
            self._bling_nova_account = conta_bling_service.get_by_cnpj("54533")
        return self._bling_nova_account

    def _get_bling_order_details(self, order_id: str, api_key: str) -> dict:
        """Fetches full order details from the Bling API."""
        url = f"https://api.bling.com.br/Api/v3/pedidos/vendas/{order_id}"
        headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {api_key}'
        }
        try:
            response = requests.get(url, headers=headers, timeout=20)
            response.raise_for_status()
            return response.json().get('data', {})
        except requests.RequestException as e:
            logger.error(f"❌ Erro ao buscar detalhes do pedido {order_id} no Bling: {e}")
            return None

    def _get_bling_order_by_shopee_id(self, shopee_order_id: str, api_key: str) -> dict:
        """Fetches an order from Bling API using the numeroLoja (Shopee ID)."""
        url = f"https://api.bling.com.br/Api/v3/pedidos/vendas?numerosLojas[]={shopee_order_id}"
        headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {api_key}'
        }
        try:
            response = requests.get(url, headers=headers, timeout=20)
            response.raise_for_status()
            data = response.json().get('data', [])
            return data[0] if data else None
        except requests.RequestException as e:
            logger.error(f"❌ Erro ao buscar pedido Shopee ID {shopee_order_id} no Bling: {e}")
            return None

    def _get_bling_product_details(self, product_id: str, api_key: str) -> dict:
        """Fetches product details from the Bling API."""
        url = f"https://api.bling.com.br/Api/v3/produtos/{product_id}"
        headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {api_key}'
        }
        try:
            response = requests.get(url, headers=headers, timeout=20)
            response.raise_for_status()
            return response.json().get('data', {})
        except requests.RequestException as e:
            logger.error(f"❌ Erro ao buscar detalhes do produto {product_id} no Bling: {e}")
            return None

    def _upsert_pedido_bling(self, payload, integracao_instancia_id):
        """UPSERT em pedidos_bling (RAW fiel do payload)"""
        bling_id = payload.get('id')
        if not bling_id:
            return None
            
        data = {
            'bling_id': bling_id,
            'numero': str(payload.get('numero', '')),
            'numero_loja': payload.get('numeroLoja'),
            'situacao_id': payload.get('situacao', {}).get('id'),
            'situacao_valor': payload.get('situacao', {}).get('valor'),
            'contato': payload.get('contato'),
            'itens': payload.get('itens'),
            'transporte': payload.get('transporte'),
            'intermediador_cnpj': payload.get('intermediador', {}).get('cnpj'),
            'loja_id': payload.get('loja', {}).get('id'),
            'observacoes': payload.get('observacoes'),
            'observacoes_internas': payload.get('observacoesInternas'),
            'raw_payload': payload,
            'integracao_instancia_id': integracao_instancia_id,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
        
        res = self.supabase.table('pedidos_bling').upsert(data, on_conflict='bling_id').execute()
        return res.data[0]['id'] if res.data else None

    def _find_channel_connection(self, bling_integration_id, aggregator_store_id):
        """Consulta channel_connections para mapear loja Bling → integração Shopee + canal"""
        res = self.supabase.rpc('find_shopee_connection', {
            'p_bling_integration_id': bling_integration_id,
            'p_aggregator_store_id': str(aggregator_store_id),
        }).execute()
        return res.data[0] if res.data else None

    def _upsert_pedido_shopee(self, shopee_data, shop_id):
        """UPSERT em pedidos_shopee com campos crus"""
        if not shopee_data:
            return None
            
        order_sn = shopee_data.get('order_sn')
        if not order_sn:
            return None
            
        # Converte pay_time de timestamp para ISO
        pay_time = None
        if shopee_data.get('pay_time'):
            pay_time = datetime.fromtimestamp(shopee_data['pay_time'], tz=timezone.utc).isoformat()
            
        data = {
            'order_sn': order_sn,
            'order_status': shopee_data.get('order_status'),
            'fulfillment_flag': shopee_data.get('fulfillment_flag'),
            'shipping_carrier': shopee_data.get('shipping_carrier'),
            'package_list': shopee_data.get('package_list'),
            'pay_time': pay_time,
            'recipient_address': shopee_data.get('recipient_address'),
            'item_list': shopee_data.get('item_list'),
            'shop_id': shop_id,
            'raw_payload': shopee_data,
            'enriched_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
        
        res = self.supabase.table('pedidos_shopee').upsert(data, on_conflict='order_sn').execute()
        return res.data[0]['id'] if res.data else None

    def _upsert_pedido_master(self, payload, **kwargs):
        """UPSERT em pedidos (tabela centralizadora)"""
        bling_numero = str(payload.get('numero', ''))
        numero_loja = payload.get('numeroLoja')
        codigo_externo = numero_loja if numero_loja else bling_numero
        
        data = {
            'codigo_pedido_externo': codigo_externo,
            'numero_pedido': bling_numero,
            'pedido_bling_id': kwargs.get('pedido_bling_id'),
            'pedido_shopee_id': kwargs.get('pedido_shopee_id'),
            'shop_id_shopee': kwargs.get('shop_id_shopee'),
            'is_flex': kwargs.get('is_flex', False),
            'modalidade_logistica': kwargs.get('modalidade_logistica', 'STANDARD'),
            'canal_venda_id': kwargs.get('canal_venda_id'),
            'cliente_nome': payload.get('contato', {}).get('nome'),
            'data_venda': payload.get('data'),
            'origem': 'BLING',
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
        
        # Mapping situation to situacao_pedido_id (placeholder, should use integration_status_mappings)
        # For now, let's try to map some common ones or keep null
        
        res = self.supabase.table('pedidos').upsert(data, on_conflict='codigo_pedido_externo').execute()
        return res.data[0]['id'] if res.data else None

    def _volume_servico(self, payload):
        volumes = payload.get('transporte', {}).get('volumes', [])
        return volumes[0].get('servico') if volumes else None

    def _save_order_to_db(self, payload, integracao_bling_id):
        """Fluxo refatorado de salvamento de pedido conforme Parte A do plano"""
        # 1. UPSERT em pedidos_bling
        pedido_bling_id = self._upsert_pedido_bling(payload, integracao_bling_id)

        # 2. Detectar Shopee via channel_connections
        pedido_shopee_id, shop_id_shopee, shopee_data = None, None, None
        aggregator_store_id = payload.get('loja', {}).get('id')
        
        conn = self._find_channel_connection(
            bling_integration_id=integracao_bling_id,
            aggregator_store_id=aggregator_store_id,
        )
        
        canal_venda_id = conn['channel_id'] if conn else None

        # 3. Se Shopee, enriquecer
        if conn and conn.get('marketplace_integration_id'):
            integration_shopee = {
                'id': conn['marketplace_integration_id'],
                'config': conn.get('shopee_config', {}),
                'credentials': conn.get('shopee_credentials', {}),
                'shop_id': conn.get('shopee_config', {}).get('shop_id') or conn.get('shopee_credentials', {}).get('shop_id')
            }
            
            try:
                order_sn = payload.get('numeroLoja')
                shopee_details = shopee_driver.get_order_detail(
                    integration=integration_shopee,
                    order_ids=[order_sn]
                )
                
                if shopee_details and len(shopee_details) > 0:
                    shopee_data = shopee_details[0].get('raw')
                    shop_id_shopee = integration_shopee['shop_id']
                    pedido_shopee_id = self._upsert_pedido_shopee(shopee_data, shop_id_shopee)
            except Exception as e:
                logger.error(f"Erro ao enriquecer pedido Shopee {payload.get('numeroLoja')}: {e}")

        # 4. Classificação Flex
        fields = {
            'servico_logistico': self._volume_servico(payload),
            'shipping_carrier': (shopee_data or {}).get('shipping_carrier'),
            'fulfillment_flag': (shopee_data or {}).get('fulfillment_flag'),
        }
        
        if not fields['shipping_carrier'] and shopee_data and shopee_data.get('package_list'):
            fields['shipping_carrier'] = shopee_data['package_list'][0].get('shipping_carrier')

        flex = flex_classifier_service.classify(
            self.supabase,
            fields=fields,
            integracao_instancia_id=(conn or {}).get('marketplace_integration_id') or integracao_bling_id,
            canal_venda_id=canal_venda_id,
        )

        # 5. UPSERT em pedidos Master
        pedido_id = self._upsert_pedido_master(
            payload,
            pedido_bling_id=pedido_bling_id,
            pedido_shopee_id=pedido_shopee_id,
            shop_id_shopee=shop_id_shopee,
            canal_venda_id=canal_venda_id,
            is_flex=flex.is_flex,
            modalidade_logistica=flex.modalidade
        )

        # 6. Criar demanda de produção
        demanda_producao_service.create_from_order(
            order_data=payload,
            is_flex=flex.is_flex,
            modalidade_logistica=flex.modalidade,
            canal_venda_id=canal_venda_id
        )
        
        return pedido_id

    def process_webhook(self, webhook_payload: dict):
        """
        Main method to process an incoming order webhook.
        Updated to use the new refactored flow.
        """
        logger.info("Processing Bling order webhook with refactored flow...")

        if not self.bling_antiga_account:
            raise Exception("Bling account (antiga) not found. Check CNPJ 13597 in contas_bling.")

        # O payload do webhook contém um objeto 'data' com os dados do evento
        inner_payload = webhook_payload.get('data', {})
        order_id = inner_payload.get('id')

        if not order_id:
            logger.warning("⚠️ Webhook sem ID de pedido. Pulando.")
            return {"status": "skipped", "message": "No order ID in payload."}

        # 1. Get full order details from Bling API using the "antiga" account
        api_key_antiga = self.bling_antiga_account.get('access_token')
        if not api_key_antiga:
            raise Exception("API key for Bling Antiga account not found.")

        full_order_data = self._get_bling_order_details(order_id, api_key_antiga)

        if not full_order_data:
            return {"status": "failed", "message": f"Could not fetch details for order {order_id}."}
        
        # 2. Apply filters
        # Status "Em andamento" (id 15)
        situacao_id = full_order_data.get('situacao', {}).get('id')
        if situacao_id != 15:
            logger.info(f"⏭️ Pedido {order_id} ignorado. Status é {situacao_id}, esperado 15.")
            return {"status": "skipped", "message": f"Order status is {situacao_id}, expected 15."}

        # Nome do contato não pode conter '**'
        contact_name = full_order_data.get('contato', {}).get('nome', '')
        if '**' in contact_name:
            logger.info(f"⏭️ Pedido {order_id} ignorado. Nome do contato contém '**'.")
            return {"status": "skipped", "message": "Contact name contains '**'."}
        
        # 3. Cross-check with Bling Nova account
        if not self.bling_nova_account:
            logger.warning("Bling Nova account not found for cross-check.")
        else:
            api_key_nova = self.bling_nova_account.get('access_token')
            shopee_order_id = full_order_data.get('numeroLoja')
            if shopee_order_id:
                order_from_nova = self._get_bling_order_by_shopee_id(shopee_order_id, api_key_nova)
                if order_from_nova:
                    situacao_id_nova = order_from_nova.get('situacao', {}).get('id')
                    if situacao_id_nova != 15:
                        logger.info(f"⏭️ Pedido {shopee_order_id} ignorado (Nova status {situacao_id_nova}).")
                        return {"status": "skipped", "message": "Nova account status not 15."}
                    
                    # Update data with Nova info (mirroring legacy logic)
                    nova_items = order_from_nova.get('itens', [])
                    if not nova_items:
                         order_from_nova['itens'] = full_order_data.get('itens', [])
                    full_order_data = order_from_nova

        # 4. Check for personalized items
        has_personalized_item, processed_items = self._check_for_personalized_items(
            full_order_data.get('itens', []),
            api_key_antiga
        )

        if not has_personalized_item:
            logger.info(f"⏭️ Pedido {full_order_data.get('numero')} ignorado. Sem itens personalizados.")
            return {"status": "skipped", "message": "No personalized items found."}

        full_order_data['itens'] = processed_items

        # 5. Save to database using refactored flow
        try:
            # integracao_bling_id is the ID of the "antiga" account
            pedido_id = self._save_order_to_db(full_order_data, self.bling_antiga_account['id'])
            return {"status": "success", "pedido_id": pedido_id}
        except Exception as e:
            logger.error(f"❌ Erro ao salvar pedido {full_order_data.get('numero')}: {e}")
            return {"status": "failed", "message": str(e)}

    def _check_for_personalized_items(self, items: list, api_key: str):
        """Checks a list of items for personalized products."""
        has_personalized_item = False
        processed_items = []
        ID_CAMPO_CUSTOMIZADO_PERSONALIZADO = 2797770

        for item in items:
            is_personalized = False
            item_description = item.get('descricao', '')
            product_id = item.get('produto', {}).get('id')

            if product_id:
                product_details = self._get_bling_product_details(product_id, api_key)
                if product_details and 'camposCustomizados' in product_details:
                    for field in product_details.get('camposCustomizados', []):
                        if (field.get('idCampoCustomizado') == ID_CAMPO_CUSTOMIZADO_PERSONALIZADO and
                                str(field.get('valor', '')).lower() == 'true'):
                            is_personalized = True
                            break
            
            if not is_personalized and 'personaliza' in item_description.lower():
                is_personalized = True

            if is_personalized:
                has_personalized_item = True
            
            item['_is_personalized'] = is_personalized
            processed_items.append(item)
            
        return has_personalized_item, processed_items

    def import_single_order_by_shop_id(self, shopee_order_sn: str):
        """Manual import using refactored flow."""
        if not self.bling_antiga_account:
            return False, "Conta Bling Antiga não configurada."

        api_key_antiga = self.bling_antiga_account.get('access_token')
        order_summary = self._get_bling_order_by_shopee_id(shopee_order_sn, api_key_antiga)

        if not order_summary:
            return False, f"Pedido {shopee_order_sn} não encontrado na Bling Antiga."

        full_order_data = self._get_bling_order_details(order_summary['id'], api_key_antiga)
        if not full_order_data:
            return False, "Não foi possível obter detalhes do pedido."

        has_personalized_item, items_to_save = self._check_for_personalized_items(
            full_order_data.get('itens', []),
            api_key_antiga
        )
        full_order_data['itens'] = items_to_save

        try:
            pedido_id = self._save_order_to_db(full_order_data, self.bling_antiga_account['id'])
            return True, f"Pedido {shopee_order_sn} importado com sucesso (ID: {pedido_id})."
        except Exception as e:
            return False, str(e)

# Global instance
bling_order_processing_service = BlingOrderProcessingService()

def import_single_order_by_shop_id(shopee_order_sn: str):
    return bling_order_processing_service.import_single_order_by_shop_id(shopee_order_sn)
