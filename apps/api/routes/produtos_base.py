from flask import Blueprint

produtos_bp = Blueprint('produtos', __name__, url_prefix='/produtos')
produtos_api_bp = Blueprint('produtos_api', __name__, url_prefix='/api/v2/produtos')
