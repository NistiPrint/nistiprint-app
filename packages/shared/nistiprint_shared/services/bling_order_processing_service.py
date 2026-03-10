import requests
import json
from datetime import datetime
from nistiprint_shared.services.conta_bling_service import conta_bling_service
from nistiprint_shared.database.database import db
from nistiprint_shared.database.supabase_db_service import get_db_session, supabase_db
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
        # ID da Conta Bling 01 conforme solicitado (ID exato)
        self.BLING_ACCOUNT_01_ID = "4LkzB9yWc07whoPi4IbT"

    def _get_bling_client_for_details(self):
        """Retorna um BlingClient configurado para a Conta 01."""
        from nistiprint_shared.services.bling.bling_client import BlingClient
        from nistiprint_shared.services.conta_bling_service import conta_bling_service
        
        # Busca pelo ID exato fornecido pelo usuário na tabela contas_bling
        account = conta_bling_service.get_by_id(self.BLING_ACCOUNT_01_ID)
        
        if account:
            return BlingClient(account)
            
        raise Exception(f"Conta Bling 01 (ID {self.BLING_ACCOUNT_01_ID}) não encontrada para obter detalhes.")

    def process_webhook(self, webhook_payload: dict):
        """
        Main method to process an incoming order webhook.
        """
        from nistiprint_shared.services.order_sync_service import order_sync_service
        
        # O Bling envia no formato: {"data": {"id": 123, "situacao": {"id": 15, "valor": 3}, ...}}
        data = webhook_payload.get('data', webhook_payload)
        order_id = data.get('id')
        situacao = data.get('situacao', {})
        situacao_id = situacao.get('id')

        if not order_id:
            return {"status": "skipped", "message": "No order ID in payload."}

        print(f"📄 Processando Evento Bling - Pedido: {order_id}, Situação: {situacao_id}")

        # REGRAS DE NEGÓCIO POR SITUAÇÃO:
        
        # 1. EM ANDAMENTO (ID 15) -> FOCO: Buscar detalhes completos e processar
        if situacao_id == 15:
            print(f"🚀 Pedido {order_id} em ANDAMENTO. Buscando detalhes na Conta 01...")
            try:
                client = self._get_bling_client_for_details()
                full_order_data = client.get_order(order_id)
                
                if not full_order_data:
                    return {"status": "failed", "message": f"Could not fetch details for order {order_id}."}

                # Sincroniza com o modelo unificado e gera demanda se necessário
                sync_result = order_sync_service.sync_bling_order(full_order_data)
                
                # Salva no banco legado (BlingPedidos) para manter compatibilidade
                self._save_order_to_db(full_order_data)
                
                return {"status": "success", "message": f"Order {order_id} processed fully.", "core_id": sync_result.get('id')}
            except Exception as e:
                print(f"❌ Erro ao processar detalhes do pedido {order_id}: {e}")
                return {"status": "error", "message": str(e)}

        # 2. EM ABERTO (ID 6) ou ATENDIDO (ID 9) -> Apenas atualizar status local
        elif situacao_id in [6, 9]:
            status_name = "ABERTO" if situacao_id == 6 else "ATENDIDO"
            print(f"ℹ️ Pedido {order_id} está {status_name}. Atualizando apenas status local...")
            
            # Sincroniza apenas o status (usando o payload simplificado do webhook)
            order_sync_service.sync_bling_order(data)
            
            # Atualiza também o banco legado se o pedido já existir lá
            self._update_legacy_status(order_id, situacao_id)
            
            return {"status": "success", "message": f"Status updated to {status_name}."}

        # 3. OUTROS STATUS
        else:
            print(f"⏭️ Pedido {order_id} ignorado (Situação {situacao_id} não é 15, 6 ou 9).")
            return {"status": "skipped", "message": f"Status {situacao_id} ignored."}

    def _update_legacy_status(self, bling_id, situacao_id):
        """Atualiza o status no banco legado (BlingPedidos) sem precisar de detalhes completos."""
        try:
            res = supabase_db.table('pedidos_bling').select('id').eq('bling_id', str(bling_id)).execute()
            if res.data:
                legacy_id = res.data[0]['id']
                supabase_db.table('pedidos_bling').update({
                    'atualizado_em': datetime.utcnow().isoformat()
                }).eq('id', legacy_id).execute()
        except Exception as e:
            print(f"⚠️ Erro ao atualizar status legado para {bling_id}: {e}")

    def _save_order_to_db(self, order_data: dict):
        """Saves the order and its items to the database (UPSERT logic)."""
        # Check if order exists by numeroLoja, which is more unique than numero
        numero_loja = order_data.get('numeroLoja')
        if not numero_loja:
            # Fallback para numero se numeroLoja não existir
            numero_loja = str(order_data.get('numero'))

        # SQLAlchemy fallback ou Supabase direto
        if get_current_database_mode().name != 'SUPABASE':
            order_record = BlingPedidos.query.filter_by(numeroLoja=numero_loja).first()
            if order_record:
                order_record.numero = order_data['numero']
                order_record.data = datetime.fromisoformat(order_data['data'])
                order_record.contato = json.dumps(order_data.get('contato', {}))
                order_record.bling_id = order_data['id']
                order_record.atualizado_em = datetime.utcnow()
            else:
                order_record = BlingPedidos(
                    numero=order_data['numero'],
                    numeroLoja=numero_loja,
                    data=datetime.fromisoformat(order_data['data']),
                    contato=json.dumps(order_data.get('contato', {})),
                    bling_id=order_data['id'],
                    personalizado=True
                )
                db.session.add(order_record)
            db.session.commit()
        else:
            # Supabase Upsert logic
            res = supabase_db.table('pedidos_bling').select('id').eq('numeroLoja', numero_loja).execute()
            order_payload = {
                'numero': order_data['numero'],
                'numeroLoja': numero_loja,
                'data': order_data['data'],
                'contato': json.dumps(order_data.get('contato', {})),
                'bling_id': str(order_data['id']),
                'personalizado': True,
                'atualizado_em': datetime.utcnow().isoformat()
            }
            if res.data:
                order_id = res.data[0]['id']
                supabase_db.table('pedidos_bling').update(order_payload).eq('id', order_id).execute()
            else:
                order_payload['created_at'] = datetime.utcnow().isoformat()
                res_ins = supabase_db.table('pedidos_bling').insert(order_payload).execute()
                order_id = res_ins.data[0]['id']

            # Sync items
            supabase_db.table('bling_pedido_itens').delete().eq('pedido_id', order_id).execute()
            items_to_insert = []
            for item_data in order_data.get('itens', []):
                items_to_insert.append({
                    'pedido_id': order_id,
                    'codigo': item_data.get('codigo'),
                    'unidade': item_data.get('unidade', 'UN'),
                    'quantidade': item_data['quantidade'],
                    'valor': item_data['valor'],
                    'descricao': item_data['descricao'],
                    'produto': json.dumps(item_data.get('produto', {})),
                    'personalizado': True # Na consolidação V2 tudo é tratado como personalizável inicialmente
                })
            if items_to_insert:
                supabase_db.table('bling_pedido_itens').insert(items_to_insert).execute()
        
        # --- INTEGRAÇÃO COM DEMANDA DE PRODUÇÃO ---
        try:
            print(f"🏭 [LOG] Gerando Demanda de Produção para o pedido {order_data.get('numero')}...")
            demanda_producao_service.create_from_order(order_data)
        except Exception as e:
            print(f"❌ [LOG] FALHA AO CRIAR DEMANDA AUTOMÁTICA: {e}")

    def import_single_order_by_shop_id(self, shopee_order_sn: str):
        """
        Importa manualmente um pedido baseado no numeroLoja (Shopee SN).
        Utiliza a Conta 01 para buscar os detalhes.
        """
        print(f"🚀 [MANUAL] Iniciando importação para o pedido Shopee SN: {shopee_order_sn}")
        try:
            client = self._get_bling_client_for_details()
            
            # 1. Buscar o pedido pelo numeroLoja na Conta 01
            url = f"pedidos/vendas?numerosLojas[]={shopee_order_sn}"
            response = client._request('GET', url)
            
            if not response or not response.get('data'):
                return False, f"Pedido {shopee_order_sn} não encontrado na conta Bling 01."
            
            order_summary = response['data'][0]
            order_id = order_summary.get('id')
            
            # 2. Buscar detalhes completos
            full_order_data = client.get_order(order_id)
            if not full_order_data:
                return False, f"Não foi possível obter os detalhes do pedido {order_id}."
            
            # 3. Sincronizar (Isso já salva no banco unificado e gera demanda)
            from nistiprint_shared.services.order_sync_service import order_sync_service
            order_sync_service.sync_bling_order(full_order_data)
            
            # 4. Salva no banco legado
            self._save_order_to_db(full_order_data)
            
            return True, f"Pedido {shopee_order_sn} importado com sucesso!"
            
        except Exception as e:
            print(f"❌ Erro na importação manual: {e}")
            return False, str(e)

# Global instance for use throughout the application
bling_order_processing_service = BlingOrderProcessingService()

# Expose the function at the module level for easy import (Used by routes.ferramentas)
def import_single_order_by_shop_id(shopee_order_sn: str):
    return bling_order_processing_service.import_single_order_by_shop_id(shopee_order_sn)
