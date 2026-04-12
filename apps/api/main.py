import sys
import os
import logging
from datetime import datetime
from flask import Flask, send_from_directory
from flask_cors import CORS

# 1. Carregamento centralizado do ambiente e inicialização do pacote compartilhado
try:
    from nistiprint_shared.utils.env_loader import load_nistiprint_env
    from nistiprint_shared.database.initializer import setup_mock_query_interface
    
    # Carrega variáveis de ambiente (.env)
    load_nistiprint_env()
    
    # Configura a interface de compatibilidade (Mock SQLAlchemy/Supabase)
    setup_mock_query_interface()
    
    print("✓ V3 Infrastructure Initialized (Shared Package)")
except ImportError as e:
    print(f"❌ Erro: Pacote nistiprint-shared não localizado ou incompleto: {e}")
    # Fallback para load_dotenv local caso o shared falhe (útil durante migração)
    from dotenv import load_dotenv
    load_dotenv()
except Exception as e:
    print(f"❌ Erro inesperado na inicialização: {e}")

from nistiprint_shared.database.database import db, cleanup_session
from nistiprint_shared.database.supabase_db_service import init_app_with_supabase_db

from nistiprint_shared.constants import BLING_ID_LOJA, PLATFORM_ICONS

# Import Blueprints
from routes.main import main_bp
from routes.integrations import integrations_bp
from routes.integracoes import integracoes_bp, integracoes_api_bp
from routes.consolidar import consolidar_bp
from routes.auth import auth_bp
from routes.nfe import nfe_bp
from routes.vendas import vendas_bp, vendas_api_bp
from routes.cadastros_web import cadastros_bp
from routes.cadastros_api import cadastros_api_bp
from routes.consolidar_base import consolidar_base_bp

from routes.ordem_compra import ordem_compra_bp
from routes.estoque_web import estoque_bp
from routes.estoque_api import estoque_api_bp
from routes.auditoria_estoque import auditoria_estoque_bp
from routes.produtos_web import produtos_bp
from routes.produtos_api import produtos_api_bp
from routes.ferramentas import ferramentas_bp, ferramentas_api_bp
from routes.ordem_producao import ordem_producao_bp
from routes.configuracoes import configuracoes_bp
from routes.configuracoes import configuracoes_api_bp
from routes.producao_web import producao_bp
from routes.producao_api import producao_api_bp
from routes.api import api_bp
from routes.relatorios import relatorios_api_bp
from routes.uom_conversions import uom_conversions_bp, uom_conversions_api_bp
from routes.demanda_producao_web import demanda_producao_bp
from routes.demanda_producao_api import demanda_producao_api_bp
from routes.tasks_api import tasks_api_bp
from routes.task_schedules_api import task_schedules_api_bp
from routes.usuarios_setores import usuarios_setores_bp, usuarios_setores_api_bp
from routes.notifications import notifications_bp
from routes.orders import orders_api_bp
from routes.marketplace_api_base import marketplace_api_bp
from routes.marketplace_api_routes import marketplace_api_bp as marketplace_api_routes_bp
from routes.marketplace import marketplace_bp
from routes.printing import printing_bp, printing_api_bp
from routes.jobs import jobs_bp
from routes.unified_orders import unified_orders_bp
from routes.integracao_canais import integracao_canais_bp
from routes.pedidos import pedidos_bp
from routes.pedidos_gestao import pedidos_gestao_bp
from routes.demanda_consolidada import demanda_consolidada_bp
from routes.demandas import demandas_bp
from routes.alertas import alertas_bp
from routes.webhooks import webhooks_bp
from routes.producao_contexto import producao_contexto_bp
from routes.erp_links import erp_links_bp
from routes.personalizados import personalizados_api_bp
from routes.impressao import impressao_api_bp

# Import Models to ensure they are registered
from nistiprint_shared.models import *

# Import Services to ensure they are initialized
from nistiprint_shared.services.priority_calculation_service import priority_calculation_service
from nistiprint_shared.services.capacity_planning_service import capacity_planning_service
from nistiprint_shared.services.calendar_service import calendar_service
from nistiprint_shared.services.production_planning_service import production_planning_service
from nistiprint_shared.services.artwork_service import artwork_service
from nistiprint_shared.services.print_service import print_service

# Import utilities for template filters
from utils import br_currency, br_number

def create_app():
    app = Flask(__name__)
    
    # Prioridade para variável de ambiente, fallback para string fixa
    secret = os.environ.get('SECRET_KEY')
    if not secret:
        app.logger.warning("⚠️ SECRET_KEY não encontrada no ambiente! Usando chave de fallback.")
        secret = 'dev_secret_key_fixed_for_stability'
    
    app.secret_key = secret
    app.config['SECRET_KEY'] = secret

    # Session configuration
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_SECURE'] = False  # Set to True in production with HTTPS
    app.config['SESSION_COOKIE_HTTPONLY'] = True

    # Database configuration
    supabase_url = os.environ.get('SUPABASE_URL')
    supabase_key = os.environ.get('SUPABASE_SERVICE_KEY')
    
    if supabase_url and supabase_key:
        # Use Supabase (PostgreSQL)
        app.config['SQLALCHEMY_DATABASE_URI'] = supabase_url.replace("http://", "postgresql://").replace("https://", "postgresql://")
        app.logger.info("Using Supabase (PostgreSQL) as main database.")
        
        # Configure Binds for Legacy MySQL
        legacy_db_url = os.environ.get('DATABASE_URL')
        if legacy_db_url:
             app.config['SQLALCHEMY_BINDS'] = {
                'legacy_mysql': legacy_db_url
            }
             app.logger.info("Legacy MySQL bind configured.")
    else:
        # Fallback to legacy MySQL
        app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
        app.logger.info("Using MySQL as main database.")

    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_recycle': 280,
        'pool_pre_ping': True
    }

    # Upload folder configuration
    app.config['UPLOAD_FOLDER'] = 'uploads/artworks'

    # Initialize the SQLAlchemy instance with the app
    db.init_app(app)

    # Initialize Extensions with Supabase database support (connection test etc)
    if supabase_url and supabase_key:
        init_app_with_supabase_db(app)

    # Since we're migrating to Supabase, we no longer need Firebase

    # Initialize CORS with credentials support for development
    # Obtenha as origens de uma variável de ambiente, com um fallback para desenvolvimento
    cors_origins = os.environ.get('CORS_ALLOWED_ORIGINS', 'http://localhost:5173,http://localhost:5174,http://localhost:3000').split(',')
    CORS(app, supports_credentials=True, origins=cors_origins)
    app.logger.info(f"CORS enabled for origins: {cors_origins}")

    # Configure logging
    if not app.debug:
        logging.basicConfig(level=logging.INFO)
        app.logger.setLevel(logging.INFO)

    # Register Blueprints
    # Auth Blueprint already has /api/v2 hardcoded in its routes
    app.register_blueprint(auth_bp) 
    
    # Standardizing API prefix for v3
    app.register_blueprint(api_bp, url_prefix='/api/v2')
    
    app.register_blueprint(ferramentas_bp)
    app.register_blueprint(ferramentas_api_bp, url_prefix='/api/v2/ferramentas')
    app.register_blueprint(main_bp)
    app.register_blueprint(integrations_bp)
    app.register_blueprint(integracoes_bp)
    app.register_blueprint(integracoes_api_bp, url_prefix='/api/v2/integracoes')
    app.register_blueprint(consolidar_bp)
    app.register_blueprint(nfe_bp)
    app.register_blueprint(vendas_bp)
    app.register_blueprint(vendas_api_bp, url_prefix='/api/v2/vendas')
    app.register_blueprint(cadastros_bp)
    app.register_blueprint(cadastros_api_bp, url_prefix='/api/v2/cadastros')
    app.register_blueprint(consolidar_base_bp, url_prefix='/api/v2/consolidar-base')

    app.register_blueprint(ordem_compra_bp)
    app.register_blueprint(estoque_bp)
    app.register_blueprint(estoque_api_bp, url_prefix='/api/v2/estoque')
    app.register_blueprint(auditoria_estoque_bp)
    app.register_blueprint(produtos_bp)
    app.register_blueprint(produtos_api_bp, url_prefix='/api/v2/produtos')
    app.register_blueprint(ordem_producao_bp)
    app.register_blueprint(configuracoes_bp)
    app.register_blueprint(configuracoes_api_bp, url_prefix='/api/v2/configuracoes')
    app.register_blueprint(producao_bp)
    app.register_blueprint(producao_api_bp, url_prefix='/api/v2/producao')
    app.register_blueprint(relatorios_api_bp, url_prefix='/api/v2/relatorios')
    app.register_blueprint(uom_conversions_bp)
    app.register_blueprint(uom_conversions_api_bp, url_prefix='/api/v2/cadastros/uom-conversions')
    app.register_blueprint(demanda_producao_bp)
    app.register_blueprint(demanda_producao_api_bp, url_prefix='/api/v2/demanda_producao')
    app.register_blueprint(tasks_api_bp)
    app.register_blueprint(task_schedules_api_bp)
    app.register_blueprint(usuarios_setores_bp)
    app.register_blueprint(usuarios_setores_api_bp, url_prefix='/api/v2/usuarios-setores')
    app.register_blueprint(notifications_bp)
    app.register_blueprint(orders_api_bp, url_prefix='/api/v2/orders')
    app.register_blueprint(marketplace_api_bp, url_prefix='/api/v2/marketplace')
    app.register_blueprint(marketplace_bp)
    app.register_blueprint(printing_bp)
    app.register_blueprint(printing_api_bp, url_prefix='/api/v2/printing')
    app.register_blueprint(jobs_bp)
    app.register_blueprint(unified_orders_bp)
    app.register_blueprint(integracao_canais_bp)
    app.register_blueprint(pedidos_bp)
    app.register_blueprint(pedidos_gestao_bp)
    app.register_blueprint(demanda_consolidada_bp)
    app.register_blueprint(demandas_bp)
    app.register_blueprint(alertas_bp)
    app.register_blueprint(webhooks_bp)
    app.register_blueprint(producao_contexto_bp, url_prefix='/api/v2/producao-contexto')
    app.register_blueprint(erp_links_bp)
    app.register_blueprint(personalizados_api_bp)
    app.register_blueprint(impressao_api_bp)

    @app.route('/test_route')
    def test_route():
        return "Test route works!"

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

    # Logging de requisições
    @app.before_request
    def log_request_info():
        from flask import request
        app.logger.info(f'{request.method} {request.url} - {request.remote_addr}')

    return app

if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("PORT", 8080))
    # In production, debug should be False.
    debug_mode = os.environ.get('FLASK_ENV') == 'development'
    app.run(host='0.0.0.0', port=port, debug=debug_mode)





