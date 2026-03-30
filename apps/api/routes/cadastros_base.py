from flask import Blueprint

cadastros_bp = Blueprint('cadastros', __name__)
cadastros_api_bp = Blueprint('cadastros_api', __name__, url_prefix='/api/v2/cadastros')
