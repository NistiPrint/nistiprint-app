from flask import Blueprint, request
from routes.auth import require_request_permission

produtos_bp = Blueprint('produtos', __name__, url_prefix='/produtos')
produtos_api_bp = Blueprint('produtos_api', __name__, url_prefix='/api/v2/produtos')


@produtos_api_bp.before_request
def enforce_product_permissions():
    if request.method == 'OPTIONS':
        return None
    path = request.path.rstrip('/')
    prefix = '/api/v2/produtos'
    suffix = path[len(prefix):].strip('/') if path.startswith(prefix) else ''
    if request.method in {'GET', 'HEAD'}:
        action = 'ler'
    elif request.method == 'POST':
        action = 'criar' if not suffix or suffix.endswith('/clone') else 'editar'
    elif request.method == 'PUT':
        action = 'editar'
    elif request.method == 'DELETE':
        action = 'excluir' if suffix and '/' not in suffix else 'editar'
    else:
        return None
    return require_request_permission('produtos', action)
