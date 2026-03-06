import os
from functools import wraps
from flask import request, redirect, url_for, session, flash, render_template, Blueprint, jsonify
from nistiprint_shared.services.usuario_service import usuario_service
from nistiprint_shared.services.permissao_service import permissao_service
from nistiprint_shared.database.supabase_db_service import get_current_database_mode, DatabaseMode

auth_bp = Blueprint('auth', __name__)


def get_current_user():
    """Obtém o usuário atual da sessão."""
    if 'user_id' in session:
        return usuario_service.get_by_id(int(session['user_id']))
    return None


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Autenticação requerida'}), 401
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Autenticação requerida'}), 401
        if not session.get('user_is_admin', False):
            return jsonify({'error': 'Acesso negado. Permissões de administrador necessárias'}), 403
        return f(*args, **kwargs)
    return decorated_function


def check_permission(recurso, acao):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                return jsonify({'error': 'Autenticação requerida'}), 401

            # Admins have all permissions
            if session.get('user_is_admin', False):
                return f(*args, **kwargs)

            user_id = session.get('user_id')
            if not permissao_service.has_permission(user_id, recurso, acao):
                return jsonify({'error': f'Acesso negado. Permissão de {acao} em {recurso} necessária'}), 403

            return f(*args, **kwargs)
        return decorated_function
    return decorator


@auth_bp.route('/api/v2/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = request.get_json()
        email = data.get('email')
        senha = data.get('senha')

        if not email or not senha:
            return jsonify({'error': 'Email e senha são obrigatórios'}), 400

        # Use different authentication based on database mode
        if get_current_database_mode() == DatabaseMode.SUPABASE:
            # Use Supabase Auth for authentication but MySQL for user details
            from nistiprint_shared.services.supabase_auth_service import supabase_auth
            auth_result = supabase_auth.authenticate(email, senha)

            if auth_result:
                # Find user in MySQL database using email
                usuario = usuario_service.get_by_email(email)
                if usuario:
                    # Ensure setor_nome is properly set for all users
                    if not usuario.get('setor_nome'):
                        # Fetch the setor name from the database if not already populated
                        from nistiprint_shared.models.setor import Setor
                        setor_model = Setor.query.get(usuario['setor_id'])
                        if setor_model:
                            usuario['setor_nome'] = setor_model.nome
                        elif usuario.get('is_admin'):
                            usuario['setor_nome'] = 'Administrativo'
                        else:
                            usuario['setor_nome'] = 'Não atribuído'

                    session['user_id'] = usuario['id']
                    session['user_nome'] = usuario['nome']
                    session['user_email'] = usuario['email']
                    session['user_setor'] = usuario['setor_nome']
                    session['user_is_admin'] = usuario['is_admin']

                    # Store permissions in session for quick access
                    permissions = permissao_service.get_setor_permissions(usuario['setor_id'])
                    session['user_permissions'] = permissions

                    session.permanent = True

                    # Add permissions to the returned user object
                    usuario['permissoes'] = permissions

                    return jsonify({
                        'message': "Login realizado com sucesso!",
                        'redirect': '/',
                        'usuario': usuario
                    }), 200
                else:
                    return jsonify({'error': 'Usuário não encontrado no banco de dados'}), 401
            else:
                return jsonify({'error': 'Credenciais inválidas'}), 401
        else:
            # Use traditional authentication for MySQL mode
            usuario = usuario_service.authenticate(email, senha)
            if usuario:
                # Ensure setor_nome is properly set for all users
                if not usuario.get('setor_nome'):
                    # Fetch the setor name from the database if not already populated
                    from nistiprint_shared.models.setor import Setor
                    setor_model = Setor.query.get(usuario['setor_id'])
                    if setor_model:
                        usuario['setor_nome'] = setor_model.nome
                    elif usuario.get('is_admin'):
                        usuario['setor_nome'] = 'Administrativo'
                    else:
                        usuario['setor_nome'] = 'Não atribuído'

                session['user_id'] = usuario['id']
                session['user_nome'] = usuario['nome']
                session['user_email'] = usuario['email']
                session['user_setor'] = usuario['setor_nome']
                session['user_is_admin'] = usuario['is_admin']

                # Store permissions in session for quick access
                permissions = permissao_service.get_setor_permissions(usuario['setor_id'])
                session['user_permissions'] = permissions

                session.permanent = True

                # Add permissions to the returned user object
                usuario['permissoes'] = permissions

                return jsonify({
                    'message': "Login realizado com sucesso!",
                    'redirect': '/',
                    'usuario': usuario
                }), 200
            else:
                return jsonify({'error': 'Credenciais inválidas'}), 401

    return render_template('login.html')


@auth_bp.route('/api/v2/logout', methods=['GET', 'POST'])
@login_required
def logout():
    # Clear all session data
    session.clear()
    response = jsonify({
        'message': "Logout realizado com sucesso!",
        'redirect': '/login'
    })
    # Clear client-side data to prevent stuck sessions
    response.headers['Clear-Site-Data'] = '"cookies", "storage"'
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response, 200


@auth_bp.route('/api/v2/current-user')
@login_required
def current_user():
    """Retorna informações do usuário atual."""
    usuario = get_current_user()
    if usuario:
        # Include permissions if not already there
        if 'permissoes' not in usuario:
            permissions = permissao_service.get_setor_permissions(usuario['setor_id'])
            usuario['permissoes'] = permissions

        # Ensure setor_nome is properly set - it should already be set by get_current_user()
        # which calls usuario_service.get_by_id(), but we double check for safety
        if not usuario.get('setor_nome'):
            from nistiprint_shared.models.setor import Setor
            setor_model = Setor.query.get(usuario['setor_id'])
            if setor_model:
                usuario['setor_nome'] = setor_model.nome
            elif usuario.get('is_admin'):
                usuario['setor_nome'] = 'Administrativo'
            else:
                usuario['setor_nome'] = 'Não atribuído'

        return jsonify({'usuario': usuario}), 200
    return jsonify({'error': 'Usuário não encontrado'}), 404


@auth_bp.route('/api/v2/clear-all-sessions', methods=['POST'])
@admin_required
def clear_all_sessions():
    """Limpa todas as sessões ativas (apenas para administradores)."""
    from flask import _app_ctx_stack

    # Get the app context
    app = _app_ctx_stack.top.app

    # Clear session store if using filesystem or similar
    # For Flask default session, we can't directly clear all sessions
    # But we can provide a way to force logout all users

    # For now, just return success - in production you'd implement proper session clearing
    return jsonify({
        'message': 'Para limpar todas as sessões, reinicie o servidor Flask.',
        'instructions': 'Execute: python app.py (após parar o servidor atual)'
    }), 200





