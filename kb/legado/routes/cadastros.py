from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash
from services.fornecedor_service import fornecedor_service
from services.deposito_service import deposito_service
from services.conta_bling_service import conta_bling_service
from services.canal_venda_service import canal_venda_service
from services.category_service import category_service
from services.tag_service import tag_service
from services.unit_of_measure_service import unit_of_measure_service
from services.composition_template_service import composition_template_service

cadastros_bp = Blueprint('cadastros', __name__)

# Fornecedor routes
@cadastros_bp.route('/fornecedor')
def fornecedor_list():
    """List all fornecedores."""
    try:
        fornecedores = fornecedor_service.get_all()
        return render_template('fornecedor/list.html', fornecedores=fornecedores)
    except Exception as e:
        flash(f'Erro ao carregar fornecedores: {str(e)}', 'error')
        return render_template('error.html')

@cadastros_bp.route('/fornecedor/novo', methods=['GET', 'POST'])
def fornecedor_new():
    """Create new fornecedor."""
    if request.method == 'POST':
        try:
            data = {
                'nome_razao_social': request.form['nome_razao_social'],
                'cpf_cnpj': request.form.get('cpf_cnpj'),
                'email': request.form.get('email'),
                'telefone': request.form.get('telefone'),
                'ativo': request.form.get('ativo') == 'on'
            }
            fornecedor_service.create(data)
            flash('Fornecedor criado com sucesso!', 'success')
            return redirect(url_for('cadastros.fornecedor_list'))
        except Exception as e:
            flash(f'Erro ao criar fornecedor: {str(e)}', 'error')

    return render_template('fornecedor/form.html', fornecedor=None)

@cadastros_bp.route('/fornecedor/<fornecedor_id>/editar', methods=['GET', 'POST'])
def fornecedor_edit(fornecedor_id):
    """Edit existing fornecedor."""
    fornecedor = fornecedor_service.get_by_id(fornecedor_id)
    if not fornecedor:
        flash('Fornecedor não encontrado.', 'error')
        return redirect(url_for('cadastros.fornecedor_list'))

    if request.method == 'POST':
        try:
            data = {
                'nome_razao_social': request.form['nome_razao_social'],
                'cpf_cnpj': request.form.get('cpf_cnpj'),
                'email': request.form.get('email'),
                'telefone': request.form.get('telefone'),
                'ativo': request.form.get('ativo') == 'on'
            }
            fornecedor_service.update(fornecedor_id, data)
            flash('Fornecedor atualizado com sucesso!', 'success')
            return redirect(url_for('cadastros.fornecedor_list'))
        except Exception as e:
            flash(f'Erro ao atualizar fornecedor: {str(e)}', 'error')

    return render_template('fornecedor/form.html', fornecedor=fornecedor)

# Depósito routes
@cadastros_bp.route('/deposito')
def deposito_list():
    """List all depósitos."""
    try:
        depositos = deposito_service.get_all()
        return render_template('deposito/list.html', depositos=depositos)
    except Exception as e:
        flash(f'Erro ao carregar depósitos: {str(e)}', 'error')
        return render_template('error.html')

@cadastros_bp.route('/deposito/novo', methods=['GET', 'POST'])
def deposito_new():
    """Create new depósito."""
    if request.method == 'POST':
        try:
            data = {
                'nome': request.form['nome'],
                'tipo': request.form.get('tipo', 'MATERIA_PRIMA'),
                'ativo': request.form.get('ativo') == 'on'
            }
            deposito_service.create(data)
            flash('Depósito criado com sucesso!', 'success')
            return redirect(url_for('cadastros.deposito_list'))
        except Exception as e:
            flash(f'Erro ao criar depósito: {str(e)}', 'error')

    return render_template('deposito/form.html', deposito=None)

@cadastros_bp.route('/deposito/<deposito_id>/editar', methods=['GET', 'POST'])
def deposito_edit(deposito_id):
    """Edit existing depósito."""
    deposito = deposito_service.get_by_id(deposito_id)
    if not deposito:
        flash('Depósito não encontrado.', 'error')
        return redirect(url_for('cadastros.deposito_list'))

    if request.method == 'POST':
        try:
            data = {
                'nome': request.form['nome'],
                'tipo': request.form.get('tipo'),
                'ativo': request.form.get('ativo') == 'on'
            }
            deposito_service.update(deposito_id, data)
            flash('Depósito atualizado com sucesso!', 'success')
            return redirect(url_for('cadastros.deposito_list'))
        except Exception as e:
            flash(f'Erro ao atualizar depósito: {str(e)}', 'error')

    return render_template('deposito/form.html', deposito=deposito)

# Canal de Venda routes
@cadastros_bp.route('/canal-venda')
def canal_venda_list():
    """List all canais de venda."""
    try:
        canais = canal_venda_service.get_all()
        contas_bling = conta_bling_service.get_all()  # For dependency display
        return render_template('canal_venda/list.html', canais=canais, contas_bling=contas_bling)
    except Exception as e:
        flash(f'Erro ao carregar canais de venda: {str(e)}', 'error')
        return render_template('error.html')

@cadastros_bp.route('/canal-venda/novo', methods=['GET', 'POST'])
def canal_venda_new():
    """Create new canal de venda."""
    contas_bling = conta_bling_service.get_all()

    if request.method == 'POST':
        try:
            data = {
                'nome': request.form['nome'],
                'plataforma': request.form.get('plataforma'),
                'conta_bling_id': request.form['conta_bling_id'],
                'ativo': request.form.get('ativo') == 'on'
            }
            canal_venda_service.create(data)
            flash('Canal de venda criado com sucesso!', 'success')
            return redirect(url_for('cadastros.canal_venda_list'))
        except Exception as e:
            flash(f'Erro ao criar canal de venda: {str(e)}', 'error')

    return render_template('canal_venda/form.html', canal=None, contas_bling=contas_bling)

@cadastros_bp.route('/canal-venda/<canal_id>/editar', methods=['GET', 'POST'])
def canal_venda_edit(canal_id):
    """Edit existing canal de venda."""
    canal = canal_venda_service.get_by_id(canal_id)
    contas_bling = conta_bling_service.get_all()

    if not canal:
        flash('Canal de venda não encontrado.', 'error')
        return redirect(url_for('cadastros.canal_venda_list'))

    if request.method == 'POST':
        try:
            data = {
                'nome': request.form['nome'],
                'plataforma': request.form.get('plataforma'),
                'conta_bling_id': request.form['conta_bling_id'],
                'ativo': request.form.get('ativo') == 'on'
            }
            canal_venda_service.update(canal_id, data)
            flash('Canal de venda atualizado com sucesso!', 'success')
            return redirect(url_for('cadastros.canal_venda_list'))
        except Exception as e:
            flash(f'Erro ao atualizar canal de venda: {str(e)}', 'error')

    return render_template('canal_venda/form.html', canal=canal, contas_bling=contas_bling)

# Category routes
@cadastros_bp.route('/categoria')
def categoria_list():
    """List all categorias."""
    try:
        categorias = category_service.get_all()
        return render_template('categoria/list.html', categorias=categorias)
    except Exception as e:
        flash(f'Erro ao carregar categorias: {str(e)}', 'error')
        return render_template('error.html')

@cadastros_bp.route('/categoria/novo', methods=['GET', 'POST'])
def categoria_new():
    """Create new categoria."""
    categorias = category_service.get_all()

    if request.method == 'POST':
        try:
            parent_id = request.form.get('parent_category_id')
            composition_template_id = request.form.get('composition_template_id')
            data = {
                'name': request.form['name'],
                'description': request.form.get('description'),
                'bling_category_id': request.form.get('bling_category_id') or None,
                'parent_category_id': parent_id if parent_id else None,
                'composition_template_id': composition_template_id if composition_template_id else None
            }
            category_service.create(data)
            flash('Categoria criada com sucesso!', 'success')
            return redirect(url_for('cadastros.categoria_list'))
        except Exception as e:
            flash(f'Erro ao criar categoria: {str(e)}', 'error')

    templates = composition_template_service.get_all_templates()
    return render_template('categoria/form.html', categoria=None, categorias=categorias, templates=templates)

@cadastros_bp.route('/categoria/<categoria_id>/editar', methods=['GET', 'POST'])
def categoria_edit(categoria_id):
    """Edit existing categoria."""
    categoria = category_service.get_by_id(categoria_id)
    categorias = category_service.get_all()

    if not categoria:
        flash('Categoria não encontrada.', 'error')
        return redirect(url_for('cadastros.categoria_list'))

    if request.method == 'POST':
        try:
            parent_id = request.form.get('parent_category_id')
            composition_template_id = request.form.get('composition_template_id')
            data = {
                'name': request.form['name'],
                'description': request.form.get('description'),
                'bling_category_id': request.form.get('bling_category_id') or None,
                'parent_category_id': parent_id if parent_id else None,
                'composition_template_id': composition_template_id if composition_template_id else None
            }
            category_service.update(categoria_id, data)
            flash('Categoria atualizada com sucesso!', 'success')
            return redirect(url_for('cadastros.categoria_list'))
        except Exception as e:
            flash(f'Erro ao atualizar categoria: {str(e)}', 'error')

    templates = composition_template_service.get_all_templates()
    return render_template('categoria/form.html', categoria=categoria, categorias=categorias, templates=templates)

# Tag routes
@cadastros_bp.route('/tag')
def tag_list():
    """List all tags."""
    try:
        tags = tag_service.get_all()
        return render_template('tag/list.html', tags=tags)
    except Exception as e:
        flash(f'Erro ao carregar tags: {str(e)}', 'error')
        return render_template('error.html')

@cadastros_bp.route('/tag/novo', methods=['GET', 'POST'])
def tag_new():
    """Create new tag."""
    if request.method == 'POST':
        try:
            composition_template_id = request.form.get('composition_template_id')
            data = {
                'name': request.form['name'],
                'composition_template_id': composition_template_id if composition_template_id else None
            }
            tag_service.create(data)
            flash('Tag criada com sucesso!', 'success')
            return redirect(url_for('cadastros.tag_list'))
        except Exception as e:
            flash(f'Erro ao criar tag: {str(e)}', 'error')

    templates = composition_template_service.get_all_templates()
    return render_template('tag/form.html', tag=None, templates=templates)

@cadastros_bp.route('/tag/<tag_id>/editar', methods=['GET', 'POST'])
def tag_edit(tag_id):
    """Edit existing tag."""
    tag = tag_service.get_by_id(tag_id)
    if not tag:
        flash('Tag não encontrada.', 'error')
        return redirect(url_for('cadastros.tag_list'))

    if request.method == 'POST':
        try:
            composition_template_id = request.form.get('composition_template_id')
            data = {
                'name': request.form['name'],
                'composition_template_id': composition_template_id if composition_template_id else None
            }
            tag_service.update(tag_id, data)
            flash('Tag atualizada com sucesso!', 'success')
            return redirect(url_for('cadastros.tag_list'))
        except Exception as e:
            flash(f'Erro ao atualizar tag: {str(e)}', 'error')

    templates = composition_template_service.get_all_templates()
    return render_template('tag/form.html', tag=tag, templates=templates)

# Unidade de Medida routes
@cadastros_bp.route('/unidade-medida')
def unidade_medida_list():
    """List all unidades de medida."""
    try:
        unidades = unit_of_measure_service.get_all()
        return render_template('unidade_medida/list.html', unidades=unidades)
    except Exception as e:
        flash(f'Erro ao carregar unidades de medida: {str(e)}', 'error')
        return render_template('error.html')

@cadastros_bp.route('/unidade-medida/novo', methods=['GET', 'POST'])
def unidade_medida_new():
    """Create new unidade de medida."""
    if request.method == 'POST':
        try:
            data = {
                'name': request.form['name'],
                'symbol': request.form['symbol']
            }
            unit_of_measure_service.create(data)
            flash('Unidade de medida criada com sucesso!', 'success')
            return redirect(url_for('cadastros.unidade_medida_list'))
        except Exception as e:
            flash(f'Erro ao criar unidade de medida: {str(e)}', 'error')

    return render_template('unidade_medida/form.html', unidade=None)

@cadastros_bp.route('/unidade-medida/<unidade_id>/editar', methods=['GET', 'POST'])
def unidade_medida_edit(unidade_id):
    """Edit existing unidade de medida."""
    unidade = unit_of_measure_service.get_by_id(unidade_id)
    if not unidade:
        flash('Unidade de medida não encontrada.', 'error')
        return redirect(url_for('cadastros.unidade_medida_list'))

    if request.method == 'POST':
        try:
            data = {
                'name': request.form['name'],
                'symbol': request.form['symbol']
            }
            unit_of_measure_service.update(unidade_id, data)
            flash('Unidade de medida atualizada com sucesso!', 'success')
            return redirect(url_for('cadastros.unidade_medida_list'))
        except Exception as e:
            flash(f'Erro ao atualizar unidade de medida: {str(e)}', 'error')

    return render_template('unidade_medida/form.html', unidade=unidade)

# API endpoints for AJAX requests
@cadastros_bp.route('/api/fornecedor/search')
def fornecedor_api_search():
    """API endpoint for fornecedor search."""
    query = request.args.get('q', '')
    try:
        results = fornecedor_service.search(query)
        return jsonify([{
            'id': f['id'],
            'text': f"{f['nome_razao_social']} ({f['cpf_cnpj'] or 'Sem CPF/CNPJ'})"
        } for f in results])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@cadastros_bp.route('/api/conta-bling/search')
def conta_bling_api_search():
    """API endpoint for conta bling search."""
    try:
        results = conta_bling_service.get_all()
        return jsonify([{
            'id': c['id'],
            'text': f"{c['account_name']} ({c['cnpj']})"
        } for c in results])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@cadastros_bp.route('/api/deposito/search')
def deposito_api_search():
    """API endpoint for depósito search."""
    try:
        results = deposito_service.get_all()
        return jsonify([{
            'id': d['id'],
            'text': f"{d['nome']} ({d['tipo']})"
        } for d in results])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@cadastros_bp.route('/api/canal-venda/search')
def canal_venda_api_search():
    """API endpoint for canal venda search."""
    try:
        results = canal_venda_service.get_all()
        return jsonify([{
            'id': c['id'],
            'text': f"{c['nome']} ({c['plataforma'] or 'N/A'})"
        } for c in results])
    except Exception as e:
        return jsonify({'error': str(e)}), 500
