from datetime import datetime
from google.cloud.firestore_v1.field_path import FieldPath
from google.cloud.firestore import transactional
from services.firebase.firestore_client import firestore_client
from services.ordem_producao_service import ordem_producao_service
from services.product_service import product_service
from services.canal_venda_service import canal_venda_service
from typing import List, Dict, Any, Optional

class DemandaProducaoService:
    def __init__(self):
        self.demandas_collection = firestore_client.collection('demandas_producao')

    def criar_demanda_direta(self, nome_demanda: str, canal_venda_id: str, data_entrega_str: str, lista_de_itens: list) -> Dict[str, Any]:
        """
        Cria uma demanda de produção completa no Firestore a partir de uma lista de itens.
        Para cada item, cria uma Ordem de Produção no Firestore e a associa à demanda.
        """
        # Buscar o nome do canal de venda para denormalização
        try:
            canal_venda = canal_venda_service.get_by_id(str(canal_venda_id))
            canal_venda_nome = canal_venda.get('nome') if canal_venda else ''
        except Exception as e:
            raise ValueError(f"Erro ao buscar canal de venda: {e}")

        demanda_data = {
            'nome': nome_demanda,
            'canal_venda_id': canal_venda_id,
            'canal_venda_nome': canal_venda_nome,
            'data_entrega': data_entrega_str, # Data de entrega da demanda
            'data_criacao': datetime.utcnow(),
            'status': 'Em Produção' # Status inicial da demanda
        }
        
        # Adiciona o documento da demanda principal
        demanda_ref = self.demandas_collection.document()
        demanda_ref.set(demanda_data)
        demanda_data['id'] = demanda_ref.id

        itens_criados = []
        for item_data in lista_de_itens:
            produto_id = item_data.get('produto_id')
            quantidade = item_data.get('quantidade')

            if not all([produto_id, quantidade]):
                # Rollback: delete created demand and OPs if any item data is incomplete
                self._rollback_demanda_creation(demanda_ref.id, itens_criados)
                raise ValueError("Dados de item incompletos para criar a demanda.")

            try:
                # 1. Criar a Ordem de Produção (OP) no Firestore
                op_draft = ordem_producao_service.create_draft(
                    product_id=str(produto_id), 
                    quantity_to_produce=float(quantidade)
                )
                op_iniciada = ordem_producao_service.start_production(op_draft['id'])

                # 2. Buscar dados para denormalização
                produto = product_service.get_by_id(str(produto_id))

                # 3. Criar o ItemDemandaProducao como subcoleção no Firestore
                item_doc_data = {
                    'ordem_producao_id': op_iniciada['id'],
                    'product_id': produto_id, # Adicionado para facilitar a busca
                    'canal_venda': canal_venda_nome, # Usando o nome do canal da demanda
                    'item_descricao': produto.get('name', 'Produto não encontrado'),
                    'quantidade_total': int(quantidade),
                    'data_entrega': data_entrega_str, # Usando a data de entrega da demanda
                    'capas_impressas_qtd': 0,
                    'capas_produzidas_qtd': 0,
                    'capas_prontas_retirada_qtd': 0,
                    'miolos_prontos_retirada_qtd': 0,
                    'expedicao_capas_retiradas_qtd': 0,
                    'expedicao_miolos_retirados_qtd': 0,
                    'status_item': 'Em Produção'
                }
                item_ref = demanda_ref.collection('itens_demanda').document()
                item_ref.set(item_doc_data)
                item_doc_data['id'] = item_ref.id
                itens_criados.append(item_doc_data)

            except Exception as e:
                self._rollback_demanda_creation(demanda_ref.id, itens_criados)
                raise e
        
        demanda_data['itens'] = itens_criados # Adiciona os itens criados para retorno
        return demanda_data

    def _rollback_demanda_creation(self, demanda_id: str, itens_criados: List[Dict[str, Any]]):
        """
        Tenta reverter a criação da demanda e das OPs associadas em caso de erro.
        """
        print(f"Realizando rollback para demanda {demanda_id}...")
        # 1. Deletar a demanda principal
        self.demandas_collection.document(demanda_id).delete()
        
        # 2. Tentar cancelar as OPs criadas
        for item in itens_criados:
            op_id = item.get('ordem_producao_id')
            if op_id:
                try:
                    ordem_producao_service.cancel_production(op_id)
                    print(f"OP {op_id} cancelada durante rollback.")
                except Exception as e:
                    print(f"Erro ao cancelar OP {op_id} durante rollback: {e}")
        print(f"Rollback para demanda {demanda_id} concluído.")

    def get_all_demandas(self) -> List[Dict[str, Any]]:
        """
        Retorna todas as demandas de produção do Firestore, ordenadas por data de criação,
        com o progresso percentual calculado.
        """
        docs = self.demandas_collection.order_by('data_criacao', direction='DESCENDING').stream()
        demandas = []
        for doc in docs:
            demanda_data = doc.to_dict()
            demanda_data['id'] = doc.id

            # Calculate quantitative status
            itens_docs = self.demandas_collection.document(demanda_data['id']).collection('itens_demanda').stream()
            total_quantidade = 0
            completed_quantidade = 0
            for item_doc in itens_docs:
                item_data = item_doc.to_dict()
                quantidade_total_item = item_data.get('quantidade_total', 0)
                total_quantidade += quantidade_total_item
                if item_data.get('status_item') == 'Concluído':
                    completed_quantidade += quantidade_total_item
            
            progresso_percentual = 0
            if total_quantidade > 0:
                progresso_percentual = (completed_quantidade / total_quantidade) * 100
            
            demanda_data['progresso_percentual'] = round(progresso_percentual, 2)
            demanda_data['total_quantidade'] = total_quantidade
            demanda_data['completed_quantidade'] = completed_quantidade

            demandas.append(demanda_data)
        return demandas

    def get_demanda_with_itens(self, demanda_id: str) -> Optional[Dict[str, Any]]:
        """
        Retorna uma demanda de produção específica e todos os seus itens.
        """
        demanda_doc = self.demandas_collection.document(demanda_id).get()
        if not demanda_doc.exists:
            return None

        demanda_data = demanda_doc.to_dict()
        demanda_data['id'] = demanda_doc.id

        itens_docs = self.demandas_collection.document(demanda_id).collection('itens_demanda').stream()
        itens = []
        total_quantidade = 0
        completed_quantidade = 0
        for item_doc in itens_docs:
            item_data = item_doc.to_dict()
            item_data['id'] = item_doc.id
            itens.append(item_data)

            quantidade_total_item = item_data.get('quantidade_total', 0)
            total_quantidade += quantidade_total_item
            if item_data.get('status_item') == 'Concluído':
                completed_quantidade += quantidade_total_item
        
        progresso_percentual = 0
        if total_quantidade > 0:
            progresso_percentual = (completed_quantidade / total_quantidade) * 100
        
        demanda_data['progresso_percentual'] = round(progresso_percentual, 2)
        demanda_data['total_quantidade'] = total_quantidade
        demanda_data['completed_quantidade'] = completed_quantidade

        demanda_data['itens'] = itens
        return demanda_data

    def atualizar_progresso_item(self, demanda_id: str, item_id: str, quantities_to_update: dict) -> Dict[str, Any]:
        """
        Atualiza as quantidades de progresso para um item de demanda de produção no Firestore.
        """
        item_ref = self.demandas_collection.document(demanda_id).collection('itens_demanda').document(item_id)
        item_doc = item_ref.get()

        if not item_doc.exists:
            raise ValueError(f"Item de demanda com ID {item_id} não encontrado na demanda {demanda_id}.")

        updates = {}
        for field, value in quantities_to_update.items():
            # Basic validation: ensure value is an integer and non-negative
            try:
                int_value = int(value)
                if int_value < 0:
                    raise ValueError(f"Quantidade para {field} não pode ser negativa.")
                updates[field] = int_value
            except ValueError:
                raise ValueError(f"Valor inválido para {field}. Deve ser um número inteiro.")
        
        if updates:
            item_ref.update(updates)
            updated_item_data = item_ref.get().to_dict()
            updated_item_data['id'] = item_ref.id
            return updated_item_data
        else:
            # No updates provided, return current item data
            current_item_data = item_doc.to_dict()
            current_item_data['id'] = item_doc.id
            return current_item_data

    def finalizar_item(self, demanda_id: str, item_id: str) -> Dict[str, Any]:
        """
        Finaliza um item de demanda de produção, entrega a OP associada e verifica se a demanda pai pode ser finalizada.
        """
        item_ref = self.demandas_collection.document(demanda_id).collection('itens_demanda').document(item_id)
        item_doc = item_ref.get()

        if not item_doc.exists:
            raise ValueError(f"Item de demanda com ID {item_id} não encontrado na demanda {demanda_id}.")

        item_data = item_doc.to_dict()
        op_id = item_data.get('ordem_producao_id')
        quantidade_total = item_data.get('quantidade_total')

        if not op_id or quantidade_total is None:
            raise ValueError(f"Dados incompletos para finalizar a OP associada ao item {item_id}.")

        # 1. Entregar a Ordem de Produção associada completamente
        try:
            # Assuming deliver_production handles setting OP status to COMPLETED if quantity matches
            ordem_producao_service.deliver_production(po_id=op_id, quantity_delivered=float(quantidade_total))
            print(f"OP {op_id} entregue completamente ao finalizar item {item_id}.")
        except Exception as e:
            # Log the error but allow item finalization to proceed if OP delivery is not critical path
            # Or, re-raise if OP delivery is mandatory for item finalization
            print(f"ATENÇÃO: Erro ao entregar OP {op_id} para item {item_id}: {e}")
            # Decide whether to re-raise or just log. For now, let's re-raise to ensure consistency.
            raise ValueError(f"Falha ao entregar a Ordem de Produção associada: {e}")


        # 2. Atualiza o status do item para 'Concluído'
        item_ref.update({'status_item': 'Concluído'})
        updated_item_data = item_ref.get().to_dict()
        updated_item_data['id'] = item_ref.id

        # 3. Verifica se todos os itens da demanda estão concluídos
        all_items_concluidos = True
        itens_docs = self.demandas_collection.document(demanda_id).collection('itens_demanda').stream()
        for item_in_demanda_doc in itens_docs:
            if item_in_demanda_doc.to_dict().get('status_item') != 'Concluído':
                all_items_concluidos = False
                break
        
        # 4. Se todos os itens estiverem concluídos, atualiza o status da demanda principal
        if all_items_concluidos:
            self.demandas_collection.document(demanda_id).update({'status': 'Concluído'})

        return updated_item_data
    def associar_saida_a_demanda(self, demanda_id: str, product_id: str, quantity: int):
        """
        Associa uma saída de estoque de miolos a um item de demanda, incrementando
        a quantidade de miolos prontos para retirada.
        """
        print(f"DEBUG: associar_saida_a_demanda called with demanda_id={demanda_id}, product_id={product_id}, quantity={quantity}")
        demanda_ref = self.demandas_collection.document(demanda_id)
        itens_ref = demanda_ref.collection('itens_demanda')

        # Query for the item with the matching product_id
        query = itens_ref.where('product_id', '==', product_id).limit(1)
        
        try:
            item_docs = list(query.stream())
        except Exception as e:
            print(f"ERROR: Failed to query itens_demanda for product_id {product_id} in demand {demanda_id}. Error: {e}")
            raise # Re-raise the exception to be caught by the calling function

        if not item_docs:
            print(f"WARN: No item found for product_id {product_id} in demand {demanda_id}. Cannot associate stock removal.")
            return

        item_doc = item_docs[0]
        item_ref = item_doc.reference
        print(f"DEBUG: Found item_ref {item_ref.id} for product_id {product_id} in demand {demanda_id}.")

        # Use a transaction to safely increment the quantity
        @transactional
        def update_in_transaction(transaction, item_reference, qty_to_add):
            try:
                snapshot = item_reference.get(transaction=transaction)
                current_qty = snapshot.get('miolos_prontos_retirada_qtd') or 0
                new_qty = current_qty + qty_to_add
                transaction.update(item_reference, {
                    'miolos_prontos_retirada_qtd': new_qty
                })
                print(f"DEBUG: Transaction updated item {item_reference.id}: miolos_prontos_retirada_qtd from {current_qty} to {new_qty}.")
            except Exception as e:
                print(f"ERROR: Transaction failed for item {item_reference.id}. Error: {e}")
                raise # Re-raise the exception to be caught by the calling function

        try:
            transaction = firestore_client.db.transaction()
            update_in_transaction(transaction, item_ref, quantity)
            print(f"Successfully associated removal of {quantity} of product {product_id} with demand {demanda_id}.")
        except Exception as e:
            print(f"ERROR: Failed to execute Firestore transaction for demand {demanda_id}, product {product_id}. Error: {e}")
            raise # Re-raise the exception to be caught by the calling function


    def get_demandas_by_status(self, statuses: List[str], product_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Retorna todas as demandas de produção com um dos status fornecidos, opcionalmente filtradas por produto.
        """
        print(f"DEBUG: get_demandas_by_status called with statuses: {statuses}, product_id: {product_id}")
        query = self.demandas_collection.where('status', 'in', statuses)

        if product_id:
            try:
                # First, find all demand item documents that contain the product_id
                # This requires a collection group index on 'itens_demanda' and 'product_id'
                item_docs_with_product = firestore_client.db.collection_group('itens_demanda') \
                                                    .where('product_id', '==', product_id) \
                                                    .stream()
                
                demanda_refs_with_product = set()
                for item_doc in item_docs_with_product:
                    demanda_refs_with_product.add(item_doc.reference.parent.parent)
                
                print(f"DEBUG: Found {len(demanda_refs_with_product)} unique demands with product {product_id}")

                if not demanda_refs_with_product:
                    return [] # No demands found for this product

                # Now, filter the main demands query by these demand IDs
                # Firestore 'in' query supports up to 10 values
                # If more than 10 demanda_refs_with_product, this will need to be batched
                # For simplicity, assuming less than 10 for now or handling will be added if it becomes an issue
                query = query.where(FieldPath.document_id(), 'in', list(demanda_refs_with_product))

            except Exception as e:
                print(f"ERROR: Firestore query for product_id {product_id} failed. This might require a composite index. Error: {e}")
                # Depending on the desired behavior, you might want to re-raise or return an empty list
                # For now, we'll return an empty list to prevent the application from crashing.
                return []

        docs = query.order_by('data_criacao', direction='DESCENDING').stream()
        demandas = []
        for doc in docs:
            demanda_data = doc.to_dict()
            demanda_data['id'] = doc.id
            demandas.append(demanda_data)        
        
        return demandas

    def marcar_como_coletado(self, demanda_id: str) -> Dict[str, Any]:
        """
        Marca uma demanda de produção como 'Coletado' e registra a data/hora da coleta.
        """
        demanda_ref = self.demandas_collection.document(demanda_id)
        demanda_doc = demanda_ref.get()

        if not demanda_doc.exists:
            raise ValueError(f"Demanda com ID {demanda_id} não encontrada.")

        demanda_data = demanda_doc.to_dict()

        # Apenas demandas 'Concluídas' podem ser marcadas como 'Coletado'
        if demanda_data.get('status') != 'Concluído':
            raise ValueError("Apenas demandas com status 'Concluído' podem ser marcadas como coletadas.")

        # Atualiza o status e adiciona a data da coleta
        updates = {
            'status': 'Coletado',
            'data_coleta': datetime.utcnow()
        }
        demanda_ref.update(updates)

        # Retorna os dados atualizados
        demanda_data.update(updates)
        return demanda_data

demanda_producao_service = DemandaProducaoService()
