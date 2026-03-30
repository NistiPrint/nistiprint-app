from flask import Blueprint
from routes.auth import login_required

estoque_bp = Blueprint('estoque', __name__, url_prefix='/estoque')
estoque_api_bp = Blueprint('estoque_api', __name__, url_prefix='/api/v2/estoque')
