from datetime import datetime
from flask import Blueprint, render_template
from nistiprint_shared.database.supabase_db_service import supabase_db

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    """Página principal que testa a conexão com o Supabase."""

    try:
        # Teste de conexão com Supabase
        # Tenta listar uma tabela básica (ex: usuarios) apenas para validar
        if supabase_db._ensure_client():
            # Apenas verifica se o cliente está ativo
            supabase_status = 'Conectado com sucesso ao Supabase!'
            connection_status = 'OK'
        else:
            supabase_status = 'Erro na conexão com Supabase'
            connection_status = 'Erro'

    except Exception as e:
        supabase_status = f'Erro na conexão: {str(e)}'
        connection_status = 'Erro'

    # Retorna uma resposta simples caso o template index.html não exista
    # ou renderiza se o usuário preferir. 
    # Por segurança, retornamos texto puro por enquanto para evitar Erro 500 de template missing.
    return f"""
    <h1>NistiPrint API V3 - Status</h1>
    <p><strong>Status Supabase:</strong> {supabase_status}</p>
    <p><strong>Timestamp:</strong> {datetime.now()}</p>
    <hr>
    <p>API operando em modo modular.</p>
    """





