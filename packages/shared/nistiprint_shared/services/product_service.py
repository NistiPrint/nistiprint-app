import math
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.category_service import category_service
from nistiprint_shared.services.tag_service import tag_service
from nistiprint_shared.services.unit_of_measure_service import unit_of_measure_service
from nistiprint_shared.services.estoque_service import estoque_service
from datetime import datetime
from typing import List, Dict, Any, Optional
import json
from fuzzywuzzy import fuzz
import time
import logging

class ProductService:
    """Service for managing products in Supabase with BOM support."""

    def __init__(self):
        self.table = supabase_db.table('produtos')
        self.produtos_externos_table = supabase_db.table('produtos_externos')
        self._product_cache = {}

    def clear_cache(self):
        """Clears the in-memory product cache."""
        self._product_cache = {}

    def get_products(self, q: str = None, categoria_id: str = None, status: str = None, page: int = 1, per_page: int = 50, material_type: str = None, only_marketable: bool = False, include_variants: bool = False, enrich: bool = True, filter_by_sector_id: str = None):
        """
        Get products with batching to avoid N+1 connection issues.
        """
        query = self.table.select("*")

        if only_marketable:
            marketable_ids = category_service.get_marketable_ids()
            if marketable_ids:
                query = query.in_('categoria_id', marketable_ids)
            else:
                return [], 0

        if categoria_id:
            query = query.eq('categoria_id', categoria_id)
        if status:
            query = query.eq('status', status)
        if material_type:
            query = query.eq('tipo_material', material_type)
        if not include_variants:
            query = query.is_('parent_id', None)
        if q:
            query = query.or_(f"nome.ilike.%{q}%,sku.ilike.%{q}%")

        # Filtrar por setor responsável se especificado
        if filter_by_sector_id:
            query = query.eq('setor_responsavel_id', filter_by_sector_id)

        offset = (page - 1) * per_page
        query = query.range(offset, offset + per_page - 1)
        query = query.order('id', desc=True)

        response = supabase_db.execute_with_retry(query)
        if not response.data:
            return [], 0

        raw_products = response.data
        product_ids = [str(p['id']) for p in raw_products]
        
        # --- BATCH FETCHING ---
        all_variants = {}
        if include_variants:
            v_query = self.table.select("*").in_('parent_id', product_ids)
            v_resp = supabase_db.execute_with_retry(v_query)
            for v in v_resp.data:
                pid = str(v['parent_id'])
                if pid not in all_variants: all_variants[pid] = []
                v_data = dict(v)
                v_data['id'] = v['id']
                all_variants[pid].append(v_data)

        # Pre-fetch Categories and UOMs if enriching
        all_cats = {}
        all_uoms = {}
        if enrich:
            cat_ids = list(set([str(p['categoria_id']) for p in raw_products if p.get('categoria_id')]))
            if cat_ids:
                # We assume category_service can handle multiple or we do it here
                c_resp = supabase_db.table('categorias').select("*").in_('id', cat_ids).execute()
                all_cats = {str(c['id']): c for c in c_resp.data}
            
            uom_ids = list(set([str(p['unidade_medida_id']) for p in raw_products if p.get('unidade_medida_id')]))
            if uom_ids:
                u_resp = supabase_db.table('unidades_medida').select("*").in_('id', uom_ids).execute()
                all_uoms = {str(u['id']): u for u in u_resp.data}

        # --- ASSEMBLY ---
        products = []
        for row in raw_products:
            p_data = dict(row)
            p_id_str = str(p_data['id'])
            
            if include_variants:
                p_variants = all_variants.get(p_id_str, [])
                p_data['variants'] = p_variants
                p_data['has_variants'] = len(p_variants) > 0

            if enrich:
                # Optimized enrichment using pre-fetched data
                p_data = self._enrich_product_data_optimized(p_data, all_cats, all_uoms)
            else:
                p_data['name'] = p_data.get('nome')
                p_data['sku_mestre'] = p_data.get('sku')

            products.append(p_data)

        total_count = len(products) if len(products) < per_page else (page * per_page) + 1
        return products, math.ceil(total_count / per_page) if per_page > 0 else 1

    def _enrich_product_data_optimized(self, product, pre_fetched_cats, pre_fetched_uoms):
        """Versão otimizada do enrich_product_data que usa dados pré-carregados."""
        if not product: return product
        
        # Mapeamentos básicos
        attributes = product.get('atributos') or {}
        pricing = product.get('precificacao') or {}
        product['name'] = product.get('nome')
        product['sku_mestre'] = product.get('sku')
        product['material_type'] = product.get('tipo_material') or attributes.get('material_type', 'produto_acabado')
        product['status'] = product.get('status') if product.get('status') is not None else attributes.get('status', 'ativo')
        
        # Preços e Estoque
        product['cost_price'] = float(product.get('preco_custo') or pricing.get('cost_price', 0))
        product['price'] = float(product.get('preco_venda') or pricing.get('price', 0))
        product['stock_min'] = product.get('estoque_minimo') or attributes.get('stock_min', 0)
        
        # Categoria
        cid = str(product.get('categoria_id'))
        if cid in pre_fetched_cats:
            cat = pre_fetched_cats[cid]
            product['category_name'] = cat.get('nome')
            product['comercializavel'] = cat.get('comercializavel', False)

        # UOM
        uid = str(product.get('unidade_medida_id'))
        if uid in pre_fetched_uoms:
            uom = pre_fetched_uoms[uid]
            product['unit_name'] = uom.get('nome')
            product['unit_symbol'] = uom.get('abreviacao')

        # Setor Responsável
        setor_id = str(product.get('setor_responsavel_id'))
        if setor_id and setor_id != 'None':
            from nistiprint_shared.services.setor_service import setor_service
            setor = setor_service.get_by_id(int(setor_id))
            if setor:
                product['setor_responsavel_nome'] = setor.get('nome')

        return product



    def get_by_id(self, product_id: str):
        """Get a product by its ID."""
        # Check cache first
        if product_id in self._product_cache:
            return self._product_cache[product_id]

        try:
            query = self.table.select("*").eq('id', product_id)
            response = supabase_db.execute_with_retry(query)
            if response.data:
                product = dict(response.data[0])
                product['id'] = product.get('id')

                # Add variants to the product
                variants = self.get_variants(product_id)
                product['variants'] = variants
                product['has_variants'] = len(variants) > 0

                # Cache the result
                self._product_cache[product_id] = product
                return product
        except Exception as e:
            logging.warning(f"Error getting product by ID {product_id}: {e}")
        return None

    def get_by_sku(self, sku: str):
        """Get a product by its SKU."""
        try:
            query = self.table.select("*").eq('sku', sku)
            response = supabase_db.execute_with_retry(query)
            if response.data:
                product = dict(response.data[0])
                product['id'] = product.get('id')
                return product
        except Exception as e:
            logging.warning(f"Error getting product by SKU {sku}: {e}")
        return None

    def create(self, product_data: Dict[str, Any]):
        """Create a new product."""
        # Validate product consistency before creation
        validation_errors = self.validate_product_consistency(product_data)
        if validation_errors:
            raise ValueError(f"Validation errors: {', '.join(validation_errors)}")

        # Prepare data for insertion with normalized columns
        data = {
            'sku': product_data.get('sku'),
            'nome': product_data.get('name') or product_data.get('nome'),
            'descricao': product_data.get('description') or product_data.get('descricao'),
            'categoria_id': product_data.get('category_id') or product_data.get('categoria_id') or None,
            'tags': product_data.get('tags', []),

            # Normalized columns
            'preco_custo': float(product_data.get('cost_price') or 0),
            'preco_venda': float(product_data.get('preco') or product_data.get('price') or 0),
            'estoque_minimo': int(product_data.get('stock_min') or 0),
            'estoque_maximo': int(product_data.get('stock_max') or 0),
            'tipo_material': product_data.get('material_type'),
            'unidade_medida_id': product_data.get('unit_of_measure_id') or product_data.get('unidade_medida_id'),
            'status': product_data.get('status', 'ativo'),
            'parent_id': product_data.get('parent_id'),
            'sku_pai': product_data.get('sku_pai'),
            'setor_responsavel_id': product_data.get('setor_responsavel_id'),

            # New fields for product formats and inheritance
            'formato': product_data.get('formato', 'simples'),
            'herdar_dados_pai': product_data.get('herdar_dados_pai', True),
            'herdar_bom_pai': product_data.get('herdar_bom_pai', True),

            'created_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat()
        }

        # Handle attributes mapping (LEGACY support)
        attributes = {
            'material_type': product_data.get('material_type'),
            'stock_min': product_data.get('stock_min'),
            'stock_max': product_data.get('stock_max'),
            'requires_personalization': product_data.get('requires_personalization'),
            'unidade_medida_id': product_data.get('unit_of_measure_id') or product_data.get('unidade_medida_id')
        }
        data['atributos'] = attributes

        # Handle pricing (LEGACY support)
        pricing = {
            'cost_price': float(product_data.get('cost_price') or 0),
            'price': float(product_data.get('preco') or product_data.get('price') or 0)
        }
        data['precificacao'] = pricing

        response = self.table.insert(data).execute()
        if response.data:
            result = dict(response.data[0])
            result['id'] = result.get('id')

            # Clear cache since we've added a new product
            self.clear_cache()
            return result

        return None

    def update(self, product_id: str, product_data: Dict[str, Any]):
        """Update an existing product."""
        # Get existing product to merge with new data for validation
        current = self.get_by_id(product_id)
        if not current:
            raise ValueError(f"Product {product_id} not found")

        # Merge current and new data for validation
        merged_product_data = current.copy()
        merged_product_data.update(product_data)
        merged_product_data['id'] = product_id

        # Validate product consistency before update
        validation_errors = self.validate_product_consistency(merged_product_data)
        if validation_errors:
            raise ValueError(f"Validation errors: {', '.join(validation_errors)}")

        # Prepare update data
        update_data = {'updated_at': datetime.utcnow().isoformat()}

        # Core fields
        if 'sku' in product_data: update_data['sku'] = product_data['sku']
        if 'name' in product_data: update_data['nome'] = product_data['name']
        if 'nome' in product_data: update_data['nome'] = product_data['nome']
        if 'description' in product_data: update_data['descricao'] = product_data['description']
        if 'descricao' in product_data: update_data['descricao'] = product_data['descricao']

        # Support both names for category_id
        cat_id = product_data.get('category_id') or product_data.get('categoria_id')
        if cat_id is not None or 'category_id' in product_data or 'categoria_id' in product_data:
            update_data['categoria_id'] = cat_id if cat_id else None

        if 'tags' in product_data: update_data['tags'] = product_data['tags']

        # Normalized columns updates
        if 'cost_price' in product_data: update_data['preco_custo'] = float(product_data['cost_price'] or 0)
        if 'preco' in product_data: update_data['preco_venda'] = float(product_data['preco'] or 0)
        if 'price' in product_data: update_data['preco_venda'] = float(product_data['price'] or 0)
        if 'stock_min' in product_data: update_data['estoque_minimo'] = int(product_data['stock_min'] or 0)
        if 'stock_max' in product_data: update_data['estoque_maximo'] = int(product_data['stock_max'] or 0)
        if 'material_type' in product_data: update_data['tipo_material'] = product_data['material_type']
        if 'unit_of_measure_id' in product_data or 'unidade_medida_id' in product_data:
            update_data['unidade_medida_id'] = product_data.get('unit_of_measure_id') or product_data.get('unidade_medida_id')
        if 'status' in product_data: update_data['status'] = product_data['status']

        # New fields for product formats and inheritance
        if 'formato' in product_data: update_data['formato'] = product_data['formato']
        if 'herdar_dados_pai' in product_data: update_data['herdar_dados_pai'] = product_data['herdar_dados_pai']
        if 'herdar_bom_pai' in product_data: update_data['herdar_bom_pai'] = product_data['herdar_bom_pai']

        # Handle setor responsável
        if 'setor_responsavel_id' in product_data:
            update_data['setor_responsavel_id'] = product_data['setor_responsavel_id']

        # Get existing product to merge JSONB fields
        current = self.get_by_id(product_id)
        if not current:
            raise ValueError(f"Product {product_id} not found")

        # Merge attributes (LEGACY support)
        current_attributes = current.get('atributos') or {}
        if 'material_type' in product_data: current_attributes['material_type'] = product_data['material_type']
        if 'stock_min' in product_data: current_attributes['stock_min'] = product_data['stock_min']
        if 'stock_max' in product_data: current_attributes['stock_max'] = product_data['stock_max']
        if 'requires_personalization' in product_data: current_attributes['requires_personalization'] = product_data['requires_personalization']
        if 'unit_of_measure_id' in product_data or 'unidade_medida_id' in product_data:
             current_attributes['unidade_medida_id'] = product_data.get('unit_of_measure_id') or product_data.get('unidade_medida_id')

        update_data['atributos'] = current_attributes

        # Merge pricing (LEGACY support)
        current_pricing = current.get('precificacao') or {}
        if 'cost_price' in product_data: current_pricing['cost_price'] = float(product_data['cost_price'] or 0)
        if 'preco' in product_data: current_pricing['price'] = float(product_data['preco'] or 0)
        if 'price' in product_data: current_pricing['price'] = float(product_data['price'] or 0)

        update_data['precificacao'] = current_pricing

        # Check for external_product_links update
        if 'external_product_links' in product_data:
            current_attributes['external_product_links'] = product_data['external_product_links']
            update_data['atributos'] = current_attributes

        response = self.table.update(update_data).eq('id', product_id).execute()

        # Clear cache since we've updated a product
        self.clear_cache()

        # Return updated product
        return self.get_by_id(product_id)

    def delete(self, product_id: str):
        """Delete a product."""
        response = self.table.delete().eq('id', product_id).execute()
        
        # Clear cache since we've removed a product
        self.clear_cache()
        
        return len(response.data) > 0

    def search_produtos(self, query: str, limit: int = 20, exclude_id: str = None, status: str = None, category_id: str = None, only_marketable: bool = False, contexto: str = None, filter_by_sector_id: str = None):
        """Search for products by name or SKU with contextual filtering."""
        try:
            # Start query
            db_query = self.table.select("*")

            if query:
                db_query = db_query.or_(f"nome.ilike.%{query}%,sku.ilike.%{query}%")

            if exclude_id:
                db_query = db_query.neq('id', exclude_id)

            if category_id:
                db_query = db_query.eq('categoria_id', category_id)

            # Contextual filtering based on the 'contexto' parameter
            if contexto == 'producao':
                # For production context, filter for products marked as materia-prima/componentes
                db_query = db_query.eq('tipo_material', 'materia_prima')
            elif contexto == 'kit':
                # For kit context, allow commercializable products (finished goods)
                db_query = db_query.eq('tipo_material', 'produto_acabado')
            elif contexto == 'variacoes':
                # For variations context, exclude products that are parents of variations
                # (since parents can't be sold individually)
                db_query = db_query.eq('formato', 'simples').or_('formato.eq.variacao')
            elif contexto == 'todos':
                # No additional filtering
                pass

            if only_marketable:
                marketable_ids = category_service.get_marketable_ids()
                if marketable_ids:
                    # Supabase requires tuple format for 'in' filter with multiple values
                    db_query = db_query.in_('categoria_id', marketable_ids)
                else:
                    return []

            # Filtrar por setor responsável se especificado
            if filter_by_sector_id:
                db_query = db_query.eq('setor_responsavel_id', filter_by_sector_id)

            response = db_query.limit(limit).execute()

            products = []
            for row in response.data:
                product = dict(row)
                product['id'] = row.get('id')
                # Calculate similarity score for ranking
                name_score = fuzz.partial_ratio(query.lower(), product.get('nome', '').lower())
                sku_score = fuzz.partial_ratio(query.lower(), product.get('sku', '').lower())
                product['similarity_score'] = max(name_score, sku_score)
                products.append(product)

            # Sort by similarity score
            products.sort(key=lambda x: x['similarity_score'], reverse=True)
            return products
        except Exception as e:
            logging.warning(f"Error searching products for query {query}: {e}")
            return []

    def get_all(self, per_page: int = 9999, filter_by_sector_id: str = None):
        """Get all products."""
        query = self.table.select("*").limit(per_page)

        # Filtrar por setor responsável se especificado
        if filter_by_sector_id:
            query = query.eq('setor_responsavel_id', filter_by_sector_id)

        response = query.execute()

        products = []
        for row in response.data:
            product = dict(row)
            product['id'] = row.get('id')
            products.append(product)

        return products

    def get_by_ids(self, product_ids: List[str], filter_by_sector_id: str = None) -> Dict[str, Dict[str, Any]]:
        """
        Get multiple products by their IDs with optional sector filtering.
        """
        if not product_ids:
            return {}

        query = self.table.select("*").in_('id', product_ids)

        # Filtrar por setor responsável se especificado
        if filter_by_sector_id:
            query = query.eq('setor_responsavel_id', filter_by_sector_id)

        response = supabase_db.execute_with_retry(query)

        products = {}
        for row in response.data:
            product = dict(row)
            product['id'] = row.get('id')
            products[str(product['id'])] = product

        return products

    def get_all_identifiers_map(self) -> Dict[str, str]:
        """
        Returns a dictionary mapping all internal product SKUs to their names.
        Used for resolving miolos from external SKUs.
        """
        products = self.get_all()
        return {p.get('sku'): p.get('nome') for p in products if p.get('sku')}

    def find_internal_product(self, platform: str, external_sku: str, external_name: str) -> List[Dict[str, Any]]:
        """
        Attempts to find internal products matching an external SKU or name.
        Strategies:
        1. Exact SKU match
        2. Exact name match
        3. Fuzzy search by name or SKU
        """
        # 1. Exact SKU Match
        if external_sku:
            try:
                product = self.get_by_sku(external_sku)
                if product:
                    return [product]
            except Exception as e:
                logging.warning(f"Error searching by SKU {external_sku}: {e}")

        # 2. Exact Name Match
        if external_name:
            try:
                query = self.table.select("*").eq('nome', external_name)
                response = supabase_db.execute_with_retry(query)
                if response.data:
                    return [dict(row) for row in response.data]
            except Exception as e:
                logging.warning(f"Error searching by name {external_name}: {e}")

        # 3. Fuzzy search as fallback
        query = external_sku or external_name
        if query:
            try:
                return self.search_produtos(query, limit=5)
            except Exception as e:
                logging.warning(f"Error in fuzzy search for {query}: {e}")

        return []

    def enrich_product_data(self, product: Dict[str, Any]) -> Dict[str, Any]:
        """
        Enriches product data with details from related services (Category, Unit, etc.).
        Also maps JSONB fields to top-level keys for template/frontend compatibility.
        """
        if not product:
            return product

        # Ensure ID is string for consistency
        if 'id' in product:
            product['id'] = str(product['id'])

        # Map attributes and normalized columns to top level
        attributes = product.get('atributos') or {}
        pricing = product.get('precificacao') or {}
        
        # Alias and mapping for frontend compatibility
        product['name'] = product.get('nome')
        product['sku_mestre'] = product.get('sku')
        product['material_type'] = product.get('tipo_material') or attributes.get('material_type', 'produto_acabado')
        # Prioritize column status, fallback to attributes only if column is None/Empty
        product['status'] = product.get('status') if product.get('status') is not None else attributes.get('status', 'ativo')
        product['requires_personalization'] = attributes.get('requires_personalization', False)
        
        # Use normalized columns if available, fallback to JSON attributes
        product['stock_min'] = product.get('estoque_minimo') if product.get('estoque_minimo') is not None else attributes.get('stock_min')
        product['stock_max'] = product.get('estoque_maximo') if product.get('estoque_maximo') is not None else attributes.get('stock_max')
        product['estoque_minimo'] = product['stock_min']
        product['estoque_maximo'] = product['stock_max']
        
        # Support both naming conventions for unit ID
        product['unit_of_measure_id'] = product.get('unidade_medida_id') or attributes.get('unidade_medida_id') or attributes.get('unit_of_measure_id')
        product['unidade_medida_id'] = product['unit_of_measure_id']
        
        product['external_product_links'] = attributes.get('external_product_links', {'skus': [], 'names': [], 'ids': []})
        
        # Prioritize normalized price columns
        product['cost_price'] = float(product.get('preco_custo')) if product.get('preco_custo') is not None else pricing.get('cost_price', 0)
        product['preco_custo'] = product['cost_price']
        product['price'] = float(product.get('preco_venda')) if product.get('preco_venda') is not None else pricing.get('price', 0)
        product['preco_venda'] = product['price']

        # Enrich Category
        if product.get('categoria_id'):
            category = category_service.get_by_id(str(product['categoria_id']))
            if category:
                product['category_name'] = category.get('nome')
                product['categoria_nome'] = category.get('nome')
                product['comercializavel'] = category.get('comercializavel', False)

        # Enrich Unit of Measure
        if product.get('unidade_medida_id'):
            unit = unit_of_measure_service.get_by_id(str(product['unidade_medida_id']))
            if unit:
                product['unit_name'] = unit.get('name')
                product['unit_symbol'] = unit.get('symbol')
                product['unit_of_measure_name'] = unit.get('name')
                product['unit_of_measure_symbol'] = unit.get('symbol')

        # Check if is composite (has BOM components)
        # Note: We do a light check to avoid full BOM load if possible
        try:
            from nistiprint_shared.services.bom_service import bom_service
            # If the product id is not numeric, we skip BOM for now to avoid errors
            if str(product['id']).isdigit():
                bom_count_resp = bom_service.bom_table.select("id", count="exact").eq('produto_pai_id', int(product['id'])).execute()
                product['is_composite'] = (bom_count_resp.count or 0) > 0
            else:
                product['is_composite'] = False
        except Exception:
            product['is_composite'] = False

        # Include artworks for the product
        try:
            from nistiprint_shared.services.artwork_service import artwork_service
            artworks = artwork_service.get_artworks_for_product(product['id'])
            product['artworks'] = [artwork.to_dict(use_updated_url=True) for artwork in artworks] if artworks else []
        except Exception as e:
            logging.warning(f"Error getting artworks for product {product['id']}: {e}")
            product['artworks'] = []

        # Dynamic inheritance logic for variations
        if product.get('parent_id') and product.get('herdar_dados_pai', False):
            # Fetch parent product to inherit data
            parent_product = self.get_by_id(str(product['parent_id']))
            if parent_product:
                # Inherit fields from parent if not explicitly set in the variant
                if not product.get('nome') or product.get('nome') == '':
                    product['nome'] = parent_product.get('nome')
                    product['name'] = parent_product.get('nome')

                if not product.get('descricao') or product.get('descricao') == '':
                    product['descricao'] = parent_product.get('descricao')

                if not product.get('categoria_id'):
                    product['categoria_id'] = parent_product.get('categoria_id')
                    product['category_name'] = parent_product.get('category_name')
                    product['categoria_nome'] = parent_product.get('categoria_nome')

                if not product.get('tags') or len(product.get('tags', [])) == 0:
                    product['tags'] = parent_product.get('tags', [])

                # Inherit images if available in attributes
                parent_attributes = parent_product.get('atributos') or {}
                variant_attributes = product.get('atributos') or {}

                # Inherit images from parent if not set in variant
                if 'images' not in variant_attributes and 'images' in parent_attributes:
                    variant_attributes['images'] = parent_attributes['images']
                    product['atributos'] = variant_attributes

        # Logic for Frontend Permissions
        # Allow stock movement if it's a Variant (has parent_id) OR if it's a Simple Product (no variants)
        # Note: has_variants must be populated by the caller (e.g. get_by_id) for this to be accurate for Parent products.
        product['allow_stock_movement'] = (product.get('parent_id') is not None) or (not product.get('has_variants', False))

        return product

    # --- BOM Methods ---

    def _product_is_composite(self, product_id: str) -> bool:
        """
        Verifica se um produto é composto (possui BOM).
        """
        if not str(product_id).isdigit():
            return False
        
        from nistiprint_shared.services.bom_service import bom_service
        try:
            response = bom_service.bom_table.select("id", count="exact").eq('produto_pai_id', int(product_id)).execute()
            return (response.count or 0) > 0
        except Exception:
            return False

    def get_parent_products_using_component(self, component_id: str) -> List[str]:
        """
        Retorna lista de IDs de produtos pais que usam este componente em suas BOMs.
        """
        if not str(component_id).isdigit():
            return []
        
        from nistiprint_shared.services.bom_service import bom_service
        try:
            response = bom_service.bom_table.select("produto_pai_id").eq('componente_id', int(component_id)).execute()
            # Filtrar apenas IDs válidos (não nulos e numéricos)
            parent_ids = []
            for row in response.data:
                pid = row.get('produto_pai_id')
                if pid is not None and str(pid).isdigit():
                    parent_ids.append(str(pid))
            return list(set(parent_ids))
        except Exception as e:
            logging.error(f"Error getting parent products for component {component_id}: {e}")
            return []

    def get_bom_components(self, product_id: str, **kwargs) -> List[Dict[str, Any]]:
        """Retrieves BOM components for a product, optionally enriched with stock data."""
        from nistiprint_shared.services.bom_service import bom_service # Local import to avoid cycle

        product = self.get_by_id(product_id)
        if not product:
            return []

        # Ensure we only try to fetch BOM if ID is numeric, as per current bom_service expectations
        if not str(product['id']).isdigit():
            return []

        components = bom_service.get_bom_for_produto(int(product['id']))
        deposito_id = kwargs.get('deposito_id')
        
        # Enrich components with details
        result = []
        for comp in components:
            # comp is BOMItem object
            comp_product = self.get_by_id(str(comp.componente_id))
            
            if comp_product:
                comp_product = self.enrich_product_data(comp_product)
                item = {
                    'component_id': comp_product['id'], 
                    'id': comp_product['id'], # For backward compatibility
                    'sku': comp_product.get('sku'),
                    'name': comp_product.get('nome'),
                    'quantity': comp.quantidade,
                    'bom_quantity': comp.quantidade, # For backward compatibility
                    'unit': comp.unit,
                    'cost': comp_product.get('cost_price', 0),
                    'material_type': comp_product.get('material_type'),
                    'categoria_id': comp_product.get('categoria_id'),
                    'is_inherited': comp.is_inherited
                    }
                # Add stock info if deposit is provided
                if deposito_id:
                    from nistiprint_shared.services.estoque_service import estoque_service
                    saldo = estoque_service.get_saldo_atual(str(comp_product['id']), deposito_id)
                    item['physical_stock'] = float(saldo.get('quantidade_fisica', 0))
                    item['reserved_stock'] = float(saldo.get('quantidade_reservada', 0))
                    item['available_stock'] = float(saldo.get('quantidade_disponivel', 0))
                
                result.append(item)
        return result

    def add_bom_component(self, product_id: str, component_id: str, quantity: float):
        """Adds a component to the BOM."""
        self._validate_physical_product(str(product_id))
        from nistiprint_shared.services.bom_service import bom_service
        bom_service.add_bom_component(int(product_id), int(component_id), quantity)

    def remove_bom_component(self, product_id: str, component_id: str):
        """Removes a component from the BOM."""
        self._validate_physical_product(str(product_id))
        from nistiprint_shared.services.bom_service import bom_service
        bom_service.remove_bom_component(int(product_id), int(component_id))

    def remove_all_bom_components(self, product_id: str):
        """Removes all components from the BOM for a product."""
        self._validate_physical_product(str(product_id))
        from nistiprint_shared.services.bom_service import bom_service
        # Assuming bom_service has a way or we call delete on table
        bom_service.bom_table.delete().eq('produto_pai_id', int(product_id)).execute()
        self.update_composite_product_cost(product_id)

    def update_bom_component_quantity(self, product_id: str, component_id: str, quantity: float):
        """Updates quantity of a component in BOM."""
        self._validate_physical_product(str(product_id))
        from nistiprint_shared.services.bom_service import bom_service
        bom_service.add_bom_component(int(product_id), int(component_id), quantity)

    def update_composite_product_cost(self, product_id: str):
        """
        Updates the cost of a composite product based on its BOM (recursive calculation).
        """
        cost = self.calcular_custo_bom_recursivo(product_id)

        # Update product cost
        current = self.get_by_id(product_id)
        if current:
            pricing = current.get('precificacao') or {}
            pricing['cost_price'] = cost

            update_data = {
                'updated_at': datetime.utcnow().isoformat(),
                'precificacao': pricing,
                'preco_custo': cost # New normalized column
            }
            self.table.update(update_data).eq('id', int(product_id)).execute()
            self.clear_cache()

    def update_composite_product_cost_cascade(self, product_id: str, visited: set = None):
        """
        Atualiza o custo de um produto composto e propaga em cascata para todos
        os produtos pais que o utilizam como componente.
        
        Args:
            product_id: ID do produto para atualizar custo
            visited: Set de IDs já visitados para evitar ciclos infinitos
        """
        if visited is None:
            visited = set()
        
        # Evita ciclo infinito
        if product_id in visited:
            logging.warning(f"Ciclo detectado ao propagar custo do produto {product_id}")
            return
        
        visited.add(product_id)
        
        # Atualiza custo deste produto
        self.update_composite_product_cost(product_id)
        logging.info(f"Custo atualizado para produto {product_id}")
        
        # Encontra todos os produtos pais que usam este produto como componente
        parent_ids = self.get_parent_products_using_component(product_id)
        
        # Propaga para cada pai
        for parent_id in parent_ids:
            logging.info(f"Propagando custo de {product_id} para produto pai {parent_id}")
            self.update_composite_product_cost_cascade(parent_id, visited.copy())

    def calcular_custo_bom(self, product_id: str) -> float:
        """Calculates the total cost of BOM components."""
        components = self.get_bom_components(product_id)
        total_cost = 0.0
        for comp in components:
            qty = float(comp.get('quantity', 0))
            unit_cost = float(comp.get('cost', 0))
            total_cost += qty * unit_cost
        return total_cost

    def calcular_custo_bom_recursivo(self, product_id: str, visited: set = None) -> float:
        """
        Calcula o custo total da BOM de forma recursiva, considerando que componentes
        podem ser produtos compostos (ter sua própria BOM).
        
        Args:
            product_id: ID do produto para calcular custo
            visited: Set de IDs já visitados para evitar ciclos infinitos
        
        Returns:
            Custo total calculado
        """
        if visited is None:
            visited = set()
        
        # Evita ciclo infinito
        if product_id in visited:
            logging.warning(f"Ciclo detectado ao calcular custo do produto {product_id}")
            return 0.0
        
        visited.add(product_id)
        
        # Verifica se produto tem BOM
        if not self._product_is_composite(product_id):
            # Produto simples: retorna custo direto
            product = self.get_by_id(product_id)
            if product:
                return float(product.get('preco_custo') or product.get('cost_price') or 0.0)
            return 0.0
        
        # Produto composto: calcular custo baseado nos componentes
        components = self.get_bom_components(product_id)
        
        if not components:
            # Produto marcado como composto mas sem componentes
            return 0.0
        
        total_cost = 0.0
        for comp in components:
            comp_id = str(comp['component_id'])
            qty = float(comp.get('quantity', 0))
            
            # Verifica se componente é composto
            if self._product_is_composite(comp_id):
                # Componente é composto: calcular custo recursivamente
                unit_cost = self.calcular_custo_bom_recursivo(comp_id, visited.copy())
            else:
                # Componente simples: usar custo direto
                unit_cost = float(comp.get('cost', 0))
            
            total_cost += qty * unit_cost
        
        return total_cost

    # --- Clone Methods ---

    def clone_product(self, product_id: str, new_sku: str, new_name: str = None) -> Dict[str, Any]:
        """
        Clona um produto copiando todos os dados, incluindo BOM, artworks e links externos.
        
        Args:
            product_id: ID do produto original a ser clonado
            new_sku: SKU do novo produto clonado
            new_name: Nome do novo produto (opcional, usa o original se não fornecido)
        
        Returns:
            Dados do produto clonado
        
        Raises:
            ValueError: Se o SKU já existir ou produto original não for encontrado
        """
        # Verifica se produto original existe
        original_product = self.get_by_id(product_id)
        if not original_product:
            raise ValueError(f"Produto {product_id} não encontrado")
        
        # Verifica se novo SKU já existe
        existing = self.get_by_sku(new_sku)
        if existing:
            raise ValueError(f"SKU '{new_sku}' já está em uso")
        
        # Prepara dados do novo produto
        new_product_data = {
            'sku': new_sku,
            'nome': new_name or f"{original_product.get('nome')} (CÓPIA)",
            'descricao': original_product.get('descricao'),
            'categoria_id': original_product.get('categoria_id'),
            'tags': original_product.get('tags', []),
            'preco_custo': original_product.get('preco_custo') or 0,
            'preco_venda': original_product.get('preco_venda') or 0,
            'estoque_minimo': original_product.get('estoque_minimo') or 0,
            'estoque_maximo': original_product.get('estoque_maximo') or 0,
            'tipo_material': original_product.get('tipo_material'),
            'unidade_medida_id': original_product.get('unidade_medida_id'),
            'status': 'rascunho',  # Novo produto começa como rascunho
            'parent_id': original_product.get('parent_id'),
            'sku_pai': original_product.get('sku_pai'),
            'setor_responsavel_id': original_product.get('setor_responsavel_id'),
            'formato': original_product.get('formato') or 'simples',
            'herdar_dados_pai': original_product.get('herdar_dados_pai', True),
            'herdar_bom_pai': original_product.get('herdar_bom_pai', True),
            'atributos': original_product.get('atributos') or {},
            'precificacao': original_product.get('precificacao') or {},
        }
        
        # Cria o novo produto
        created_product = self.create(new_product_data)
        if not created_product:
            raise ValueError("Erro ao criar produto clonado")
        
        new_product_id = str(created_product['id'])
        
        # Copia a BOM (lista de componentes)
        try:
            from nistiprint_shared.services.bom_service import bom_service
            original_components = self.get_bom_components(product_id)
            
            if original_components:
                components_data = []
                for comp in original_components:
                    components_data.append({
                        'component_id': int(comp['component_id']),
                        'quantity': float(comp['quantity']),
                        'unit': comp.get('unit', 'un')
                    })
                
                if components_data:
                    bom_service.sync_bom_for_product(int(new_product_id), components_data)
                    logging.info(f"BOM copiada para produto clonado {new_product_id}")
        except Exception as e:
            logging.error(f"Erro ao copiar BOM para produto clonado {new_product_id}: {e}")
        
        # Copia artworks
        try:
            from nistiprint_shared.services.artwork_service import artwork_service
            original_artworks = artwork_service.get_artworks_for_product(product_id)
            
            if original_artworks:
                for artwork in original_artworks:
                    # Copia artwork apontando para o novo produto
                    artwork_data = {
                        'product_id': int(new_product_id),
                        'filename': artwork.filename,
                        'original_filename': artwork.original_filename,
                        'file_path': artwork.file_path,
                        'file_size': artwork.file_size,
                        'mime_type': artwork.mime_type,
                    }
                    artwork_service.create_artwork(artwork_data)
                logging.info(f"Artworks copiados para produto clonado {new_product_id}")
        except Exception as e:
            logging.error(f"Erro ao copiar artworks para produto clonado {new_product_id}: {e}")
        
        # Copia links externos (Bling, etc.)
        try:
            original_links = self.get_external_product_links(product_id)
            for link in original_links:
                try:
                    self.add_external_product_link(
                        int(new_product_id),
                        link['codigo_externo'],
                        link['plataforma'],
                        link.get('metadados')
                    )
                except ValueError:
                    # Link já existe, ignora
                    pass
            logging.info(f"Links externos copiados para produto clonado {new_product_id}")
        except Exception as e:
            logging.error(f"Erro ao copiar links externos para produto clonado {new_product_id}: {e}")
        
        # Limpa cache
        self.clear_cache()
        
        logging.info(f"Produto {product_id} clonado com sucesso para {new_product_id} (SKU: {new_sku})")
        
        return self.get_by_id(new_product_id)

    # --- External Product Links Methods ---

    def get_external_product_links(self, product_id: str, plataforma: str = None) -> List[Dict[str, Any]]:
        """Get external product links."""
        try:
            query = self.produtos_externos_table.select("*").eq('produto_id', product_id)
            if plataforma:
                query = query.eq('plataforma', plataforma)
            response = query.execute()
            return [dict(row) for row in response.data]
        except Exception as e:
            print(f"Error fetching external product links: {e}")
            return []

    def add_external_product_link(self, product_id: str, codigo_externo: str, plataforma: str, metadados: Dict[str, Any] = None):
        """Add a link to an external product."""
        data = {
            'produto_id': product_id,
            'codigo_externo': codigo_externo,
            'plataforma': plataforma,
            'metadados': metadados or {},
            'created_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat()
        }

        try:
             self.produtos_externos_table.insert(data).execute()
        except Exception as e:
             raise ValueError(f"External product link already exists or error: {e}")

    def remove_external_product_link(self, product_id: str, codigo_externo: str, plataforma: str):
        """Remove a link to an external product."""
        links = self.get_external_product_links(product_id, plataforma)
        for link in links:
            if link.get('codigo_externo') == codigo_externo and link.get('plataforma') == plataforma:
                self.produtos_externos_table.delete().eq('id', link['id']).execute()
                return

    def get_bling_product_links(self, product_id: str) -> List[Dict[str, Any]]:
        """Get Bling product links (backward compatibility)."""
        return self.get_external_product_links(product_id, 'Bling')

    def add_bling_product_link(self, product_id: str, bling_product_id: str, bling_sku: str, bling_account_id: str, bling_name: str = ''):
        """Add a link to a Bling product (backward compatibility)."""
        metadados = {
            'bling_product_id': bling_product_id,
            'bling_account_id': bling_account_id,
            'bling_name': bling_name
        }
        self.add_external_product_link(product_id, bling_sku, 'Bling', metadados)

    def remove_bling_product_link(self, product_id: str, bling_product_id: str, bling_account_id: str):
        """Remove a link to a Bling product (backward compatibility)."""
        links = self.get_bling_product_links(product_id)
        for link in links:
            config = link.get('metadados', {})
            if str(config.get('bling_product_id')) == str(bling_product_id) and str(config.get('bling_account_id')) == str(bling_account_id):
                self.produtos_externos_table.delete().eq('id', link['id']).execute()
                return

    def sync_external_product_links(self, product_id: str, links_data: Dict[str, Any]):
        """
        Synchronizes external product links for a product.
        links_data format: {'skus': ['A', 'B'], 'names': ['Name A', 'Name B'], 'ids': ['1', '2']}
        or list of dicts: [{'sku': 'A', 'name': 'Name A', ...}]
        """
        try:
            # 1. Get current links
            current_links = self.get_external_product_links(product_id)
            current_map = {(l['plataforma'], l['codigo_externo']): l for l in current_links}

            # 2. Process incoming links
            # The frontend sends a structured dict with lists (based on form implementation)
            # We need to parse this into a list of link objects
            incoming_links = []
            
            # Check if we received the 'structure of lists' format (common in existing forms)
            if isinstance(links_data, dict) and 'skus' in links_data:
                skus = links_data.get('skus', [])
                names = links_data.get('names', [])
                # We assume platform is 'Bling' for legacy compatibility if not specified
                # ideally the form should provide platform. 
                # For now, we'll try to deduce or default to Bling as per legacy behavior
                for i, sku in enumerate(skus):
                    if sku: # Ignore empty SKUs
                        name = names[i] if i < len(names) else ''
                        incoming_links.append({
                            'codigo_externo': sku,
                            'plataforma': 'Bling', # Defaulting to Bling for now as per legacy context
                            'metadados': {'bling_name': name}
                        })
            
            # 3. Identify Additions and Removals
            incoming_keys = set()
            
            for link in incoming_links:
                key = (link['plataforma'], link['codigo_externo'])
                incoming_keys.add(key)
                
                if key not in current_map:
                    # Add new link
                    self.add_external_product_link(
                        product_id=product_id,
                        codigo_externo=link['codigo_externo'],
                        plataforma=link['plataforma'],
                        metadados=link.get('metadados')
                    )
            
            # 4. Remove missing links
            # We only remove links for the platforms we are syncing (e.g. Bling)
            # to avoid accidentally deleting links from other platforms not present in this form
            platforms_in_sync = {l['plataforma'] for l in incoming_links} if incoming_links else {'Bling'}
            
            for key, existing_link in current_map.items():
                if key not in incoming_keys and existing_link['plataforma'] in platforms_in_sync:
                    self.remove_external_product_link(
                        product_id=product_id,
                        codigo_externo=existing_link['codigo_externo'],
                        plataforma=existing_link['plataforma']
                    )

        except Exception as e:
            logging.error(f"Error syncing external links for product {product_id}: {e}")
            # Don't raise, just log, so we don't break the main product update flow

    def get_artworks_for_product(self, product_id: str) -> List[Dict[str, Any]]:
        """Get all artworks associated with a product."""
        try:
            # Using Supabase session to query the ProductArtwork model
            from nistiprint_shared.models.product_artwork import ProductArtwork
            from nistiprint_shared.database.supabase_db_service import get_db_session
            with get_db_session() as session:
                artworks = session.query_model(ProductArtwork).filter_by(
                    product_id=product_id
                ).all()

            return [artwork.to_dict(use_updated_url=True) for artwork in artworks]
        except Exception as e:
            logging.warning(f"Error getting artworks for product {product_id}: {e}")
            return []

    def add_artwork_to_product(self, product_id: str, artwork_data: Dict[str, Any]) -> Dict[str, Any]:
        """Add an artwork to a product."""
        try:
            from nistiprint_shared.models.product_artwork import ProductArtwork
            from nistiprint_shared.database.supabase_db_service import get_db_session

            # Create new artwork record
            artwork = ProductArtwork(
                product_id=product_id,
                filename=artwork_data.get('filename'),
                original_filename=artwork_data.get('original_filename'),
                file_path=artwork_data.get('file_path'),
                file_size=artwork_data.get('file_size'),
                mime_type=artwork_data.get('mime_type')
            )

            with get_db_session() as session:
                session.add(artwork)
                session.commit()

            return artwork.to_dict(use_updated_url=True)
        except Exception as e:
            logging.error(f"Error adding artwork to product {product_id}: {e}")
            raise e

    def delete_artwork_from_product(self, artwork_id: str) -> bool:
        """Delete an artwork from a product."""
        try:
            from nistiprint_shared.models.product_artwork import ProductArtwork
            from nistiprint_shared.database.supabase_db_service import get_db_session

            with get_db_session() as session:
                artwork = session.query_model(ProductArtwork).filter_by(
                    id=artwork_id
                ).first()

                if not artwork:
                    return False

                # Delete the physical file if it exists
                import os
                if os.path.exists(artwork.file_path):
                    os.remove(artwork.file_path)

                session.delete(artwork)
                session.commit()

            return True
        except Exception as e:
            logging.error(f"Error deleting artwork {artwork_id}: {e}")
            return False

    # --- Variations Methods ---

    def has_variants(self, product_id: str) -> bool:
        """Check if a product has variants (is a Parent Product)."""
        try:
            # We use count='exact' and head=True to avoid fetching data
            response = self.table.select("id", count="exact").eq('parent_id', product_id).limit(1).execute()
            count = response.count if response.count is not None else len(response.data)
            return count > 0
        except Exception as e:
            logging.warning(f"Error checking variants for {product_id}: {e}")
            return False

    def identify_product_role(self, product_id: str) -> str:
        """
        Classifica o papel do produto na produção baseado nas categorias configuradas.
        Retorna: 'MIOLO', 'CAPA_ACABADA', 'CAPA_IMPRESSAO' ou 'OUTRO'.
        """
        from nistiprint_shared.services.app_config_service import app_config_service
        
        product = self.get_by_id(product_id)
        if not product:
            return 'OUTRO'
            
        cat_id = str(product.get('categoria_id'))
        
        # Busca configurações
        miolo_cat = str(app_config_service.get_config('producao_miolos_category_id') or '6')
        capa_cat = str(app_config_service.get_config('producao_capas_category_id') or '12')
        impressao_cat = str(app_config_service.get_config('producao_capas_impressas_category_id') or '13')
        
        if cat_id == miolo_cat:
            return 'MIOLO'
        elif cat_id == capa_cat:
            return 'CAPA_ACABADA'
        elif cat_id == impressao_cat:
            return 'CAPA_IMPRESSAO'
            
        # Fallback por nome se a categoria não estiver setada corretamente
        nome = product.get('nome', '').lower()
        if 'miolo' in nome: return 'MIOLO'
        if 'capa' in nome:
            if 'impress' in nome: return 'CAPA_IMPRESSAO'
            return 'CAPA_ACABADA'
            
        return 'OUTRO'

    def can_hold_stock(self, product_id: str) -> bool:
        """
        Determine if a product can hold stock.
        Returns:
            True: If it's a Variant OR a Simple Product (no variants).
            False: If it's a Parent Product (has variants).
        """
        product = self.get_by_id(product_id)
        if not product:
            return False

        # If it has a parent_id, it is a Variant -> Can hold stock
        if product.get('parent_id'):
            return True

        # If it has no parent_id, it might be a Simple Product or a Parent Product
        if self.has_variants(product_id):
            return False  # It is a Parent Product -> Cannot hold stock directly

        return True  # It is a Simple Product -> Can hold stock

    def _validate_physical_product(self, product_id: str):
        """Validates if the product is a physical SKU (Simple or Variant) suitable for BOM/Stock."""
        if not self.can_hold_stock(product_id):
            raise ValueError("O Produto Pai (Template) não pode ter Ficha Técnica ou Estoque direto. Utilize as Variações.")

    def get_variants(self, parent_id: str) -> List[Dict[str, Any]]:
        """Get all variants for a parent product."""
        try:
            response = self.table.select("*").eq('parent_id', parent_id).execute()
            variants = []
            for row in response.data:
                variant = dict(row)
                variant['id'] = row.get('id')
                variants.append(variant)
            return variants
        except Exception as e:
            logging.warning(f"Error getting variants for parent {parent_id}: {e}")
            return []

    def create_variant(self, parent_id: str, variant_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new product variant."""
        sku = variant_data.get('sku')
        if sku:
            existing = self.get_by_sku(sku)
            if existing:
                 raise ValueError(f"SKU '{sku}' já existe no sistema.")

        # Get parent to inherit properties
        parent = self.get_by_id(parent_id)
        if not parent:
            raise ValueError(f"Parent product {parent_id} not found")

        # Prepare data for insertion with normalized columns
        data = {
            'sku': sku,
            'nome': variant_data.get('name') or variant_data.get('nome'),
            'descricao': variant_data.get('description') or variant_data.get('descricao') or parent.get('descricao'),
            'categoria_id': variant_data.get('category_id') or variant_data.get('categoria_id') or parent.get('categoria_id'),
            'tags': variant_data.get('tags') or parent.get('tags', []),
            'parent_id': parent_id,

            # Normalized columns
            'preco_custo': float(variant_data.get('cost_price') or variant_data.get('preco_custo') or parent.get('preco_custo') or 0),
            'preco_venda': float(variant_data.get('preco') or variant_data.get('price') or variant_data.get('preco_venda') or parent.get('preco_venda') or 0),
            'estoque_minimo': int(variant_data.get('stock_min') or variant_data.get('estoque_minimo') or 0),
            'estoque_maximo': int(variant_data.get('stock_max') or variant_data.get('estoque_maximo') or 0),
            'tipo_material': variant_data.get('material_type') or parent.get('tipo_material') or 'produto_acabado',
            'unidade_medida_id': variant_data.get('unit_of_measure_id') or variant_data.get('unidade_medida_id') or parent.get('unidade_medida_id'),

            # New fields for product formats and inheritance
            'formato': 'variacao',  # Variants always have this formato
            'herdar_dados_pai': variant_data.get('herdar_dados_pai', True),
            'herdar_bom_pai': variant_data.get('herdar_bom_pai', True),

            'created_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat()
        }

        # Validate the variant before creation
        validation_errors = self.validate_product_consistency(data)
        if validation_errors:
            raise ValueError(f"Validation errors: {', '.join(validation_errors)}")

        # Handle attributes mapping (LEGACY support)
        parent_attrs = parent.get('atributos') or {}
        variation_values = variant_data.get('variation_values') or {}
        
        attributes = {
            'material_type': data['tipo_material'],
            'stock_min': data['estoque_minimo'],
            'stock_max': data['estoque_maximo'],
            'requires_personalization': variant_data.get('requires_personalization') or parent_attrs.get('requires_personalization', False),
            'unidade_medida_id': data['unidade_medida_id'],
            'variation_values': variation_values
        }
        data['atributos'] = attributes

        # Handle pricing (LEGACY support)
        pricing = {
            'cost_price': float(variant_data.get('cost_price') or 0),
            'price': float(variant_data.get('preco') or variant_data.get('price') or 0)
        }
        data['precificacao'] = pricing

        response = self.table.insert(data).execute()
        if response.data:
            result = dict(response.data[0])
            result['id'] = result.get('id')
            
            # --- NORMALIZAÇÃO DE ATRIBUTOS (TASK 4.1) ---
            if variation_values:
                from nistiprint_shared.services.attribute_service import attribute_service
                for attr_name, attr_value in variation_values.items():
                    attr_id = attribute_service.get_or_create_attribute(attr_name)
                    val_id = attribute_service.get_or_create_value(attr_id, str(attr_value))
                    attribute_service.link_product_to_attribute_value(result['id'], val_id)

            # Clear cache since we've added a new product
            self.clear_cache()
            return result

        return None

    def update_variant(self, variant_id: str, variant_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing product variant."""
        # Prepare update data
        update_data = {'updated_at': datetime.utcnow().isoformat()}

        # Core fields
        if 'sku' in variant_data: update_data['sku'] = variant_data['sku']
        if 'name' in variant_data: update_data['nome'] = variant_data['name']
        if 'nome' in variant_data: update_data['nome'] = variant_data['nome']
        if 'description' in variant_data: update_data['descricao'] = variant_data['description']
        if 'descricao' in variant_data: update_data['descricao'] = variant_data['descricao']

        # Support both names for category_id
        cat_id = variant_data.get('category_id') or variant_data.get('categoria_id')
        if cat_id is not None or 'category_id' in variant_data or 'categoria_id' in variant_data:
            update_data['categoria_id'] = cat_id if cat_id else None

        if 'tags' in variant_data: update_data['tags'] = variant_data['tags']

        # Normalized columns updates
        if 'cost_price' in variant_data: update_data['preco_custo'] = float(variant_data['cost_price'] or 0)
        if 'preco' in variant_data: update_data['preco_venda'] = float(variant_data['preco'] or 0)
        if 'price' in variant_data: update_data['preco_venda'] = float(variant_data['price'] or 0)
        if 'stock_min' in variant_data: update_data['estoque_minimo'] = int(variant_data['stock_min'] or 0)
        if 'stock_max' in variant_data: update_data['estoque_maximo'] = int(variant_data['stock_max'] or 0)
        if 'material_type' in variant_data: update_data['tipo_material'] = variant_data['material_type']
        if 'unit_of_measure_id' in variant_data or 'unidade_medida_id' in variant_data:
            update_data['unidade_medida_id'] = variant_data.get('unit_of_measure_id') or variant_data.get('unidade_medida_id')

        # New fields for product formats and inheritance
        if 'formato' in variant_data: update_data['formato'] = variant_data['formato']
        if 'herdar_dados_pai' in variant_data: update_data['herdar_dados_pai'] = variant_data['herdar_dados_pai']
        if 'herdar_bom_pai' in variant_data: update_data['herdar_bom_pai'] = variant_data['herdar_bom_pai']

        # Get existing variant to merge JSONB fields
        current = self.get_by_id(variant_id)
        if not current:
            raise ValueError(f"Variant {variant_id} not found")

        # Merge attributes (LEGACY support)
        current_attributes = current.get('atributos') or {}
        if 'material_type' in variant_data: current_attributes['material_type'] = variant_data['material_type']
        if 'stock_min' in variant_data: current_attributes['stock_min'] = variant_data['stock_min']
        if 'stock_max' in variant_data: current_attributes['stock_max'] = variant_data['stock_max']
        if 'requires_personalization' in variant_data: current_attributes['requires_personalization'] = variant_data['requires_personalization']
        if 'unit_of_measure_id' in variant_data or 'unidade_medida_id' in variant_data:
             current_attributes['unidade_medida_id'] = variant_data.get('unit_of_measure_id') or variant_data.get('unidade_medida_id')

        # Update variation values if provided
        if 'variation_values' in variant_data:
            current_attributes['variation_values'] = variant_data['variation_values']

        update_data['atributos'] = current_attributes

        # Merge pricing (LEGACY support)
        current_pricing = current.get('precificacao') or {}
        if 'cost_price' in variant_data: current_pricing['cost_price'] = float(variant_data['cost_price'] or 0)
        if 'preco' in variant_data: current_pricing['price'] = float(variant_data['preco'] or 0)
        if 'price' in variant_data: current_pricing['price'] = float(variant_data['price'] or 0)

        update_data['precificacao'] = current_pricing

        response = self.table.update(update_data).eq('id', variant_id).execute()

        # Clear cache since we've updated a product
        self.clear_cache()

        # Return updated variant
        return self.get_by_id(variant_id)

    def create_product_with_variations(self, parent_data: Dict[str, Any], variations_config: List[Dict[str, Any]], variations_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Create or Update a parent product and synchronize its variations."""
        parent_id = parent_data.get('id')
        if not parent_id:
            raise ValueError("Parent product ID is required")

        # Get the existing parent product
        parent_product = self.get_by_id(str(parent_id))
        if not parent_product:
            raise ValueError(f"Parent product with ID {parent_id} not found")

        # Update variations configuration on parent product
        parent_attributes = parent_product.get('atributos') or {}
        parent_attributes['variations_config'] = variations_config
        update_data = {'atributos': parent_attributes}
        parent_product = self.update(str(parent_id), update_data)

        # --- Sync Logic: Handle Inactivation of Orphans ---
        
        # 1. Get all currently existing variants from DB
        existing_variants = self.get_variants(str(parent_id))
        existing_ids = {str(v['id']) for v in existing_variants}
        
        # 2. Get IDs present in the payload (active variations)
        payload_ids = {str(v['id']) for v in variations_data if v.get('id')}
        
        # 3. Identify orphans (Existing in DB but NOT in Payload)
        orphans_ids = existing_ids - payload_ids
        
        # 4. Inactivate orphans
        for orphan_id in orphans_ids:
            # We use update instead of delete to preserve history (Soft Delete)
            self.update(orphan_id, {'status': 'inativo'})

        # --- Create / Update Active Variations ---

        for variation in variations_data:
            variation_values = variation.get('variation_values', {})
            
            # Generate Name following the format: $nome_pai - $attr1:$val1; $attr2:$val2...
            if not variation.get('nome') and not variation.get('name'):
                attrs_str = "; ".join([f"{k}:{v}" for k, v in variation_values.items()])
                variation['nome'] = f"{parent_product.get('nome')} - {attrs_str}"

            # Generate a unique SKU for the variation if not provided
            if not variation.get('sku'):
                variation_values_str = "-".join([f"{v}" for v in variation_values.values()])
                variation['sku'] = f"{parent_product['sku']}-{variation_values_str}"

            # Set the parent ID for the variation
            variation['parent_id'] = parent_id
            
            # Ensure status is active for sent variations
            variation['status'] = 'ativo'

            if variation.get('id'):
                # Update existing variation
                self.update_variant(str(variation['id']), variation)
            else:
                # Create new variation
                self.create_variant(str(parent_id), variation)

        # Clear cache
        self.clear_cache()

        # Return the updated parent product with variations
        return self.enrich_product_data_with_variations(parent_product)

    def resolve_variation(self, sku_externo: str, plataforma: str, nome_externo: str = None) -> Optional[Dict[str, Any]]:
        """
        Resolve a product variation based on exact SKU match.

        Simplified Strategy:
        1. Product.sku (Exact Internal Match) -> Returns Variant or Parent.

        The external SKU must be identical to the internal SKU for automatic mapping.
        """
        if not sku_externo:
            return None

        # Try exact internal SKU match
        try:
            product = self.get_by_sku(sku_externo)
            if product:
                return product
        except Exception as e:
            logging.warning(f"Error searching by internal SKU {sku_externo}: {e}")

        return None

    def resolve_variations_batch(self, skus_externos: List[str]) -> Dict[str, Optional[Dict[str, Any]]]:
        """
        Resolve múltiplos produtos de uma vez usando batch loading.
        
        Args:
            skus_externos: Lista de SKUs externos para buscar
            
        Returns:
            Dicionário {sku_externo: produto_interno ou None}
        """
        if not skus_externos:
            return {}
        
        # Remove duplicatas e valores vazios
        unique_skus = list(set([sku for sku in skus_externos if sku and str(sku).strip()]))
        
        if not unique_skus:
            return {}
        
        result = {}
        
        # Busca todos os produtos de uma vez
        try:
            response = self.table.select("*").in_('sku', unique_skus).execute()
            
            if response.data:
                # Mapeia resultados por SKU
                for product in response.data:
                    sku = product.get('sku')
                    result[sku] = dict(product)
                
                # Preenche com None os SKUs não encontrados
                for sku in unique_skus:
                    if sku not in result:
                        result[sku] = None
            else:
                # Nenhum produto encontrado
                result = {sku: None for sku in unique_skus}
                
        except Exception as e:
            logging.error(f"Erro no batch loading de produtos: {e}")
            result = {sku: None for sku in unique_skus}
        
        return result

    def get_products_by_ids_batch(self, product_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Busca múltiplos produtos por ID em uma única query.
        
        Args:
            product_ids: Lista de IDs de produtos
            
        Returns:
            Dicionário {product_id: produto}
        """
        if not product_ids:
            return {}
        
        # Remove duplicatas e converte para string
        unique_ids = list(set([str(pid) for pid in product_ids if pid]))
        
        if not unique_ids:
            return {}
        
        try:
            # Filtra apenas IDs numéricos válidos
            numeric_ids = [int(pid) for pid in unique_ids if str(pid).isdigit()]
            
            if not numeric_ids:
                return {}
            
            response = self.table.select("*").in_('id', numeric_ids).execute()
            
            if response.data:
                return {str(product['id']): dict(product) for product in response.data}
            else:
                return {}
                
        except Exception as e:
            logging.error(f"Erro no batch loading de produtos por ID: {e}")
            return {}

    def enrich_product_data_with_variations(self, product: Dict[str, Any]) -> Dict[str, Any]:
        """Enrich product data with its variations."""
        if not product:
            return product

        # Add variations to the product data
        variants = self.get_variants(str(product['id']))
        product['variants'] = variants
        product['has_variants'] = len(variants) > 0

        return product

    def map_bling_product_format(self, bling_product_data: Dict[str, Any]) -> str:
        """
        Maps Bling product format to our internal product format.
        Bling types: P (Produto), V (Variação), K (Kit)
        Our formats: simples, com_variacao, variacao, composicao, kit
        """
        bling_tipo = bling_product_data.get('tipo', '').upper()
        bling_codigo_pai = bling_product_data.get('codigo_pai')

        if bling_tipo == 'K':
            return 'kit'
        elif bling_tipo == 'V':
            return 'variacao'
        elif bling_codigo_pai:  # Has a parent code, so it's a variation
            return 'variacao'
        else:
            # For 'P' type or products without parent, determine based on other factors
            # If it has variations, it's a 'com_variacao', otherwise 'simples'
            # This would typically be determined by checking if other products reference this as parent
            return 'simples'

    def map_bling_inheritance_flags(self, bling_product_data: Dict[str, Any]) -> Dict[str, bool]:
        """
        Maps Bling inheritance flags to our internal flags.
        """
        # Bling's 'utilizar_dados_pai' flag maps to our 'herdar_dados_pai'
        utilizar_dados_pai = bling_product_data.get('utilizar_dados_pai', True)

        # For now, assuming herdar_bom_pai follows the same pattern
        herdar_bom_pai = bling_product_data.get('utilizar_dados_pai', True)

        return {
            'herdar_dados_pai': utilizar_dados_pai,
            'herdar_bom_pai': herdar_bom_pai
        }

    def validate_product_consistency(self, product_data: Dict[str, Any]) -> List[str]:
        """
        Validates product data consistency based on format and business rules.
        Returns a list of validation errors.
        """
        errors = []

        formato = product_data.get('formato', 'simples')
        parent_id = product_data.get('parent_id')
        estoque = product_data.get('estoque_atual', 0)  # Assuming estoque_atual comes from elsewhere

        # Rule: Products with formato 'com_variacao' (Parent) cannot have direct stock
        if formato == 'com_variacao':
            # Check if the product has any direct stock
            # This would require checking the estoque_atual table
            from nistiprint_shared.services.estoque_service import estoque_service
            # Get all deposits for this product and check if any have stock
            try:
                posicao_estoque = estoque_service.get_posicao_estoque([str(product_data.get('id'))])
                total_stock = sum(item.get('quantidade', 0) for item in posicao_estoque if item.get('produto_id') == str(product_data.get('id')))

                if total_stock > 0:
                    errors.append("Produtos do tipo 'com_variacao' (Modelo/Template) não podem ter estoque direto. Utilize as variações para controle de estoque.")
            except:
                # If there's an issue checking stock, continue with other validations
                pass

        # Rule: Products with formato 'variacao' must have a parent
        if formato == 'variacao' and not parent_id:
            errors.append("Produtos do tipo 'variacao' devem ter um produto pai associado.")

        return errors

    def can_delete_component(self, component_id: str) -> bool:
        """
        Checks if a component can be deleted (not used in active kits or compositions).
        """
        from nistiprint_shared.services.bom_service import bom_service

        # Check if this component is used in any BOM
        # This would require querying the ficha_tecnica table for references to this component
        try:
            response = supabase_db.table('ficha_tecnica').select('*').eq('componente_id', component_id).execute()
            if response.data:
                # Check if any of these parent products are active kits or compositions
                for bom_entry in response.data:
                    parent_product = self.get_by_id(str(bom_entry['produto_pai_id']))
                    if parent_product and parent_product.get('formato') in ['composicao', 'kit']:
                        return False  # Component is used in an active kit or composition
            return True
        except:
            # If there's an issue checking references, assume it's safe to delete
            return True

    def get_products_by_sector(self, setor_id: str) -> List[Dict[str, Any]]:
        """
        Obtém produtos filtrados pelo setor responsável.

        Args:
            setor_id: ID do setor responsável

        Returns:
            Lista de produtos associados ao setor
        """
        try:
            response = self.table.select("*").eq('setor_responsavel_id', setor_id).execute()
            return [dict(row) for row in response.data]
        except Exception as e:
            print(f"Erro ao obter produtos por setor: {str(e)}")
            return []


product_service = ProductService()

