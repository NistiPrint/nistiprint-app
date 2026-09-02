from flask import request, jsonify
from nistiprint_shared.services.product_service import product_service
from nistiprint_shared.database.supabase_db_service import supabase_db
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
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 20))
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
                'name': p.get('nome') or p.get('name'), 'description': p.get('descricao') or p.get('description'),
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

@produtos_api_bp.route('/variation-axes', methods=['GET'])
@login_required
def api_get_variation_axes():
    try:
        return jsonify({'eixos': product_service.get_variation_axes()})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@produtos_api_bp.route('/variacoes/pendentes', methods=['GET'])
@login_required
def api_variation_review_queue():
    """Produtos cujos eixos ainda dependem de decisão humana.

    O backfill de `20260831190000` gravou só o MIOLO — o segmento do SKU que
    corresponde a um produto cadastrado, e portanto verificável. Estampa e
    acabamento ficaram de fora de propósito: 17 dos 44 acabados nem seguem a
    gramática de três segmentos, e adivinhar ali seria gravar erro no banco.
    """
    try:
        return jsonify({
            'pendentes': product_service.get_variation_review_queue(),
            'eixos': product_service.get_variation_axes(),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@produtos_api_bp.route('/<produto_id>/variacao-valores', methods=['PUT'])
@login_required
def api_set_variation_values(produto_id):
    """Grava os eixos de um produto e o tira da fila de revisão."""
    try:
        data = request.get_json() or {}
        valores = data.get('valores') or data.get('axis_values')
        if not isinstance(valores, dict) or not valores:
            return jsonify({'error': 'Informe os valores dos eixos'}), 400
        produto = product_service.set_variation_values(produto_id, valores)
        return jsonify({'success': True, 'produto': produto})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@produtos_api_bp.route('/eixos/<axis_code>/opcoes', methods=['POST'])
@login_required
def api_create_axis_option(axis_code):
    """Cadastra uma opção de eixo. Uma estampa nova da coleção é exatamente isso."""
    try:
        data = request.get_json() or {}
        opcao = product_service.create_axis_option(
            axis_code, data.get('codigo'), data.get('nome'))
        return jsonify({'success': True, 'opcao': opcao}), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@produtos_api_bp.route('/kits/pendentes', methods=['GET'])
@login_required
def api_kit_pending_codes():
    """Códigos de pedido que não resolvem para nenhum produto interno.

    É a fila de cadastro do combo: o código aparece na venda, a fábrica precisa
    dele, e enquanto ele não for um produto (`formato = 'kit'`) com ficha de
    produtos acabados, a consolidação não tem como explodi-lo.
    """
    try:
        resultado = supabase_db.rpc('codigos_externos_sem_produto', {}).execute()
        return jsonify({'pendentes': resultado.data or []})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@produtos_api_bp.route('/readiness', methods=['GET'])
@login_required
def api_product_readiness():
    try:
        tag_id = request.args.get('tag_id')
        estagio = request.args.get('estagio')
        query = supabase_db.rpc('listar_produtos_prontidao', {
            'p_tag_id': int(tag_id) if tag_id else None,
            'p_estagio': estagio or None,
        })
        return jsonify({'produtos': query.execute().data or []})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@produtos_api_bp.route('/anuncios', methods=['GET'])
@login_required
def api_product_ads():
    try:
        return jsonify({'anuncios': product_service.list_product_ads(request.args.get('orfaos') == 'true')})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@produtos_api_bp.route('/anuncios/<ad_id>/vincular', methods=['PUT'])
@login_required
def api_link_product_ad(ad_id):
    try:
        data = request.get_json() or {}
        return jsonify({'anuncio': product_service.link_product_ad(ad_id, data.get('produto_id'))})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@produtos_api_bp.route('/aliases', methods=['GET', 'POST'])
@login_required
def api_product_aliases():
    try:
        if request.method == 'POST':
            data = request.get_json() or {}
            return jsonify({'alias': product_service.add_product_alias(data.get('produto_id'), data.get('codigo_externo'), data.get('tipo'), data.get('plataforma'))}), 201
        return jsonify({'aliases': product_service.list_product_aliases(request.args.get('produto_id'))})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@produtos_api_bp.route('/<produto_id>/precos', methods=['GET', 'POST'])
@login_required
def api_product_prices(produto_id):
    try:
        if request.method == 'POST':
            return jsonify({'preco': product_service.add_product_price(produto_id, request.get_json() or {})}), 201
        return jsonify({'precos': product_service.list_product_prices(produto_id)})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@produtos_api_bp.route('/<produto_id>/publicar', methods=['POST'])
@login_required
def api_publish_product(produto_id):
    try:
        result = supabase_db.rpc('publicar_produto', {'p_produto_id': int(produto_id)}).execute()
        if not result.data:
            return jsonify({'error': 'Produto não encontrado'}), 404
        return jsonify({'success': True, 'produto': result.data[0]})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@produtos_api_bp.route('/por-setor', methods=['GET'])
@login_required
def api_produtos_por_setor():
    try:
        usuario = get_current_user()
        produtos = product_service.get_products_by_sector(usuario['setor_id'])
        from nistiprint_shared.services.estoque_service import estoque_service
        saldos = estoque_service.get_saldos_em_lote([p['id'] for p in produtos])
        produtos_com_saldo = []
        for p in produtos:
            p_cs = p.copy()
            p_cs['saldo_atual'] = saldos.get(str(p['id']), {'quantidade': 0})['quantidade']
            produtos_com_saldo.append(p_cs)
        return jsonify({'produtos': produtos_com_saldo, 'setor_usuario': usuario['setor_id']})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@produtos_api_bp.route('', methods=['POST'])
@login_required
def api_criar():
    try:
        data = request.get_json()
        dados_produto = {
            'sku': data.get('sku'), 'name': data.get('name'), 'description': data.get('description'),
            'category_id': data.get('category_id'), 'unit_of_measure_id': data.get('unit_of_measure_id'),
            'material_type': data.get('material_type', 'produto_acabado'), 'cost_price': float(data.get('cost_price') or 0),
            'stock_min': data.get('stock_min'), 'stock_max': data.get('stock_max'),
            'requires_personalization': data.get('requires_personalization'), 'status': data.get('status', 'inativo'),
            'estagio': data.get('estagio', 'RASCUNHO'),
            'formato': data.get('formato', 'simples'), 'setor_responsavel_id': data.get('setor_responsavel_id'),
            'parent_id': data.get('parent_id'), 'herdar_dados_pai': data.get('herdar_dados_pai', True),
            'herdar_bom_pai': data.get('herdar_bom_pai', True), 'tags': [{'tag_id': tid} for tid in data.get('tags', []) if tid],
            **{field: data[field] for field in ('ncm', 'cest', 'origem_mercadoria', 'cfop_padrao_venda', 'gtin', 'gtin_embalagem', 'marca', 'fabricante', 'mpn', 'peso_liquido', 'peso_bruto', 'comprimento', 'largura', 'altura', 'garantia_meses', 'perfil_fiscal_id', 'origem_fiscal') if field in data}
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
            'bom_components': product_service.get_bom_components(produto_id) if produto.get('is_composite') else [],
            'bling_product_links': product_service.get_bling_product_links(produto_id),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

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
@login_required
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
            **{field: data[field] for field in ('ncm', 'cest', 'origem_mercadoria', 'cfop_padrao_venda', 'gtin', 'gtin_embalagem', 'marca', 'fabricante', 'mpn', 'peso_liquido', 'peso_bruto', 'comprimento', 'largura', 'altura', 'garantia_meses', 'perfil_fiscal_id', 'origem_fiscal') if field in data}
        }
        # M4: `tags` estava SEMPRE presente no dict, e `sync_product_tags` apaga
        # antes de inserir. Qualquer cliente que fizesse PUT sem o campo (script
        # de sincronizacao, integracao, edicao em massa) zerava as tags do
        # produto — inclusive a tag que define a colecao no painel de prontidao.
        if 'tags' in data:
            dados['tags'] = [{'tag_id': tid} for tid in (data.get('tags') or []) if tid]
        # M3: `estagio` chegava do formulario e era descartado aqui. A esteira de
        # estagios so andava por `publicar_produto`; nenhum outro avanco ou
        # retrocesso era possivel pela tela do produto.
        if 'estagio' in data:
            dados['estagio'] = data['estagio']
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
@login_required
def api_deletar(produto_id):
    try:
        product_service.delete(produto_id)
        return jsonify({'success': True, 'message': 'Excluído!'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@produtos_api_bp.route('/bulk_update', methods=['POST'])
@login_required
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
@login_required
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
@login_required
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
        for p in product_service.search_produtos(request.args.get('q', ''), int(request.args.get('limit', 20)), request.args.get('exclude_id'), 'ativo', request.args.get('category_id')):
            p = product_service.enrich_product_data(p)
            res.append({'id': p['id'], 'text': f"{p.get('sku_mestre', '')} - {p.get('name', '')}", 'sku': p.get('sku_mestre', ''), 'name': p.get('name', ''), 'cost': p.get('cost_price', 0), 'categoria_id': p.get('categoria_id')})
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
@login_required
def api_add_bling_link(produto_id):
    try:
        data = request.get_json()
        product_service.add_bling_product_link(produto_id, data.get('bling_product_id'), data.get('bling_sku'), data.get('bling_account_id'), data.get('bling_name', ''))
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@produtos_api_bp.route('/<produto_id>/bling_links/<bid>/<aid>', methods=['DELETE'])
@login_required
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
@login_required
def api_create_product_with_variations(produto_id):
    try:
        data = request.get_json()
        res = product_service.create_product_with_variations({'id': produto_id}, data.get('variations_config', []), data.get('variations_data', []))
        return jsonify({'success': True, 'produto': res})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@produtos_api_bp.route('/<produto_id>/variation-axes', methods=['GET', 'PUT'])
def api_product_variation_axes(produto_id):
    try:
        if request.method == 'PUT':
            data = request.get_json() or {}
            eixos = product_service.configure_variation_axes(produto_id, data.get('eixos', []))
        else:
            eixos = product_service.get_variation_axes(produto_id)
        return jsonify({'eixos': eixos})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

