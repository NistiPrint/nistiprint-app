from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple
from firebase_admin import firestore
from services.firebase.firestore_client import firestore_client

class OrdemCompraService:
    """Serviço para gerenciamento de ordens de compra"""

    def __init__(self):
        self._collection = None
        self._items_collection = None

    @property
    def collection(self):
        if self._collection is None:
            self._collection = firestore_client.collection('ordens_compra')
        return self._collection

    @property
    def items_collection(self):
        if self._items_collection is None:
            self._items_collection = firestore_client.collection('ordem_compra_itens')
        return self._items_collection

    def create_ordem_compra(self, oc_data: Dict[str, Any]) -> str:
        """Cria nova ordem de compra"""
        # Gera número único da OC se não fornecido
        if 'numero_oc' not in oc_data:
            oc_data['numero_oc'] = self._generate_numero_oc()

        doc_data = {
            **oc_data,
            'status': 'ABERTA',
            'data_criacao': datetime.utcnow(),
            'data_atualizacao': datetime.utcnow()
        }

        # Calcula valor total se não fornecido
        if 'valor_total' not in doc_data:
            doc_data['valor_total'] = 0

        doc_ref = self.collection.add(doc_data)[1]
        return doc_ref.id

    def update_ordem_compra(self, oc_id: str, update_data: Dict[str, Any]) -> bool:
        """Atualiza ordem de compra"""
        try:
            update_data['data_atualizacao'] = datetime.utcnow()
            self.collection.document(oc_id).update(update_data)
            return True
        except Exception:
            return False

    def get_ordem_compra(self, oc_id: str) -> Optional[Dict[str, Any]]:
        """Busca ordem de compra por ID"""
        doc = self.collection.document(oc_id).get()
        if not doc.exists:
            return None

        oc = {**doc.to_dict(), 'id': doc.id}

        # Busca itens da OC
        items_docs = self.items_collection.where('ordem_compra_id', '==', oc_id).stream()
        oc['itens'] = [{**item.to_dict(), 'id': item.id} for item in items_docs]

        return oc

    def list_ordens_compra(self, fornecedor_id: Optional[int] = None, status: Optional[str] = None,
                          limit: int = 50) -> List[Dict[str, Any]]:
        """Lista ordens de compra com filtros"""
        query = self.collection.order_by('data_emissao', direction='DESCENDING').limit(limit)

        if fornecedor_id:
            query = query.where('fornecedor_id', '==', fornecedor_id)

        if status:
            query = query.where('status', '==', status)

        docs = query.stream()
        return [{**doc.to_dict(), 'id': doc.id} for doc in docs]

    def add_item_to_ordem_compra(self, oc_id: str, item_data: Dict[str, Any]) -> str:
        """Adiciona item à ordem de compra"""
        item_doc_data = {
            **item_data,
            'ordem_compra_id': oc_id,
            'quantidade_recebida': 0,
            'data_criacao': datetime.utcnow()
        }

        doc_ref = self.items_collection.add(item_doc_data)[1]
        self._update_oc_valor_total(oc_id)
        return doc_ref.id

    def receber_item(self, item_id: str, quantidade_recebida: float,
                    deposito_id: int, usuario_id: Optional[int] = None) -> bool:
        """Registra recebimento de item da OC"""
        try:
            # Busca item atual
            item_doc = self.items_collection.document(item_id)
            item_data = item_doc.get().to_dict()

            quantidade_anterior = item_data['quantidade_recebida'] or 0
            nova_quantidade = quantidade_anterior + quantidade_recebida

            # Atualiza item
            update_data = {
                'quantidade_recebida': nova_quantidade,
                'data_ultima_recebimento': datetime.utcnow()
            }
            item_doc.update(update_data)

            # Lança entrada no estoque
            from services.estoque_service import estoque_service
            estoque_service.registrar_entrada(
                produto_id=item_data['produto_id'],
                deposito_id=deposito_id,
                quantidade=quantidade_recebida,
                observacao=f'Recebimento OC - Item {item_id}',
                ordem_compra_id=item_data['ordem_compra_id'],
                usuario_id=usuario_id
            )

            # Atualiza custo do produto (custo médio)
            self._atualizar_custo_produto(item_data['produto_id'], item_data['custo_unitario'])

            # Verifica se OC está completa
            self._check_oc_completa(item_data['ordem_compra_id'])

            return True
        except Exception as e:
            print(f"Erro no recebimento: {str(e)}")
            return False

    def cancelar_ordem_compra(self, oc_id: str) -> bool:
        """Cancela ordem de compra"""
        try:
            self.collection.document(oc_id).update({
                'status': 'CANCELADA',
                'data_atualizacao': datetime.utcnow()
            })
            return True
        except Exception:
            return False

    def _generate_numero_oc(self) -> str:
        """Gera número único para OC"""
        timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
        return f'OC{timestamp}'

    def _update_oc_valor_total(self, oc_id: str) -> None:
        """Recalcula valor total da OC"""
        try:
            # Busca todos os itens
            items_docs = self.items_collection.where('ordem_compra_id', '==', oc_id).stream()

            total = 0
            for item_doc in items_docs:
                item = item_doc.to_dict()
                quantidade = item.get('quantidade', 0)
                custo_unitario = item.get('custo_unitario', 0)
                total += quantidade * custo_unitario

            self.collection.document(oc_id).update({'valor_total': total})
        except Exception as e:
            print(f"Erro atualizando valor total: {str(e)}")

    def _check_oc_completa(self, oc_id: str) -> None:
        """Verifica se OC está completa (todos itens recebidos)"""
        try:
            items_docs = self.items_collection.where('ordem_compra_id', '==', oc_id).stream()

            todos_recebidos = True
            for item_doc in items_docs:
                item = item_doc.to_dict()
                quantidade = item.get('quantidade', 0)
                recebida = item.get('quantidade_recebida', 0)
                if recebida < quantidade:
                    todos_recebidos = False
                    break

            if todos_recebidos:
                self.collection.document(oc_id).update({
                    'status': 'FINALIZADA',
                    'data_recebimento': datetime.utcnow(),
                    'data_atualizacao': datetime.utcnow()
                })
            else:
                # Verifica se há recebimentos parciais
                algum_recebido = any(item.get('quantidade_recebida', 0) > 0 for item in items_docs)
                if algum_recebido:
                    self.collection.document(oc_id).update({
                        'status': 'RECEBIDA_PARCIAL',
                        'data_atualizacao': datetime.utcnow()
                    })
        except Exception as e:
            print(f"Erro verificando OC completa: {str(e)}")

    def _atualizar_custo_produto(self, produto_id: str, novo_custo: float) -> None:
        """Atualiza custo médio do produto"""
        from services.product_service import product_service

        try:
            # Busca custo atual do produto
            produto = product_service.get_by_id(produto_id)
            if not produto:
                return

            custo_atual = produto.get('custo', 0)

            # Busca saldo atual em estoque
            from services.estoque_service import estoque_service
            saldos = estoque_service.get_saldos_produto(produto_id)
            quantidade_total = sum(saldo['quantidade'] for saldo in saldos)

            if quantidade_total > 0:
                # Cálculo do custo médio ponderado
                # Novo custo = (quantidade_atual * custo_atual + quantidade_entrada * custo_entrada) / (quantidade_atual + quantidade_entrada)
                # Como estamos fazendo entrada incremental, simplificamos
                custo_medio = (custo_atual + novo_custo) / 2  # Simplificado - implementar cálculo completo depois

                product_service.update_custo(produto_id, custo_medio)
        except Exception as e:
            print(f"Erro atualizando custo produto: {str(e)}")

ordem_compra_service = OrdemCompraService()
