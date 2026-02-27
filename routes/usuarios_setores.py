from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash
from services.setor_service import setor_service
from services.usuario_service import usuario_service
from services.permissao_service import permissao_service
from models.permissao import Recurso
from routes.auth import admin_required

usuarios_setores_bp = Blueprint('usuarios_setores', __name__)
usuarios_setores_api_bp = Blueprint('usuarios_setores_api', __name__, url_prefix='/api/v2/usuarios-setores')

# Legacy routes to prevent BuildError in templates
@usuarios_setores_bp.route('/usuarios')
@admin_required
def usuario_list():
    return render_template('usuarios/list.html')

@usuarios_setores_bp.route('/setores')
@admin_required
def setor_list():
    return render_template('setores/list.html')

# API Setor routes
@usuarios_setores_api_bp.route('/setor', methods=['GET'])
def api_setor_list():
    try:
        setores = setor_service.get_all_including_inactive()
        return jsonify({'setores': setores})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@usuarios_setores_api_bp.route('/setor', methods=['POST'])
@admin_required
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

@usuarios_setores_api_bp.route('/setor/<setor_id>', methods=['GET'])
@admin_required
def api_setor_get(setor_id):
    try:
        setor = setor_service.get_by_id(int(setor_id))
        if not setor:
            return jsonify({'error': 'Setor não encontrado.'}), 404
        return jsonify({'setor': setor})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@usuarios_setores_api_bp.route('/setor/<setor_id>', methods=['PUT'])
@admin_required
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

@usuarios_setores_api_bp.route('/setor/<setor_id>', methods=['DELETE'])
@admin_required
def api_setor_delete(setor_id):
    try:
        setor_service.delete(int(setor_id))
        return jsonify({'success': True, 'message': 'Setor deletado com sucesso!'})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

# Permission Routes
@usuarios_setores_api_bp.route('/recursos', methods=['GET'])
@admin_required
def api_recursos_list():
    try:
        recursos = Recurso.query.all()
        return jsonify({'recursos': [r.to_dict() for r in recursos]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@usuarios_setores_api_bp.route('/setor/<setor_id>/permissoes', methods=['GET'])
@admin_required
def api_setor_permissoes_get(setor_id):
    try:
        permissoes = permissao_service.get_setor_permissions(int(setor_id))
        return jsonify({'permissoes': permissoes})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@usuarios_setores_api_bp.route('/setor/<setor_id>/permissoes', methods=['POST'])
@admin_required
def api_setor_permissoes_update(setor_id):
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Dados inválidos'}), 400
            
        recurso_nome = data.get('recurso')
        pode_ler = data.get('ler')
        pode_criar = data.get('criar')
        pode_editar = data.get('editar')
        pode_excluir = data.get('excluir')
        
        permissao = permissao_service.update_setor_permission(
            setor_id=int(setor_id),
            recurso_nome=recurso_nome,
            pode_ler=pode_ler,
            pode_criar=pode_criar,
            pode_editar=pode_editar,
            pode_excluir=pode_excluir
        )
        
        return jsonify({'success': True, 'permissao': permissao})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

# API Usuario routes
@usuarios_setores_api_bp.route('/usuario', methods=['GET'])
@admin_required
def api_usuario_list():
    try:
        usuarios = usuario_service.get_all()
        return jsonify({'usuarios': usuarios})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@usuarios_setores_api_bp.route('/usuario', methods=['POST'])
@admin_required
def api_usuario_new():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Dados inválidos'}), 400

        usuario_data = {
            'nome': data.get('nome'),
            'email': data.get('email'),
            'senha': data.get('senha'),
            'setor_id': int(data.get('setor_id')),
            'ativo': data.get('ativo', True),
            'is_admin': data.get('is_admin', False)
        }
        new_usuario = usuario_service.create(usuario_data)
        return jsonify({'success': True, 'message': 'Usuário criado com sucesso!', 'usuario': new_usuario}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@usuarios_setores_api_bp.route('/usuario/<usuario_id>', methods=['GET'])
@admin_required
def api_usuario_get(usuario_id):
    try:
        usuario = usuario_service.get_by_id(int(usuario_id))
        setores = setor_service.get_all()
        if not usuario:
            return jsonify({'error': 'Usuário não encontrado.'}), 404
        return jsonify({'usuario': usuario, 'setores': setores})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@usuarios_setores_api_bp.route('/usuario/<usuario_id>', methods=['PUT'])
@admin_required
def api_usuario_edit(usuario_id):
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Dados inválidos'}), 400

        usuario_data = {
            'nome': data.get('nome'),
            'email': data.get('email'),
            'setor_id': int(data.get('setor_id')) if data.get('setor_id') else None,
            'ativo': data.get('ativo', True),
            'is_admin': data.get('is_admin', False)
        }

        # Only include password if provided
        if data.get('senha'):
            usuario_data['senha'] = data.get('senha')

        updated_usuario = usuario_service.update(int(usuario_id), usuario_data)
        return jsonify({'success': True, 'message': 'Usuário atualizado com sucesso!', 'usuario': updated_usuario})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@usuarios_setores_api_bp.route('/usuario/<usuario_id>', methods=['DELETE'])
@admin_required
def api_usuario_delete(usuario_id):
    try:
        usuario_service.delete(int(usuario_id))
        return jsonify({'success': True, 'message': 'Usuário deletado com sucesso!'})
    except Exception as e:
        return jsonify({'error': str(e)}), 400
