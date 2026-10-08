from flask import Blueprint, request
from routes.auth import require_request_permission

producao_bp = Blueprint('producao', __name__, url_prefix='/producao')
producao_api_bp = Blueprint('producao_api', __name__, url_prefix='/api/v2/producao')


@producao_api_bp.before_request
def enforce_production_permissions():
    if request.method == 'OPTIONS':
        return None
    if request.path.rstrip('/').endswith('/api/auditoria'):
        return require_request_permission('auditoria', 'ler')
    if request.method in {'GET', 'HEAD'}:
        action = 'ler'
    elif request.method == 'POST' and request.path.rstrip('/').endswith((
        '/registrar-item', '/registrar-saida-estoque', '/registrar-sinal',
    )):
        action = 'criar'
    elif request.method in {'POST', 'PUT', 'PATCH'}:
        action = 'editar'
    elif request.method == 'DELETE':
        action = 'excluir'
    else:
        return None
    return require_request_permission('producao', action)
