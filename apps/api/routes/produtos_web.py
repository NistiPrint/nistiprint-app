from flask import request, render_template, flash, redirect, url_for
import json
import uuid
from nistiprint_shared.services.product_service import product_service
from nistiprint_shared.services.category_service import category_service
from nistiprint_shared.services.tag_service import tag_service
from nistiprint_shared.services.unit_of_measure_service import unit_of_measure_service
from nistiprint_shared.services.app_config_service import app_config_service
from nistiprint_shared.services.conta_bling_service import conta_bling_service
from routes.auth import login_required
from .produtos_base import produtos_bp

@produtos_bp.route('', methods=['GET'])
def index():
    try:
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))
        q = request.args.get('q', '').strip()
        category_id = request.args.get('category_id', '').strip()
        status = request.args.get('status', '').strip()

        produtos, total_pages = product_service.get_products(q=q, category_id=category_id, status=status, page=page, per_page=per_page)
        produtos = [product_service.enrich_product_data(p) for p in produtos]

        return render_template('produtos/index.html', produtos=produtos, page=page, per_page=per_page, total_pages=total_pages, 
                               q=q, category_id=category_id, status=status, categorias=category_service.get_all(),
                               unidades=unit_of_measure_service.get_all(), tags=tag_service.get_all())
    except Exception as e:
        flash(f'Erro ao carregar produtos: {str(e)}', 'error')
        return render_template('produtos/index.html', produtos=[], page=1, total_pages=1, q='', category_id='', categorias=category_service.get_all())

@produtos_bp.route('/novo', methods=['GET', 'POST'])
def criar():
    try:
        if request.method == 'POST':
            dados_produto = {
                'sku': request.form.get('sku_mestre'), 'name': request.form.get('name'), 'description': request.form.get('description'),
                'category_id': request.form.get('category_id'), 'unit_of_measure_id': request.form.get('unit_of_measure_id'),
                'material_type': request.form.get('material_type', 'produto_acabado'), 'cost_price': float(request.form.get('cost_price') or 0),
                'stock_min': request.form.get('stock_min'), 'stock_max': request.form.get('stock_max'),
                'requires_personalization': request.form.get('requires_personalization') == 'on',
                'status': request.form.get('status'), 'formato': request.form.get('formato', 'simples'),
                'setor_responsavel_id': request.form.get('setor_responsavel_id'),
                'tags': [{'tag_id': tid} for tid in request.form.getlist('tags') if tid]
            }
            if not dados_produto['sku'] or not dados_produto['name']:
                flash('SKU Mestre e Nome são obrigatórios', 'error')
                return redirect(request.url)
            produto = product_service.create(dados_produto)
            flash(f'Produto "{produto["name"]}" criado!', 'success')
            return redirect(url_for('produtos.editar', produto_id=produto['id']))

        return render_template('produtos/form.html', produto=None, categorias=category_service.get_all(), 
                             unidades=unit_of_measure_service.get_all(), tags=tag_service.get_all(), 
                             temp_product_id=str(uuid.uuid4()), view_mode=False, 
                             default_bling_account_id=app_config_service.get_config('default_bling_account_id'),
                             bling_product_links=[], external_product_links={'skus': [], 'names': [], 'ids': []})
    except Exception as e:
        flash(f'Erro ao carregar formulário: {str(e)}', 'error')
        return render_template('produtos/form.html', produto=None, categorias=[], unidades=[], tags=[], view_mode=False)

@produtos_bp.route('/associate/<component_id>', methods=['GET'])
def associate_component(component_id):
    try:
        component = product_service.enrich_product_data(product_service.get_by_id(component_id))
        if not component:
            flash('Componente não encontrado', 'error')
            return redirect(url_for('produtos.index'))
        return render_template('produtos/associate_component.html', component=component, 
                             categorias=category_service.get_all(), tags=tag_service.get_all())
    except Exception as e:
        flash(f'Erro ao carregar página de associação: {str(e)}', 'error')
        return redirect(url_for('produtos.index'))

@produtos_bp.route('/<produto_id>/editar', methods=['GET', 'POST', 'PUT'])
def editar(produto_id):
    try:
        product_service.clear_cache()
        produto = product_service.get_by_id(produto_id)
        if not produto:
            flash('Produto não encontrado', 'error')
            return redirect(url_for('produtos.index'))

        categorias, unidades, tags_d = category_service.get_all(), unit_of_measure_service.get_all(), tag_service.get_all()
        bom_components = product_service.get_bom_components(produto_id) if produto.get('is_composite') else []
        bling_links = product_service.get_bling_product_links(produto_id)
        artworks = product_service.get_artworks_for_product(produto_id)

        if request.method in ['POST', 'PUT']:
            dados_atualizacao = {
                'sku': request.form.get('sku_mestre'), 'name': request.form.get('name'), 'description': request.form.get('description'),
                'category_id': request.form.get('category_id'), 'unit_of_measure_id': request.form.get('unit_of_measure_id'),
                'material_type': request.form.get('material_type'), 'cost_price': float(request.form.get('cost_price') or 0),
                'stock_min': request.form.get('stock_min'), 'stock_max': request.form.get('stock_max'),
                'requires_personalization': request.form.get('requires_personalization') == 'on',
                'status': request.form.get('status'), 'formato': request.form.get('formato'),
                'setor_responsavel_id': request.form.get('setor_responsavel_id'),
                'tags': [{'tag_id': tid} for tid in request.form.getlist('tags') if tid]
            }
            try:
                dados_atualizacao['external_product_links'] = json.loads(request.form.get('external_product_links_json', '{}'))
            except:
                dados_atualizacao['external_product_links'] = {'skus': [], 'names': [], 'ids': []}

            if not dados_atualizacao['sku'] or not dados_atualizacao['name']:
                flash('Campos obrigatórios ausentes', 'error')
                return render_template('produtos/form.html', produto=produto, categorias=categorias, unidades=unidades, 
                                     tags=tags_d, bom_components=bom_components, product_artworks=artworks, view_mode=False)

            produto_atualizado = product_service.update(produto_id, dados_atualizacao)
            product_service.sync_external_product_links(produto_id, dados_atualizacao['external_product_links'])
            flash(f'Produto "{produto_atualizado["name"]}" atualizado!', 'success')
            return redirect(url_for('produtos.editar', produto_id=produto_id))

        return render_template('produtos/form.html', produto=produto, categorias=categorias, unidades=unidades, 
                             tags=tags_d, bom_components=bom_components, bling_product_links=bling_links, 
                             product_artworks=artworks, external_product_links=produto.get('external_product_links', {'skus': [], 'names': [], 'ids': []}), 
                             view_mode=False, default_bling_account_id=app_config_service.get_config('default_bling_account_id'), 
                             all_bling_accounts=conta_bling_service.get_all())
    except Exception as e:
        flash(f'Erro ao carregar/editar produto: {str(e)}', 'error')
        return redirect(url_for('produtos.index'))
