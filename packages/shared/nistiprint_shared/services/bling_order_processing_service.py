import requests
import json
from datetime import datetime
from nistiprint_shared.services.conta_bling_service import conta_bling_service
from nistiprint_shared.database.database import db
from nistiprint_shared.database.supabase_db_service import get_db_session
from nistiprint_shared.database.supabase_db_service import get_current_database_mode
from nistiprint_shared.models.bling_pedidos import BlingPedidos
from nistiprint_shared.models.bling_pedido_itens import BlingPedidoItens
from nistiprint_shared.services.demanda_producao_service import demanda_producao_service


class BlingOrderProcessingService:
    """
    Service to process Bling order webhooks, applying business logic
    and saving valid orders to the database.
    """

    def __init__(self):
        # Lazy load accounts to avoid circular dependencies or loading too early
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
            response.raise_for_status()  # Raises an HTTPError for bad responses (4xx or 5xx)
            return response.json().get('data', {})
        except requests.RequestException as e:
            print(f"❌ Erro ao buscar detalhes do pedido {order_id} no Bling: {e}")
            return None

    def process_webhook(self, webhook_payload: dict):
        """
        Main method to process an incoming order webhook.
        """
        print("Processing Bling order webhook...")

        if not self.bling_antiga_account or not self.bling_nova_account:
            raise Exception("Bling accounts (antiga or nova) not found. Check CNPJs in Firestore.")

        # O payload do webhook contém um objeto 'data' com os dados do evento
        inner_payload = webhook_payload.get('data', {})
        order_id = inner_payload.get('id')

        if not order_id:
            print("⚠️ Webhook sem ID de pedido. Pulando.")
            return {"status": "skipped", "message": "No order ID in payload."}

        print(f"📄 Processando para o ID do pedido Bling: {order_id}")

        # 1. Get full order details from Bling API using the "antiga" account
        api_key_antiga = self.bling_antiga_account.get('access_token')
        if not api_key_antiga:
            raise Exception("API key for Bling Antiga account not found.")

        print(f"🔎 Buscando detalhes completos do pedido {order_id}...")
        full_order_data = self._get_bling_order_details(order_id, api_key_antiga)

        if not full_order_data:
            # Erro já foi logado no método _get_bling_order_details
            return {"status": "failed", "message": f"Could not fetch details for order {order_id}."}
        
        print(f"✅ Detalhes do pedido {order_id} obtidos com sucesso.")

        # 2. Apply filters
        # Filtro 1: Status do pedido deve ser "Em andamento" (id 15)
        situacao_id = full_order_data.get('situacao', {}).get('id')
        if situacao_id != 15:
            print(f"⏭️  Pedido {order_id} ignorado. Status é {situacao_id}, esperado 15.")
            return {"status": "skipped", "message": f"Order status is {situacao_id}, expected 15."}

        # Filtro 2: Nome do contato não pode conter '**'
        contact_name = full_order_data.get('contato', {}).get('nome', '')
        if '**' in contact_name:
            print(f"⏭️  Pedido {order_id} ignorado. Nome do contato contém '**'.")
            return {"status": "skipped", "message": "Contact name contains '**'."}
        
        print("✅ Pedido passou nos filtros iniciais (Status e Nome do Contato).")

        # Filtro 3: Cross-check de status na conta Bling Nova
        api_key_nova = self.bling_nova_account.get('access_token')
        if not api_key_nova:
            raise Exception("API key for Bling Nova account not found.")

        shopee_order_id = full_order_data.get('numeroLoja')
        if not shopee_order_id:
            print(f"⏭️  Pedido {order_id} ignorado. Não possui numeroLoja para verificação cruzada.")
            return {"status": "skipped", "message": "Order does not have numeroLoja for cross-check."}

        print(f"🔎 Verificando pedido {shopee_order_id} na conta Bling Nova...")
        order_from_nova = self._get_bling_order_by_shopee_id(shopee_order_id, api_key_nova)

        if not order_from_nova:
            print(f"⏭️  Pedido {shopee_order_id} não encontrado na conta Bling Nova. Ignorando.")
            return {"status": "skipped", "message": f"Order {shopee_order_id} not found in Bling Nova account."}

        situacao_id_nova = order_from_nova.get('situacao', {}).get('id')
        if situacao_id_nova != 15:
            print(f"⏭️  Pedido {shopee_order_id} ignorado. Status na conta Nova é {situacao_id_nova}, esperado 15.")
            return {"status": "skipped", "message": f"Order status in Nova account is {situacao_id_nova}, expected 15."}
        
        # Atualiza os dados do pedido com as informações da conta nova, como no script PHP
        print("✅ Verificação cruzada bem-sucedida. Atualizando dados do pedido.")
        order_to_save = order_from_nova
        # Mantém os itens da conta antiga, pois a nova pode não tê-los
        order_to_save['itens'] = full_order_data.get('itens', [])

        # Filtro 4: Verificar se o pedido contém pelo menos um item personalizado
        print(f"🔎 Verificando itens personalizados para o pedido {order_to_save.get('numero')}...")
        has_personalized_item = False
        ID_CAMPO_CUSTOMIZADO_PERSONALIZADO = 2797770  # Do script PHP

        items_to_save = []
        for item in order_to_save.get('itens', []):
            is_personalized = False
            product_id = item.get('produto', {}).get('id')

            if product_id:
                product_details = self._get_bling_product_details(product_id, api_key_antiga)
                if product_details:
                    for field in product_details.get('camposCustomizados', []):
                        if (field.get('idCampoCustomizado') == ID_CAMPO_CUSTOMIZADO_PERSONALIZADO and
                                str(field.get('valor', '')).lower() == 'true'):
                            is_personalized = True
                            break
            
            # Fallback para a descrição do item
            if not is_personalized and 'personaliza' in item.get('descricao', '').lower():
                is_personalized = True

            if is_personalized:
                has_personalized_item = True

            # Adiciona o status de personalização ao item para salvar depois
            item['_is_personalized'] = is_personalized
            items_to_save.append(item)

        if not has_personalized_item:
            print(f"⏭️  Pedido {order_to_save.get('numero')} ignorado. Nenhum item personalizado encontrado.")
            return {"status": "skipped", "message": "No personalized items found."}

        print(f"✅ Pedido {order_to_save.get('numero')} contém itens personalizados.")
        order_to_save['itens'] = items_to_save

        # 3. Save to database if all filters pass
        try:
            self._save_order_to_db(order_to_save)
            print(f"💾 Pedido {order_to_save.get('numero')} salvo no banco de dados com sucesso.")
            return {"status": "success", "message": "Order processed and saved successfully."}
        except Exception as e:
            print(f"❌ Erro ao salvar o pedido {order_to_save.get('numero')} no banco de dados: {e}")
            return {"status": "failed", "message": f"Database error: {e}"}

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
            print(f"❌ Erro ao buscar pedido Shopee ID {shopee_order_id} no Bling: {e}")
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
            print(f"❌ Erro ao buscar detalhes do produto {product_id} no Bling: {e}")
            return None

    def import_single_order_by_shop_id(self, shopee_order_sn: str):
        """
        Imports a single order from Bling based on the Shopee Order SN (numeroLoja).
        This method replicates the core logic of the webhook processor but is triggered manually.
        """
        print(f"🚀 [LOG] Iniciando importação manual para o pedido Shopee SN: {shopee_order_sn}")

        if not self.bling_antiga_account or not self.bling_nova_account:
            print("❌ [LOG] Contas Bling (antiga ou nova) não configuradas.")
            return False, "Contas Bling (antiga ou nova) não configuradas."

        api_key_antiga = self.bling_antiga_account.get('access_token')
        if not api_key_antiga:
            print("❌ [LOG] API key para a conta Bling Antiga não encontrada.")
            return False, "API key para a conta Bling Antiga não encontrada."
        print("🔑 [LOG] API Key da conta antiga obtida.")

        # 1. Find the order in the "antiga" account by shopee_order_sn
        print(f"🔎 [LOG] Buscando pedido {shopee_order_sn} na conta Bling Antiga...")
        order_summary_antiga = self._get_bling_order_by_shopee_id(shopee_order_sn, api_key_antiga)

        if not order_summary_antiga:
            print(f"❌ [LOG] Pedido {shopee_order_sn} não encontrado na conta Bling Antiga.")
            return False, f"Pedido {shopee_order_sn} não encontrado na conta Bling Antiga."

        order_id_antiga = order_summary_antiga.get('id')
        print(f"📄 [LOG] ID do pedido na Bling Antiga: {order_id_antiga}")

        # 2. Get full order details from the "antiga" account
        print(f"🔎 [LOG] Buscando detalhes completos do pedido {order_id_antiga}...")
        full_order_data = self._get_bling_order_details(order_id_antiga, api_key_antiga)

        if not full_order_data:
            print(f"❌ [LOG] Não foi possível obter os detalhes do pedido {order_id_antiga}.")
            return False, f"Não foi possível obter os detalhes do pedido {order_id_antiga}."

        print("✅ [LOG] Detalhes do pedido obtidos com sucesso.")
        # print(f"📦 [LOG] Dados completos da conta antiga: {json.dumps(full_order_data, indent=2)}")


        # 3. Apply initial filters (only contact name)
        contact_name = full_order_data.get('contato', {}).get('nome', '')
        if '**' in contact_name:
            print(f"❌ [LOG] Pedido ignorado. Nome do contato '{contact_name}' contém '**'.")
            return False, "Pedido ignorado. Nome do contato contém '**'."

        print("✅ [LOG] Pedido passou no filtro de nome.")

        # 4. Cross-check with "nova" account
        api_key_nova = self.bling_nova_account.get('access_token')
        if not api_key_nova:
            print("❌ [LOG] API key para a conta Bling Nova não encontrada.")
            return False, "API key para a conta Bling Nova não encontrada."
        print("🔑 [LOG] API Key da conta nova obtida.")

        print(f"🔎 [LOG] Verificando pedido {shopee_order_sn} na conta Bling Nova...")
        order_from_nova = self._get_bling_order_by_shopee_id(shopee_order_sn, api_key_nova)

        if not order_from_nova:
            print(f"❌ [LOG] Pedido {shopee_order_sn} não encontrado na conta Bling Nova.")
            return False, f"Pedido {shopee_order_sn} não encontrado na conta Bling Nova para verificação."
        
        print("✅ [LOG] Verificação cruzada bem-sucedida. Usando dados da conta Nova como base.")
        # print(f"📦 [LOG] Dados da conta nova: {json.dumps(order_from_nova, indent=2)}")


        # REMOVED: Status check is no longer required for manual import
        # situacao_id_nova = order_from_nova.get('situacao', {}).get('id')
        # if situacao_id_nova != 15:
        #     print(f"❌ [LOG] Pedido ignorado. Status na conta Nova é {situacao_id_nova} (esperado 15).")
        #     return False, f"Pedido ignorado. Status na conta Nova é {situacao_id_nova} (esperado 15)."

        order_to_save = order_from_nova
        order_to_save['itens'] = full_order_data.get('itens', [])

        # 5. Check for personalized items
        print(f"🔎 [LOG] Verificando itens personalizados para o pedido {order_to_save.get('numero')}...")
        has_personalized_item, items_to_save = self._check_for_personalized_items(
            order_to_save.get('itens', []),
            api_key_antiga
        )

        if not has_personalized_item:
            print(f"❌ [LOG] Pedido {order_to_save.get('numero')} não contém itens personalizados. Abortando.")
            return False, f"Pedido {order_to_save.get('numero')} não contém itens personalizados."

        print(f"✅ [LOG] Pedido {order_to_save.get('numero')} contém itens personalizados.")
        order_to_save['itens'] = items_to_save

        # 6. Save to database
        try:
            print(f"💾 [LOG] Tentando salvar o pedido {order_to_save.get('numero')} no banco de dados...")
            self._save_order_to_db(order_to_save)
            msg = f"Pedido {order_to_save.get('numero')} ({shopee_order_sn}) importado com sucesso!"
            print(f"🎉 [LOG] {msg}")
            return True, msg
        except Exception as e:
            error_msg = f"Erro ao salvar o pedido {order_to_save.get('numero')} no banco de dados: {e}"
            print(f"❌ [LOG] {error_msg}")
            return False, error_msg

    def _check_for_personalized_items(self, items: list, api_key: str):
        """
        Checks a list of items for personalized products.
        Returns a tuple: (has_personalized_item: bool, processed_items: list)
        """
        has_personalized_item = False
        processed_items = []
        ID_CAMPO_CUSTOMIZADO_PERSONALIZADO = 2797770
        print(f"🕵️ [LOG] Verificando {len(items)} item(ns)...")

        for i, item in enumerate(items):
            is_personalized = False
            item_description = item.get('descricao', '')
            product_id = item.get('produto', {}).get('id')
            print(f"  - [LOG] Item {i+1}: '{item_description}' (Produto ID: {product_id})")

            if product_id:
                product_details = self._get_bling_product_details(product_id, api_key)
                if product_details and 'camposCustomizados' in product_details:
                    for field in product_details.get('camposCustomizados', []):
                        if (field.get('idCampoCustomizado') == ID_CAMPO_CUSTOMIZADO_PERSONALIZADO and
                                str(field.get('valor', '')).lower() == 'true'):
                            print(f"    ✔️ [LOG] Item marcado como personalizado via campo customizado do produto.")
                            is_personalized = True
                            break
            
            if not is_personalized and 'personaliza' in item_description.lower():
                print(f"    ✔️ [LOG] Item marcado como personalizado via descrição ('{item_description}').")
                is_personalized = True

            if is_personalized:
                has_personalized_item = True
            
            print(f"    👉 [LOG] Resultado do item {i+1}: Personalizado = {is_personalized}")
            item['_is_personalized'] = is_personalized
            processed_items.append(item)
            
        return has_personalized_item, processed_items

    def _save_order_to_db(self, order_data: dict):
        """Saves the order and its items to the database (UPSERT logic)."""
        # Check if order exists by numeroLoja, which is more unique than numero
        order_record = BlingPedidos.query.filter_by(numeroLoja=order_data['numeroLoja']).first()

        if order_record:
            # Update existing order
            print(f"🔄 Atualizando pedido existente: {order_data['numeroLoja']}")
            order_record.numero = order_data['numero']
            order_record.data = datetime.fromisoformat(order_data['data'])
            order_record.contato = json.dumps(order_data.get('contato', {}))
            order_record.bling_id = order_data['id']
            order_record.personalizado = True
            order_record.deletado = False
            order_record.atualizado_em = datetime.utcnow()
        else:
            # Create new order
            print(f"✨ Criando novo pedido: {order_data['numeroLoja']}")
            order_record = BlingPedidos(
                numero=order_data['numero'],
                numeroLoja=order_data.get('numeroLoja'),
                data=datetime.fromisoformat(order_data['data']),
                contato=json.dumps(order_data.get('contato', {})),
                bling_id=order_data['id'],
                personalizado=True,
                deletado=False
            )

            # Only add to session if using SQLAlchemy mode, not Supabase
            if get_current_database_mode().name != 'SUPABASE':
                db.session.add(order_record)
                # Commit to get the order ID if it's new
                db.session.commit()
            else:
                # For Supabase, use the session context manager
                with get_db_session() as session:
                    session.add(order_record)
                    session.commit()

        # Delete existing items to re-sync (Batch optimized)
        if get_current_database_mode().name != 'SUPABASE':
            BlingPedidoItens.query.filter_by(pedido_id=order_record.id).delete()
            db.session.commit()
        else:
            # Delete in batch using Supabase client directly for efficiency
            supabase_db.table('bling_pedido_itens').delete().eq('pedido_id', order_record.id).execute()

        # Add new items IN BATCH for Supabase
        if get_current_database_mode().name == 'SUPABASE':
            items_to_insert = []
            for item_data in order_data.get('itens', []):
                items_to_insert.append({
                    'pedido_id': order_record.id,
                    'codigo': item_data.get('codigo'),
                    'unidade': item_data.get('unidade', 'UN'),
                    'quantidade': item_data['quantidade'],
                    'valor': item_data['valor'],
                    'descricao': item_data['descricao'],
                    'produto': json.dumps(item_data.get('produto', {})),
                    'personalizado': item_data.get('_is_personalized', False)
                })
            
            if items_to_insert:
                supabase_db.execute_with_retry(supabase_db.table('bling_pedido_itens').insert(items_to_insert))
        else:
            # SQLAlchemy legacy mode
            for item_data in order_data.get('itens', []):
                item_record = BlingPedidoItens(
                    pedido_id=order_record.id,
                    codigo=item_data.get('codigo'),
                    unidade=item_data.get('unidade', 'UN'),
                    quantidade=item_data['quantidade'],
                    valor=item_data['valor'],
                    descricao=item_data['descricao'],
                    produto=json.dumps(item_data.get('produto', {})),
                    personalizado=item_data.get('_is_personalized', False)
                )
                db.session.add(item_record)
            db.session.commit()
        
        # --- INTEGRAÇÃO COM MODELO UNIFICADO (V3) ---
        try:
            from nistiprint_shared.services.order_sync_service import order_sync_service
            print(f"🔗 [LOG] Sincronizando com Modelo Unificado para o pedido {order_data.get('numero')}...")
            order_sync_service.sync_bling_order(order_data)
        except Exception as e:
            print(f"⚠️ [LOG] Erro ao salvar no modelo unificado: {e}")

        # --- INTEGRAÇÃO COM DEMANDA DE PRODUÇÃO ---
        try:
            print(f"🏭 [LOG] Gerando Demanda de Produção para o pedido {order_data.get('numero')}...")
            demanda = demanda_producao_service.create_from_order(order_data)
            print(f"✅ [LOG] Demanda criada/recuperada com ID: {demanda.get('id')}")
        except Exception as e:
            print(f"❌ [LOG] FALHA AO CRIAR DEMANDA AUTOMÁTICA: {e}")
            # Não lançamos exceção aqui para não invalidar o salvamento do pedido no banco SQL
            # TODO: Notificar admin ou criar log de erro persistente

# Global instance for use throughout the application
bling_order_processing_service = BlingOrderProcessingService()

# Expose the new function at the module level for easy import
def import_single_order_by_shop_id(shopee_order_sn: str):
    return bling_order_processing_service.import_single_order_by_shop_id(shopee_order_sn)

