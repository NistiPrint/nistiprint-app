from flask import request, jsonify
from nistiprint_shared.services.ponto_coleta_service import ponto_coleta_service
from nistiprint_shared.services.plataforma_service import plataforma_service
from nistiprint_shared.services.setor_service import setor_service
from nistiprint_shared.services.fornecedor_service import fornecedor_service
from nistiprint_shared.services.deposito_service import deposito_service
from nistiprint_shared.services.canal_venda_service import canal_venda_service
from nistiprint_shared.services.conta_bling_service import conta_bling_service
from nistiprint_shared.services.category_service import category_service
from nistiprint_shared.services.category_bom_rule_service import category_bom_rule_service
from nistiprint_shared.services.tag_service import tag_service
from nistiprint_shared.services.unit_of_measure_service import unit_of_measure_service
from .cadastros_base import cadastros_api_bp

# Ponto de Coleta
@cadastros_api_bp.route('/ponto-coleta', methods=['GET'])
def api_ponto_coleta_list():
    try:
        active_only = request.args.get('active_only', 'true').lower() == 'true'
        pontos = ponto_coleta_service.get_all(active_only=active_only)
        return jsonify({'pontos': pontos})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@cadastros_api_bp.route('/ponto-coleta', methods=['POST'])
def api_ponto_coleta_new():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Dados inválidos'}), 400
        
        new_ponto = ponto_coleta_service.create(data)
        return jsonify({'success': True, 'message': 'Ponto de coleta criado com sucesso!', 'ponto': new_ponto}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@cadastros_api_bp.route('/ponto-coleta/<int:id>', methods=['GET'])
def api_ponto_coleta_get(id):
    try:
        ponto = ponto_coleta_service.get_by_id(id)
        if not ponto:
            return jsonify({'error': 'Ponto de coleta não encontrado.'}), 404
        return jsonify({'ponto': ponto})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@cadastros_api_bp.route('/ponto-coleta/<int:id>', methods=['PUT'])
def api_ponto_coleta_edit(id):
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Dados inválidos'}), 400
        
        updated_ponto = ponto_coleta_service.update(id, data)
        return jsonify({'success': True, 'message': 'Ponto de coleta atualizado com sucesso!', 'ponto': updated_ponto})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@cadastros_api_bp.route('/ponto-coleta/<int:id>', methods=['DELETE'])
def api_ponto_coleta_delete(id):
    try:
        ponto_coleta_service.delete(id)
        return jsonify({'success': True, 'message': 'Ponto de coleta deletado com sucesso!'})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

# Plataforma
@cadastros_api_bp.route('/plataforma', methods=['GET'])
def api_plataforma_list():
    try:
        plataformas = plataforma_service.get_all()
        return jsonify({'plataformas': plataformas})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@cadastros_api_bp.route('/plataforma', methods=['POST'])
def api_plataforma_new():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Dados inválidos'}), 400
        
        plataforma_data = {
            'nome': data.get('nome'),
            'ativo': data.get('ativo', True)
        }
        new_plataforma = plataforma_service.create(plataforma_data)
        return jsonify({'success': True, 'message': 'Plataforma criada com sucesso!', 'plataforma': new_plataforma}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@cadastros_api_bp.route('/plataforma/<plataforma_id>', methods=['GET'])
def api_plataforma_get(plataforma_id):
    try:
        plataforma = plataforma_service.get_by_id(plataforma_id)
        if not plataforma:
            return jsonify({'error': 'Plataforma não encontrada.'}), 404
        return jsonify({'plataforma': plataforma})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@cadastros_api_bp.route('/plataforma/<plataforma_id>', methods=['PUT'])
def api_plataforma_edit(plataforma_id):
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Dados inválidos'}), 400
        
        plataforma_data = {
            'nome': data.get('nome'),
            'ativo': data.get('ativo', True)
        }
        updated_plataforma = plataforma_service.update(plataforma_id, plataforma_data)
        return jsonify({'success': True, 'message': 'Plataforma atualizada com sucesso!', 'plataforma': updated_plataforma})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@cadastros_api_bp.route('/plataforma/<plataforma_id>', methods=['DELETE'])
def api_plataforma_delete(plataforma_id):
    try:
        plataforma_service.delete(plataforma_id)
        return jsonify({'success': True, 'message': 'Plataforma deletada com sucesso!'})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

# Setor
@cadastros_api_bp.route('/setor', methods=['GET'])
def api_setor_list():
    try:
        setores = setor_service.get_all_including_inactive()
        return jsonify({'setores': setores})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@cadastros_api_bp.route('/setor', methods=['POST'])
def api_setor_new():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Dados inválidos'}), 400

        setor_data = {
            'nome': data.get('nome'),
            'descricao': data.get('descricao', ''),
            'ativo': data.get('ativo', True)
        }
        new_setor = setor_service.create(setor_data)
        return jsonify({'success': True, 'message': 'Setor criado com sucesso!', 'setor': new_setor}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@cadastros_api_bp.route('/setor/<setor_id>', methods=['GET'])
def api_setor_get(setor_id):
    try:
        setor = setor_service.get_by_id(int(setor_id))
        if not setor:
            return jsonify({'error': 'Setor não encontrado.'}), 404
        return jsonify({'setor': setor})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@cadastros_api_bp.route('/setor/<setor_id>', methods=['PUT'])
def api_setor_edit(setor_id):
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Dados inválidos'}), 400

        setor_data = {
            'nome': data.get('nome'),
            'descricao': data.get('descricao', ''),
            'ativo': data.get('ativo', True)
        }
        updated_setor = setor_service.update(int(setor_id), setor_data)
        return jsonify({'success': True, 'message': 'Setor atualizado com sucesso!', 'setor': updated_setor})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@cadastros_api_bp.route('/setor/<setor_id>', methods=['DELETE'])
def api_setor_delete(setor_id):
    try:
        setor_service.delete(int(setor_id))
        return jsonify({'success': True, 'message': 'Setor deletado com sucesso!'})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

# Fornecedor
@cadastros_api_bp.route('/fornecedor', methods=['GET'])
def api_fornecedor_list():
    try:
        fornecedores = fornecedor_service.get_all()
        return jsonify({'fornecedores': fornecedores})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@cadastros_api_bp.route('/fornecedor', methods=['POST'])
def api_fornecedor_new():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Dados inválidos'}), 400
        
        supplier_data = {
            'nome_razao_social': data.get('nome_razao_social'),
            'cpf_cnpj': data.get('cpf_cnpj'),
            'email': data.get('email'),
            'telefone': data.get('telefone'),
            'ativo': data.get('ativo', False)
        }
        new_fornecedor = fornecedor_service.create(supplier_data)
        return jsonify({'success': True, 'message': 'Fornecedor criado com sucesso!', 'fornecedor': new_fornecedor}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@cadastros_api_bp.route('/fornecedor/<fornecedor_id>', methods=['GET'])
def api_fornecedor_get(fornecedor_id):
    try:
        fornecedor = fornecedor_service.get_by_id(fornecedor_id)
        if not fornecedor:
            return jsonify({'error': 'Fornecedor não encontrado.'}), 404
        return jsonify({'fornecedor': fornecedor})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@cadastros_api_bp.route('/fornecedor/<fornecedor_id>', methods=['PUT'])
def api_fornecedor_edit(fornecedor_id):
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Dados inválidos'}), 400
        
        supplier_data = {
            'nome_razao_social': data.get('nome_razao_social'),
            'cpf_cnpj': data.get('cpf_cnpj'),
            'email': data.get('email'),
            'telefone': data.get('telefone'),
            'ativo': data.get('ativo', False)
        }
        updated_fornecedor = fornecedor_service.update(fornecedor_id, supplier_data)
        return jsonify({'success': True, 'message': 'Fornecedor atualizado com sucesso!', 'fornecedor': updated_fornecedor})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@cadastros_api_bp.route('/fornecedor/<fornecedor_id>', methods=['DELETE'])
def api_fornecedor_delete(fornecedor_id):
    try:
        fornecedor_service.delete(fornecedor_id)
        return jsonify({'success': True, 'message': 'Fornecedor deletado com sucesso!'})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

# Depósito
@cadastros_api_bp.route('/deposito', methods=['GET'])
def api_deposito_list():
    try:
        depositos = deposito_service.get_all()
        return jsonify({'depositos': depositos})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@cadastros_api_bp.route('/deposito', methods=['POST'])
def api_deposito_new():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Dados inválidos'}), 400
        
        deposit_data = {
            'nome': data.get('nome'),
            'tipo': data.get('tipo', 'MATERIA_PRIMA'),
            'ativo': data.get('ativo', False)
        }
        new_deposito = deposito_service.create(deposit_data)
        return jsonify({'success': True, 'message': 'Depósito criado com sucesso!', 'deposito': new_deposito}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@cadastros_api_bp.route('/deposito/<deposito_id>', methods=['GET'])
def api_deposito_get(deposito_id):
    try:
        deposito = deposito_service.get_by_id(deposito_id)
        if not deposito:
            return jsonify({'error': 'Depósito não encontrado.'}), 404
        return jsonify({'deposito': deposito})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@cadastros_api_bp.route('/deposito/<deposito_id>', methods=['PUT'])
def api_deposito_edit(deposito_id):
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Dados inválidos'}), 400
        
        deposit_data = {
            'nome': data.get('nome'),
            'tipo': data.get('tipo', 'MATERIA_PRIMA'),
            'ativo': data.get('ativo', False)
        }
        updated_deposito = deposito_service.update(deposito_id, deposit_data)
        return jsonify({'success': True, 'message': 'Depósito atualizado com sucesso!', 'deposito': updated_deposito})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@cadastros_api_bp.route('/deposito/<deposito_id>', methods=['DELETE'])
def api_deposito_delete(deposito_id):
    try:
        deposito_service.delete(deposito_id)
        return jsonify({'success': True, 'message': 'Depósito deletado com sucesso!'})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

# Canal de Venda
@cadastros_api_bp.route('/canal-venda', methods=['GET'])
def api_canal_venda_list():
    try:
        active_only = request.args.get('active_only', 'true').lower() == 'true'
        canais = canal_venda_service.get_all(active_only=active_only)
        contas_bling = conta_bling_service.get_all()
        return jsonify({'canais': canais, 'contas_bling': contas_bling})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@cadastros_api_bp.route('/canal-venda', methods=['POST'])
def api_canal_venda_new():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Dados inválidos'}), 400

        canal_data = {
            'nome': data.get('nome'),
            'slug': data.get('slug'),
            'plataforma': data.get('plataforma'),
            'conta_bling_id': data.get('conta_bling_id'),
            'horario_coleta': data.get('horario_coleta'),
            'flex': data.get('flex', False),
            'fulfillment': data.get('fulfillment', False),
            'color': data.get('color', '#007bff'),
            'ativo': data.get('ativo', False)
        }

        regras_logisticas = data.get('regras_logisticas')
        if regras_logisticas is None and 'configuracao' in data and 'regras_logisticas' in data['configuracao']:
            regras_logisticas = data['configuracao']['regras_logisticas']

        new_canal = canal_venda_service.create(canal_data)

        if regras_logisticas is not None:
            from nistiprint_shared.services.regra_logistica_service import regra_logistica_service
            regra_logistica_service.delete_all_by_canal(new_canal['id'])
            regras_para_criar = []
            for modalidade, regras in regras_logisticas.items():
                if isinstance(regras, list):
                    for regra in regras:
                        regras_para_criar.append({
                            'canal_venda_id': new_canal['id'],
                            'modalidade': modalidade,
                            'tipo_envio': regra.get('tipo') or regra.get('tipo_envio'),
                            'horario_limite': regra['horario_limite'],
                            'ponto_coleta_id': regra.get('ponto_coleta_id'),
                            'prioridade_uso': regra.get('prioridade_uso', 1)
                        })
            if regras_para_criar:
                regra_logistica_service.bulk_create_regras(regras_para_criar)
            new_canal['regras_logisticas'] = regra_logistica_service.get_by_canal(new_canal['id'])

        return jsonify({'success': True, 'message': 'Canal de venda criado com sucesso!', 'canal': new_canal}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@cadastros_api_bp.route('/canal-venda/<canal_id>', methods=['GET'])
def api_canal_venda_get(canal_id):
    try:
        canal = canal_venda_service.get_by_id(canal_id)
        contas_bling = conta_bling_service.get_all()
        if not canal:
            return jsonify({'error': 'Canal de venda não encontrado.'}), 404
        return jsonify({'canal': canal, 'contas_bling': contas_bling})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@cadastros_api_bp.route('/canal-venda/<canal_id>', methods=['PUT'])
def api_canal_venda_edit(canal_id):
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Dados inválidos'}), 400

        canal_data = {
            'nome': data.get('nome'),
            'slug': data.get('slug'),
            'plataforma': data.get('plataforma'),
            'conta_bling_id': data.get('conta_bling_id'),
            'horario_coleta': data.get('horario_coleta'),
            'flex': data.get('flex', False),
            'fulfillment': data.get('fulfillment', False),
            'color': data.get('color', '#007bff'),
            'ativo': data.get('ativo', False)
        }

        regras_logisticas = data.get('regras_logisticas')
        if regras_logisticas is None and 'configuracao' in data and 'regras_logisticas' in data['configuracao']:
            regras_logisticas = data['configuracao']['regras_logisticas']

        updated_canal = canal_venda_service.update(canal_id, canal_data)

        if regras_logisticas is not None:
            from nistiprint_shared.services.regra_logistica_service import regra_logistica_service
            regra_logistica_service.delete_all_by_canal(canal_id)
            regras_para_criar = []
            for modalidade, regras in regras_logisticas.items():
                if isinstance(regras, list):
                    for regra in regras:
                        regras_para_criar.append({
                            'canal_venda_id': int(canal_id),
                            'modalidade': modalidade,
                            'tipo_envio': regra.get('tipo') or regra.get('tipo_envio'),
                            'horario_limite': regra['horario_limite'],
                            'ponto_coleta_id': regra.get('ponto_coleta_id'),
                            'prioridade_uso': regra.get('prioridade_uso', 1)
                        })
            if regras_para_criar:
                regra_logistica_service.bulk_create_regras(regras_para_criar)
            updated_canal['regras_logisticas'] = regra_logistica_service.get_by_canal(canal_id)

        return jsonify({'success': True, 'message': 'Canal de venda atualizado com sucesso!', 'canal': updated_canal})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@cadastros_api_bp.route('/canal-venda/<canal_id>', methods=['DELETE'])
def api_canal_venda_delete(canal_id):
    try:
        canal_venda_service.delete(canal_id)
        return jsonify({'success': True, 'message': 'Canal de venda deletado com sucesso!'})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

# Categoria
@cadastros_api_bp.route('/categoria', methods=['GET'])
def api_categoria_list():
    try:
        categorias = category_service.get_all()
        return jsonify({'categorias': categorias})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@cadastros_api_bp.route('/categoria', methods=['POST'])
def api_categoria_new():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Dados inválidos'}), 400
        
        category_data = {
            'name': data.get('name'),
            'description': data.get('description'),
            'parent_category_id': data.get('parent_category_id') if data.get('parent_category_id') else None,
            'comercializavel': data.get('comercializavel', False),
            'componente': data.get('componente', False)
        }
        new_categoria = category_service.create(category_data)
        return jsonify({'success': True, 'message': 'Categoria criada com sucesso!', 'categoria': new_categoria}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@cadastros_api_bp.route('/categoria/<categoria_id>', methods=['GET'])
def api_categoria_get(categoria_id):
    try:
        categoria = category_service.get_by_id(categoria_id)
        if not categoria:
            return jsonify({'error': 'Categoria não encontrada.'}), 404
        
        categorias = category_service.get_all()
        return jsonify({'categoria': categoria, 'categorias': categorias})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@cadastros_api_bp.route('/categoria/<categoria_id>', methods=['PUT'])
def api_categoria_edit(categoria_id):
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Dados inválidos'}), 400
        
        category_data = {
            'name': data.get('name'),
            'description': data.get('description'),
            'parent_category_id': data.get('parent_category_id') if data.get('parent_category_id') else None,
            'comercializavel': data.get('comercializavel', False),
            'componente': data.get('componente', False)
        }
        updated_categoria = category_service.update(categoria_id, category_data)
        return jsonify({'success': True, 'message': 'Categoria atualizada com sucesso!', 'categoria': updated_categoria})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@cadastros_api_bp.route('/categoria/<categoria_id>', methods=['DELETE'])
def api_categoria_delete(categoria_id):
    try:
        category_service.delete(categoria_id)
        return jsonify({'success': True, 'message': 'Categoria deletada com sucesso!'})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@cadastros_api_bp.route('/categoria/<categoria_id>/regras', methods=['GET'])
def api_categoria_regras_list(categoria_id):
    try:
        regras = category_bom_rule_service.get_by_category_pai(categoria_id)
        return jsonify({'regras': regras})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@cadastros_api_bp.route('/categoria/<categoria_id>/regras', methods=['POST'])
def api_categoria_regras_new(categoria_id):
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Dados inválidos'}), 400
        
        rule_data = {
            'categoria_pai_id': categoria_id,
            'nome_grupo': data.get('nome_grupo'),
            'categoria_componente_id': data.get('categoria_componente_id'),
            'min_quantidade': data.get('min_quantidade', 1),
            'max_quantidade': data.get('max_quantidade', 1),
            'ordem': data.get('ordem', 0)
        }
        new_regra = category_bom_rule_service.create(rule_data)
        return jsonify({'success': True, 'message': 'Regra criada com sucesso!', 'regra': new_regra}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@cadastros_api_bp.route('/categoria/regras/<regra_id>', methods=['PUT'])
def api_categoria_regras_edit(regra_id):
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Dados inválidos'}), 400
        
        updated_regra = category_bom_rule_service.update(regra_id, data)
        return jsonify({'success': True, 'message': 'Regra atualizada com sucesso!', 'regra': updated_regra})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@cadastros_api_bp.route('/categoria/regras/<regra_id>', methods=['DELETE'])
def api_categoria_regras_delete(regra_id):
    try:
        category_bom_rule_service.delete(regra_id)
        return jsonify({'success': True, 'message': 'Regra deletada com sucesso!'})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

# Tag
@cadastros_api_bp.route('/tag', methods=['GET'])
def api_tag_list():
    try:
        tags = tag_service.get_all()
        return jsonify({'tags': tags})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@cadastros_api_bp.route('/tag', methods=['POST'])
def api_tag_new():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Dados inválidos'}), 400
        
        tag_data = {'name': data.get('name')}
        new_tag = tag_service.create(tag_data)
        return jsonify({'success': True, 'message': 'Tag criada com sucesso!', 'tag': new_tag}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@cadastros_api_bp.route('/tag/<tag_id>', methods=['GET'])
def api_tag_get(tag_id):
    try:
        tag = tag_service.get_by_id(tag_id)
        if not tag:
            return jsonify({'error': 'Tag não encontrada.'}), 404
        return jsonify({'tag': tag})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@cadastros_api_bp.route('/tag/<tag_id>', methods=['PUT'])
def api_tag_edit(tag_id):
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Dados inválidos'}), 400
        
        tag_data = {'name': data.get('name')}
        updated_tag = tag_service.update(tag_id, tag_data)
        return jsonify({'success': True, 'message': 'Tag atualizada com sucesso!', 'tag': updated_tag})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@cadastros_api_bp.route('/tag/<tag_id>', methods=['DELETE'])
def api_tag_delete(tag_id):
    try:
        tag_service.delete(tag_id)
        return jsonify({'success': True, 'message': 'Tag deletada com sucesso!'})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

# Unidade de Medida
@cadastros_api_bp.route('/unidade-medida', methods=['GET'])
def api_unidade_medida_list():
    try:
        unidades = unit_of_measure_service.get_all()
        return jsonify({'unidades': unidades})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@cadastros_api_bp.route('/unidade-medida', methods=['POST'])
def api_unidade_medida_new():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Dados inválidos'}), 400
        
        unit_data = {'name': data.get('name'), 'symbol': data.get('symbol')}
        new_unidade = unit_of_measure_service.create(unit_data)
        return jsonify({'success': True, 'message': 'Unidade de medida criada com sucesso!', 'unidade': new_unidade}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@cadastros_api_bp.route('/unidade-medida/<unidade_id>', methods=['GET'])
def api_unidade_medida_get(unidade_id):
    try:
        unidade = unit_of_measure_service.get_by_id(unidade_id)
        if not unidade:
            return jsonify({'error': 'Unidade de medida não encontrada.'}), 404
        return jsonify({'unidade': unidade})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@cadastros_api_bp.route('/unidade-medida/<unidade_id>', methods=['PUT'])
def api_unidade_medida_edit(unidade_id):
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Dados inválidos'}), 400
        
        unit_data = {'name': data.get('name'), 'symbol': data.get('symbol')}
        updated_unidade = unit_of_measure_service.update(unidade_id, unit_data)
        return jsonify({'success': True, 'message': 'Unidade de medida atualizada com sucesso!', 'unidade': updated_unidade})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@cadastros_api_bp.route('/unidade-medida/<unidade_id>', methods=['DELETE'])
def api_unidade_medida_delete(unidade_id):
    try:
        unit_of_measure_service.delete(unidade_id)
        return jsonify({'success': True, 'message': 'Unidade de medida deletada com sucesso!'})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

# Search Endpoints
@cadastros_api_bp.route('/fornecedor/search', methods=['GET'])
def api_fornecedor_search():
    query = request.args.get('q', '')
    try:
        results = fornecedor_service.search(query)
        return jsonify([{'id': f['id'], 'text': f"{f['nome_razao_social']} ({f['cpf_cnpj'] or 'Sem CPF/CNPJ'})"} for f in results])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@cadastros_api_bp.route('/conta-bling/search', methods=['GET'])
def api_conta_bling_search():
    try:
        results = conta_bling_service.get_all()
        return jsonify([{'id': c['id'], 'text': f"{c['account_name']} ({c['cnpj']})"} for c in results])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@cadastros_api_bp.route('/deposito/search', methods=['GET'])
def api_deposito_search():
    try:
        results = deposito_service.get_all()
        return jsonify([{'id': d['id'], 'text': f"{d['nome']} ({d['tipo']})"} for d in results])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@cadastros_api_bp.route('/canal-venda/search', methods=['GET'])
def api_canal_venda_search():
    try:
        results = canal_venda_service.get_all()
        return jsonify([{'id': c['id'], 'text': f"{c['nome']} ({c['plataforma'] or 'N/A'})"} for c in results])
    except Exception as e:
        return jsonify({'error': str(e)}), 500
