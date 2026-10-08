import os
from functools import wraps
from flask import request, redirect, url_for, session, flash, render_template, Blueprint, jsonify
from nistiprint_shared.services.usuario_service import usuario_service
from nistiprint_shared.services.permissao_service import permissao_service
from nistiprint_shared.database.supabase_db_service import get_current_database_mode, DatabaseMode
from nistiprint_shared.models.setor import Setor
from nistiprint_shared.services.auditoria_service import auditoria_service

auth_bp = Blueprint('auth', __name__)


@auth_bp.before_app_request
def require_password_change_before_api_access():
    """Limit first-login accounts to profile, password change, and logout APIs."""
    if not session.get('must_change_password'):
        return None
    allowed_paths = {
        '/api/v2/current-user',
        '/api/v2/change-password',
        '/api/v2/logout',
        '/api/v2/login',
    }
    if request.path in allowed_paths:
        return None
    if request.endpoint == 'static' or request.path.startswith('/static/'):
        return None
    # Older APIs use several versions and a few unversioned paths. A forced
    # password change must not be bypassable through one of those routes.
    # Browser navigations can still load the SPA so it can render the profile.
    if (request.path.startswith('/api/') or request.method not in {'GET', 'HEAD'}
            or not request.accept_mimetypes.accept_html):
        return jsonify({
            'success': False,
            'code': 'password_change_required',
            'error': 'Altere sua senha para continuar.',
        }), 403
    return None


def get_current_user():
    """Obtém o usuário atual da sessão."""
    if 'user_id' in session:
        return usuario_service.get_by_id(int(session['user_id']))
    return None


def _active_session_user():
    user_id = session.get('user_id')
    if not user_id:
        return None
    usuario = usuario_service.get_by_id(int(user_id))
    if not usuario or not usuario.get('ativo'):
        session.clear()
        return None
    try:
        setor = Setor.query.filter_by(id=usuario.get('setor_id'), ativo=True).first()
    except Exception:
        # Fail closed when the sector state cannot be verified.
        session.clear()
        return None
    if not setor:
        session.clear()
        return None
    current_version = int(usuario.get('session_version') or 0)
    session_version = int(session.get('user_session_version', current_version) or 0)
    if session_version != current_version:
        session.clear()
        return None
    # Keep administrative decisions fresh when a session survives a role change.
    session['user_is_admin'] = bool(usuario.get('is_admin'))
    session['user_setor'] = usuario.get('setor_nome')
    return usuario


def user_has_permission(user, resource, action='ler'):
    if not user:
        return False
    if user.get('is_admin') is True:
        return True
    return permissao_service.has_permission(int(user['id']), resource, action)


def user_has_demand_permission(user, action):
    if not user:
        return False
    if user.get('is_admin') is True:
        return True
    permissions = permissao_service.get_demand_permissions(user.get('setor_id'))
    return action in (permissions.get('actions') or [])


def require_request_permission(resource, action):
    """Authorize a blueprint request using the active user's current policy."""
    user = _active_session_user()
    if not user:
        return jsonify({'success': False, 'error': 'Autenticação requerida.'}), 401
    if not user_has_permission(user, resource, action):
        return jsonify({
            'success': False,
            'error': f'Acesso negado. Permissão de {action} em {resource} necessária.',
        }), 403
    return None


def _has_active_sector(user):
    try:
        return bool(Setor.query.filter_by(id=user.get('setor_id'), ativo=True).first())
    except Exception:
        return False


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not _active_session_user():
            return jsonify({'error': 'Autenticação requerida'}), 401
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = _active_session_user()
        if not user:
            return jsonify({'error': 'Autenticação requerida'}), 401
        if not user.get('is_admin', False):
            return jsonify({'error': 'Acesso negado. Permissões de administrador necessárias'}), 403
        return f(*args, **kwargs)
    return decorated_function


def check_permission(recurso, acao):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = _active_session_user()
            if not user:
                return jsonify({'error': 'Autenticação requerida'}), 401

            if not user_has_permission(user, recurso, acao):
                return jsonify({'error': f'Acesso negado. Permissão de {acao} em {recurso} necessária'}), 403

            return f(*args, **kwargs)
        return decorated_function
    return decorator


def check_demand_action(action):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = _active_session_user()
            if not user:
                return jsonify({'error': 'Autenticação requerida'}), 401
            if not user_has_demand_permission(user, action):
                return jsonify({'error': 'Acesso negado. O setor não possui autorização para esta ação.'}), 403
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
                    if not usuario.get('ativo'):
                        return jsonify({'error': 'Conta inativa. Procure um administrador.'}), 403
                    if not _has_active_sector(usuario):
                        return jsonify({'error': 'O setor desta conta está inativo.'}), 403
                    if usuario.get('auth_user_id') and str(usuario['auth_user_id']) != str(auth_result.get('id')):
                        return jsonify({'error': 'A identidade autenticada não corresponde à conta operacional.'}), 401
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
                    session['user_session_version'] = int(usuario.get('session_version') or 0)
                    session['must_change_password'] = bool(usuario.get('must_change_password'))
                    if auth_result.get('id') and usuario.get('auth_user_id') != auth_result['id']:
                        usuario_service.update(usuario['id'], {'auth_user_id': auth_result['id']})

                    # Store permissions in session for quick access
                    permissions = permissao_service.get_setor_permissions(usuario['setor_id'])
                    session['user_permissions'] = permissions

                    session.permanent = True

                    # Add permissions to the returned user object
                    usuario['permissoes'] = permissions
                    usuario['permissoes_demanda'] = permissao_service.get_demand_permissions(usuario['setor_id'])
                    usuario['can_view_operations'] = user_has_permission(usuario, 'central_operacoes', 'ler')
                    usuario['can_view_audit'] = user_has_permission(usuario, 'auditoria', 'ler')

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

                if not usuario.get('ativo'):
                    return jsonify({'error': 'Conta inativa. Procure um administrador.'}), 403
                if not _has_active_sector(usuario):
                    return jsonify({'error': 'O setor desta conta está inativo.'}), 403

                session['user_id'] = usuario['id']
                session['user_nome'] = usuario['nome']
                session['user_email'] = usuario['email']
                session['user_setor'] = usuario['setor_nome']
                session['user_is_admin'] = usuario['is_admin']
                session['user_session_version'] = int(usuario.get('session_version') or 0)
                session['must_change_password'] = bool(usuario.get('must_change_password'))

                # Store permissions in session for quick access
                permissions = permissao_service.get_setor_permissions(usuario['setor_id'])
                session['user_permissions'] = permissions

                session.permanent = True

                # Add permissions to the returned user object
                usuario['permissoes'] = permissions
                usuario['permissoes_demanda'] = permissao_service.get_demand_permissions(usuario['setor_id'])
                usuario['can_view_operations'] = user_has_permission(usuario, 'central_operacoes', 'ler')
                usuario['can_view_audit'] = user_has_permission(usuario, 'auditoria', 'ler')

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


@auth_bp.route('/api/v2/current-user', methods=['GET', 'PATCH'])
@login_required
def current_user():
    """Retorna informações do usuário atual."""
    usuario = get_current_user()
    if usuario:
        if request.method == 'PATCH':
            data = request.get_json(silent=True) or {}
            nome = str(data.get('nome') or '').strip()
            if not nome or len(nome) > 100:
                return jsonify({'success': False, 'error': 'Informe um nome com até 100 caracteres.'}), 400
            old_name = usuario.get('nome')
            usuario = usuario_service.update(int(usuario['id']), {'nome': nome})
            try:
                auditoria_service.log_event('USUARIO_PERFIL_ATUALIZADO', {
                    'entidade_tipo': 'usuario', 'entidade_id': usuario['id'],
                    'descricao': 'O usuário atualizou o próprio perfil.',
                    'dados_anteriores': {'nome': old_name},
                    'dados_novos': {'nome': usuario.get('nome')},
                }, user_id=usuario['id'])
            except Exception:
                import logging
                logging.getLogger(__name__).exception('Não foi possível registrar alteração de perfil.')
            return jsonify({'success': True, 'usuario': usuario}), 200

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

        usuario['permissoes'] = permissao_service.get_setor_permissions(usuario['setor_id'])
        usuario['permissoes_demanda'] = permissao_service.get_demand_permissions(usuario['setor_id'])
        usuario['can_view_operations'] = user_has_permission(usuario, 'central_operacoes', 'ler')
        usuario['can_view_audit'] = user_has_permission(usuario, 'auditoria', 'ler')
        return jsonify({'usuario': usuario}), 200
    return jsonify({'error': 'Usuário não encontrado'}), 404


@auth_bp.route('/api/v2/change-password', methods=['POST'])
@login_required
def change_password():
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    current = data.get('senha_atual')
    new_password = data.get('nova_senha')
    if not current or not isinstance(new_password, str) or len(new_password) < 8:
        return jsonify({'success': False, 'error': 'Informe a senha atual e uma nova senha com ao menos 8 caracteres.'}), 400
    try:
        if get_current_database_mode() == DatabaseMode.SUPABASE:
            from nistiprint_shared.services.supabase_auth_service import supabase_auth
            supabase_auth.change_password(user['email'], current, new_password)
        else:
            usuario_service.change_password(int(user['id']), current, new_password)
        next_version = int(user.get('session_version') or 0) + 1
        usuario = usuario_service.update(int(user['id']), {
            'must_change_password': False,
            'session_version': next_version,
        })
        session['user_session_version'] = next_version
        session['must_change_password'] = False
        try:
            auditoria_service.log_event('USUARIO_SENHA_ATUALIZADA', {
                'entidade_tipo': 'usuario', 'entidade_id': user['id'],
                'descricao': 'Senha atualizada pelo próprio usuário.',
            }, user_id=user['id'])
        except Exception:
            import logging
            logging.getLogger(__name__).exception('Não foi possível registrar alteração de senha.')
        return jsonify({'success': True, 'usuario': usuario})
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
    except Exception:
        return jsonify({'success': False, 'error': 'Não foi possível atualizar a senha.'}), 500


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





