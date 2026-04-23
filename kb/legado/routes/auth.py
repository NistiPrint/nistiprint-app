import os
from functools import wraps
import firebase_admin
from firebase_admin import auth
from flask import request, redirect, url_for, session, flash, render_template, Blueprint

auth_bp = Blueprint('auth', __name__)


def get_current_user():
    """Obtém o usuário atual da sessão."""
    from services.firebase.firestore_client import firestore_client
    if 'user_id' in session:
        user_doc = firestore_client.collection('users').document(session['user_id']).get()
        if user_doc.exists:
            return user_doc.to_dict()
    return None


def perfil_required(perfil_necessario):
    """Decorador para verificar se o usuário tem o perfil necessário."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            env = os.environ.get("FLASK_ENV", "development")
            if env != 'development':
                user = get_current_user()
                if not user:
                    return redirect(url_for('auth.login'))

                if user.get('perfil') != perfil_necessario and user.get('perfil') != 'administrador':
                    flash("Acesso negado. Você não tem permissão para essa operação.", "error")
                    return redirect(url_for('main.index'))

            return f(*args, **kwargs)
        return decorated_function
    return decorator


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        env = os.environ.get("FLASK_ENV", "development")
        if env == 'development':
            # Para ambiente DEV, simula usuário automaticamente
            session['user_id'] = 'cxmgPwLblZTii9jX4GWDb0VgV2r1'  # admin
            # session['user_id'] = 'xenUydQLt3fuu6Gs6wKvD5j0Zu52' # operacional

            # Define perfil com base no usuário do banco de dados
            user = get_current_user()
            if user:
                session['user_perfil'] = user.get('perfil', 'operacional')
            else:
                # Cria usuário padrão se não existir
                _create_default_user(session['user_id'])
                session['user_perfil'] = 'administrador'  # fallback
            return f(*args, **kwargs)

        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


def _create_default_user(firebase_uid):
    """Cria usuário padrão no Firestore se não existir."""
    from services.firebase.firestore_client import firestore_client
    from firebase_admin import firestore

    user_ref = firestore_client.collection('users').document(firebase_uid)
    if not user_ref.get().exists:
        user_data = {
            'firebase_uid': firebase_uid,
            'perfil': 'operacional',  # perfil padrão
            'created_at': firestore.SERVER_TIMESTAMP
        }
        user_ref.set(user_data)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = request.get_json()
        try:
            # Busca/verifica perfil do usuário no Firestore
            from services.firebase.firestore_client import firestore_client
            user_doc = firestore_client.collection('users').document(data['uid']).get()

            if not user_doc.exists:
                # Se não encontrou, cria registro com perfil padrão (usuário novo)
                _create_default_user(data['uid'])
                user_data = {'perfil': 'operacional'}
            else:
                user_data = user_doc.to_dict()

            session['user_id'] = data['uid']
            session['user_perfil'] = user_data.get('perfil', 'operacional')
            session.permanent = True
            return {
                'message': "Login realizado com sucesso!",
                'redirect': '/'
            }, 200
        except firebase_admin.auth.UserNotFoundError:
            flash("Usuário não encontrado.", "error")
            return redirect(url_for('auth.login'))
        except Exception as e:
            flash(str(e), "error")
            return redirect(url_for('auth.login'))
    return render_template('login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    session.pop('user_id', None)
    session.pop('user_perfil', None)
    return {
        'message': "Logout realizado com sucesso!",
        'redirect': '/'
    }, 200
