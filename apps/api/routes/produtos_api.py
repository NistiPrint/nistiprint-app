from flask import request, jsonify
from nistiprint_shared.services.product_service import product_service
from nistiprint_shared.services.category_service import category_service
from nistiprint_shared.services.tag_service import tag_service
from nistiprint_shared.services.unit_of_measure_service import unit_of_measure_service
from nistiprint_shared.services.bom_service import bom_service
from nistiprint_shared.services.bling.bling_client import BlingClient
from nistiprint_shared.services.conta_bling_service import conta_bling_service
from routes.auth import login_required, get_current_user
from .produtos_base import produtos_api_bp
import logging

@produtos_api_bp.route('', methods=['GET'])
def api_index():
    page = max(1, request.args.get('page', 1, type=int))
    per_page = max(1, min(100, request.args.get('per_page', 20, type=int)))
    q = request.args.get('q', '').strip()
    category_id = request.args.get('category_id', '').strip()
    status = request.args.get('status', '').strip()
    material_type = request.args.get('material_type', '').strip()
    only_marketable = request.args.get('only_marketable') == 'true'
    include_variants = request.args.get('include_variants') == 'true'

    try:
        produtos, total_pages = product_service.get_products(
            q=q, categoria_id=category_id, status=status, page=page, per_page=per_page,
            material_type=material_type, only_marketable=only_marketable, include_variants=include_variants
        )
        categorias_map = {cat['id']: cat['nome'] for cat in category_service.get_all()}
        basic_produtos = []
        for p in produtos:
            basic_produtos.append({
                'id': p.get('id'), 'sku': p.get('sku'), 'sku_mestre': p.get('sku'),
                'name': p.get('nome') or p.get('name'), 'nome': p.get('nome') or p.get('name'),
                'description': p.get('descricao') or p.get('description'),
                'categoria_id': p.get('categoria_id'), 'categoria_nome': categorias_map.get(p.get('categoria_id'), 'N/A'),
                'status': p.get('status'), 'material_type': p.get('tipo_material') or p.get('material_type'),
                'cost_price': p.get('preco_custo') or p.get('cost_price', 0), 'price': p.get('preco_venda') or p.get('price', 0),
                'parent_id': p.get('parent_id'), 'has_variants': p.get('has_variants', False),
                'variants': p.get('variants', []), 'created_at': p.get('created_at'), 'updated_at': p.get('updated_at')
            })
        return jsonify({
            'produtos': basic_produtos, 'page': page, 'per_page': per_page, 'total_pages': total_pages,
            'q': q, 'category_id': category_id, 'status': status, 'categorias': category_service.get_all(),
            'unidades': unit_of_measure_service.get_all(), 'tags': tag_service.get_all()
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@produtos_api_bp.route('/por-setor', methods=['GET'])
@login_required
def api_produtos_por_setor():
    try:
        usuario = get_current_user()
        setor_id = usuario.get('setor_id')
        if not setor_id:
            return jsonify({'error': 'Usuário sem setor associado.'}), 403
        page = max(1, request.args.get('page', 1, type=int))
        per_page = max(1, min(100, request.args.get('per_page', 100, type=int)))
        categoria_id = request.args.get('category_id', type=int)
        produtos, total = product_service.get_products_by_sector_paginated(
            setor_id, page=page, per_page=per_page, categoria_id=categoria_id
        )
        from nistiprint_shared.services.estoque_service import estoque_service
        saldos = estoque_service.get_saldos_em_lote([p['id'] for p in produtos])
        produtos_com_saldo = []
        for p in produtos:
            p_cs = p.copy()
            p_cs['saldo_atual'] = saldos.get(str(p['id']), {'quantidade': 0})['quantidade']
            produtos_com_saldo.append(p_cs)
        return jsonify({
            'produtos': produtos_com_saldo,
            'setor_usuario': setor_id,
            'page': page,
            'per_page': per_page,
            'total': total,
            'total_pages': max(1, (total + per_page - 1) // per_page),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@produtos_api_bp.route('', methods=['POST'])
def api_criar():
    try:
        data = request.get_json()
        dados_produto = {
            'sku': data.get('sku'), 'name': data.get('name'), 'description': data.get('description'),
            'category_id': data.get('category_id'), 'unit_of_measure_id': data.get('unit_of_measure_id'),
            'material_type': data.get('material_type', 'produto_acabado'), 'cost_price': float(data.get('cost_price') or 0),
            'stock_min': data.get('stock_min'), 'stock_max': data.get('stock_max'),
            'requires_personalization': data.get('requires_personalization'), 'status': data.get('status') or 'rascunho',
            'formato': data.get('formato', 'simples'), 'setor_responsavel_id': data.get('setor_responsavel_id'),
            'parent_id': data.get('parent_id'), 'herdar_dados_pai': data.get('herdar_dados_pai', True),
            'herdar_bom_pai': data.get('herdar_bom_pai', True), 'tags': [{'tag_id': tid} for tid in data.get('tags', []) if tid]
        }
        if not dados_produto['sku'] or not dados_produto['name']: return jsonify({'error': 'SKU e Nome são obrigatórios'}), 400
        produto = product_service.create(dados_produto)
        return jsonify({'success': True, 'message': f'Produto "{produto.get("nome", produto.get("name"))}" criado!', 'produto_id': produto['id']}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@produtos_api_bp.route('/<produto_id>', methods=['GET'])
def api_get_produto(produto_id):
    try:
        produto = product_service.get_by_id(produto_id)
        if not produto: return jsonify({'error': 'Produto não encontrado'}), 404
        produto = product_service.enrich_product_data(produto)
        return jsonify({
            **produto, 'produto': produto, 'categorias': category_service.get_all(),
            'unidades': unit_of_measure_service.get_all(), 'tags': tag_service.get_all(),
            'bling_product_links': product_service.get_bling_product_links(produto_id),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@produtos_api_bp.route('/<produto_id>/readiness', methods=['GET'])
def api_product_readiness(produto_id):
    """Expose the staged readiness assessment without changing commercial status."""
    try:
        result = product_service.evaluate_readiness(produto_id)
        if result.get('role') is None:
            return jsonify(result), 404
        return jsonify(result)
    except Exception as e:
        logging.exception('Erro ao avaliar prontidão do produto %s', produto_id)
        return jsonify({'error': str(e)}), 500

@produtos_api_bp.route('/<produto_id>/clone', methods=['POST'])
def api_clonar_produto(produto_id):
    data = request.get_json(silent=True)
    if not produto_id.isdigit():
        return jsonify({'error': 'Produto não encontrado'}), 404
    if not isinstance(data, dict):
        return jsonify({'error': 'Corpo JSON inválido'}), 400

    sku = data.get('new_sku')
    name = data.get('new_name')
    child_skus = data.get('child_skus', {})
    if not isinstance(sku, str) or not sku.strip() or len(sku.strip()) > 100:
        return jsonify({'error': 'Novo SKU deve ter entre 1 e 100 caracteres'}), 400
    if name is not None and not isinstance(name, str):
        return jsonify({'error': 'Novo nome inválido'}), 400
    name = name.strip() if name else None
    if name and len(name) > 255:
        return jsonify({'error': 'Novo nome deve ter até 255 caracteres'}), 400
    if not isinstance(child_skus, dict) or any(
        not str(key).isdigit() or not isinstance(value, str) or not value.strip() or len(value.strip()) > 100
        for key, value in child_skus.items()
    ):
        return jsonify({'error': 'Informe um SKU válido para cada variação'}), 400

    try:
        product = product_service.clone_product(produto_id, sku.strip(), name, child_skus)
        return jsonify({'success': True, 'product': product}), 201
    except Exception as exc:
        code = getattr(exc, 'code', None)
        if code == 'P0002':
            return jsonify({'error': 'Produto não encontrado'}), 404
        if code in ('22023', '23505', '22001'):
            return jsonify({'error': str(exc)}), 400
        logging.exception('Erro ao clonar produto %s', produto_id)
        return jsonify({'error': 'Não foi possível clonar o produto'}), 500

@produtos_api_bp.route('/<produto_id>/artes-recursivas', methods=['GET'])
def api_get_recursive_artworks(produto_id):
    """Lista componentes da ficha técnica que aceitam arte local."""
    try:
        from nistiprint_shared.services.recursive_artwork_service import recursive_artwork_service
        product = product_service.get_by_id(produto_id)
        if not product:
            return jsonify({'error': 'Produto não encontrado'}), 404
        return jsonify({
            'produto_id': str(produto_id),
            'artes': recursive_artwork_service.list_for_product(str(produto_id)),
        })
    except Exception as e:
        logging.exception('Erro ao resolver artes recursivas')
        return jsonify({'error': str(e)}), 500

@produtos_api_bp.route('/<produto_id>', methods=['PUT'])
def api_editar(produto_id):
    try:
        data = request.get_json()
        dados = {
            'sku': data.get('sku'), 'name': data.get('name'), 'description': data.get('description'),
            'category_id': data.get('category_id'), 'unit_of_measure_id': data.get('unit_of_measure_id'),
            'material_type': data.get('material_type'), 'cost_price': float(data.get('cost_price') or 0),
            'stock_min': data.get('stock_min'), 'stock_max': data.get('stock_max'),
            'requires_personalization': data.get('requires_personalization'), 'status': data.get('status'),
            'setor_responsavel_id': data.get('setor_responsavel_id'),
            'herdar_dados_pai': data.get('herdar_dados_pai'),
            'herdar_bom_pai': data.get('herdar_bom_pai'),
            'tags': [{'tag_id': tid} for tid in data.get('tags', []) if tid]
        }
        # Campos que mudam a NATUREZA do produto: so incluir se o cliente
        # enviou explicitamente. Sem isso, editar uma variacao via UI sem
        # reenviar parent_id/formato sobrescrevia esses campos com None,
        # transformando a variacao em produto raiz orfao e disparando
        # "Produtos do tipo 'variacao' devem ter um produto pai associado".
        if 'parent_id' in data:
            dados['parent_id'] = data['parent_id']
        if 'formato' in data:
            dados['formato'] = data['formato']
        if not dados['sku'] or not dados['name']: return jsonify({'error': 'SKU e Nome são obrigatórios'}), 400
        p_atualizado = product_service.update(produto_id, dados)
        return jsonify({'success': True, 'message': 'Produto atualizado!', 'produto': p_atualizado})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@produtos_api_bp.route('/<produto_id>', methods=['DELETE'])
def api_deletar(produto_id):
    try:
        product_service.delete(produto_id)
        return jsonify({'success': True, 'message': 'Excluído!'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@produtos_api_bp.route('/bulk_update', methods=['POST'])
def api_bulk_update():
    data = request.get_json()
    product_ids, updates = data.get('product_ids', []), data.get('updates', {})
    if not product_ids or not updates: return jsonify({'error': 'Inválido'}), 400
    allowed = ['material_type', 'category_id', 'status']
    filtered = {k: v for k, v in updates.items() if k in allowed}
    count, errors = 0, []
    for pid in product_ids:
        try:
            product_service.update(pid, filtered)
            count += 1
        except Exception as e:
            errors.append({'id': pid, 'error': str(e)})
    return jsonify({'success': True, 'message': f'{count} atualizados.', 'errors': errors})

@produtos_api_bp.route('/<produto_id>/bom', methods=['GET', 'POST', 'DELETE', 'PUT'])
def api_gerenciar_bom(produto_id):
    try:
        if request.method == 'POST':
            data = request.get_json()
            product_service.add_bom_component(produto_id, data.get('componente_id'), float(data.get('quantidade')))
            return jsonify({'success': True})
        elif request.method == 'DELETE':
            product_service.remove_bom_component(produto_id, request.args.get('componente_id'))
            return jsonify({'success': True})
        elif request.method == 'PUT':
            data = request.get_json()
            product_service.update_bom_component_quantity(produto_id, data.get('component_id'), float(data.get('quantity')))
            return jsonify({'success': True})
        return jsonify({'components': product_service.get_bom_components(produto_id)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@produtos_api_bp.route('/<produto_id>/bom/copy-from-parent', methods=['POST'])
def api_copy_bom_from_parent(produto_id):
    try:
        return jsonify({'success': bom_service.copy_bom_from_parent(produto_id)})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@produtos_api_bp.route('/<produto_id>/category_rules', methods=['GET'])
def api_get_product_category_rules(produto_id):
    try:
        from nistiprint_shared.services.category_bom_rule_service import category_bom_rule_service
        p = product_service.get_by_id(produto_id)
        if not p or not p.get('category_id'): return jsonify({'regras': []})
        return jsonify({'regras': category_bom_rule_service.get_by_category_pai(p['category_id'])})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@produtos_api_bp.route('/<produto_id>/custo-calculado', methods=['GET'])
def api_custo_calculado(produto_id):
    try:
        custo = product_service.calcular_custo_bom(produto_id)
        p = product_service.get_by_id(produto_id)
        return jsonify({'custo_calculado': custo, 'custo_atual': p.get('cost_price', 0)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@produtos_api_bp.route('/search', methods=['GET'])
def api_search():
    try:
        res = []
        material_types = [value for value in request.args.getlist('material_type') if value]
        for p in product_service.search_produtos(request.args.get('q', ''), int(request.args.get('limit', 20)), request.args.get('exclude_id'), 'ativo', request.args.get('category_id')):
            p = product_service.enrich_product_data(p)
            material_type = p.get('material_type') or p.get('tipo_material') or 'produto_acabado'
            if material_types and material_type not in material_types:
                continue
            res.append({'id': p['id'], 'text': f"{p.get('sku_mestre', '')} - {p.get('name', '')}", 'sku': p.get('sku_mestre', ''), 'name': p.get('name', ''), 'material_type': material_type, 'cost': p.get('cost_price', 0), 'categoria_id': p.get('categoria_id')})
        return jsonify({'results': res})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@produtos_api_bp.route('/bling_products/search', methods=['GET'])
def api_search_bling_products():
    try:
        acc = conta_bling_service.get_by_id(request.args.get('account_id'))
        if not acc: return jsonify({'error': 'Conta não encontrada'}), 404
        products = BlingClient(acc).search_products(request.args.get('q', ''), int(request.args.get('page', 1)), int(request.args.get('per_page', 100)))
        return jsonify({'results': [{'id': p.get('id'), 'sku': p.get('codigo'), 'name': p.get('nome'), 'account_id': acc['id']} for p in products]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@produtos_api_bp.route('/<produto_id>/bling_links', methods=['POST'])
def api_add_bling_link(produto_id):
    try:
        data = request.get_json()
        product_service.add_bling_product_link(produto_id, data.get('bling_product_id'), data.get('bling_sku'), data.get('bling_account_id'), data.get('bling_name', ''))
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@produtos_api_bp.route('/<produto_id>/bling_links/<bid>/<aid>', methods=['DELETE'])
def api_remove_bling_link(produto_id, bid, aid):
    try:
        product_service.remove_bling_product_link(produto_id, bid, aid)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@produtos_api_bp.route('/bling_products/<bid>', methods=['GET'])
def api_get_bling_product(bid):
    try:
        acc = conta_bling_service.get_by_id(request.args.get('account_id'))
        p = BlingClient(acc).get_product(bid)
        return jsonify({'success': True, 'product': p}) if p else jsonify({'success': False}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@produtos_api_bp.route('/<produto_id>/variations', methods=['POST'])
def api_create_product_with_variations(produto_id):
    try:
        data = request.get_json()
        from nistiprint_shared.services.catalogo_familia_service import CatalogoFamiliaService
        from nistiprint_shared.database.supabase_db_service import supabase_db
        catalog = CatalogoFamiliaService(supabase_db)
        family = catalog.get(int(produto_id))
        if family is None:
            return jsonify({'success': False, 'error': 'Produto não encontrado'}), 404
        expected_version = data.get('expected_version', family.get('catalogo_versao', 1))
        result = catalog.save(int(produto_id), {
            'expected_version': expected_version,
            'eixos': data.get('eixos', data.get('variations_config', [])),
            'variacoes': data.get('variacoes', data.get('variations_data', [])),
            'inativar_ids': data.get('inativar_ids', []),
        }, (get_current_user() or {}).get('id'))
        updated = product_service.get_by_id(produto_id)
        res = product_service.enrich_product_data_with_variations(updated) if updated else result
        return jsonify({'success': True, 'produto': res})
    except Exception as e:
        code = getattr(e, 'code', None) or getattr(e, 'sqlstate', None)
        if code in {'40001', 'CATALOG_VERSION_CONFLICT'}:
            return jsonify({'success': False, 'error': 'A família foi alterada por outra pessoa. Atualize os dados e tente novamente.'}), 409
        if code in {'22023', '23505', '23503', 'P0002'} or isinstance(e, ValueError):
            return jsonify({'success': False, 'error': str(e)}), 422
        logging.exception('Erro ao salvar grade transacional do produto %s', produto_id)
        return jsonify({'success': False, 'error': 'Não foi possível salvar a grade do produto.'}), 503
