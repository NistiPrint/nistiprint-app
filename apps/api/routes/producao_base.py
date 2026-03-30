from flask import Blueprint

producao_bp = Blueprint('producao', __name__, url_prefix='/producao')
producao_api_bp = Blueprint('producao_api', __name__, url_prefix='/api/v2/producao')
