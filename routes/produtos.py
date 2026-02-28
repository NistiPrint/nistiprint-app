from flask import Blueprint, request, jsonify, render_template, flash, redirect, url_for
import json
import uuid
from datetime import datetime, timedelta
from nistiprint_shared.services.product_service import product_service
from nistiprint_shared.services.category_service import category_service
from nistiprint_shared.services.tag_service import tag_service
from nistiprint_shared.services.unit_of_measure_service import unit_of_measure_service
from nistiprint_shared.services.bom_service import bom_service
from nistiprint_shared.services.bling.bling_client import BlingClient
from nistiprint_shared.services.app_config_service import app_config_service
from nistiprint_shared.services.conta_bling_service import conta_bling_service
from routes.auth import login_required

produtos_bp = Blueprint('produtos', __name__, url_prefix='/produtos')
produtos_api_bp = Blueprint('produtos_api', __name__, url_prefix='/api/v2/produtos')


# API Produtos routes
@produtos_api_bp.route('', methods=['GET'])
def api_index():
    """Lists all products with pagination and filters (API)."""
    try:
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))
        q = request.args.get('q', '').strip()
        category_id = request.args.get('category_id', '').strip()
        status = request.args.get('status', '').strip()
        material_type = request.args.get('material_type', '').strip()
        only_marketable = request.args.get('only_marketable') == 'true'
        include_variants = request.args.get('include_variants') == 'true'

        produtos, total_pages = product_service.get_products(
            q=q,
            categoria_id=category_id,
            status=status,
            page=page,
            per_page=per_page,
            material_type=material_type,
            only_marketable=only_marketable,
            include_variants=include_variants
        )

        # Return basic product data without enrichment to avoid connection issues
        # The enrichment will happen only when viewing individual products
        # Also include category name for filtering purposes
        categorias_map = {cat['id']: cat['nome'] for cat in category_service.get_all()}

        basic_produtos = []
        for p in produtos:
            # Only include basic fields to minimize data transfer and processing
            basic_product = {
                'id': p.get('id'),
                'sku': p.get('sku'),
                'sku_mestre': p.get('sku'),  # Add sku_mestre for frontend compatibility
                'name': p.get('nome') or p.get('name'),
                'description': p.get('descricao') or p.get('description'),
                'categoria_id': p.get('categoria_id'),
                'categoria_nome': categorias_map.get(p.get('categoria_id'), 'N/A'),  # Add category name for filtering
                'status': p.get('status'),
                'material_type': p.get('tipo_material') or p.get('material_type'),
                'cost_price': p.get('preco_custo') or p.get('cost_price', 0),
                'price': p.get('preco_venda') or p.get('price', 0),  # Add price field for frontend
                'parent_id': p.get('parent_id'), # Add parent_id for variation links
                'has_variants': p.get('has_variants', False),  # Add variants info for frontend
                'variants': p.get('variants', []),  # Add variants data for frontend
                'created_at': p.get('created_at'),
                'updated_at': p.get('updated_at')
            }
            basic_produtos.append(basic_product)

        categorias = category_service.get_all()
        unidades = unit_of_measure_service.get_all()
        tags = tag_service.get_all()

        return jsonify({
            'produtos': basic_produtos,
            'page': page,
            'per_page': per_page,
            'total_pages': total_pages,
            'q': q,
            'category_id': category_id,
            'status': status,
            'categorias': categorias,
            'unidades': unidades,
            'tags': tags
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Rota para obter produtos filtrados pelo setor do usuário
@produtos_api_bp.route('/por-setor', methods=['GET'])
@login_required
def api_produtos_por_setor():
    """API para obter produtos filtrados pelo setor do usuário logado."""
    try:
        from routes.auth import get_current_user

        usuario = get_current_user()
        setor_usuario = usuario['setor_id']

        # Obter produtos filtrados pelo setor responsável
        produtos = product_service.get_products_by_sector(setor_usuario)

        # Obter saldos de estoque para esses produtos
        from nistiprint_shared.services.estoque_service import estoque_service
        produto_ids = [p['id'] for p in produtos]
        saldos = estoque_service.get_saldos_em_lote(produto_ids)

        # Combinar informações de produtos com saldos
        produtos_com_saldo = []
        for produto in produtos:
            produto_com_saldo = produto.copy()
            saldo_info = saldos.get(str(produto['id']), {'quantidade': 0})
            produto_com_saldo['saldo_atual'] = saldo_info['quantidade']
            produtos_com_saldo.append(produto_com_saldo)

        return jsonify({
            'produtos': produtos_com_saldo,
            'setor_usuario': setor_usuario
        })
    except Exception as e:
        print(f"Erro na API ao obter produtos por setor: {str(e)}")
        return jsonify({'error': str(e)}), 500

@produtos_api_bp.route('', methods=['POST'])
def api_criar():
    """Creates a new product (API)."""
    try:
        data = request.get_json()
        dados_produto = {
            'sku': data.get('sku'),
            'name': data.get('name'),
            'description': data.get('description'),
            'category_id': data.get('category_id'),
            'unit_of_measure_id': data.get('unit_of_measure_id'),
            'material_type': data.get('material_type', 'produto_acabado'),
            'cost_price': float(data.get('cost_price') or 0),
            'stock_min': data.get('stock_min'),
            'stock_max': data.get('stock_max'),
            'requires_personalization': data.get('requires_personalization'),
            'status': data.get('status'),
            'formato': data.get('formato', 'simples'),
            'setor_responsavel_id': data.get('setor_responsavel_id')
        }
        tags_ids = data.get('tags', [])
        dados_produto['tags'] = [{'tag_id': tag_id} for tag_id in tags_ids if tag_id]

        if not dados_produto['sku'] or not dados_produto['name']:
            return jsonify({'error': 'SKU Mestre e Nome são obrigatórios'}), 400

        produto = product_service.create(dados_produto)
        return jsonify({'success': True, 'message': f'Produto "{produto.get("nome", produto.get("name"))}" criado com sucesso!', 'produto_id': produto['id']}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@produtos_api_bp.route('/<produto_id>', methods=['GET'])
def api_get_produto(produto_id):
    """Retrieves a single product (API)."""
    try:
        produto = product_service.get_by_id(produto_id)
        if not produto:
            return jsonify({'error': 'Produto não encontrado'}), 404

        produto = product_service.enrich_product_data(produto)

        categorias = category_service.get_all()
        unidades = unit_of_measure_service.get_all()
        tags_disponiveis = tag_service.get_all()
        bom_components = product_service.get_bom_components(produto_id) if produto.get('is_composite') else []
        bling_product_links_data = product_service.get_bling_product_links(produto_id)

        # Get artworks for the product
        product_artworks = product_service.get_artworks_for_product(produto_id)

        return jsonify({
            **produto, # Flatten for UI components like ProductSelector
            'produto': produto, # Keep for detail pages
            'categorias': categorias,
            'unidades': unidades,
            'tags': tags_disponiveis,
            'bom_components': bom_components,
            'bling_product_links': bling_product_links_data,
            'artworks': product_artworks
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@produtos_api_bp.route('/<produto_id>', methods=['PUT'])
def api_editar(produto_id):
    """Edits an existing product (API)."""
    try:
        data = request.get_json()
        dados_atualizacao = {
            'sku': data.get('sku'),
            'name': data.get('name'),
            'description': data.get('description'),
            'category_id': data.get('category_id'),
            'unit_of_measure_id': data.get('unit_of_measure_id'),
            'material_type': data.get('material_type'),
            'cost_price': float(data.get('cost_price') or 0),
            'stock_min': data.get('stock_min'),
            'stock_max': data.get('stock_max'),
            'requires_personalization': data.get('requires_personalization'),
            'status': data.get('status'),
            'formato': data.get('formato'),
            'setor_responsavel_id': data.get('setor_responsavel_id')
        }
        tags_ids = data.get('tags', [])
        dados_atualizacao['tags'] = [{'tag_id': tag_id} for tag_id in tags_ids if tag_id]

        if not dados_atualizacao['sku'] or not dados_atualizacao['name']:
            return jsonify({'error': 'SKU Mestre e Nome são obrigatórios'}), 400

        produto_atualizado = product_service.update(produto_id, dados_atualizacao)
        return jsonify({'success': True, 'message': f'Produto "{produto_atualizado.get("nome", produto_atualizado.get("name"))}" atualizado com sucesso!', 'produto': produto_atualizado})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@produtos_api_bp.route('/<produto_id>', methods=['DELETE'])
def api_deletar(produto_id):
    """Deletes a product (API)."""
    try:
        product_service.delete(produto_id)
        return jsonify({'success': True, 'message': 'Produto excluído com sucesso!'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@produtos_api_bp.route('/bulk_update', methods=['POST'])
def api_bulk_update():
    """Updates multiple products in bulk (API)."""
    try:
        data = request.get_json()
        product_ids = data.get('product_ids', [])
        updates = data.get('updates', {})

        if not product_ids or not isinstance(product_ids, list):
            return jsonify({'error': 'Lista de product_ids inválida ou vazia'}), 400

        if not updates or not isinstance(updates, dict):
             return jsonify({'error': 'Dados de atualização (updates) inválidos ou vazios'}), 400

        # Sanitize updates - only allow specific fields for now
        allowed_fields = ['material_type', 'category_id', 'status']
        filtered_updates = {k: v for k, v in updates.items() if k in allowed_fields}

        if not filtered_updates:
            return jsonify({'error': 'Nenhum campo válido para atualização fornecido'}), 400

        updated_count = 0
        errors = []

        for product_id in product_ids:
            try:
                # Using existing update method which retrieves and updates
                product_service.update(product_id, filtered_updates)
                updated_count += 1
            except Exception as e:
                errors.append({'id': product_id, 'error': str(e)})

        return jsonify({
            'success': True,
            'message': f'{updated_count} produtos atualizados com sucesso.',
            'updated_count': updated_count,
            'errors': errors
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@produtos_api_bp.route('/<produto_id>/bom', methods=['GET', 'POST', 'DELETE', 'PUT'])
def api_gerenciar_bom(produto_id):
    """Gerenciamento de BOM (Bill of Materials) (API)."""
    try:
        if request.method == 'POST':
            # Adiciona componente à BOM
            data = request.get_json()
            component_id = data.get('componente_id')
            quantidade = float(data.get('quantidade'))

            product_service.add_bom_component(produto_id, component_id, quantidade)
            return jsonify({'success': True, 'message': 'Componente adicionado à BOM com sucesso!'})

        elif request.method == 'DELETE':
            # Remove componente da BOM
            component_id = request.args.get('componente_id')
            product_service.remove_bom_component(produto_id, component_id)
            return jsonify({'success': True, 'message': 'Componente removido da BOM com sucesso!'})

        elif request.method == 'PUT':
            # Atualiza a quantidade de um componente
            data = request.get_json()
            component_id = data.get('component_id')
            quantity = float(data.get('quantity'))

            if not component_id or quantity is None:
                return jsonify({'error': 'Component ID and quantity are required'}), 400

            product_service.update_bom_component_quantity(produto_id, component_id, quantity)
            return jsonify({'success': True, 'message': 'Quantidade atualizada com sucesso!'})

        else: # GET
            # Retorna componentes da BOM
            componentes = product_service.get_bom_components(produto_id)
            return jsonify({'components': componentes})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@produtos_api_bp.route('/<produto_id>/category_rules', methods=['GET'])
def api_get_product_category_rules(produto_id):
    """Retorna as regras de BOM da categoria do produto (API)."""
    try:
        from nistiprint_shared.services.category_bom_rule_service import category_bom_rule_service

        produto = product_service.get_by_id(produto_id)
        if not produto or not produto.get('category_id'):
            return jsonify({'regras': []})

        regras = category_bom_rule_service.get_by_category_pai(produto['category_id'])
        return jsonify({'regras': regras})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@produtos_api_bp.route('/<produto_id>/custo-calculado', methods=['GET'])
def api_custo_calculado(produto_id):
    """Retorna custo calculado para um produto (API)."""
    try:
        custo_calculado = product_service.calcular_custo_bom(produto_id)
        produto = product_service.get_by_id(produto_id)

        if produto:
            return jsonify({
                'product_id': produto_id,
                'product_name': produto.get('name', ''),
                'custo_calculado': custo_calculado,
                'custo_atual': produto.get('cost_price', 0),
                'diferenca': custo_calculado - produto.get('cost_price', 0)
            })
        else:
            return jsonify({'error': 'Produto não encontrado'}), 404

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@produtos_api_bp.route('/search', methods=['GET'])
def api_search():
    """API para busca de produtos (autocomplete)"""
    try:
        q = request.args.get('q', '')
        limit = int(request.args.get('limit', 20))
        exclude_id = request.args.get('exclude_id')
        category_id = request.args.get('category_id')

        produtos = product_service.search_produtos(q, limit, exclude_id, status='ativo', category_id=category_id)
        produtos = [product_service.enrich_product_data(p) for p in produtos]

        results = []
        for p in produtos:
            results.append({
                'id': p['id'],
                'text': f"{p.get('sku_mestre', '')} - {p.get('name', '')}",
                'sku': p.get('sku_mestre', ''),
                'name': p.get('name', ''),
                'cost': p.get('cost_price', 0),
                'categoria_id': p.get('categoria_id')
            })

        return jsonify({'results': results})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@produtos_api_bp.route('/bling_products/search', methods=['GET'])
def api_search_bling_products():
    """API para buscar produtos no Bling."""
    try:
        query = request.args.get('q', '').strip()
        account_id = request.args.get('account_id', '').strip()
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 100))

        if not query:
            return jsonify({'results': []})

        # Get Bling account data from Supabase
        account = conta_bling_service.get_by_id(account_id)
        if not account:
            return jsonify({'error': 'Conta Bling não encontrada'}), 404

        bling_client = BlingClient(account)
        bling_products = bling_client.search_products(query, page, per_page)

        results = []
        for p in bling_products:
            results.append({
                'id': p.get('id'),
                'sku': p.get('codigo'),
                'name': p.get('nome'),
                'description': p.get('descricao'),
                'account_id': account_id # Add account_id to the result
            })
        return jsonify({'results': results})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@produtos_api_bp.route('/<produto_id>/bling_links', methods=['POST'])
def api_add_bling_link(produto_id):
    """Adiciona um link de produto Bling a um produto interno (API)."""
    try:
        data = request.get_json()
        bling_product_id = data.get('bling_product_id')
        bling_sku = data.get('bling_sku')
        bling_account_id = data.get('bling_account_id')
        bling_name = data.get('bling_name', '')

        if not all([bling_product_id, bling_sku, bling_account_id]):
            return jsonify({'error': 'bling_product_id, bling_sku e bling_account_id são obrigatórios'}), 400

        product_service.add_bling_product_link(produto_id, bling_product_id, bling_sku, bling_account_id, bling_name)
        return jsonify({'success': True, 'message': 'Link Bling adicionado com sucesso!'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@produtos_api_bp.route('/<produto_id>/bling_links/<bling_product_id>/<bling_account_id>', methods=['DELETE'])
def api_remove_bling_link(produto_id, bling_product_id, bling_account_id):
    """Remove um link de produto Bling de um produto interno (API)."""
    try:
        product_service.remove_bling_product_link(produto_id, bling_product_id, bling_account_id)
        return jsonify({'success': True, 'message': 'Link Bling removido com sucesso!'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@produtos_api_bp.route('/bling_accounts', methods=['GET'])
def api_list_bling_accounts():
    """API para listar contas Bling."""
    try:
        accounts = BlingClient.list_accounts()
        return jsonify(accounts)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@produtos_api_bp.route('/bling_products/<bling_product_id>', methods=['GET'])
def api_get_bling_product(bling_product_id):
    """API para buscar um produto Bling por ID."""
    try:
        account_id = request.args.get('account_id', '').strip()
        if not account_id:
            return jsonify({'error': 'account_id é obrigatório'}), 400

        account = conta_bling_service.get_by_id(account_id)
        if not account:
            return jsonify({'error': 'Conta Bling não encontrada'}), 404

        bling_client = BlingClient(account)
        product = bling_client.get_product(bling_product_id)

        if product:
            return jsonify({'success': True, 'product': product})
        else:
            return jsonify({'success': False, 'message': 'Produto Bling não encontrado'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@produtos_api_bp.route('/bling_products/search_by_skus', methods=['GET'])
def api_search_bling_products_by_skus():
    """API para buscar produtos Bling por uma lista de SKUs."""
    try:
        skus_param = request.args.get('skus', '').strip()
        account_id = request.args.get('account_id', '').strip()

        if not account_id:
            return jsonify({'error': 'account_id é obrigatório'}), 400
        if not skus_param:
            return jsonify({'results': []})

        skus = [s.strip() for s in skus_param.split(',') if s.strip()]

        account = conta_bling_service.get_by_id(account_id)
        if not account:
            return jsonify({'error': 'Conta Bling não encontrada'}), 404

        bling_client = BlingClient(account)
        bling_products = bling_client.search_products_by_skus(skus)

        results = []
        for p in bling_products:
            results.append({
                'id': p.get('id'),
                'sku': p.get('codigo'),
                'name': p.get('nome'),
                'description': p.get('descricao'),
                'account_id': account_id
            })
        return jsonify({'results': results})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@produtos_api_bp.route('/search_for_bom', methods=['GET'])
def api_search_for_bom():
    """API para buscar produtos para associação em massa (API)."""
    try:
        name = request.args.get('name', '').strip()
        category_id = request.args.get('category_id', '').strip()
        tag_id = request.args.get('tag_id', '').strip()

        query = product_service.collection
        if category_id:
            query = query.where('category_id', '==', category_id)

        docs = query.stream()

        produtos_filtrados = []
        for doc in docs:
            produto_data = doc.to_dict()

            if name:
                if name.lower() not in produto_data.get('name', '').lower():
                    continue

            if tag_id:
                tags = produto_data.get('tags', [])
                tags_ids = [tag_ref.get('tag_id') for tag_ref in tags]
                if tag_id not in tags_ids:
                    continue

            produto_data['id'] = doc.id
            produto_data['name'] = produto_data.get('name', '')
            produto_data['sku'] = produto_data.get('sku', '')
            produtos_filtrados.append(produto_data)

        result = []
        for produto in produtos_filtrados[:100]:
            result.append({
                'id': produto['id'],
                'name': produto.get('name', ''),
                'sku': produto.get('sku', ''),
                'category_id': produto.get('category_id')
            })

        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@produtos_api_bp.route('/<component_id>/associate_in_bulk', methods=['POST'])
def api_associate_in_bulk(component_id):
    """Associa componente a múltiplos produtos em massa (API)."""
    try:
        data = request.get_json()

        if not data or 'associations' not in data:
            return jsonify({'error': 'Dados de associação obrigatórios'}), 400

        associations = data['associations']
        if not isinstance(associations, list) or len(associations) == 0:
            return jsonify({'error': 'Lista de associações deve conter pelo menos um item'}), 400

        required_keys = {'product_id', 'quantity'}
        for assoc in associations:
            if not all(key in assoc for key in required_keys):
                return jsonify({'error': 'Cada associação deve ter product_id e quantity'}), 400
            if assoc.get('quantity', 0) <= 0:
                return jsonify({'error': 'Quantidade deve ser maior que zero'}), 400

        bom_service.bulk_add_component_to_products(component_id, associations)

        return jsonify({
            'success': True,
            'message': f'Componente associado a {len(associations)} produtos com sucesso',
            'associated_count': len(associations)
        })

    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@produtos_api_bp.route('/<produto_id>/artwork', methods=['POST'])
def api_upload_artwork(produto_id):
    """Upload artwork for a product."""
    try:
        from nistiprint_shared.services.artwork_service import artwork_service

        if 'artwork' not in request.files:
            return jsonify({'error': 'No artwork file provided'}), 400

        file = request.files['artwork']

        if file.filename == '':
            return jsonify({'error': 'No artwork file selected'}), 400

        # Save the artwork using the artwork service
        artwork = artwork_service.save_artwork(file, produto_id)

        return jsonify({
            'success': True,
            'message': 'Artwork uploaded successfully!',
            'artwork': artwork.to_dict(use_updated_url=True)
        }), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@produtos_api_bp.route('/<produto_id>/artworks', methods=['GET'])
def api_get_artworks(produto_id):
    """Get all artworks for a product."""
    try:
        artworks = product_service.get_artworks_for_product(produto_id)
        return jsonify({'artworks': artworks}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@produtos_api_bp.route('/artwork/<artwork_id>', methods=['DELETE'])
def api_delete_artwork(artwork_id):
    """Delete an artwork."""
    try:
        from nistiprint_shared.services.artwork_service import artwork_service

        success = artwork_service.delete_artwork(artwork_id)
        if success:
            return jsonify({'success': True, 'message': 'Artwork deleted successfully!'}), 200
        else:
            return jsonify({'error': 'Artwork not found'}), 404
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@produtos_api_bp.route('/artwork/<artwork_id>/view', methods=['GET'])
def api_view_artwork(artwork_id):
    """Secure endpoint to view artwork - authenticates user and redirects to signed URL."""
    try:
        from flask import session
        from nistiprint_shared.services.usuario_service import usuario_service
        from nistiprint_shared.models.product_artwork import ProductArtwork
        from nistiprint_shared.database.supabase_db_service import get_db_session

        # Check if user is authenticated (this assumes you have user session management)
        # Adjust this check based on your actual authentication mechanism
        if 'user_id' not in session and 'user' not in session:
            return jsonify({'error': 'Authentication required'}), 401

        # Fetch artwork from database
        with get_db_session() as db_session:
            artwork = db_session.query_model(ProductArtwork).filter_by(id=artwork_id).first()
            if not artwork:
                return jsonify({'error': 'Artwork not found'}), 404

            # Debug: print artwork details
            print(f"Artwork ID: {artwork.id}, Filename: {artwork.filename}, File Path: {artwork.file_path}")

            # Get the signed URL for the artwork
            from nistiprint_shared.services.supabase_storage_service import supabase_storage_service
            signed_url = supabase_storage_service.get_file_url(artwork.filename)

            if not signed_url:
                print(f"Could not generate signed URL for filename: {artwork.filename}")
                return jsonify({'error': f'Could not generate access URL for artwork. Filename: {artwork.filename}'}), 500

            # Return the signed URL - the frontend will handle the redirection
            return jsonify({'signed_url': signed_url}), 200

    except Exception as e:
        print(f"Exception in api_view_artwork: {str(e)}")
        return jsonify({'error': str(e)}), 500

@produtos_api_bp.route('/<produto_id>/variations', methods=['POST'])
def api_create_product_with_variations(produto_id):
    """Create a product with its variations."""
    try:
        data = request.get_json()
        variations_config = data.get('variations_config', [])
        variations_data = data.get('variations_data', [])

        # Use the product service to create the product with variations
        result = product_service.create_product_with_variations(
            {'id': produto_id},  # We're just passing the ID since the product already exists
            variations_config,
            variations_data
        )

        return jsonify({
            'success': True,
            'message': 'Variações criadas com sucesso!',
            'produto': result
        }), 200

    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@produtos_api_bp.route('/<produto_id>/print', methods=['POST'])
def api_send_to_print(produto_id):
    """Send product artwork to printing workflow."""
    try:
        from nistiprint_shared.services.print_service import print_service

        data = request.get_json() or {}
        artwork_id = data.get('artwork_id')

        # Create print job using the print service
        print_job = print_service.create_print_job(produto_id, artwork_id)

        return jsonify({
            'success': True,
            'message': 'Trabalho de impressão criado com sucesso!',
            'print_job': print_job
        }), 200

    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Regular Produtos routes
@produtos_bp.route('', methods=['GET'])
def index():
    """Lista todos os produtos com paginação e filtros"""
    try:
        # Parâmetros de busca, filtro e paginação
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))
        q = request.args.get('q', '').strip()
        category_id = request.args.get('category_id', '').strip()
        status = request.args.get('status', '').strip()

        # Busca produtos usando o novo método de filtro
        produtos, total_pages = product_service.get_products(
            q=q,
            category_id=category_id,
            status=status,
            page=page,
            per_page=per_page
        )

        # Enriquecer dados dos produtos para exibição
        produtos = [product_service.enrich_product_data(p) for p in produtos]

        # Dados para filtros
        categorias = category_service.get_all()
        unidades = unit_of_measure_service.get_all()
        tags = tag_service.get_all()

        return render_template('produtos/index.html',
                                 produtos=produtos,
                                 page=page,
                                 per_page=per_page,
                                 total_pages=total_pages,
                                 q=q,
                                 category_id=category_id,
                                 status=status,
                                 categorias=categorias,
                                 unidades=unidades,
                                 tags=tags)

    except Exception as e:
        flash(f'Erro ao carregar produtos: {str(e)}', 'error')
        # Em caso de erro, ainda passar o mínimo para renderizar o template
        return render_template('produtos/index.html',
                                 produtos=[],
                                 page=1,
                                 total_pages=1,
                                 q=request.args.get('q', ''),
                                 category_id=request.args.get('category_id', ''),
                                 categorias=category_service.get_all())


@produtos_bp.route('/novo', methods=['GET', 'POST'])
def criar():
    """Cria novo produto"""
    try:
        if request.method == 'POST':
            # Existing HTML form handling
            dados_produto = {
                'sku': request.form.get('sku_mestre'),
                'name': request.form.get('name'),
                'description': request.form.get('description'),
                'category_id': request.form.get('category_id'),
                'unit_of_measure_id': request.form.get('unit_of_measure_id'),
                'material_type': request.form.get('material_type', 'produto_acabado'),
                'cost_price': float(request.form.get('cost_price') or 0),
                'stock_min': request.form.get('stock_min'),
                'stock_max': request.form.get('stock_max'),
                'requires_personalization': request.form.get('requires_personalization') == 'on',
                'status': request.form.get('status'),
                'formato': request.form.get('formato', 'simples'),
                'setor_responsavel_id': request.form.get('setor_responsavel_id')
            }

            tags_ids = request.form.getlist('tags')
            dados_produto['tags'] = [{'tag_id': tag_id} for tag_id in tags_ids if tag_id]

            if not dados_produto['sku'] or not dados_produto['name']:
                flash('SKU Mestre e Nome são obrigatórios', 'error')
                return redirect(request.url)

            temp_product_id = request.form.get('temp_product_id')
            produto = product_service.create(dados_produto)
            flash(f'Produto "{produto["name"]}" criado com sucesso!', 'success')
            return redirect(url_for('produtos.editar', produto_id=produto['id']))

        # GET: Mostra formulário
        print("Accessing /produtos/novo (GET request)")
        categorias = category_service.get_all()
        unidades = unit_of_measure_service.get_all()
        tags = tag_service.get_all()
        # Generate a temporary ID for new products to allow BOM operations before saving (Session only)
        temp_product_id = str(uuid.uuid4())
        print(f"Generated temp_product_id: {temp_product_id}")
        default_bling_account_id = app_config_service.get_config('default_bling_account_id')
        all_bling_accounts = conta_bling_service.get_all()

        return render_template('produtos/form.html',
                             produto=None,
                             categorias=categorias,
                             unidades=unidades,
                             tags=tags,
                             temp_product_id=temp_product_id,
                             view_mode=False,
                             default_bling_account_id=default_bling_account_id,
                             bling_product_links=[],
                             external_product_links={'skus': [], 'names': [], 'ids': []})

    except Exception as e:
        print(f"ERROR in criar function: {e}")
        flash(f'Erro ao carregar página de criação: {str(e)}', 'error')
        # Em caso de erro, ainda renderiza o formulário com campos vazios
        return render_template('produtos/form.html',
                             produto=None,
                             categorias=[],
                             unidades=[],
                             tags=[],
                             view_mode=False,
                             temp_product_id=temp_product_id,
                             bling_product_links=[])


@produtos_bp.route('/associate/<component_id>', methods=['GET'])
def associate_component(component_id):
    """Página para associar componente a múltiplos produtos em massa"""
    try:
        # Buscar componente
        component = product_service.get_by_id(component_id)
        if not component:
            flash('Componente não encontrado', 'error')
            return redirect(url_for('produtos.index'))

        # Enriquecer dados do componente
        component = product_service.enrich_product_data(component)

        # Dados para os filtros de busca
        categorias = category_service.get_all()
        tags_disponiveis = tag_service.get_all()

        return render_template('produtos/associate_component.html',
                             component=component,
                             categorias=categorias,
                             tags=tags_disponiveis)

    except Exception as e:
        flash(f'Erro ao carregar página de associação: {str(e)}', 'error')
        return redirect(url_for('produtos.index'))


@produtos_bp.route('/<produto_id>/editar', methods=['GET', 'POST', 'PUT'])
def editar(produto_id):
    """Visualiza e edita produto existente"""
    try:
        product_service.clear_cache() # Clear cache at the start of a new product view/edit operation

        # Busca produto atual
        produto = product_service.get_by_id(produto_id)

        if not produto:
            flash('Produto não encontrado', 'error')
            return redirect(url_for('produtos.index'))

        # Dados para os formulários (GET and POST/PUT)
        categorias = category_service.get_all()
        unidades = unit_of_measure_service.get_all()
        tags_disponiveis = tag_service.get_all()

        # Busca componentes da BOM
        bom_components = product_service.get_bom_components(produto_id) if produto.get('is_composite') else []

        # Busca links de produtos Bling
        bling_product_links_data = product_service.get_bling_product_links(produto_id)

        # Buscar artworks do produto
        product_artworks = product_service.get_artworks_for_product(produto_id)

        if request.method in ['POST', 'PUT']:

            # Coleta dados do formulário
            dados_atualizacao = {
                'sku': request.form.get('sku_mestre'),
                'name': request.form.get('name'),
                'description': request.form.get('description'),
                'category_id': request.form.get('category_id'),
                'unit_of_measure_id': request.form.get('unit_of_measure_id'),
                'material_type': request.form.get('material_type'),
                'cost_price': float(request.form.get('cost_price') or 0),
                'stock_min': request.form.get('stock_min'),
                'stock_max': request.form.get('stock_max'),
                'requires_personalization': request.form.get('requires_personalization') == 'on',
                'status': request.form.get('status'),
                'formato': request.form.get('formato'),
                'setor_responsavel_id': request.form.get('setor_responsavel_id')
            }

            # TAGS: Coleta múltimos tags (array)
            tags_ids = request.form.getlist('tags')
            dados_atualizacao['tags'] = [{'tag_id': tag_id} for tag_id in tags_ids if tag_id]

            # EXTERNAL PRODUCT LINKS: Coleta os vínculos externos
            external_product_links_json = request.form.get('external_product_links_json')
            if external_product_links_json:
                try:
                    dados_atualizacao['external_product_links'] = json.loads(external_product_links_json)
                except json.JSONDecodeError:
                    # Handle invalid JSON gracefully
                    dados_atualizacao['external_product_links'] = {'skus': [], 'names': [], 'ids': []}
            else:
                dados_atualizacao['external_product_links'] = {'skus': [], 'names': [], 'ids': []}

            # Validação básica
            if not dados_atualizacao['sku'] or not dados_atualizacao['name']:
                flash('SKU Mestre e Nome são obrigatórios', 'error')

                # Re-render form with current data and error
                return render_template('produtos/form.html',
                                     produto=produto,
                                     categorias=categorias,
                                     unidades=unidades,
                                     tags=tags_disponiveis,
                                     bom_components=bom_components,
                                     product_artworks=product_artworks,
                                     view_mode=False) # Stay in edit mode on error

            # Atualiza produto
            produto_atualizado = product_service.update(produto_id, dados_atualizacao)

            # --- CORREÇÃO: Persistir Integrações na Tabela Relacional ---
            if 'external_product_links' in dados_atualizacao:
                product_service.sync_external_product_links(produto_id, dados_atualizacao['external_product_links'])
            # -----------------------------------------------------------

            flash(f'Produto "{produto_atualizado["name"]}" atualizado com sucesso!', 'success')

            return redirect(url_for('produtos.editar', produto_id=produto_id))

        else: # GET request
            # Existing HTML form GET handling
            default_bling_account_id = app_config_service.get_config('default_bling_account_id')
            all_bling_accounts = conta_bling_service.get_all()

            # Garantir que external_product_links sempre seja passado, mesmo que vazio
            external_links = produto.get('external_product_links', {'skus': [], 'names': [], 'ids': []})

            return render_template('produtos/form.html',
                                 produto=produto,
                                 categorias=categorias,
                                 unidades=unidades,
                                 tags=tags_disponiveis,
                                 bom_components=bom_components,
                                 bling_product_links=bling_product_links_data,
                                 product_artworks=product_artworks,
                                 external_product_links=external_links, # Passa os links de produtos externos
                                 view_mode=False,
                                 default_bling_account_id=default_bling_account_id,
                                 all_bling_accounts=all_bling_accounts)

    except Exception as e:
        print(f"ERROR in editar function - produto_id {produto_id} | {e}")
        flash(f'Erro ao carregar/editar produto: {str(e)}', 'error')
        return redirect(url_for('produtos.index'))





