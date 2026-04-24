from flask import Blueprint, request, jsonify, render_template, flash, redirect, url_for
import json
from services.firebase.firestore_client import firestore_client
from services.product_service import product_service
from services.category_service import category_service
from services.tag_service import tag_service
from services.unit_of_measure_service import unit_of_measure_service
from services.bom_service import bom_service
from services.composition_template_service import composition_template_service
from services.bling.bling_client import BlingClient
import uuid
from services.app_config_service import app_config_service
from services.conta_bling_service import conta_bling_service

produtos_bp = Blueprint('produtos', __name__, url_prefix='/produtos')


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
            # Coleta dados do formulário
            dados_produto = {
                'sku': request.form.get('sku_mestre'),
                'name': request.form.get('name'),
                'description': request.form.get('description'),
                'category_id': request.form.get('category_id'),
                'unit_of_measure_id': request.form.get('unit_of_measure_id'),
                'cost_price': float(request.form.get('cost_price') or 0),
                'stock_min': request.form.get('stock_min'),
                'stock_max': request.form.get('stock_max'),
                'requires_personalization': request.form.get('requires_personalization') == 'on',
                'status': request.form.get('status')
            }

            # TAGS: Coleta múltiplos tags (array)
            tags_ids = request.form.getlist('tags')
            dados_produto['tags'] = [{'tag_id': tag_id} for tag_id in tags_ids if tag_id]

            # Validação básica
            if not dados_produto['sku'] or not dados_produto['name']:
                flash('SKU Mestre e Nome são obrigatórios', 'error')
                return redirect(request.url)

            # Cria produto
            temp_product_id = request.form.get('temp_product_id') # Get the temporary ID from the form
            produto = product_service.create(dados_produto, product_id=temp_product_id)
            flash(f'Produto "{produto["name"]}" criado com sucesso!', 'success')
            return redirect(url_for('produtos.editar', produto_id=produto['id']))

        # GET: Mostra formulário
        print("Accessing /produtos/novo (GET request)")
        categorias = category_service.get_all()
        unidades = unit_of_measure_service.get_all()
        tags = tag_service.get_all()
        # Generate a Firestore ID for new products to allow BOM operations before saving
        print(f"Type of firestore_client: {type(firestore_client)}")
        print(f"Value of firestore_client: {firestore_client}")
        temp_product_id = firestore_client.collection('products').document().id
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
                             all_bling_accounts=all_bling_accounts,
                             bling_product_links=[])

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


@produtos_bp.route('/<produto_id>/editar', methods=['GET', 'POST'])
def editar(produto_id):
    """Visualiza e edita produto existente"""
    try:
        # Busca produto atual
        produto = product_service.get_by_id(produto_id)
        if not produto:
            flash('Produto não encontrado', 'error')
            return redirect(url_for('produtos.index'))

        # Enriquecer dados do produto para exibição
        produto = product_service.enrich_product_data(produto)

        # Dados para os formulários (GET e POST)
        categorias = category_service.get_all()
        unidades = unit_of_measure_service.get_all()
        tags_disponiveis = tag_service.get_all()

        # Busca componentes da BOM
        bom_components = product_service.get_bom_components(produto_id) if produto.get('is_composite') else []

        # Busca links de produtos Bling
        bling_product_links_data = product_service.get_bling_product_links(produto_id)
        print(f"DEBUG: bling_product_links_data before rendering: {bling_product_links_data}")

        # Buscar templates de composição aplicáveis
        aplicable_templates = []
        if produto.get('category_id'):
            category = category_service.get_by_id(produto['category_id'])
            if category and category.get('composition_template_id'):
                template = composition_template_service.get_template_by_id(category['composition_template_id'])
                if template:
                    aplicable_templates.append(template)

        for tag_ref in produto.get('tags', []):
            tag = tag_service.get_by_id(tag_ref['tag_id'])
            if tag and tag.get('composition_template_id'):
                template = composition_template_service.get_template_by_id(tag['composition_template_id'])
                if template and template not in aplicable_templates:
                    aplicable_templates.append(template)

        if request.method == 'POST':
            # Coleta dados do formulário
            dados_atualizacao = {
                'sku': request.form.get('sku_mestre'),
                'name': request.form.get('name'),
                'description': request.form.get('description'),
                'category_id': request.form.get('category_id'),
                'unit_of_measure_id': request.form.get('unit_of_measure_id'),
                'cost_price': float(request.form.get('cost_price') or 0),
                'stock_min': request.form.get('stock_min'),
                'stock_max': request.form.get('stock_max'),
                'requires_personalization': request.form.get('requires_personalization') == 'on',
                'status': request.form.get('status')
            }

            # TAGS: Coleta múltiplos tags (array)
            tags_ids = request.form.getlist('tags')
            dados_atualizacao['tags'] = [{'tag_id': tag_id} for tag_id in tags_ids if tag_id]

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
                                     aplicable_templates=aplicable_templates,
                                     view_mode=False) # Stay in edit mode on error

            # Atualiza produto
            produto_atualizado = product_service.update(produto_id, dados_atualizacao)
            flash(f'Produto "{produto_atualizado["name"]}" atualizado com sucesso!', 'success')
            return redirect(url_for('produtos.editar', produto_id=produto_id))

        # GET: Mostra formulário com dados atuais para edição
        default_bling_account_id = app_config_service.get_config('default_bling_account_id')
        all_bling_accounts = conta_bling_service.get_all()
        return render_template('produtos/form.html',
                             produto=produto,
                             categorias=categorias,
                             unidades=unidades,
                             tags=tags_disponiveis,
                             bom_components=bom_components, # Passa os componentes da BOM para o template
                             bling_product_links=bling_product_links_data, # Passa os links de produtos Bling
                             aplicable_templates=aplicable_templates,
                             view_mode=False,
                             default_bling_account_id=default_bling_account_id,
                             all_bling_accounts=all_bling_accounts) # Sempre em modo de edição

    except Exception as e:
        print(f"ERROR in editar function - produto_id {produto_id} | {e}")
        flash(f'Erro ao carregar/editar produto: {str(e)}', 'error')
        return redirect(url_for('produtos.index'))


# ==================== API ENDPOINTS ====================

@produtos_bp.route('/api/search', methods=['GET'])
def api_search():
    """API para busca de produtos (autocomplete)"""
    try:
        q = request.args.get('q', '')
        limit = int(request.args.get('limit', 20))
        exclude_id = request.args.get('exclude_id')

        produtos = product_service.search_produtos(q, limit, exclude_id, status='ativo')
        produtos = [product_service.enrich_product_data(p) for p in produtos]

        results = []
        for p in produtos:
            results.append({
                'id': p['id'],
                'text': f"{p.get('sku_mestre', '')} - {p.get('name', '')}",
                'sku': p.get('sku_mestre', ''),
                'name': p.get('name', ''),
                'cost': p.get('cost_price', 0)
            })

        return jsonify({'results': results})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@produtos_bp.route('/api/bling_products/search', methods=['GET'])
def api_search_bling_products():
    """API para buscar produtos no Bling."""
    try:
        query = request.args.get('q', '').strip()
        account_id = request.args.get('account_id', '').strip()
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 100))

        if not query:
            return jsonify({'results': []})

        # Get Bling account data from Firestore
        account_doc = firestore_client.collection('bling_accounts').document(account_id).get()
        if not account_doc.exists:
            return jsonify({'error': 'Conta Bling não encontrada'}), 404
        
        bling_client = BlingClient(account_doc.to_dict())
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

@produtos_bp.route('/<produto_id>/bling_links', methods=['POST'])
def add_bling_link(produto_id):
    """Adiciona um link de produto Bling a um produto interno."""
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

@produtos_bp.route('/<produto_id>/bling_links/<bling_product_id>/<bling_account_id>', methods=['DELETE'])
def remove_bling_link(produto_id, bling_product_id, bling_account_id):
    """Remove um link de produto Bling de um produto interno."""
    try:
        product_service.remove_bling_product_link(produto_id, bling_product_id, bling_account_id)
        return jsonify({'success': True, 'message': 'Link Bling removido com sucesso!'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@produtos_bp.route('/api/bling_accounts', methods=['GET'])
def api_list_bling_accounts():
    """API para listar contas Bling."""
    try:
        accounts = BlingClient.list_accounts()
        return jsonify(accounts)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@produtos_bp.route('/api/bling_products/<bling_product_id>', methods=['GET'])
def api_get_bling_product(bling_product_id):
    """API para buscar um produto Bling por ID."""
    try:
        account_id = request.args.get('account_id', '').strip()
        if not account_id:
            return jsonify({'error': 'account_id é obrigatório'}), 400

        account_doc = firestore_client.collection('bling_accounts').document(account_id).get()
        if not account_doc.exists:
            return jsonify({'error': 'Conta Bling não encontrada'}), 404
        
        bling_client = BlingClient(account_doc.to_dict())
        product = bling_client.get_product(bling_product_id)

        if product:
            return jsonify({'success': True, 'product': product})
        else:
            return jsonify({'success': False, 'message': 'Produto Bling não encontrado'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@produtos_bp.route('/api/bling_products/search_by_skus', methods=['GET'])
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

        account_doc = firestore_client.collection('bling_accounts').document(account_id).get()
        if not account_doc.exists:
            return jsonify({'error': 'Conta Bling não encontrada'}), 404
        
        bling_client = BlingClient(account_doc.to_dict())
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





@produtos_bp.route('/<produto_id>/bom', methods=['GET', 'POST', 'DELETE', 'PUT'])
def gerenciar_bom(produto_id):
    """Gerenciamento de BOM (Bill of Materials)"""
    try:
        if request.method == 'POST':
            # Adiciona componente à BOM
            component_id = request.form.get('componente_id')
            quantidade = float(request.form.get('quantidade'))

            product_service.add_bom_component(produto_id, component_id, quantidade)
            return jsonify({'success': True})

        elif request.method == 'DELETE':
            # Remove componente da BOM
            component_id = request.args.get('componente_id')
            product_service.remove_bom_component(produto_id, component_id)
            return jsonify({'success': True})

        elif request.method == 'PUT':
            # Atualiza a quantidade de um componente
            data = request.get_json()
            component_id = data.get('component_id')
            quantity = float(data.get('quantity'))

            if not component_id or quantity is None:
                return jsonify({'error': 'Component ID and quantity are required'}), 400

            product_service.update_bom_component_quantity(produto_id, component_id, quantity)
            return jsonify({'success': True, 'message': 'Quantity updated successfully'})

        else:
            # Retorna componentes da BOM
            componentes = product_service.get_bom_components(produto_id)
            result = []
            for comp in componentes:
                result.append({
                    'component_id': comp['id'],
                    'sku': comp.get('sku_mestre', ''),
                    'name': comp.get('name', ''),
                    'quantity': comp['bom_quantity'],
                    'cost': comp.get('cost_price', 0)
                })
            return jsonify({'components': result})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@produtos_bp.route('/<produto_id>/deletar', methods=['POST'])
def deletar(produto_id):
    """Deleta produto"""
    try:
        product_service.delete(produto_id)
        flash('Produto deletado com sucesso', 'success')
    except Exception as e:
        flash(f'Erro ao deletar produto: {str(e)}', 'error')

    return redirect(url_for('produtos.index'))


@produtos_bp.route('/atualizar-custos-automaticos', methods=['POST'])
def atualizar_custos_automaticos():
    """Atualiza custos automáticos de produtos compostos"""
    try:
        atualizacoes = product_service.atualizar_custos_automaticos()
        flash(f'Custos atualizados para {atualizacoes} produtos', 'success')
    except Exception as e:
        flash(f'Erro ao atualizar custos: {str(e)}', 'error')

    return redirect(url_for('produtos.index'))


@produtos_bp.route('/<produto_id>/custo-calculado')
def custo_calculado(produto_id):
    """Retorna custo calculado para um produto"""
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


@produtos_bp.route('/relatorios/custos', methods=['GET'])
def relatorio_custos():
    """Relatório de custos: Informado vs Calculado"""
    try:
        # Buscar produtos compostos
        docs = product_service.collection.where('is_composite', '==', True).stream()
        produtos_compostos = []

        for doc in docs:
            product_data = doc.to_dict()
            product_data['id'] = doc.id

            # Enriquecer dados
            enriched = product_service.enrich_product_data(product_data)

            custo_informado = enriched.get('cost_price', 0)
            custo_calculado = enriched['total_cost']

            if custo_calculado > 0:  # Só incluir se tem componentes
                produtos_compostos.append({
                    'id': enriched['id'],
                    'sku_mestre': enriched.get('sku_mestre', ''),
                    'name': enriched.get('name', ''),
                    'custo_informado': custo_informado,
                    'custo_calculado': custo_calculado,
                    'diferenca': custo_calculado - custo_informado,
                    'margem_percentual': ((custo_calculado - custo_informado) / custo_calculado * 100) if custo_calculado > 0 else 0
                })

        # Ordenar por diferença (maiores diferenças primeiro)
        produtos_compostos.sort(key=lambda x: abs(x['diferenca']), reverse=True)

        return render_template('produtos/relatorio_custos.html',
                             produtos_compostos=produtos_compostos)

    except Exception as e:
        flash(f'Erro ao gerar relatório: {str(e)}', 'error')
        return redirect(url_for('produtos.index'))


@produtos_bp.route('/atualizar-custos-compostos', methods=['POST'])
def atualizar_custos_compostos():
    """Atualiza automaticamente os custos de todos os produtos compostos"""
    try:
        atualizados = 0

        # Buscar produtos compostos
        docs = product_service.collection.where('is_composite', '==', True).stream()

        for doc in docs:
            product_id = doc.id
            product_data = doc.to_dict()

            # Calcular custo baseado nos componentes
            custo_calculado = product_service.get_total_cost(product_data)

            if custo_calculado > 0:
                # Atualizar cost_price com o valor calculado
                product_service.collection.document(product_id).update({
                    'cost_price': custo_calculado,
                    'updated_at': datetime.utcnow()
                })
                atualizados += 1

        flash(f'Custos de {atualizados} produtos compostos atualizados automaticamente!', 'success')
        return redirect(url_for('produtos.index'))

    except Exception as e:
        flash(f'Erro ao atualizar custos: {str(e)}', 'error')
        return redirect(url_for('produtos.index'))


# ==================== NOVAS ROTAS PARA FUNCIONALIDADES ====================

@produtos_bp.route('/search_for_bom', methods=['GET'])
def search_for_bom():
    """API para buscar produtos para associação em massa"""
    try:
        name = request.args.get('name', '').strip()
        category_id = request.args.get('category_id', '').strip()
        tag_id = request.args.get('tag_id', '').strip()

        # Filtrar produtos baseado nos critérios
        query = product_service.collection
        if category_id:
            query = query.where('category_id', '==', category_id)

        docs = query.stream()

        produtos_filtrados = []
        for doc in docs:
            produto_data = doc.to_dict()

            # Filtros adicionais de texto
            if name:
                if name.lower() not in produto_data.get('name', '').lower():
                    continue

            # Filtro por tag se especificado
            if tag_id:
                tags = produto_data.get('tags', [])
                tags_ids = [tag_ref.get('tag_id') for tag_ref in tags]
                if tag_id not in tags_ids:
                    continue

            produto_data['id'] = doc.id
            produto_data['name'] = produto_data.get('name', '')
            produto_data['sku'] = produto_data.get('sku', '')
            produtos_filtrados.append(produto_data)

        # Retornar apenas dados necessários
        result = []
        for produto in produtos_filtrados[:100]:  # Limitar a 100 resultados
            result.append({
                'id': produto['id'],
                'name': produto.get('name', ''),
                'sku': produto.get('sku', ''),
                'category_id': produto.get('category_id')
            })

        return jsonify(result)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@produtos_bp.route('/<component_id>/associate_in_bulk', methods=['POST'])
def associate_in_bulk(component_id):
    """Associa componente a múltiplos produtos em massa"""
    try:
        data = request.get_json()

        if not data or 'associations' not in data:
            return jsonify({'error': 'Dados de associação obrigatórios'}), 400

        associations = data['associations']
        if not isinstance(associations, list) or len(associations) == 0:
            return jsonify({'error': 'Lista de associações deve conter pelo menos um item'}), 400

        # Validar formato dos dados
        required_keys = {'product_id', 'quantity'}
        for assoc in associations:
            if not all(key in assoc for key in required_keys):
                return jsonify({'error': 'Cada associação deve ter product_id e quantity'}), 400
            if assoc.get('quantity', 0) <= 0:
                return jsonify({'error': 'Quantidade deve ser maior que zero'}), 400

        # Executar associação em massa
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


@produtos_bp.route('/<produto_id>/apply_template/<template_id>', methods=['POST'])
def apply_template(produto_id, template_id):
    """Aplica template de composição a um produto"""
    try:
        composition_template_service.apply_template_to_product(template_id, produto_id)

        return jsonify({
            'success': True,
            'message': 'Template aplicado com sucesso'
        })

    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500
