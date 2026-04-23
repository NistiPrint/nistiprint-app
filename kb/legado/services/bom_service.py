from services.firebase.firestore_client import firestore_client
from services.product_service import product_service # Importar product_service
from typing import List, Dict, Any
from models.bom import BOMItem # Assuming models/bom.py exists and defines BOMItem

class BomService:
    """Service for managing Bill of Materials (BOM) in Firestore."""

    def __init__(self):
        # Não precisamos de uma coleção 'boms' separada, pois a BOM está no documento do produto
        pass

    def sync_bom_for_product(self, product_id: str, components_data: List[Dict[str, Any]]) -> None:
        """
        Synchronizes the BOM for a given product.
        This replaces the entire existing BOM with the new data provided.
        """
        product_ref = firestore_client.collection('products').document(product_id)

        # Prepare the new BOM data in the format expected by Firestore
        new_bom = []
        for item in components_data:
            try:
                new_bom.append({
                    'product_id': item['component_id'],
                    'quantity': float(item['quantity'])
                })
            except (ValueError, KeyError) as e:
                raise ValueError(f"Invalid component data format: {item}. Error: {e}")

        # Atomically update the product with the new BOM and composite status
        is_composite = len(new_bom) > 0
        product_ref.update({
            'bom_components': new_bom,
            'is_composite': is_composite
        })

        # After updating the BOM, recalculate the product's cost
        product_service.update_composite_product_cost(product_id)

    def sync_bom_for_product(self, product_id: str, components_data: List[Dict[str, Any]]):
        """
        Atomically synchronizes the Bill of Materials for a product.
        It replaces the old BOM with the new one and updates the calculated cost.
        """
        product_ref = firestore_client.collection('products').document(product_id)

        # Format the BOM data for Firestore storage
        new_bom_list = []
        for item in components_data:
            if not all(k in item for k in ['component_id', 'quantity']):
                continue # Skip malformed items
            try:
                new_bom_list.append({
                    'product_id': item['component_id'],
                    'quantity': float(item['quantity'])
                })
            except (ValueError, TypeError):
                continue # Skip items with invalid quantity

        # Update the product document with the new BOM and composite status
        is_composite = len(new_bom_list) > 0
        product_ref.update({
            'bom_components': new_bom_list,
            'is_composite': is_composite
        })

        # After updating the BOM, trigger a cost update for this specific product
        product_service.update_composite_product_cost(product_id)

    def get_bom_for_produto(self, product_id: str) -> List[BOMItem]:
        """
        Retrieves the Bill of Materials for a given product from the product document itself.
        """
        product = product_service.get_by_id(product_id)
        if not product:
            return []

        components = []
        # A BOM está no campo 'bom_components' do documento do produto
        for item_data in product.get('bom_components', []):
            components.append(BOMItem(
                componente_id=item_data.get('product_id'), # O campo é 'product_id' no product_service
                quantidade=item_data.get('quantity') # O campo é 'quantity' no product_service
            ))
        return components

    def bulk_add_component_to_products(self, component_id: str, associations: List[Dict[str, Any]]) -> bool:
        """
        Adiciona um componente a múltiplos produtos em massa.
        associations é uma lista de dicionários com {'product_id': 'string', 'quantity': float}
        Retorna True se todos foram processados com sucesso.
        """
        if not associations:
            raise ValueError("Nenhuma associação fornecida")

        # Validações iniciais
        component = product_service.get_by_id(component_id)
        if not component:
            raise ValueError(f"Componente com ID '{component_id}' não encontrado")

        failed_associations = []

        # Verificar se todos os produtos existem antes de começar
        product_ids = [assoc['product_id'] for assoc in associations]
        products_to_associate = product_service.get_by_ids(product_ids)

        for product_id in product_ids:
            if product_id not in products_to_associate:
                raise ValueError(f"Produto com ID '{product_id}' não encontrado")

        # Processar associações uma por uma
        for association in associations:
            try:
                product_id = association['product_id']
                quantity = association.get('quantity', 1.0)

                if quantity <= 0:
                    continue  # Ignorar quantidades zero ou negativas

                # Verificar se já existe esta associação
                target_product = products_to_associate[product_id]
                existing_bom = target_product.get('bom_components', [])

                already_exists = any(
                    comp.get('product_id') == component_id for comp in existing_bom
                )

                if not already_exists:
                    # Adicionar componente usando o método do product_service
                    product_service.add_bom_component(
                        parent_product_id=product_id,
                        component_product_id=component_id,
                        quantity=quantity
                    )

            except Exception as e:
                failed_associations.append({
                    'product_id': association['product_id'],
                    'error': str(e)
                })
                continue

        if failed_associations:
            error_msg = f"Falhas na associação: {', '.join([f'{f['product_id']}: {f['error']}' for f in failed_associations])}"
            raise ValueError(error_msg)

        return True

# Global instance for use throughout the application
bom_service = BomService()
