from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from nistiprint_shared.database.supabase_db_service import supabase_db
import logging

class OrderService:
    """
    Serviço unificado para gestão de pedidos.
    Implementa a arquitetura Core Order + Integration Links (V3).
    """

    def __init__(self):
        self.pedidos_table = supabase_db.table('pedidos')
        self.itens_table = supabase_db.table('itens_pedido')
        self.vinculos_table = supabase_db.table('vinculos_integracao_pedido')

    def _parse_json(self, data):
        import json
        if not data: return {}
        if isinstance(data, (dict, list)): return data
        try: return json.loads(data)
        except: return {}

    def upsert_order(self, order_data: Dict[str, Any], platform: str, platform_order_id: str, 
                     raw_payload: Dict[str, Any], items: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Realiza o Upsert inteligente de um pedido.
        Garante a unicidade pelo codigo_pedido_externo.
        """
        external_id = order_data.get('codigo_pedido_externo')
        if not external_id:
            raise ValueError("codigo_pedido_externo é obrigatório para upsert.")

        try:
            # 1. Tentar encontrar o pedido Core existente
            existing_order = self.pedidos_table.select("id").eq('codigo_pedido_externo', external_id).execute()
            
            core_id = None
            if existing_order.data:
                core_id = existing_order.data[0]['id']
                # Atualiza dados operacionais básicos se necessário
                update_core = {
                    'status_unificado': order_data.get('status_unificado'),
                    'total_pedido': order_data.get('total_pedido'),
                    'updated_at': datetime.now(timezone.utc).isoformat()
                }
                # Remove chaves None para não sobrescrever dados existentes com null
                update_core = {k: v for k, v in update_core.items() if v is not None}
                self.pedidos_table.update(update_core).eq('id', core_id).execute()
            else:
                # Criar novo pedido Core
                new_core = {
                    'numero_pedido': order_data.get('numero_pedido') or external_id,
                    'codigo_pedido_externo': external_id,
                    'origem': order_data.get('origem') or platform,
                    'cliente_nome': order_data.get('cliente_nome'),
                    'cliente_documento': order_data.get('cliente_documento'),
                    'data_venda': order_data.get('data_venda') or datetime.now(timezone.utc).isoformat(),
                    'status_unificado': order_data.get('status_unificado', 'PENDENTE'),
                    'total_pedido': order_data.get('total_pedido', 0),
                    'informacoes_cliente': order_data.get('informacoes_cliente', {}),
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'updated_at': datetime.now(timezone.utc).isoformat()
                }
                res = self.pedidos_table.insert(new_core).execute()
                if not res.data:
                    raise Exception(f"Falha ao criar pedido core {external_id}")
                core_id = res.data[0]['id']

            # 2. Upsert do Vínculo de Integração
            vinculo = {
                'pedido_id': core_id,
                'plataforma': platform,
                'id_na_plataforma': platform_order_id,
                'status_na_plataforma': order_data.get('status_original'),
                'dados_brutos': raw_payload,
                'last_synced_at': datetime.now(timezone.utc).isoformat()
            }
            self.vinculos_table.upsert(vinculo, on_conflict='pedido_id,plataforma').execute()

            # 3. Processar Itens (Apenas se for novo pedido ou se itens forem fornecidos)
            if items:
                # Nota: Em uma implementação real, poderíamos verificar se os itens mudaram.
                # Para simplificar no MVP, se enviarmos itens e o pedido for novo, nós os inserimos.
                # Se o pedido já existir, poderíamos limpar e reinserir ou ignorar.
                # Aqui vamos apenas inserir se não houver itens para este pedido.
                existing_items = self.itens_table.select("id", count='exact').eq('pedido_id', core_id).execute()
                if existing_items.count == 0:
                    for item in items:
                        item_record = {
                            'pedido_id': core_id,
                            'produto_id': item.get('produto_id'),
                            'sku_externo': item.get('sku_externo'),
                            'descricao': item.get('descricao'),
                            'quantidade': item.get('quantidade', 1),
                            'preco_unitario': item.get('preco_unitario', 0),
                            'subtotal': item.get('subtotal') or (float(item.get('preco_unitario', 0)) * float(item.get('quantidade', 1))),
                            'created_at': datetime.now(timezone.utc).isoformat()
                        }
                        self.itens_table.insert(item_record).execute()

            return {"id": core_id, "external_id": external_id, "status": "success"}

        except Exception as e:
            logging.error(f"Erro no upsert_order: {str(e)}")
            raise e

    def get_order_details(self, order_id: int) -> Dict[str, Any]:
        """Retorna os detalhes completos de um pedido, incluindo itens e vínculos."""
        order = self.pedidos_table.select("*").eq('id', order_id).single().execute().data
        if not order:
            return None
            
        items = self.itens_table.select("*").eq('pedido_id', order_id).execute().data
        links = self.vinculos_table.select("*").eq('pedido_id', order_id).execute().data
        
        return {
            **order,
            "itens": items,
            "integracoes": links
        }

    def list_orders(self, page: int = 1, per_page: int = 50, filters: Dict = None) -> Dict[str, Any]:
        """Lista pedidos com paginação e filtros avançados."""
        query = self.pedidos_table.select("*, situacoes_pedido(nome, cor_status)", count='exact')
        
        if filters:
            if filters.get('origem'):
                query = query.eq('origem', filters['origem'].upper())
            if filters.get('status'):
                query = query.eq('status_unificado', filters['status'].upper())
            if filters.get('searchTerm'):
                q = filters['searchTerm']
                query = query.or_(f"cliente_nome.ilike.%{q}%,codigo_pedido_externo.ilike.%{q}%,numero_pedido.ilike.%{q}%")
            if filters.get('startDate'):
                query = query.gte('data_venda', filters['startDate'])
            if filters.get('endDate'):
                query = query.lte('data_venda', filters['endDate'])

        offset = (page - 1) * per_page
        res = query.range(offset, offset + per_page - 1).order('data_venda', desc=True).execute()
        
        return {
            "orders": res.data,
            "total": res.count,
            "page": page,
            "per_page": per_page
        }

order_service = OrderService()

