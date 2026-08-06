import firebase_admin
from functools import wraps
from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for

auth_bp = Blueprint('auth', __name__)
AUTH_EXEMPT_ENDPOINTS = {'auth.login', 'static'}
SESSION_USER_ID_KEY = 'user_id'
SESSION_USER_PROFILE_KEY = 'user_perfil'


def is_auth_exempt_endpoint(endpoint):
    return endpoint in AUTH_EXEMPT_ENDPOINTS or endpoint is None


def is_authenticated():
    return SESSION_USER_ID_KEY in session


def get_authenticated_user_id():
    """Returns the authenticated application user id stored in session."""
    return session.get(SESSION_USER_ID_KEY)


def clear_authenticated_user_session():
    """Clears only the application user session data."""
    session.pop(SESSION_USER_ID_KEY, None)
    session.pop(SESSION_USER_PROFILE_KEY, None)


def get_current_user():
    """Loads the current application user profile from Firestore."""
    from services.firebase.firestore_client import firestore_client

    user_id = get_authenticated_user_id()
    if user_id:
        user_doc = firestore_client.collection('users').document(user_id).get()
        if user_doc.exists:
            user_data = user_doc.to_dict()
            user_data['id'] = user_doc.id
            return user_data
    return None


def perfil_required(perfil_necessario):
    """Decorador para verificar se o usuario tem o perfil necessario."""

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not is_authenticated():
                return _unauthorized_response()

            user = get_current_user()
            if not user:
                clear_authenticated_user_session()
                return _unauthorized_response()

            if user.get('perfil') != perfil_necessario and user.get('perfil') != 'administrador':
                flash('Acesso negado. Voce nao tem permissao para essa operacao.', 'error')
                return redirect(url_for('main.index'))

            return f(*args, **kwargs)

        return decorated_function

    return decorator


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_authenticated():
            return _unauthorized_response()
        return f(*args, **kwargs)

    return decorated_function


def _unauthorized_response():
    next_url = request.full_path if request.query_string else request.path

    if request.path.startswith('/api/') or request.is_json:
        return jsonify({
            'message': 'Autenticacao necessaria.',
            'redirect': url_for('auth.login', next=next_url)
        }), 401

    return redirect(url_for('auth.login', next=next_url))


def _create_default_user(firebase_uid):
    """Creates the application user profile after a real Firebase Auth login."""
    from firebase_admin import firestore
    from services.firebase.firestore_client import firestore_client

    user_ref = firestore_client.collection('users').document(firebase_uid)
    if not user_ref.get().exists:
        user_data = {
            'firebase_uid': firebase_uid,
            'perfil': 'operacional',
            'created_at': firestore.SERVER_TIMESTAMP
        }
        user_ref.set(user_data)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET' and is_authenticated():
        return redirect(request.args.get('next') or url_for('main.index'))

    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        try:
            if not data.get('uid'):
                return jsonify({'message': 'UID do usuario e obrigatorio.'}), 400

            from services.firebase.firestore_client import firestore_client

            user_doc = firestore_client.collection('users').document(data['uid']).get()

            if not user_doc.exists:
                _create_default_user(data['uid'])
                user_data = {'perfil': 'operacional'}
            else:
                user_data = user_doc.to_dict()

            session[SESSION_USER_ID_KEY] = data['uid']
            session[SESSION_USER_PROFILE_KEY] = user_data.get('perfil', 'operacional')
            session.permanent = True

            return jsonify({
                'message': 'Login realizado com sucesso!',
                'redirect': data.get('next') or url_for('main.index')
            }), 200
        except firebase_admin.auth.UserNotFoundError:
            return jsonify({'message': 'Usuario nao encontrado.'}), 404
        except Exception as exc:
            return jsonify({'message': str(exc)}), 500

    return render_template('login.html', next_url=request.args.get('next', ''))


@auth_bp.route('/logout', methods=['GET', 'POST'])
def logout():
    clear_authenticated_user_session()

    if request.path.startswith('/api/') or request.is_json or request.method == 'POST':
        return jsonify({
            'message': 'Logout realizado com sucesso!',
            'redirect': url_for('auth.login')
        }), 200

    return redirect(url_for('auth.login'))
