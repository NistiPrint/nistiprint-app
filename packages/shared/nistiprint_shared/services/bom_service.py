from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.product_service import product_service # Importar product_service
from typing import List, Dict, Any
import hashlib
import json
import uuid
from decimal import Decimal, InvalidOperation
from nistiprint_shared.models.bom import BOMItem # Assuming models/bom.py exists and defines BOMItem
import logging

class BomService:
    """Service for managing Bill of Materials (BOM) in Supabase."""

    def __init__(self):
        # Using the standardized 'ficha_tecnica' table in Supabase
        self.bom_table = supabase_db.table('ficha_tecnica')

    def _update_cost_and_enqueue_cascade(self, product_id: int) -> None:
        """Update this product immediately and enqueue its dependent products."""
        product_id = str(product_id)
        product_service.update_composite_product_cost(product_id)
        try:
            from nistiprint_shared.services.celery_app import celery_app
            celery_app.send_task(
                'tasks.bom_cost_tasks.propagate_composite_cost_to_parents',
                args=[product_id],
            )
        except Exception:
            # The BOM is already persisted. Preserve cost consistency if the
            # broker is temporarily unavailable, while surfacing the incident.
            logging.exception('Falha ao enfileirar propagação de custo da BOM %s', product_id)
            product_service.propagate_composite_cost_to_parents(product_id)

    def _validate_component_can_be_used(self, component_id: int) -> Dict[str, Any]:
        component = product_service.get_by_id(str(component_id))
        if not component:
            raise ValueError(f"Componente com ID '{component_id}' nao encontrado")

        if component.get('tipo_produto') == 'PRODUTO_ACABADO':
            raise ValueError(
                f"Produto acabado nao pode ser componente de BOM: "
                f"{component.get('sku') or component.get('nome') or component_id}"
            )

        return component

    def sync_bom_for_product(self, product_id: int, components_data: List[Dict[str, Any]]) -> None:
        """
        Synchronizes the BOM for a given product.
        This replaces the entire existing BOM with the new data provided.
        """
        for item in components_data:
            try:
                self._validate_component_can_be_used(item['component_id'])
            except (ValueError, KeyError) as e:
                raise ValueError(f"Invalid component data format: {item}. Error: {e}")

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
        self._update_cost_and_enqueue_cascade(product_id)

    def get_bom_for_produto(self, product_id: int) -> List[BOMItem]:
        """Read the canonical effective BOM, including per-group inheritance."""
        if not str(product_id).isdigit():
            return []
        try:
            response = supabase_db.rpc('bom_efetiva_produto', {
                'p_produto_id': int(product_id),
            }).execute()
        except Exception as exc:
            raise RuntimeError(f'BOM_EFFECTIVE_READ_FAILED:{product_id}') from exc
        return [BOMItem(
            componente_id=row['componente_id'],
            quantidade=row['quantidade_necessaria'],
            unit=row.get('unidade_medida') or 'un',
            is_inherited=bool(row.get('is_inherited')),
            group=row.get('grupo'),
            line_id=row.get('id'),
            produto_pai_id=row.get('produto_pai_id'),
        ) for row in (response.data or [])]

    def get_bom_for_multiple_products(self, product_ids: List[int]) -> Dict[int, List[BOMItem]]:
        """
        Busca BOM de múltiplos produtos em uma única query batch.
        
        Args:
            product_ids: Lista de IDs de produtos
            
        Returns:
            Dicionário {product_id: lista_de_componentes}
        """
        if not product_ids:
            return {}
        
        # SQL is the canonical source for inherited/group-overridden BOMs.
        unique_ids = sorted(set([int(pid) for pid in product_ids if str(pid).isdigit()]))
        
        if not unique_ids:
            return {}
        
        result = {pid: [] for pid in unique_ids}
        try:
            response = supabase_db.rpc('bom_efetiva_produtos', {
                'p_produto_ids': unique_ids,
            }).execute()
        except Exception as exc:
            raise RuntimeError('BOM_EFFECTIVE_BATCH_READ_FAILED') from exc
        for row in response.data or []:
            pid = int(row['produto_id'])
            if pid in result:
                result[pid].append(BOMItem(
                    componente_id=row['componente_id'],
                    quantidade=row['quantidade_necessaria'],
                    unit=row.get('unidade_medida') or 'un',
                    is_inherited=bool(row.get('is_inherited')),
                    group=row.get('grupo'),
                    line_id=row.get('id'),
                    produto_pai_id=row.get('produto_pai_id'),
                ))
        return result

    def load_effective_graph(self, product_ids: List[int], max_depth: int = 10) -> Dict[str, Any]:
        """Carrega a BOM efetiva completa por nível, preservando linhas e herança."""
        roots = sorted({int(pid) for pid in product_ids if str(pid).isdigit()})
        if not roots:
            return {'contract_version': 1, 'roots': [], 'nodes': {}}
        graph: Dict[str, List[Dict[str, Any]]] = {}
        frontier = roots
        visited = set()
        depth = 0
        while frontier:
            current = sorted(set(frontier) - visited)
            if not current:
                break
            if depth > max_depth:
                raise ValueError(f'BOM_DEPTH_LIMIT: profundidade excede {max_depth}')
            visited.update(current)
            batch = self.get_bom_for_multiple_products(current)
            children = set()
            for product_id in current:
                lines = []
                for row in batch.get(product_id, []):
                    component_id = int(row.componente_id)
                    quantity = float(row.quantidade)
                    if quantity <= 0:
                        raise ValueError(f'BOM_INVALID_QUANTITY:{product_id}:{component_id}:{quantity}')
                    lines.append({
                        'componente_id': component_id,
                        'quantidade_necessaria': str(row.quantidade),
                        'unidade_medida': row.unit or 'un',
                        'is_inherited': bool(row.is_inherited),
                        'grupo': row.group,
                        'line_id': row.line_id,
                        'produto_pai_id': row.produto_pai_id,
                    })
                    children.add(component_id)
                graph[str(product_id)] = lines
            frontier = sorted(children - visited)
            depth += 1

        # Include conversion factors in the immutable graph, including for leaves.
        all_ids = sorted(int(value) for value in graph)
        conversions = {}
        if all_ids:
            response = supabase_db.table('conversoes_uom_produto').select(
                'produto_id,unidade_origem_id,unidade_destino_id,fator_conversao'
            ).in_('produto_id', all_ids).execute()
            for row in response.data or []:
                conversions.setdefault(str(row['produto_id']), []).append({
                    'unidade_origem_id': row['unidade_origem_id'],
                    'unidade_destino_id': row['unidade_destino_id'],
                    'fator_conversao': str(row['fator_conversao']),
                })
        nodes = {key: {'componentes': lines, 'conversoes': conversions.get(key, [])}
                 for key, lines in sorted(graph.items(), key=lambda pair: int(pair[0]))}
        result = {'contract_version': 1, 'roots': roots, 'nodes': nodes}
        self.validate_effective_graph(result)
        return result

    def validate_effective_graph(self, graph: Dict[str, Any], max_depth: int = 10) -> None:
        nodes = graph.get('nodes') or {}
        state = {}

        def visit(product_id, path):
            mark = state.get(product_id)
            if mark == 'visiting':
                cycle_start = path.index(product_id) if product_id in path else 0
                raise ValueError('BOM_CYCLE: ' + ' -> '.join(path[cycle_start:] + [product_id]))
            if mark == 'done':
                return
            if len(path) >= max_depth:
                raise ValueError(f"BOM_DEPTH_LIMIT: {' -> '.join(path + [product_id])}")
            state[product_id] = 'visiting'
            lines = (nodes.get(product_id) or {}).get('componentes') or []
            for line in lines:
                child = str(int(line['componente_id']))
                if child not in nodes:
                    raise ValueError(f'BOM_GRAPH_INCOMPLETE:{product_id}:{child}')
                if float(line['quantidade_necessaria']) <= 0:
                    raise ValueError(f'BOM_INVALID_QUANTITY:{product_id}:{child}')
                visit(child, path + [product_id])
            state[product_id] = 'done'

        for root in graph.get('roots') or []:
            visit(str(root), [])
        for product_id, node in nodes.items():
            for conversion in node.get('conversoes') or []:
                try:
                    factor = float(conversion['fator_conversao'])
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(f'BOM_CONVERSION_INVALID:{product_id}') from exc
                if factor <= 0 or factor == float('inf') or factor != factor:
                    raise ValueError(f'BOM_CONVERSION_INVALID:{product_id}:{factor}')

    def publish_effective_version(self, product_id: int, actor_id=None) -> Dict[str, Any]:
        """Publica ou reutiliza a versão imutável do grafo efetivo do produto."""
        product_id = int(product_id)
        graph = self.load_effective_graph([product_id])
        canonical = json.dumps(graph, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
        content_hash = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
        query = supabase_db.table('bom_efetiva_versoes').select('*').eq(
            'produto_id', product_id).eq('content_hash', content_hash).limit(1)
        existing = query.execute().data or []
        if existing:
            return dict(existing[0])
        record = {
            'produto_id': product_id,
            'content_hash': content_hash,
            'contract_version': 1,
            'graph': graph,
            'created_by': int(actor_id) if str(actor_id).isdigit() else None,
        }
        try:
            inserted = supabase_db.table('bom_efetiva_versoes').insert(record).execute()
            if inserted.data:
                return dict(inserted.data[0])
        except Exception:
            # Concurrent publication of the same semantic version is a benign race.
            raced = supabase_db.table('bom_efetiva_versoes').select('*').eq(
                'produto_id', product_id).eq('content_hash', content_hash).limit(1).execute().data or []
            if raced:
                return dict(raced[0])
            raise
        raise RuntimeError(f'BOM_VERSION_PUBLISH_FAILED:{product_id}')

    def get_version(self, version_id: str) -> Dict[str, Any]:
        normalized = str(uuid.UUID(str(version_id)))
        response = supabase_db.table('bom_efetiva_versoes').select('*').eq('id', normalized).limit(1).execute()
        if not response.data:
            raise ValueError(f'BOM_VERSION_NOT_FOUND:{normalized}')
        version = dict(response.data[0])
        self.validate_effective_graph(version['graph'])
        return version

    def explode_effective_version(
        self, version: Dict[str, Any], quantity: float = 1.0, max_depth: int = 10,
    ) -> List[Dict[str, Any]]:
        """Explode a published immutable graph without rereading mutable BOM rows."""
        try:
            multiplier = Decimal(str(quantity))
            product_id = int(version['produto_id'])
            graph = version['graph']
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise ValueError('BOM_VERSION_INVALID') from exc
        if not multiplier.is_finite() or multiplier <= 0:
            raise ValueError('BOM_EXPLOSION_QUANTITY_INVALID')
        self.validate_effective_graph(graph, max_depth=max_depth)
        nodes = graph.get('nodes') or {}
        leaves: Dict[int, Dict[str, Any]] = {}

        def visit(current_id: int, current_quantity: Decimal, path: List[int], depth: int) -> None:
            if current_id in path:
                raise ValueError('BOM_CYCLE: ' + ' -> '.join(map(str, path + [current_id])))
            if depth >= max_depth:
                raise ValueError(f'BOM_DEPTH_LIMIT: {" -> ".join(map(str, path + [current_id]))}')
            node = nodes.get(str(current_id))
            if node is None:
                raise ValueError(f'BOM_GRAPH_INCOMPLETE:{current_id}')
            lines = node.get('componentes') or []
            for line in lines:
                component_id = int(line['componente_id'])
                required = current_quantity * Decimal(str(line['quantidade_necessaria']))
                child_lines = (nodes.get(str(component_id)) or {}).get('componentes') or []
                if child_lines:
                    visit(component_id, required, path + [current_id], depth + 1)
                    continue
                entry = leaves.setdefault(component_id, {
                    'componente_id': component_id,
                    'quantidade_total': Decimal('0'),
                    'unidade': line.get('unidade_medida') or 'un',
                })
                if entry['unidade'] != (line.get('unidade_medida') or 'un'):
                    raise ValueError(f'BOM_UNIT_CONFLICT:{component_id}')
                entry['quantidade_total'] += required

        visit(product_id, multiplier, [], 0)
        return [
            {**entry, 'quantidade_total': format(entry['quantidade_total'].normalize(), 'f')}
            for _, entry in sorted(leaves.items())
        ]

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
        component_product = self._validate_component_can_be_used(component_product_id)
        
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
        self._update_cost_and_enqueue_cascade(parent_product_id)

    def remove_bom_component(self, parent_product_id: int, component_product_id: int):
        """
        Removes a component from a product's BOM.
        """
        self.bom_table.delete().eq('produto_pai_id', parent_product_id).eq('componente_id', component_product_id).execute()

        # Update the composite cost with cascade propagation
        self._update_cost_and_enqueue_cascade(parent_product_id)

    def copy_bom_from_parent(self, product_id: int) -> bool:
        """Keep the parent BOM inherited; variation rows override their own groups."""
        product = product_service.get_by_id(str(product_id))
        if not product or not product.get('parent_id'):
            return False
        product_service.update(str(product_id), {'herdar_bom_pai': True})
        return True

    def get_full_bom_explosion(self, product_id: int, quantity: float = 1.0, current_depth: int = 0,
                               max_depth: int = 100, _path: List[str] = None) -> List[Dict[str, Any]]:
        """
        Explode recursivamente a ficha técnica (BOM) de um produto até seus componentes básicos.
        Retorna uma lista de dicionários com 'componente_id', 'quantidade_total' e 'unidade'.
        """
        product_id = int(product_id)
        path = list(_path or [])
        product_key = str(product_id)
        if product_key in path:
            cycle = path[path.index(product_key):] + [product_key]
            raise ValueError('BOM_CYCLE: ' + ' -> '.join(cycle))
        if current_depth >= max_depth:
            raise ValueError(f'BOM_DEPTH_LIMIT: {" -> ".join(path + [product_key])}')
        path.append(product_key)

        # 1. Obter componentes diretos do produto
        components = self.get_bom_for_produto(product_id)
        if not components:
            return []

        all_leaf_components = []

        # 2. Iterar sobre cada componente
        for comp in components:
            comp_id = comp.componente_id
            qtd_necessaria = comp.quantidade * quantity
            
            # A estrutura é determinada pela ficha efetiva, não pelo formato legado.
            sub_bom = self.get_bom_for_produto(int(comp_id))
            if sub_bom:
                sub_explosion = self.get_full_bom_explosion(
                    product_id=comp_id, 
                    quantity=qtd_necessaria, 
                    current_depth=current_depth + 1,
                    max_depth=max_depth,
                    _path=path,
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
