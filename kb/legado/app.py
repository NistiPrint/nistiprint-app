import os
from datetime import datetime
from flask import Flask
from dotenv import load_dotenv
from services.firebase.firebase import initialize_firebase
from services.database.database import db, cleanup_session

# Load environment variables from .env file
load_dotenv()

from constants import BLING_ID_LOJA, PLATFORM_ICONS

# Import Blueprints
from routes.main import main_bp
from routes.integrations import integrations_bp
from routes.integracoes import integracoes_bp
from routes.consolidar import consolidar_bp
from routes.auth import auth_bp
from routes.nfe import nfe_bp
from routes.vendas import vendas_bp
from routes.cadastros import cadastros_bp

from routes.ordem_compra import ordem_compra_bp
from routes.estoque import estoque_bp
from routes.produtos import produtos_bp
from routes.ferramentas import ferramentas_bp
from routes.ordem_producao import ordem_producao_bp
from routes.configuracoes import configuracoes_bp
from routes.producao import producao_bp
from routes.api import api_bp
from routes.composition_templates import composition_templates_bp
from routes.relatorios import relatorios_bp
from routes.uom_conversions import uom_conversions_bp
from routes.demanda_producao import demanda_producao_bp

# Import Models to ensure they are registered
from models.ai_execution_log import AiExecutionLog

# Import utilities for template filters
from utils import br_currency, br_number

def create_app():
    app = Flask(__name__)
    app.secret_key = os.urandom(24)

    # Database configuration
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_recycle': 280,
        'pool_pre_ping': True
    }

    # Initialize Firebase
    initialize_firebase()

    # Initialize extensions
    db.init_app(app)

    # Register Blueprints
    app.register_blueprint(api_bp)
    app.register_blueprint(ferramentas_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(integrations_bp)
    app.register_blueprint(integracoes_bp)
    app.register_blueprint(consolidar_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(nfe_bp)
    app.register_blueprint(vendas_bp)
    app.register_blueprint(cadastros_bp)
    
    app.register_blueprint(ordem_compra_bp)
    app.register_blueprint(estoque_bp)
    app.register_blueprint(produtos_bp)
    app.register_blueprint(ordem_producao_bp)
    app.register_blueprint(configuracoes_bp)
    app.register_blueprint(producao_bp)
    app.register_blueprint(composition_templates_bp)
    app.register_blueprint(relatorios_bp)
    app.register_blueprint(uom_conversions_bp)
    app.register_blueprint(demanda_producao_bp)

    # Register Jinja2 filters
    app.jinja_env.filters['br_currency'] = br_currency
    app.jinja_env.filters['br_number'] = br_number

    # Context Processors
    @app.context_processor
    def inject_now():
        return {'now': datetime.now()}

    @app.context_processor
    def inject_bling_id_loja():
        return {'BLING_ID_LOJA': BLING_ID_LOJA}

    @app.context_processor
    def inject_icon_mapping():
        return {'iconMapping': PLATFORM_ICONS}

    @app.context_processor
    def inject_flask_env():
        return {'FLASK_ENV': os.environ.get('FLASK_ENV')}

    # Teardown app context
    app.teardown_appcontext(cleanup_session)

    return app

if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port, debug=True)
