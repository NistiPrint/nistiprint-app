import math
from services.firebase.firestore_client import firestore_client
from services.category_service import category_service
from services.tag_service import tag_service
from services.unit_of_measure_service import unit_of_measure_service
from services.estoque_service import estoque_service
from datetime import datetime
from typing import List, Dict, Any
import json

class ProductService:
    """Service for managing products in Firestore with BOM support."""

    def __init__(self):
        self.collection = firestore_client.collection('products')

    def get_products(self, q: str = None, category_id: str = None, status: str = None, page: int = 1, per_page: int = 50):
        """
        Get products with optional filtering by search query (q) and category_id,
        with pagination.
        The search query 'q' is matched against the 'name' and 'sku' fields.
        """
        query = self.collection

        # If filtering by category, we avoid ordering by a second field
        # to prevent requiring a composite index in Firestore.
        # Sorting will be done in-memory after fetching.
        if category_id:
            query = query.where('category_id', '==', category_id)
        
        if status:
            query = query.where('status', '==', status)

        if not category_id and not status:
            # If not filtering by category, we can order by name.
            query = query.order_by('name')

        docs = query.stream()

        filtered_products = []
        q_lower = q.lower() if q else None

        for doc in docs:
            product_data = doc.to_dict()
            
            if q_lower:
                name_matches = q_lower in product_data.get('name', '').lower()
                sku_matches = q_lower in product_data.get('sku', '').lower()
                
                if not name_matches and not sku_matches:
                    continue

            product_data['id'] = doc.id
            filtered_products.append(product_data)

        # If we filtered by category, the results are not sorted yet.
        if category_id:
            filtered_products.sort(key=lambda p: p.get('name', ''))

        # Manual pagination on the in-memory list
        total_items = len(filtered_products)
        start_index = (page - 1) * per_page
        end_index = start_index + per_page
        
        paginated_results = filtered_products[start_index:end_index]
        
        # We also need to return total pages for the UI
        total_pages = math.ceil(total_items / per_page) if per_page > 0 else 0

        return paginated_results, total_pages

    def get_all(self, page: int = 1, per_page: int = 50):
        """Get all products with pagination."""
        docs = self.collection.order_by('name').stream()

        products = []
        skip = (page - 1) * per_page
        limit = skip + per_page

        for i, doc in enumerate(docs):
            if i < skip:
                continue
            if i >= limit and limit != skip:
                break

            product_data = doc.to_dict()
            product_data['id'] = doc.id
            products.append(product_data)

        return products

    def update_composite_product_cost(self, product_id: str):
        """Calculates and updates the cost_price for a composite product based on its BOM."""
        product_data = self.get_by_id(product_id)
        if not product_data or not product_data.get('is_composite'):
            return # Only applies to composite products

        calculated_cost = self.get_total_cost(product_data)

        # Update the product's cost_price in Firestore
        self.collection.document(product_id).update({
            'cost_price': calculated_cost,
            'updated_at': datetime.utcnow()
        })

    def get_by_id(self, product_id: str):
        """Get product by ID and enrich with real-time stock info."""
        doc = self.collection.document(product_id).get()
        if doc.exists:
            product = doc.to_dict()
            product['id'] = doc.id
            
            # Enrich with real-time stock from estoque_service
            saldos = estoque_service.get_saldos_produto(product_id)
            total_stock = sum(s.get('quantidade', 0) for s in saldos)
            product['physicalStock'] = total_stock

            return self.enrich_product_data(product)
        return None

    def get_by_ids(self, product_ids: List[str]) -> Dict[str, Any]:
        """Get multiple products by their IDs."""
        if not product_ids:
            return {}
        
        # Create a list of DocumentReference objects
        doc_refs = [self.collection.document(pid) for pid in product_ids]
        
        # Fetch documents using firestore_client.get_all
        docs = firestore_client.db.get_all(doc_refs)
        products = {}
        for doc in docs:
            if doc.exists:
                product = doc.to_dict()
                product['id'] = doc.id
                products[doc.id] = product
        return products

    def get_by_sku(self, sku: str):
        """Get product by SKU."""
        docs = self.collection.where('sku', '==', sku).stream()
        for doc in docs:
            product = doc.to_dict()
            product['id'] = doc.id
            return product
        return None

    def get_by_category(self, category_id: str):
        """Get products by category and enrich with real-time stock info."""
        docs = self.collection.where('category_id', '==', category_id).stream()
        products = []
        for doc in docs:
            product = doc.to_dict()
            product['id'] = doc.id
            
            # Enrich with real-time stock from estoque_service
            saldos = estoque_service.get_saldos_produto(doc.id)
            total_stock = sum(s.get('quantidade', 0) for s in saldos)
            product['physicalStock'] = total_stock
            
            products.append(product)
        return products

    def search(self, query: str, page: int = 1, per_page: int = 50):
        """Search products by name or SKU."""
        # Firestore doesn't have full-text search, so we'll do simple queries
        # This is a simplified search - in production you might want to use
        # Algolia or Elasticsearch for full-text search

        name_docs = self.collection.where(field='name', op='>=', value=query).where(field='name', op='<=', value=query + '\uf8ff').order_by('name').stream()
        sku_docs = self.collection.where(field='sku_mestre', op='>=', value=query).where(field='sku_mestre', op='<=', value=query + '\uf8ff').order_by('sku_mestre').stream()

        results = set()

        # Add from name search
        for doc in name_docs:
            product = doc.to_dict()
            product['id'] = doc.id
            results.add(tuple(sorted(product.items())))

        # Add from SKU search
        for doc in sku_docs:
            product = doc.to_dict()
            product['id'] = doc.id
            results.add(tuple(sorted(product.items())))

        # Convert back to list and sort by name
        products = [dict(item) for item in results]
        products.sort(key=lambda x: x.get('name', ''))

        # Apply pagination
        skip = (page - 1) * per_page
        limit = skip + per_page
        return products[skip:limit]

    def search_produtos(self, query: str, limit: int = 50, exclude_id: str = None, status: str = None):
        """Simpler search function for routes."""
        query_upper = query.upper()
        docs = self.collection.stream()
        results = []

        for doc in docs:
            if exclude_id and doc.id == exclude_id:
                continue

            product = doc.to_dict()

            if status and product.get('status') != status:
                continue

            name = product.get('name', '').upper()
            sku = product.get('sku', '').upper()

            if query_upper in name or query_upper in sku:
                product['id'] = doc.id
                results.append(product)
                if len(results) >= limit:
                    break

        return results

    def get_total_cost(self, product_data):
        """Calculate total cost of a product including BOM recursively."""
        if not product_data.get('is_composite', False):
            # Para produtos simples, usar custo informado ou 0
            return product_data.get('cost_price', 0) or 0

        # Para produtos compostos, calcular baseada APENAS nos componentes
        total_components_cost = 0
        bom = product_data.get('bom_components', [])

        for component_ref in bom:
            component = self.get_by_id(component_ref['product_id'])
            if component:
                quantity = component_ref.get('quantity', 0)
                # Custo recursivo do componente
                component_total = self.get_total_cost(component)
                total_components_cost += component_total * quantity

        return total_components_cost

    def update_composite_product_cost(self, product_id: str):
        """
        Calculates and updates the cost_price for a composite product based on its BOM.
        """
        product = self.get_by_id(product_id)
        if not product or not product.get('is_composite'):
            return  # Do nothing if the product is not composite

        calculated_cost = self.get_total_cost(product)

        self.collection.document(product_id).update({
            'cost_price': calculated_cost,
            'updated_at': datetime.utcnow()
        })

    def enrich_product_data(self, product_data):
        """Enrich product data with related information."""
        enriched = dict(product_data)

        # Map sku to sku_mestre for compatibility
        enriched['sku_mestre'] = enriched.get('sku')

        # Add category information
        if enriched.get('category_id'):
            category = category_service.get_by_id(enriched['category_id'])
            if category:
                enriched['category_name'] = category['name']

        # Add unit of measure information
        if enriched.get('unit_of_measure_id'):
            unit = unit_of_measure_service.get_by_id(enriched['unit_of_measure_id'])
            if unit:
                enriched['unit_of_measure_name'] = unit['name']
                enriched['unit_of_measure_symbol'] = unit['symbol']

        # Add tag information
        if enriched.get('tags'):
            tag_objects = []
            for tag_ref in enriched['tags']:
                tag = tag_service.get_by_id(tag_ref['tag_id'])
                if tag:
                    tag_objects.append(tag)
            enriched['tag_objects'] = tag_objects

        # Calculate total cost
        enriched['total_cost'] = self.get_total_cost(enriched)

        # For composite products, the cost_price should reflect the calculated total_cost
        if enriched.get('is_composite'):
            enriched['cost_price'] = enriched['total_cost']

        return enriched

    def create(self, product_data, product_id: str = None):
        """Create a new product."""
        # Check if SKU already exists
        if product_data['sku'] and self.get_by_sku(product_data['sku']):
            raise ValueError(f"Product with SKU '{product_data['sku']}' already exists")

        # Prepare data
        data = {
            'sku': product_data['sku'],
            'name': product_data['name'],
            'description': product_data.get('description'),
            'requires_personalization': product_data.get('requires_personalization', False),
            'sector_id': product_data.get('sector_id'),
            'bling_product_links': json.loads(product_data.get('bling_product_links_json', '[]')),
            'category_id': product_data.get('category_id'),
            'unit_of_measure_id': product_data.get('unit_of_measure_id'),
            'cost_price': product_data.get('cost_price', 0),
            'stock_min': product_data.get('stock_min'),
            'stock_max': product_data.get('stock_max'),
            'tags': product_data.get('tags', []),
            'bom_components': product_data.get('bom_components', []),
            'status': product_data.get('status', 'ativo'),
            'created_at': datetime.utcnow(),
            'updated_at': datetime.utcnow()
        }

        # Determine if product is composite
        data['is_composite'] = len(data['bom_components']) > 0

        if product_id:
            self.collection.document(product_id).set(data)
            data['id'] = product_id
        else:
            doc_ref = self.collection.add(data)[1]
            data['id'] = doc_ref.id

        return self.enrich_product_data(data)

    def update(self, product_id: str, product_data):
        """Update an existing product."""
        # Check SKU uniqueness if it's being updated
        if 'sku' in product_data:
            existing = self.get_by_sku(product_data['sku'])
            if existing and existing['id'] != product_id:
                raise ValueError(f"Product with SKU '{product_data['sku']}' already exists")

        # Get existing product
        existing = self.get_by_id(product_id)
        if not existing:
            raise ValueError(f"Product with ID '{product_id}' not found")

        # Prepare update data
        update_data = {'updated_at': datetime.utcnow()}

        field_mappings = {
            'sku': 'sku',
            'name': 'name',
            'description': 'description',
            'requires_personalization': 'requires_personalization',
            'sector_id': 'sector_id',
            'bling_product_links': json.loads(product_data.get('bling_product_links_json', '[]')),
            'category_id': 'category_id',
            'unit_of_measure_id': 'unit_of_measure_id',
            'cost_price': 'cost_price',
            'stock_min': 'stock_min',
            'stock_max': 'stock_max',
            'tags': 'tags',
            'bom_components': 'bom_components',
            'status': 'status'
        }

        for field, key in field_mappings.items():
            if field in product_data:
                update_data[key] = product_data[field]

        # Update is_composite based on BOM components
        bom_components = update_data.get('bom_components', existing.get('bom_components', []))
        update_data['is_composite'] = len(bom_components) > 0

        if update_data:  # Only update if there's data to update
            self.collection.document(product_id).update(update_data)

        # Return updated product
        updated = self.get_by_id(product_id)
        return self.enrich_product_data(updated) if updated else None

    def delete(self, product_id: str):
        """
        Deleta um produto após verificar se ele não está sendo usado em nenhuma
        Estrutura de Produto (BOM) e se seu estoque está zerado.
        """
        # 1. Verificar se o produto está sendo usado em alguma BOM
        query = self.collection.where('is_composite', '==', True)
        docs = query.stream()
        for doc in docs:
            product_data = doc.to_dict()
            for component in product_data.get('bom_components', []):
                if component.get('product_id') == product_id:
                    parent_product_name = product_data.get('name', doc.id)
                    raise ValueError(f"Produto não pode ser excluído. É um componente em '{parent_product_name}'.")

        # 2. Verificar se o estoque do produto está zerado
        saldos = estoque_service.get_saldos_produto(product_id)
        total_stock = sum(s.get('quantidade', 0) for s in saldos)
        if total_stock != 0:
            raise ValueError(f"Produto não pode ser excluído. Estoque atual é {total_stock}.")

        # 3. Se as verificações passarem, deletar o produto
        self.collection.document(product_id).delete()
        return True

    def get_bling_product_links(self, product_id: str) -> List[Dict[str, Any]]:
        """
        Retorna todos os links de produtos Bling associados a um produto interno.
        """
        product = self.get_by_id(product_id)
        if not product:
            return []
        bling_links = product.get('bling_product_links', [])
        
        # Ensure datetime objects are converted to ISO format strings for JSON serialization
        # And ensure bling_name is always a string
        for link in bling_links:
            if isinstance(link.get('created_at'), datetime):
                link['created_at'] = link['created_at'].isoformat()
            if link.get('bling_name') is None:
                link['bling_name'] = ''
        
        return bling_links

    def add_bling_product_link(self, product_id: str, bling_product_id: str, bling_sku: str, bling_account_id: str, bling_name: str = ''):
        """
        Adiciona um link de produto Bling a um produto interno.
        """
        product = self.get_by_id(product_id)
        if not product:
            raise ValueError(f"Produto interno com ID '{product_id}' não encontrado.")

        bling_links = product.get('bling_product_links', [])

        # Verifica se o link já existe para evitar duplicatas
        for link in bling_links:
            if link.get('bling_product_id') == bling_product_id and \
               link.get('bling_account_id') == bling_account_id:
                raise ValueError(f"Link para o produto Bling '{bling_product_id}' na conta '{bling_account_id}' já existe.")

        bling_links.append({
            'bling_product_id': bling_product_id,
            'bling_sku': bling_sku,
            'bling_name': bling_name,
            'bling_account_id': bling_account_id,
            'created_at': datetime.utcnow().isoformat()
        })

        self.collection.document(product_id).update({
            'bling_product_links': bling_links,
            'updated_at': datetime.utcnow()
        })
        return True

    def remove_bling_product_link(self, product_id: str, bling_product_id: str, bling_account_id: str):
        """
        Remove um link de produto Bling de um produto interno.
        """
        product = self.get_by_id(product_id)
        if not product:
            raise ValueError(f"Produto interno com ID '{product_id}' não encontrado.")

        bling_links = product.get('bling_product_links', [])
        
        # Filtra o link a ser removido
        updated_bling_links = [
            link for link in bling_links
            if not (link.get('bling_product_id') == bling_product_id and \
                    link.get('bling_account_id') == bling_account_id)
        ]

        if len(updated_bling_links) == len(bling_links):
            raise ValueError(f"Link para o produto Bling '{bling_product_id}' na conta '{bling_account_id}' não encontrado.")

        self.collection.document(product_id).update({
            'bling_product_links': updated_bling_links,
            'updated_at': datetime.utcnow()
        })
        return True

    def add_bom_component(self, parent_product_id: str, component_product_id: str, quantity: float):
        """Add a BOM component to a product."""
        if parent_product_id == component_product_id:
            raise ValueError("Product cannot be a component of itself")

        product = self.get_by_id(parent_product_id)
        if not product:
            raise ValueError(f"Parent product with ID '{parent_product_id}' not found")

        component = self.get_by_id(component_product_id)
        if not component:
            raise ValueError(f"Component product with ID '{component_product_id}' not found")

        # Add component to BOM
        bom_components = product.get('bom_components', [])
        bom_components.append({
            'product_id': component_product_id,
            'quantity': quantity
        })

        # Após adicionar componente, recalcular custo automaticamente para produtos compostos
        update_data = {'bom_components': bom_components}
        updated_product = self.update(parent_product_id, update_data)

        # Se é produto composto, atualizar cost_price automaticamente
        if updated_product and updated_product.get('is_composite'):
            calculated_cost = self.get_total_cost(updated_product)
            self.collection.document(parent_product_id).update({
                'cost_price': calculated_cost,
                'updated_at': datetime.utcnow()
            })

        return True

    def remove_all_bom_components(self, product_id: str):
        """Removes all BOM components from a product."""
        product = self.get_by_id(product_id)
        if not product:
            raise ValueError(f"Product with ID '{product_id}' not found")

        update_data = {
            'bom_components': [],
            'is_composite': False, # No components means not composite
            'updated_at': datetime.utcnow()
        }
        self.collection.document(product_id).update(update_data)

        # Recalculate cost if it was composite before
        # Fetch the updated product to get the correct 'is_composite' status after update
        updated_product_data = self.get_by_id(product_id)
        if updated_product_data and updated_product_data.get('is_composite') == False: # Check if it's now non-composite
            calculated_cost = self.get_total_cost(updated_product_data) # Recalculate with empty BOM
            self.collection.document(product_id).update({
                'cost_price': calculated_cost,
                'updated_at': datetime.utcnow()
            })
        return True

    def update_bom_component_quantity(self, parent_product_id: str, component_product_id: str, quantity: float):
        """Update the quantity of a single BOM component."""
        if quantity <= 0:
            raise ValueError("Quantity must be a positive number.")

        product = self.get_by_id(parent_product_id)
        if not product:
            raise ValueError(f"Parent product with ID '{parent_product_id}' not found")

        bom_components = product.get('bom_components', [])
        component_found = False
        for comp in bom_components:
            if comp['product_id'] == component_product_id:
                comp['quantity'] = quantity
                component_found = True
                break

        if not component_found:
            raise ValueError("Component not found in BOM")

        # Atualizar a BOM e recalcular o custo
        update_data = {'bom_components': bom_components}
        updated_product = self.update(parent_product_id, update_data)

        if updated_product and updated_product.get('is_composite'):
            self.update_composite_product_cost(parent_product_id)

        return True

    def remove_bom_component(self, parent_product_id: str, component_product_id: str):
        """Remove a BOM component from a product."""
        product = self.get_by_id(parent_product_id)
        if not product:
            raise ValueError(f"Parent product with ID '{parent_product_id}' not found")

        bom_components = product.get('bom_components', [])
        updated_bom = [comp for comp in bom_components if comp['product_id'] != component_product_id]

        if len(updated_bom) == len(bom_components):
            raise ValueError("Component not found in BOM")

        # Após remover componente, recalcular custo automaticamente
        update_data = {'bom_components': updated_bom}
        updated_product = self.update(parent_product_id, update_data)

        # Se ainda é produto composto (ou se ficou com componentes), atualizar cost_price automaticamente
        if updated_product and updated_product.get('is_composite'):
            calculated_cost = self.get_total_cost(updated_product)
            self.collection.document(parent_product_id).update({
                'cost_price': calculated_cost,
                'updated_at': datetime.utcnow()
            })

        return True

    def get_bom_components(self, product_id: str, deposito_id: str = None):
        """
        Get BOM components with full product data and real-time stock levels.
        Optimized to use batch fetching for components and stock.
        """
        product = self.get_by_id(product_id)
        if not product:
            return []

        bom_refs = product.get('bom_components', [])
        if not bom_refs:
            return []

        component_ids = [bom_ref['product_id'] for bom_ref in bom_refs]
        
        # Batch fetch all component products
        component_products_map = self.get_by_ids(component_ids)

        # Batch fetch stock data for all components
        if deposito_id:
            # Get stock from a specific deposit for all components
            component_stock_map = estoque_service.get_saldos_for_products_in_deposit(component_ids, deposito_id)
        else:
            # Get stock summed from all deposits for all components
            component_stock_map = estoque_service.get_saldos_for_products_all_deposits(component_ids)

        components = []
        for bom_ref in bom_refs:
            component_id = bom_ref['product_id']
            component = component_products_map.get(component_id)
            
            if component:
                enriched_component = self.enrich_product_data(component)
                enriched_component['bom_quantity'] = bom_ref['quantity']

                # Get stock information from the pre-fetched map
                stock_info = component_stock_map.get(component_id, {
                    'quantidade': 0,
                    'quantidade_reservada': 0,
                    'quantidade_disponivel': 0
                })
                
                enriched_component['physical_stock'] = stock_info['quantidade']
                enriched_component['reserved_stock'] = stock_info['quantidade_reservada']
                enriched_component['available_stock'] = stock_info['quantidade_disponivel']
                
                components.append(enriched_component)

        return components

    def enrich_products_with_bom_and_stock(self, products: List[Dict[str, Any]], deposito_id: str = None) -> List[Dict[str, Any]]:
        """
        Enriches a list of products with their BOM components and real-time stock levels
        in a batched manner to optimize Firestore calls.
        """
        if not products:
            return []

        all_component_ids = set()
        for product in products:
            for bom_ref in product.get('bom_components', []):
                all_component_ids.add(bom_ref['product_id'])
        
        all_component_ids_list = list(all_component_ids)

        # Batch fetch all unique component products
        component_products_map = self.get_by_ids(all_component_ids_list)

        # Batch fetch stock data for all unique components
        if deposito_id:
            component_stock_map = estoque_service.get_saldos_for_products_in_deposit(all_component_ids_list, deposito_id)
        else:
            component_stock_map = estoque_service.get_saldos_for_products_all_deposits(all_component_ids_list)

        enriched_products = []
        for product in products:
            product_with_components = dict(product) # Create a copy to avoid modifying original list item
            product_with_components['bom_components_enriched'] = []
            
            for bom_ref in product.get('bom_components', []):
                component_id = bom_ref['product_id']
                component = component_products_map.get(component_id)
                
                if component:
                    enriched_component = self.enrich_product_data(component)
                    enriched_component['bom_quantity'] = bom_ref['quantity']

                    stock_info = component_stock_map.get(component_id, {
                        'quantidade': 0,
                        'quantidade_reservada': 0,
                        'quantidade_disponivel': 0
                    })
                    
                    enriched_component['physical_stock'] = stock_info['quantidade']
                    enriched_component['reserved_stock'] = stock_info['quantidade_reservada']
                    enriched_component['available_stock'] = stock_info['quantidade_disponivel']
                    
                    product_with_components['bom_components_enriched'].append(enriched_component)
            
            enriched_products.append(product_with_components)

        return enriched_products

    def update_custo(self, product_id: str, novo_custo: float):
        """Atualiza custo do produto."""
        try:
            self.collection.document(product_id).update({
                'cost_price': novo_custo,
                'updated_at': datetime.utcnow()
            })
            # Recalcular custos dos produtos que usam este como componente
            self._atualizar_custos_recursivos(product_id)
            return True
        except Exception:
            return False

    def calcular_custo_bom(self, product_id: str):
        """Calcula custo total baseado na BOM atual."""
        product = self.get_by_id(product_id)
        if not product:
            return 0
        return self.get_total_cost(product)

    def atualizar_custos_automaticos(self):
        """Atualiza custos de todos os produtos compostos baseado em suas BOMs."""
        try:
            # Buscar todos os produtos compostos
            docs = self.collection.where('is_composite', '==', True).stream()

            atualizacoes = 0
            for doc in docs:
                product_data = doc.to_dict()
                product_id = doc.id

                custo_calculado = self.get_total_cost(product_data)
                custo_atual = product_data.get('cost_price', 0)

                # No longer update cost_price for composite products, as it's calculated on retrieval.
                # The field 'cost_price' will now only store manually entered costs for simple products.
                pass

            print(f'Custos automáticos atualizados: {atualizacoes} produtos')
            return atualizacoes

        except Exception as e:
            print(f'Erro na atualização automática de custos: {str(e)}')
            return 0

    def _atualizar_custos_recursivos(self, component_id: str):
        """Atualiza custos de produtos que usam o componente especificado."""
        try:
            # Buscar produtos que têm este componente na BOM
            # Como Firestore não suporta consultas complexas em arrays, vamos buscar todos
            # e filtrar (não ideal, mas funcional)
            all_docs = self.collection.stream()

            for doc in all_docs:
                product_data = doc.to_dict()
                product_id = doc.id

                bom_components = product_data.get('bom_components', [])
                usa_componente = any(comp.get('product_id') == component_id for comp in bom_components)

                if usa_componente:
                    # Recalcular custo para este produto
                    custo_calculado = self.get_total_cost(product_data)
                    # No longer update cost_price for composite products, as it's calculated on retrieval.
                    pass

        except Exception as e:
            print(f'Erro em atualização recursiva de custos: {str(e)}')

    def count(self):
        """Get total count of products."""
        # This is an expensive operation in Firestore
        # Consider implementing a counter collection if this is frequently called
        docs = self.collection.stream()
        return len(list(docs))

# Global instance for use throughout the application
product_service = ProductService()
