from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple
from nistiprint_shared.database.supabase_db_service import supabase_db

class SalesService:
    """Serviço para gerenciamento de vendas do Bling"""

    def __init__(self):
        self.table = supabase_db.table('vendas')
        self.items_table = supabase_db.table('venda_itens')

    def create_sale(self, sale_data: Dict[str, Any]) -> str:
        """Cria nova venda/order"""
        doc_data = {
            **sale_data,
            'created_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat()
        }

        response = self.table.insert(doc_data).execute()
        if response.data:
            return str(response.data[0]['id'])
        return None

    def update_sale(self, sale_id: str, update_data: Dict[str, Any]) -> bool:
        """Atualiza venda existente"""
        try:
            update_data['updated_at'] = datetime.utcnow().isoformat()
            response = self.table.update(update_data).eq('id', sale_id).execute()
            return len(response.data) > 0
        except Exception:
            return False

    def get_sale_by_bling_id(self, conta_bling_id: str, bling_id: int) -> Optional[Dict[str, Any]]:
        """Busca venda por ID do Bling"""
        response = self.table.select("*").eq('conta_bling_id', conta_bling_id).eq('pedido_bling_id', bling_id).limit(1).execute()

        if response.data:
            return {**dict(response.data[0]), 'id': str(response.data[0]['id'])}
        return None

    def list_sales(self, conta_bling_id: Optional[int] = None, status: Optional[str] = None,
                  limit: int = 50) -> List[Dict[str, Any]]:
        """Lista vendas com filtros"""
        query = self.table.order('data_emissao', desc=True).limit(limit)

        if conta_bling_id:
            query = query.eq('conta_bling_id', conta_bling_id)

        if status:
            query = query.eq('status', status)

        response = query.execute()
        return [{**dict(doc), 'id': str(doc['id'])} for doc in response.data]

    def get_sale_with_items(self, sale_id: str) -> Optional[Dict[str, Any]]:
        """Busca venda completa com itens"""
        response = self.table.select("*").eq('id', sale_id).execute()
        if not response.data:
            return None

        sale = {**dict(response.data[0]), 'id': str(response.data[0]['id'])}

        # Busca itens da venda
        items_response = self.items_table.select("*").eq('venda_id', sale_id).execute()
        sale['itens'] = [{**dict(item), 'id': str(item['id'])} for item in items_response.data]

        return sale

    def create_sale_item(self, sale_item_data: Dict[str, Any]) -> str:
        """Cria item de venda"""
        doc_data = {
            **sale_item_data,
            'created_at': datetime.utcnow().isoformat()
        }

        response = self.items_table.insert(doc_data).execute()
        if response.data:
            return str(response.data[0]['id'])
        return None

    def batch_create_sale_and_items(self, sale_data: Dict[str, Any],
                                   items_data: List[Dict[str, Any]]) -> Tuple[str, List[str]]:
        """Cria venda e itens em lote (Otimizado)"""
        # Cria documento da venda
        sale_doc_data = {
            **sale_data,
            'created_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat()
        }

        sale_response = supabase_db.execute_with_retry(self.table.insert(sale_doc_data))
        if not sale_response.data:
            raise Exception("Failed to create sale")

        sale_id = str(sale_response.data[0]['id'])

        # Prepara documentos dos itens para inserção EM LOTE
        items_to_insert = []
        for item_data in items_data:
            items_to_insert.append({
                **item_data,
                'venda_id': sale_id,
                'created_at': datetime.utcnow().isoformat()
            })

        if not items_to_insert:
            return sale_id, []

        # Realiza uma ÚNICA chamada para inserir todos os itens
        items_response = supabase_db.execute_with_retry(self.items_table.insert(items_to_insert))
        item_ids = [str(item['id']) for item in items_response.data]

        return sale_id, item_ids

    def get_sales_by_date_range(self, conta_bling_id: int, start_date: datetime,
                               end_date: datetime) -> List[Dict[str, Any]]:
        """Busca vendas por período"""
        response = self.table.select("*").eq('conta_bling_id', conta_bling_id) \
                             .gte('data_emissao', start_date.isoformat()) \
                             .lte('data_emissao', end_date.isoformat()) \
                             .order('data_emissao', desc=True).execute()
        return [{**dict(doc), 'id': str(doc['id'])} for doc in response.data]

    def get_sale_items(self, sale_id: str) -> List[Dict[str, Any]]:
        """Busca itens de uma venda específica"""
        response = self.items_table.select("*").eq('venda_id', sale_id).execute()
        return [{**dict(doc), 'id': str(doc['id'])} for doc in response.data]

sales_service = SalesService()

