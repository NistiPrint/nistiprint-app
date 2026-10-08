from flask import Blueprint, request
from routes.auth import login_required
from routes.auth import require_request_permission

estoque_bp = Blueprint('estoque', __name__, url_prefix='/estoque')
estoque_api_bp = Blueprint('estoque_api', __name__, url_prefix='/api/v2/estoque')


@estoque_api_bp.before_request
def enforce_stock_permissions():
    if request.method == 'OPTIONS':
        return None
    path = request.path.rstrip('/')
    if request.method in {'GET', 'HEAD'} or path.endswith('/saldos-batch'):
        action = 'ler'
    elif request.method == 'POST' and path.endswith(('/movimentar', '/movimentar-lote')):
        action = 'criar'
    elif request.method in {'POST', 'PUT', 'PATCH'}:
        action = 'editar'
    elif request.method == 'DELETE':
        action = 'excluir'
    else:
        return None
    return require_request_permission('estoque', action)
