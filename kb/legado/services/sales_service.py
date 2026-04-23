from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple
from firebase_admin import firestore
from services.firebase.firestore_client import firestore_client

class SalesService:
    """Serviço para gerenciamento de vendas do Bling"""

    def __init__(self):
        self._collection = None
        self._items_collection = None

    @property
    def collection(self):
        if self._collection is None:
            self._collection = firestore_client.collection('vendas')
        return self._collection

    @property
    def items_collection(self):
        if self._items_collection is None:
            self._items_collection = firestore_client.collection('venda_itens')
        return self._items_collection

    def create_sale(self, sale_data: Dict[str, Any]) -> str:
        """Cria nova venda/order"""
        doc_data = {
            **sale_data,
            'data_criacao': datetime.utcnow(),
            'data_atualizacao': datetime.utcnow()
        }

        doc_ref = self.collection.add(doc_data)[1]
        return doc_ref.id

    def update_sale(self, sale_id: str, update_data: Dict[str, Any]) -> bool:
        """Atualiza venda existente"""
        try:
            update_data['data_atualizacao'] = datetime.utcnow()
            self.collection.document(sale_id).update(update_data)
            return True
        except Exception:
            return False

    def get_sale_by_bling_id(self, conta_bling_id: str, bling_id: int) -> Optional[Dict[str, Any]]:
        """Busca venda por ID do Bling"""
        docs = self.collection.where('conta_bling_id', '==', conta_bling_id) \
                             .where('pedido_bling_id', '==', bling_id) \
                             .limit(1) \
                             .stream()

        for doc in docs:
            return {**doc.to_dict(), 'id': doc.id}
        return None

    def list_sales(self, conta_bling_id: Optional[int] = None, status: Optional[str] = None,
                  limit: int = 50) -> List[Dict[str, Any]]:
        """Lista vendas com filtros"""
        query = self.collection.order_by('data_emissao', direction='DESCENDING').limit(limit)

        if conta_bling_id:
            query = query.where('conta_bling_id', '==', conta_bling_id)

        if status:
            query = query.where('status', '==', status)

        docs = query.stream()
        return [{**doc.to_dict(), 'id': doc.id} for doc in docs]

    def get_sale_with_items(self, sale_id: str) -> Optional[Dict[str, Any]]:
        """Busca venda completa com itens"""
        sale_doc = self.collection.document(sale_id).get()
        if not sale_doc.exists:
            return None

        sale = {**sale_doc.to_dict(), 'id': sale_id}

        # Busca itens da venda
        items_doc = self.items_collection.where('ordem_venda_id', '==', sale_id).stream()
        sale['itens'] = [{**item.to_dict(), 'id': item.id} for item in items_doc]

        return sale

    def create_sale_item(self, sale_item_data: Dict[str, Any]) -> str:
        """Cria item de venda"""
        doc_data = {
            **sale_item_data,
            'data_criacao': datetime.utcnow()
        }

        doc_ref = self.items_collection.add(doc_data)[1]
        return doc_ref.id

    def batch_create_sale_and_items(self, sale_data: Dict[str, Any],
                                   items_data: List[Dict[str, Any]]) -> Tuple[str, List[str]]:
        """Cria venda e itens em lote transactional"""
        batch = firestore_client.db.batch()

        # Cria documento da venda
        sale_ref = self.collection.document()
        sale_doc_data = {
            **sale_data,
            'data_criacao': datetime.utcnow(),
            'data_atualizacao': datetime.utcnow()
        }
        batch.set(sale_ref, sale_doc_data)

        # Cria documentos dos itens
        item_refs = []
        for item_data in items_data:
            item_ref = self.items_collection.document()
            item_doc_data = {
                **item_data,
                'ordem_venda_id': sale_ref.id,
                'data_criacao': datetime.utcnow()
            }
            batch.set(item_ref, item_doc_data)
            item_refs.append(item_ref.id)

        # Executa batch
        batch.commit()

        return sale_ref.id, item_refs

    def get_sales_by_date_range(self, conta_bling_id: int, start_date: datetime,
                               end_date: datetime) -> List[Dict[str, Any]]:
        """Busca vendas por período"""
        docs = self.collection.where('conta_bling_id', '==', conta_bling_id) \
                             .where('data_emissao', '>=', start_date) \
                             .where('data_emissao', '<=', end_date) \
                             .order_by('data_emissao', direction='DESCENDING') \
                             .stream()
        return [{**doc.to_dict(), 'id': doc.id} for doc in docs]

    def get_sale_items(self, sale_id: str) -> List[Dict[str, Any]]:
        """Busca itens de uma venda específica"""
        docs = self.items_collection.where('ordem_venda_id', '==', sale_id).stream()
        return [{**doc.to_dict(), 'id': doc.id} for doc in docs]

sales_service = SalesService()
