from flask import request, render_template, redirect, url_for, flash
from nistiprint_shared.services.fornecedor_service import fornecedor_service
from nistiprint_shared.services.deposito_service import deposito_service
from nistiprint_shared.services.conta_bling_service import conta_bling_service
from nistiprint_shared.services.canal_venda_service import canal_venda_service
from nistiprint_shared.services.category_service import category_service
from nistiprint_shared.services.tag_service import tag_service
from nistiprint_shared.services.unit_of_measure_service import unit_of_measure_service
from nistiprint_shared.services.plataforma_service import plataforma_service
from nistiprint_shared.services.setor_service import setor_service
from .cadastros_base import cadastros_bp

# Setor
@cadastros_bp.route('/setores')
def setor_list():
    try:
        setores = setor_service.get_all_including_inactive()
        return render_template('setor/list.html', setores=setores)
    except Exception as e:
        flash(f'Erro ao carregar setores: {str(e)}', 'error')
        return render_template('error.html')

@cadastros_bp.route('/setores/novo', methods=['GET', 'POST'])
def setor_new():
    if request.method == 'POST':
        try:
            nome = request.form['nome']
            descricao = request.form.get('descricao', '')
            ativo = request.form.get('ativo') == 'on'
            setor_data = {'nome': nome, 'descricao': descricao, 'ativo': ativo}
            setor_service.create(setor_data)
            flash('Setor criado com sucesso!', 'success')
            return redirect(url_for('cadastros.setor_list'))
        except Exception as e:
            flash(f'Erro ao criar setor: {str(e)}', 'error')
    return render_template('setor/form.html', setor=None)

@cadastros_bp.route('/setores/<setor_id>/editar', methods=['GET', 'POST', 'PUT'])
def setor_edit(setor_id):
    setor = setor_service.get_by_id(int(setor_id))
    if not setor:
        flash('Setor não encontrado.', 'error')
        return redirect(url_for('cadastros.setor_list'))
    if request.method in ['POST', 'PUT']:
        try:
            nome = request.form['nome']
            descricao = request.form.get('descricao', '')
            ativo = request.form.get('ativo') == 'on'
            setor_data = {'nome': nome, 'descricao': descricao, 'ativo': ativo}
            setor_service.update(int(setor_id), setor_data)
            flash('Setor atualizado com sucesso!', 'success')
            return redirect(url_for('cadastros.setor_list'))
        except Exception as e:
            flash(f'Erro ao atualizar setor: {str(e)}', 'error')
    return render_template('setor/form.html', setor=setor)

# Fornecedor
@cadastros_bp.route('/fornecedor')
def fornecedor_list():
    try:
        fornecedores = fornecedor_service.get_all()
        return render_template('fornecedor/list.html', fornecedores=fornecedores)
    except Exception as e:
        flash(f'Erro ao carregar fornecedores: {str(e)}', 'error')
        return render_template('error.html')

@cadastros_bp.route('/fornecedor/novo', methods=['GET', 'POST'])
def fornecedor_new():
    if request.method == 'POST':
        try:
            supplier_data = {
                'nome_razao_social': request.form['nome_razao_social'],
                'cpf_cnpj': request.form.get('cpf_cnpj'),
                'email': request.form.get('email'),
                'telefone': request.form.get('telefone'),
                'ativo': request.form.get('ativo') == 'on'
            }
            fornecedor_service.create(supplier_data)
            flash('Fornecedor criado com sucesso!', 'success')
            return redirect(url_for('cadastros.fornecedor_list'))
        except Exception as e:
            flash(f'Erro ao criar fornecedor: {str(e)}', 'error')
    return render_template('fornecedor/form.html', fornecedor=None)

@cadastros_bp.route('/fornecedor/<fornecedor_id>/editar', methods=['GET', 'POST', 'PUT'])
def fornecedor_edit(fornecedor_id):
    fornecedor = fornecedor_service.get_by_id(fornecedor_id)
    if not fornecedor:
        flash('Fornecedor não encontrado.', 'error')
        return redirect(url_for('cadastros.fornecedor_list'))
    if request.method in ['POST', 'PUT']:
        try:
            supplier_data = {
                'nome_razao_social': request.form['nome_razao_social'],
                'cpf_cnpj': request.form.get('cpf_cnpj'),
                'email': request.form.get('email'),
                'telefone': request.form.get('telefone'),
                'ativo': request.form.get('ativo') == 'on'
            }
            fornecedor_service.update(fornecedor_id, supplier_data)
            flash('Fornecedor atualizado com sucesso!', 'success')
            return redirect(url_for('cadastros.fornecedor_list'))
        except Exception as e:
            flash(f'Erro ao atualizar fornecedor: {str(e)}', 'error')
    return render_template('fornecedor/form.html', fornecedor=fornecedor)

# Depósito
@cadastros_bp.route('/deposito')
def deposito_list():
    try:
        depositos = deposito_service.get_all()
        return render_template('deposito/list.html', depositos=depositos)
    except Exception as e:
        flash(f'Erro ao carregar depósitos: {str(e)}', 'error')
        return render_template('error.html')

@cadastros_bp.route('/deposito/novo', methods=['GET', 'POST'])
def deposito_new():
    if request.method == 'POST':
        try:
            deposit_data = {
                'nome': request.form['nome'],
                'tipo': request.form.get('tipo', 'MATERIA_PRIMA'),
                'ativo': request.form.get('ativo') == 'on'
            }
            deposito_service.create(deposit_data)
            flash('Depósito criado com sucesso!', 'success')
            return redirect(url_for('cadastros.deposito_list'))
        except Exception as e:
            flash(f'Erro ao criar depósito: {str(e)}', 'error')
    return render_template('deposito/form.html', deposito=None)

@cadastros_bp.route('/deposito/<deposito_id>/editar', methods=['GET', 'POST', 'PUT'])
def deposito_edit(deposito_id):
    deposito = deposito_service.get_by_id(deposito_id)
    if not deposito:
        flash('Depósito não encontrado.', 'error')
        return redirect(url_for('cadastros.deposito_list'))
    if request.method in ['POST', 'PUT']:
        try:
            deposit_data = {
                'nome': request.form['nome'],
                'tipo': request.form.get('tipo', 'MATERIA_PRIMA'),
                'ativo': request.form.get('ativo') == 'on'
            }
            deposito_service.update(deposito_id, deposit_data)
            flash('Depósito atualizado com sucesso!', 'success')
            return redirect(url_for('cadastros.deposito_list'))
        except Exception as e:
            flash(f'Erro ao atualizar depósito: {str(e)}', 'error')
    return render_template('deposito/form.html', deposito=deposito)

# Canal de Venda
@cadastros_bp.route('/canal-venda')
def canal_venda_list():
    try:
        canais = canal_venda_service.get_all(active_only=False)
        contas_bling = conta_bling_service.get_all()
        return render_template('canal_venda/list.html', canais=canais, contas_bling=contas_bling)
    except Exception as e:
        flash(f'Erro ao carregar canais de venda: {str(e)}', 'error')
        return render_template('error.html')

@cadastros_bp.route('/canal-venda/novo', methods=['GET', 'POST'])
def canal_venda_new():
    contas_bling = conta_bling_service.get_all()
    plataformas = plataforma_service.get_all()
    if request.method == 'POST':
        try:
            canal_data = {
                'nome': request.form['nome'],
                'slug': request.form.get('slug'),
                'plataforma': request.form.get('plataforma'),
                'conta_bling_id': request.form['conta_bling_id'],
                'ativo': request.form.get('ativo') == 'on'
            }
            canal_venda_service.create(canal_data)
            flash('Canal de venda criado com sucesso!', 'success')
            return redirect(url_for('cadastros.canal_venda_list'))
        except Exception as e:
            flash(f'Erro ao criar canal de venda: {str(e)}', 'error')
    return render_template('canal_venda/form.html', canal=None, contas_bling=contas_bling, plataformas=plataformas)

@cadastros_bp.route('/canal-venda/<canal_id>/editar', methods=['GET', 'POST', 'PUT'])
def canal_venda_edit(canal_id):
    canal = canal_venda_service.get_by_id(canal_id)
    contas_bling = conta_bling_service.get_all()
    plataformas = plataforma_service.get_all()
    if not canal:
        flash('Canal de venda não encontrado.', 'error')
        return redirect(url_for('cadastros.canal_venda_list'))
    if request.method in ['POST', 'PUT']:
        try:
            canal_data = {
                'nome': request.form['nome'],
                'slug': request.form.get('slug'),
                'plataforma': request.form.get('plataforma'),
                'conta_bling_id': request.form['conta_bling_id'],
                'ativo': request.form.get('ativo') == 'on'
            }
            canal_venda_service.update(canal_id, canal_data)
            flash('Canal de venda atualizado com sucesso!', 'success')
            return redirect(url_for('cadastros.canal_venda_list'))
        except Exception as e:
            flash(f'Erro ao atualizar canal de venda: {str(e)}', 'error')
    return render_template('canal_venda/form.html', canal=canal, contas_bling=contas_bling, plataformas=plataformas)

# Categoria
@cadastros_bp.route('/categoria')
def categoria_list():
    try:
        categorias = category_service.get_all()
        return render_template('categoria/list.html', categorias=categorias)
    except Exception as e:
        flash(f'Erro ao carregar categorias: {str(e)}', 'error')
        return render_template('error.html')

@cadastros_bp.route('/categoria/novo', methods=['GET', 'POST'])
def categoria_new():
    categorias = category_service.get_all()
    if request.method == 'POST':
        try:
            category_data = {
                'name': request.form['name'],
                'description': request.form.get('description'),
                'bling_category_id': request.form.get('bling_category_id') or None,
                'parent_category_id': request.form.get('parent_category_id') or None
            }
            category_service.create(category_data)
            flash('Categoria criada com sucesso!', 'success')
            return redirect(url_for('cadastros.categoria_list'))
        except Exception as e:
            flash(f'Erro ao criar categoria: {str(e)}', 'error')
    return render_template('categoria/form.html', categoria=None, categorias=categorias)

@cadastros_bp.route('/categoria/<categoria_id>/editar', methods=['GET', 'POST', 'PUT'])
def categoria_edit(categoria_id):
    categoria = category_service.get_by_id(categoria_id)
    categorias = category_service.get_all()
    if not categoria:
        flash('Categoria não encontrada.', 'error')
        return redirect(url_for('cadastros.categoria_list'))
    if request.method in ['POST', 'PUT']:
        try:
            category_data = {
                'name': request.form['name'],
                'description': request.form.get('description'),
                'bling_category_id': request.form.get('bling_category_id') or None,
                'parent_category_id': request.form.get('parent_category_id') or None
            }
            category_service.update(categoria_id, category_data)
            flash('Categoria atualizada com sucesso!', 'success')
            return redirect(url_for('cadastros.categoria_list'))
        except Exception as e:
            flash(f'Erro ao atualizar categoria: {str(e)}', 'error')
    return render_template('categoria/form.html', categoria=categoria, categorias=categorias)

# Tags
@cadastros_bp.route('/tag')
def tag_list():
    try:
        tags = tag_service.get_all()
        return render_template('tag/list.html', tags=tags)
    except Exception as e:
        flash(f'Erro ao carregar tags: {str(e)}', 'error')
        return render_template('error.html')

@cadastros_bp.route('/tag/novo', methods=['GET', 'POST'])
def tag_new():
    if request.method == 'POST':
        try:
            tag_service.create({'name': request.form['name']})
            flash('Tag criada com sucesso!', 'success')
            return redirect(url_for('cadastros.tag_list'))
        except Exception as e:
            flash(f'Erro ao criar tag: {str(e)}', 'error')
    return render_template('tag/form.html', tag=None)

@cadastros_bp.route('/tag/<tag_id>/editar', methods=['GET', 'POST', 'PUT'])
def tag_edit(tag_id):
    tag = tag_service.get_by_id(tag_id)
    if not tag:
        flash('Tag não encontrada.', 'error')
        return redirect(url_for('cadastros.tag_list'))
    if request.method in ['POST', 'PUT']:
        try:
            tag_service.update(tag_id, {'name': request.form['name']})
            flash('Tag atualizada com sucesso!', 'success')
            return redirect(url_for('cadastros.tag_list'))
        except Exception as e:
            flash(f'Erro ao atualizar tag: {str(e)}', 'error')
    return render_template('tag/form.html', tag=tag)

# Unidade de Medida
@cadastros_bp.route('/unidade-medida')
def unidade_medida_list():
    try:
        unidades = unit_of_measure_service.get_all()
        return render_template('unidade_medida/list.html', unidades=unidades)
    except Exception as e:
        flash(f'Erro ao carregar unidades de medida: {str(e)}', 'error')
        return render_template('error.html')

@cadastros_bp.route('/unidade-medida/novo', methods=['GET', 'POST'])
def unidade_medida_new():
    if request.method == 'POST':
        try:
            unit_of_measure_service.create({'name': request.form['name'], 'symbol': request.form['symbol']})
            flash('Unidade de medida criada com sucesso!', 'success')
            return redirect(url_for('cadastros.unidade_medida_list'))
        except Exception as e:
            flash(f'Erro ao criar unidade de medida: {str(e)}', 'error')
    return render_template('unidade_medida/form.html', unidade=None)

@cadastros_bp.route('/unidade-medida/<unidade_id>/editar', methods=['GET', 'POST', 'PUT'])
def unidade_medida_edit(unidade_id):
    unidade = unit_of_measure_service.get_by_id(unidade_id)
    if not unidade:
        flash('Unidade de medida não encontrada.', 'error')
        return redirect(url_for('cadastros.unidade_medida_list'))
    if request.method in ['POST', 'PUT']:
        try:
            unit_of_measure_service.update(unidade_id, {'name': request.form['name'], 'symbol': request.form['symbol']})
            flash('Unidade de medida atualizada com sucesso!', 'success')
            return redirect(url_for('cadastros.unidade_medida_list'))
        except Exception as e:
            flash(f'Erro ao atualizar unidade de medida: {str(e)}', 'error')
    return render_template('unidade_medida/form.html', unidade=unidade)
