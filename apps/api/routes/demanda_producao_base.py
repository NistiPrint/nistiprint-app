from flask import Blueprint
from routes.auth import login_required, check_permission

demanda_producao_bp = Blueprint('demanda_producao', __name__, url_prefix='/producao/demanda')
demanda_producao_api_bp = Blueprint('demanda_producao_api', __name__, url_prefix='/api/v2/demanda_producao')
