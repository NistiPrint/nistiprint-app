from nistiprint_shared.database.supabase_db_service import supabase_db
from contextlib import contextmanager


@contextmanager
def get_db_connection():
    """
    Context manager to get a database connection
    """
    # For Supabase, we'll use the raw client directly
    yield supabase_db.client


def get_dados_gerenciais_diarios(data=None):
    """
    Retorna os dados gerenciais agregados por dia da view_gerencial_diario.
    """
    try:
        if data:
            response = supabase_db.client.from_("view_gerencial_diario").select("*").eq("data_base", data).execute()
        else:
            response = supabase_db.client.from_("view_gerencial_diario").select("*").order("data_base", desc=True).execute()

        return response.data
    except Exception as e:
        print(f"Erro ao buscar dados gerenciais diários: {e}")
        return []


def get_dados_gerenciais_demanda(demanda_id=None):
    """
    Retorna os dados gerenciais detalhados por demanda da view_gerencial_demanda.
    """
    try:
        if demanda_id:
            response = supabase_db.client.from_("view_gerencial_demanda").select("*").eq("demanda_id", demanda_id).execute()
        else:
            response = supabase_db.client.from_("view_gerencial_demanda").select("*").order("demanda_id", desc=True).execute()

        return response.data
    except Exception as e:
        print(f"Erro ao buscar dados gerenciais da demanda: {e}")
        return []


def get_sulfite_usage_report():
    """
    Gera o relatório de consumo de sulfite baseado nos logs reais de produção.
    Retorna um dicionário mapeando 'YYYY-MM' para a quantidade consumida.
    """
    try:
        from nistiprint_shared.services.app_config_service import app_config_service
        sulfite_product_id = app_config_service.get_config('sulfite_sheet_product_id')

        if not sulfite_product_id:
            return {'error': 'Produto sulfite não configurado'}

        # Buscar todos os logs de produção para o produto sulfite (sem filtro 'deleted' pois queremos histórico de consumo)
        # Na verdade, devemos filtrar deleted=False para consumo real
        response = supabase_db.table('logs_producao_diaria')\
            .select("quantidade_produzida, data")\
            .eq("produto_id", sulfite_product_id)\
            .neq("deleted", True)\
            .execute()

        if not response.data:
            return {}

        usage_by_month = {}
        for row in response.data:
            qty = float(row.get('quantidade_produzida', 0))
            # No controle de produção, a "produção" de sulfite (miolo) é registrada como valor positivo
            # mas o consumo em si é o que queremos medir.
            if qty == 0: continue
            
            data_str = row.get('data')
            if not data_str: continue
            
            month_key = data_str[:7] # YYYY-MM
            usage_by_month[month_key] = usage_by_month.get(month_key, 0) + abs(qty)

        # Ordenar por mês descendente
        return dict(sorted(usage_by_month.items(), reverse=True))

    except Exception as e:
        print(f"Erro ao gerar relatório de sulfite: {e}")
        return {'error': str(e)}


def get_producao_history(page=1, per_page=20):
    """
    Retorna o histórico detalhado de logs de produção da tabela logs_producao_diaria.
    """
    try:
        offset = (page - 1) * per_page

        response = supabase_db.table('logs_producao_diaria')\
            .select("*")\
            .neq("deleted", True)\
            .order("data_registro", desc=True)\
            .range(offset, offset + per_page)\
            .execute()

        # Verificar se tem mais páginas
        next_check = supabase_db.table('logs_producao_diaria')\
            .select("id", count='exact')\
            .neq("deleted", True)\
            .range(offset + per_page, offset + per_page)\
            .execute()

        has_next = (next_check.count or 0) > 0

        # Transformar os dados para o formato esperado pelo frontend
        formatted_logs = []
        for log in response.data:
            # Mapear campos para o formato esperado pelo frontend
            formatted_log = {
                'id': log.get('id'),
                'timestamp': log.get('data_registro') or log.get('created_at') or log.get('date'),
                'ordem_producao_id': log.get('ordem_producao_id'),
                'produto_id': log.get('produto_id'),
                'componente_id': log.get('componente_id'),
                'quantidade_produzida': log.get('quantidade_produzida'),
                'usuario_id': log.get('usuario_id') or log.get('equipe_id'),
                # Campos adicionais que podem estar presentes
                'date': log.get('date'),
                'turno': log.get('turno'),
                'equipe_nome': log.get('equipe_nome'),
                'resumo_diario': log.get('resumo_diario'),
                'producao_detalhes': log.get('producao_detalhes'),
                'problemas': log.get('problemas'),
                'created_at': log.get('created_at'),
                'updated_at': log.get('updated_at')
            }
            formatted_logs.append(formatted_log)

        return {
            'logs': formatted_logs,
            'has_next': has_next
        }
    except Exception as e:
        print(f"Erro ao buscar histórico de produção: {e}")
        return {'logs': [], 'has_next': False, 'error': str(e)}

