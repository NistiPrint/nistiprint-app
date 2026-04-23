from datetime import datetime
from typing import List, Dict, Any, Optional
from firebase_admin import firestore

from services.firebase.firestore_client import firestore_client
from services.product_service import product_service
from services.estoque_service import estoque_service
from services.app_config_service import app_config_service


class ProductionOrderService:
    """Serviço para gerenciamento de Ordens de Produção usando Firestore."""

    def __init__(self):
        self.collection = firestore_client.collection('ordens_producao')

    def create_draft(self, product_id: str, quantity_to_produce: float, notes: str = "") -> Dict[str, Any]:
        """Cria uma OP em rascunho."""
        if quantity_to_produce <= 0:
            raise ValueError("A quantidade a produzir deve ser positiva.")

        product = product_service.get_by_id(product_id)
        if not product:
            raise ValueError(f"Produto '{product_id}' não encontrado.")

        op_data = {
            'productId': product_id,
            'productName': product['name'],
            'productSku': product.get('sku', ''),
            'quantityToProduce': quantity_to_produce,
            'quantityProduced': 0.0,
            'status': 'DRAFT',
            'createdAt': datetime.utcnow(),
            'notes': notes
        }

        op_ref = self.collection.document()
        op_ref.set(op_data)

        op_data['id'] = op_ref.id
        return op_data

    def update_draft(self, po_id: str, quantity_to_produce: Optional[float] = None, notes: Optional[str] = None) -> Dict[str, Any]:
        """Atualiza OP em rascunho."""
        op_doc = self.collection.document(po_id).get()
        if not op_doc.exists:
            raise ValueError(f"OP '{po_id}' não encontrada.")

        op_data = op_doc.to_dict()
        if op_data['status'] != 'DRAFT':
            raise ValueError("Apenas OPs em DRAFT podem ser editadas.")

        updates = {}
        if quantity_to_produce is not None and quantity_to_produce > 0:
            updates['quantityToProduce'] = quantity_to_produce
        if notes is not None:
            updates['notes'] = notes

        if updates:
            updates['updatedAt'] = datetime.utcnow()
            self.collection.document(po_id).update(updates)
            op_data.update(updates)

        op_data['id'] = po_id
        return op_data

    def start_production(self, po_id: str) -> Dict[str, Any]:
        """Inicia a produção, verificando e reservando componentes via EstoqueService."""
        
        op_doc = self.collection.document(po_id).get()
        if not op_doc.exists:
            raise ValueError(f"OP '{po_id}' não encontrada.")

        op_data = op_doc.to_dict()
        if op_data['status'] != 'DRAFT':
            raise ValueError("Apenas OPs em DRAFT podem ser iniciadas.")

        product_id = op_data['productId']
        quantity_to_produce = op_data['quantityToProduce']

        # 1. Buscar BOM do produto com dados de estoque já enriquecidos e em tempo real
        bom_components = product_service.get_bom_components(product_id)

        # 2. Calcular necessidades e verificar estoque disponível
        needs = []
        insufficient = []
        
        # Obter o depósito de produção a partir das configurações
        deposito_id = app_config_service.get_config('default_production_deposit_id')
        if not deposito_id:
            raise ValueError("O depósito de produção padrão não está configurado. Por favor, configure-o na tela de Configurações -> Produção.")

        for comp in bom_components:
            required = comp['bom_quantity'] * quantity_to_produce
            # A verificação de 'available_stock' já foi feita na camada da rota, 
            # mas refazemos aqui para garantir a integridade da transação.
            saldo_componente = estoque_service.get_saldo_atual(comp['id'], deposito_id)
            available = saldo_componente.get('quantidade_disponivel', 0)

            if required > available:
                insufficient.append(f"{comp['name']}: necessita {required}, disponível {available} no depósito configurado")
            else:
                needs.append({
                    'componentId': comp['id'],
                    'componentName': comp['name'],
                    'quantityRequired': required,
                    'quantityConsumed': 0.0
                })

        if insufficient:
            raise ValueError(f"Estoque insuficiente para: {', '.join(insufficient)}")

        # 3. Reservar componentes usando o EstoqueService
        try:
            for need in needs:
                estoque_service.reservar_estoque(
                    produto_id=need['componentId'],
                    deposito_id=deposito_id,
                    ordem_id=po_id,
                    tipo_ordem='PRODUCAO',
                    quantidade=need['quantityRequired']
                )
        except Exception as e:
            # Tentar liberar reservas já feitas em caso de erro no meio do processo
            for need in needs:
                try:
                    estoque_service.liberar_reserva(
                        produto_id=need['componentId'],
                        deposito_id=deposito_id,
                        ordem_id=po_id
                    )
                except Exception:
                    pass  # Ignora erros na liberação como fallback
            raise  # Re-raise o erro original


        # 4. Atualizar OP e criar subcoleção de componentes
        op_ref = self.collection.document(po_id)
        updates = {
            'status': 'PENDING',
            'startedAt': datetime.utcnow()
        }
        op_ref.update(updates)

        components_ref = op_ref.collection('components')
        for need in needs:
            components_ref.document(need['componentId']).set({
                'componentName': need['componentName'],
                'quantityRequired': need['quantityRequired'],
                'quantityConsumed': need['quantityConsumed']
            })
        
        op_data.update(updates);
        op_data['id'] = po_id
        return op_data

    def deliver_production(self, po_id: str, quantity_delivered: float, user_id: Optional[int] = None) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """Entrega produção, consumindo reservas, registrando entrada do produto final e retornando um snapshot do estoque dos componentes."""
        if quantity_delivered <= 0:
            raise ValueError("Quantidade entregue deve ser positiva.")

        op_ref = self.collection.document(po_id)
        op_doc = op_ref.get()
        if not op_doc.exists:
            raise ValueError(f"OP '{po_id}' não encontrada.")

        op_data = op_doc.to_dict()
        if op_data['status'] not in ['PENDING', 'IN_PROGRESS', 'PARTIALLY_DELIVERED']:
            raise ValueError("Apenas OPs ativas podem receber entregas.")

        total_produced = op_data['quantityProduced'] + quantity_delivered
        total_to_produce = op_data['quantityToProduce']

        if total_produced > total_to_produce + 0.001: # Tolerância para float
            raise ValueError(f"Quantidade total produzida ultrapassaria o planejado: {total_produced} > {total_to_produce}")

        # Lista para armazenar o snapshot do estoque dos componentes
        component_stock_snapshot = []

        # Consumir componentes proporcionalmente
        components_ref = op_ref.collection('components')
        components_docs = list(components_ref.stream())
        consumption_proportion = quantity_delivered / total_to_produce
        
        deposito_id = app_config_service.get_config('default_production_deposit_id')
        if not deposito_id:
            raise ValueError("O depósito de produção padrão não está configurado.")

        try:
            for comp_doc in components_docs:
                comp_data = comp_doc.to_dict()
                qty_to_consume = comp_data['quantityRequired'] * consumption_proportion
                
                if qty_to_consume > 0:
                    # --- Início da Lógica de Snapshot ---
                    saldo_componente_antes = estoque_service.get_saldo_atual(comp_doc.id, deposito_id)
                    stock_before = saldo_componente_antes.get('quantidade', 0)

                    estoque_service.consumir_reserva(
                        produto_id=comp_doc.id,
                        deposito_id=deposito_id,
                        ordem_id=po_id,
                        quantidade=qty_to_consume,
                        observacao=f"Consumo para OP {po_id}",
                        usuario_id=user_id
                    )

                    stock_after = stock_before - qty_to_consume
                    
                    snapshot_item = {
                        "component_id": comp_doc.id,
                        "component_name": comp_data.get('componentName', ''),
                        "quantity_used": qty_to_consume,
                        "stock_before_production": stock_before,
                        "stock_after_production": stock_after
                    }
                    component_stock_snapshot.append(snapshot_item)
                    # --- Fim da Lógica de Snapshot ---

                    # Atualizar o consumo na subcoleção da OP
                    new_consumed = comp_data.get('quantityConsumed', 0) + qty_to_consume
                    comp_doc.reference.update({'quantityConsumed': new_consumed})

            # Registrar entrada do produto acabado
            estoque_service.registrar_entrada(
                produto_id=op_data['productId'],
                deposito_id=deposito_id,
                quantidade=quantity_delivered,
                observacao=f"Entrada de produção da OP {po_id}",
                usuario_id=user_id
            )

            # Atualizar status da OP
            new_status = 'COMPLETED' if total_produced >= total_to_produce else 'IN_PROGRESS'
            updates = {
                'quantityProduced': total_produced,
                'status': new_status,
                'updatedAt': datetime.utcnow()
            }
            if new_status == 'COMPLETED':
                updates['completedAt'] = datetime.utcnow()
            
            op_ref.update(updates)
            return self.get_by_id(po_id), component_stock_snapshot

        except Exception as e:
            # Idealmente, aqui deveria haver uma lógica de compensação para reverter as ações bem-sucedidas
            raise ValueError(f"Erro ao entregar produção: {str(e)}. O estado do estoque pode estar inconsistente.")

    def pause_production(self, po_id: str) -> Dict[str, Any]:
        """Pausa a produção."""
        op_doc = self.collection.document(po_id).get()
        if not op_doc.exists:
            raise ValueError(f"OP '{po_id}' não encontrada.")

        op_data = op_doc.to_dict()
        if op_data['status'] not in ['PENDING', 'IN_PROGRESS']:
            raise ValueError("Apenas OPs ativas podem ser pausadas.")

        self.collection.document(po_id).update({'status': 'PAUSED'})
        return self.get_by_id(po_id)

    def resume_production(self, po_id: str) -> Dict[str, Any]:
        """Retoma a produção."""
        op_doc = self.collection.document(po_id).get()
        if not op_doc.exists:
            raise ValueError(f"OP '{po_id}' não encontrada.")

        op_data = op_doc.to_dict()
        if op_data['status'] != 'PAUSED':
            raise ValueError("Apenas OPs pausadas podem ser retomadas.")

        self.collection.document(po_id).update({'status': 'IN_PROGRESS'})
        return self.get_by_id(po_id)

    def cancel_production(self, po_id: str) -> Dict[str, Any]:
        """Cancela a produção, estornando reservas via EstoqueService."""
        op_ref = self.collection.document(po_id)
        op_doc = op_ref.get()
        if not op_doc.exists:
            raise ValueError(f"OP '{po_id}' não encontrada.")

        op_data = op_doc.to_dict()
        if op_data['status'] in ['COMPLETED', 'CANCELED']:
            raise ValueError("OP já finalizada ou cancelada não pode ser cancelada novamente.")

        # Liberar todas as reservas restantes para esta OP
        components_ref = op_ref.collection('components')
        components_docs = list(components_ref.stream())
        
        deposito_id = app_config_service.get_config('default_production_deposit_id')
        if not deposito_id:
            raise ValueError("O depósito de produção padrão não está configurado.")

        # Apenas libera reservas se a OP chegou a ser iniciada (tendo componentes)
        if op_data['status'] != 'DRAFT':
            try:
                for comp_doc in components_docs:
                    # A função liberar_reserva do service já é inteligente para lidar
                    # com o que já foi consumido ou não.
                    estoque_service.liberar_reserva(
                        produto_id=comp_doc.id,
                        deposito_id=deposito_id,
                        ordem_id=po_id
                    )
            except Exception as e:
                # Log a critical error but continue to cancel the OP itself
                print(f"CRITICAL: Failed to release all stock reservations for OP {po_id}. Manual check required. Error: {str(e)}")

        # Atualizar status da OP
        op_ref.update({
            'status': 'CANCELED',
            'canceledAt': datetime.utcnow()
        })

        return self.get_by_id(po_id)

    def get_by_id(self, po_id: str) -> Optional[Dict[str, Any]]:
        """Busca OP por ID."""
        doc = self.collection.document(po_id).get()
        if doc.exists:
            op_data = doc.to_dict()
            op_data['id'] = po_id
            return op_data
        return None

    def get_all(self, status: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Lista OPs."""
        query = self.collection
        if status:
            query = query.where('status', '==', status)
        query = query.order_by('createdAt', direction='DESCENDING').limit(limit)

        ops = []
        for doc in query.stream():
            op_data = doc.to_dict()
            op_data['id'] = doc.id
            ops.append(op_data)
        return ops

    def get_components(self, po_id: str) -> List[Dict[str, Any]]:
        """Busca componentes da OP."""
        op_ref = self.collection.document(po_id)
        components = []
        for doc in op_ref.collection('components').stream():
            comp = doc.to_dict()
            comp['componentId'] = doc.id
            components.append(comp)
        return components


ordem_producao_service = ProductionOrderService()
