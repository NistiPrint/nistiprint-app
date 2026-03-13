from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.product_service import product_service # Importar product_service
from typing import List, Dict, Any
from nistiprint_shared.models.bom import BOMItem # Assuming models/bom.py exists and defines BOMItem

class BomService:
    """Service for managing Bill of Materials (BOM) in Supabase."""

    def __init__(self):
        # Using the standardized 'ficha_tecnica' table in Supabase
        self.bom_table = supabase_db.table('ficha_tecnica')

    def sync_bom_for_product(self, product_id: int, components_data: List[Dict[str, Any]]) -> None:
        """
        Synchronizes the BOM for a given product.
        This replaces the entire existing BOM with the new data provided.
        """
        # First, delete existing BOM entries for this product
        self.bom_table.delete().eq('produto_pai_id', product_id).execute()

        # Insert new BOM entries
        for item in components_data:
            try:
                bom_entry = {
                    'produto_pai_id': product_id,
                    'componente_id': item['component_id'],
                    'quantidade_necessaria': float(item['quantity']),
                    'unidade_medida': item.get('unit', 'un')
                }
                self.bom_table.insert(bom_entry).execute()
            except (ValueError, KeyError) as e:
                raise ValueError(f"Invalid component data format: {item}. Error: {e}")

        # After updating the BOM, recalculate the product's cost with cascade propagation
        product_service.update_composite_product_cost_cascade(str(product_id))

    def get_bom_for_produto(self, product_id: int) -> List[BOMItem]:
        """
        Retrieves the Bill of Materials for a given product from the BOM table.
        If the product is a variation and has herdar_bom_pai enabled, it retrieves the BOM from the parent product.
        Also handles cases where produto_pai_id is empty by falling back to sku lookup.
        """
        from nistiprint_shared.services.product_service import product_service

        # Get the product to check if it's a variation with inheritance enabled
        product = product_service.get_by_id(str(product_id))
        is_inherited = False

        if product and product.get('parent_id') and product.get('herdar_bom_pai', False):
            # This is a variation that inherits BOM from its parent
            parent_id = product.get('parent_id')
            response = self.bom_table.select("*").eq('produto_pai_id', parent_id).execute()
            is_inherited = True
        else:
            # Regular product or variation without inheritance
            response = self.bom_table.select("*").eq('produto_pai_id', product_id).execute()

        # If no results found by ID, try to find by SKU
        if not response.data:
            # Get the product SKU to search by sku_produto_pai
            product_sku = product.get('sku') if product else None
            if product_sku:
                response = self.bom_table.select("*").eq('sku_produto_pai', product_sku).execute()

        components = []
        for row in response.data:
            # Prioritize componente_id if available, otherwise try to get by sku_componente
            componente_id = row.get('componente_id')
            if not componente_id:
                # If componente_id is not set, try to find by sku_componente
                sku_componente = row.get('sku_componente')
                if sku_componente:
                    from nistiprint_shared.services.product_service import product_service
                    componente = product_service.get_by_sku(sku_componente)
                    if componente:
                        componente_id = componente.get('id')

            # Only add to components if we have a valid componente_id
            if componente_id:
                components.append(BOMItem(
                    componente_id=componente_id,
                    quantidade=row.get('quantidade_necessaria'),
                    unit=row.get('unidade_medida', 'un'),
                    is_inherited=is_inherited
                ))
        return components

    def bulk_add_component_to_products(self, component_id: int, associations: List[Dict[str, Any]]) -> bool:
        """
        Adiciona um componente a múltiplos produtos em massa.
        associations é uma lista de dicionários com {'product_id': int, 'quantity': float}
        """
        if not associations:
            raise ValueError("Nenhuma associação fornecida")

        # Validações iniciais
        component = product_service.get_by_id(str(component_id))
        if not component:
            raise ValueError(f"Componente com ID '{component_id}' não encontrado")

        failed_associations = []

        # Processar associações uma por uma
        for association in associations:
            try:
                product_id = association['product_id']
                quantity = association.get('quantity', 1.0)

                if quantity <= 0:
                    continue  # Ignorar quantidades zero ou negativas

                # Validation: Check if product is a Parent Product
                if not product_service.can_hold_stock(str(product_id)):
                    failed_associations.append({
                        'product_id': product_id,
                        'error': "Produto Pai (Template) não pode ter Ficha Técnica direta. Use as Variações."
                    })
                    continue

                # Verificar se já existe esta associação
                existing_bom_response = self.bom_table.select("*").eq('produto_pai_id', product_id).eq('componente_id', component_id).execute()
                
                if not existing_bom_response.data:
                    # Adicionar componente à BOM
                    bom_entry = {
                        'produto_pai_id': product_id,
                        'componente_id': component_id,
                        'quantidade_necessaria': quantity,
                        'unidade_medida': 'un'  # Default unit
                    }
                    self.bom_table.insert(bom_entry).execute()
                else:
                    # Update existing entry
                    self.bom_table.update({'quantidade_necessaria': quantity}).eq('produto_pai_id', product_id).eq('componente_id', component_id).execute()

            except Exception as e:
                failed_associations.append({
                    'product_id': association['product_id'],
                    'error': str(e)
                })
                continue

        if failed_associations:
            error_msg = f"Falhas na associação: {', '.join([f['product_id'] + ': ' + f['error'] for f in failed_associations])}"
            raise ValueError(error_msg)

        return True

    def get_component_by_role(self, product_id: int, role: str) -> Dict[str, Any]:
        """
        Finds a component in a product's BOM that matches a specific role.
        Role can be 'MIOLO', 'CAPA_ACABADA', 'CAPA_IMPRESSAO'.
        """
        bom_components = self.get_bom_for_produto(product_id)
        if not bom_components:
            return None

        for bom_item in bom_components:
            component_id = bom_item.componente_id
            component_role = product_service.identify_product_role(str(component_id))
            
            if component_role == role:
                return product_service.get_by_id(str(component_id))

        return None

    def get_miolo_component_from_bom(self, product_id: int) -> Dict[str, Any]:
        """
        Finds the 'miolo' component in a product's BOM.
        """
        return self.get_component_by_role(product_id, 'MIOLO')

    def add_bom_component(self, parent_product_id: int, component_product_id: int, quantity: float, unit: str = 'un'):
        """
        Adds a single component to a product's BOM with category rule validation.
        """
        # --- Validation Start ---
        parent_product = product_service.get_by_id(str(parent_product_id))
        component_product = product_service.get_by_id(str(component_product_id))
        
        if parent_product and parent_product.get('categoria_id'):
            from nistiprint_shared.services.category_bom_rule_service import category_bom_rule_service
            regras = category_bom_rule_service.get_by_category_pai(parent_product['categoria_id'])
            
            # Find if there is a rule for the component's category
            comp_cat_id = component_product.get('categoria_id')
            if comp_cat_id:
                # Check if this category matches any rule
                # Rules can be defined for the component category or its parents (not implemented yet, keeping it simple)
                rule = next((r for r in regras if str(r['categoria_componente_id']) == str(comp_cat_id)), None)
                
                if rule:
                    # Validate max_quantidade
                    # Get current components in this rule group
                    current_bom = self.get_bom_for_produto(parent_product_id)
                    
                    # Calculate current total for this group, excluding the item being updated if it already exists
                    other_items_total = 0
                    for item in current_bom:
                        if str(item.componente_id) != str(component_product_id):
                            item_prod = product_service.get_by_id(str(item.componente_id))
                            if item_prod and str(item_prod.get('categoria_id')) == str(comp_cat_id):
                                other_items_total += item.quantidade
                    
                    # Removida restrição restritiva - regras são apenas guias.
        # --- Validation End ---

        # Check if the entry already exists
        existing_response = self.bom_table.select("*").eq('produto_pai_id', parent_product_id).eq('componente_id', component_product_id).execute()
        
        if existing_response.data:
            # Update existing entry
            self.bom_table.update({
                'quantidade_necessaria': quantity,
                'unidade_medida': unit
            }).eq('produto_pai_id', parent_product_id).eq('componente_id', component_product_id).execute()
        else:
            # Insert new entry
            bom_entry = {
                'produto_pai_id': parent_product_id,
                'componente_id': component_product_id,
                'quantidade_necessaria': quantity,
                'unidade_medida': unit
            }
            self.bom_table.insert(bom_entry).execute()

        # Update the composite cost with cascade propagation
        product_service.update_composite_product_cost_cascade(str(parent_product_id))

    def remove_bom_component(self, parent_product_id: int, component_product_id: int):
        """
        Removes a component from a product's BOM.
        """
        self.bom_table.delete().eq('produto_pai_id', parent_product_id).eq('componente_id', component_product_id).execute()

        # Update the composite cost with cascade propagation
        product_service.update_composite_product_cost_cascade(str(parent_product_id))

    def copy_bom_from_parent(self, product_id: int) -> bool:
        """
        Copies the BOM from the parent product to the current product (variation)
        and disables inheritance.
        """
        product = product_service.get_by_id(str(product_id))
        if not product or not product.get('parent_id'):
            return False

        parent_id = product.get('parent_id')
        
        # 1. Get parent's BOM
        parent_bom_resp = self.bom_table.select("*").eq('produto_pai_id', parent_id).execute()
        
        if not parent_bom_resp.data:
            # Parent has no BOM, just disable inheritance
            product_service.update(str(product_id), {'herdar_bom_pai': False})
            return True

        # 2. Delete existing entries for this child (if any)
        self.bom_table.delete().eq('produto_pai_id', product_id).execute()

        # 3. Copy entries
        new_entries = []
        for item in parent_bom_resp.data:
            new_entries.append({
                'produto_pai_id': product_id,
                'componente_id': item['componente_id'],
                'quantidade_necessaria': item['quantidade_necessaria'],
                'unidade_medida': item.get('unidade_medida', 'un'),
                'sku_produto_pai': product.get('sku'),
                'sku_componente': item.get('sku_componente')
            })
        
        if new_entries:
            self.bom_table.insert(new_entries).execute()

        # 4. Disable inheritance
        product_service.update(str(product_id), {'herdar_bom_pai': False})
        
        return True

    def get_full_bom_explosion(self, product_id: int, quantity: float = 1.0, current_depth: int = 0, max_depth: int = 10) -> List[Dict[str, Any]]:
        """
        Explode recursivamente a ficha técnica (BOM) de um produto até seus componentes básicos.
        Retorna uma lista de dicionários com 'componente_id', 'quantidade_total' e 'unidade'.
        """
        if current_depth > max_depth:
            import logging
            logging.warning(f"BOM recursion limit reached for product {product_id}. Skipping deeper levels.")
            return []

        from nistiprint_shared.services.product_service import product_service
        
        # 1. Obter componentes diretos do produto
        components = self.get_bom_for_produto(product_id)
        if not components:
            return []

        all_leaf_components = []

        # 2. Iterar sobre cada componente
        for comp in components:
            comp_id = comp.componente_id
            qtd_necessaria = comp.quantidade * quantity
            
            # Obter o produto do componente para verificar se ele também é uma composição/kit
            comp_product = product_service.get_by_id(str(comp_id))
            
            if comp_product and comp_product.get('formato') in ['composicao', 'kit']:
                # Recursão: Explodir o sub-componente
                sub_explosion = self.get_full_bom_explosion(
                    product_id=comp_id, 
                    quantity=qtd_necessaria, 
                    current_depth=current_depth + 1,
                    max_depth=max_depth
                )
                all_leaf_components.extend(sub_explosion)
            else:
                # É um componente folha (insumo ou produto simples)
                all_leaf_components.append({
                    'componente_id': comp_id,
                    'quantidade_total': qtd_necessaria,
                    'unidade': comp.unit or 'un'
                })

        # 3. Consolidar componentes duplicados (caso o mesmo insumo apareça em múltiplos ramos da árvore)
        consolidated = {}
        for item in all_leaf_components:
            cid = item['componente_id']
            if cid in consolidated:
                consolidated[cid]['quantidade_total'] += item['quantidade_total']
            else:
                consolidated[cid] = item
        
        return list(consolidated.values())

# Global instance for use throughout the application
bom_service = BomService()

