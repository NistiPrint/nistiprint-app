from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.app_config_service import app_config_service
from contextlib import contextmanager
from datetime import datetime, timezone
import logging


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
    except Exception:
        logging.exception("Erro ao buscar dados gerenciais diários")
        raise


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
    except Exception:
        logging.exception("Erro ao buscar dados gerenciais da demanda")
        raise


def get_sulfite_usage_report():
    """
    Gera o consumo mensal líquido a partir de movimentos confirmados no ledger.
    Mantém o mapa mensal existente e acrescenta metadados e operações de origem.
    """
    try:
        sulfite_product_id = app_config_service.get_config('sulfite_sheet_product_id')
        if not sulfite_product_id:
            return {
                'monthly': {}, 'movements_by_month': {},
                'generated_at': datetime.now(timezone.utc).isoformat(),
                'source': 'confirmed_stock_movements',
                'error': 'Produto sulfite não configurado',
            }

        try:
            product_id = int(sulfite_product_id)
        except (TypeError, ValueError) as exc:
            raise ValueError('A configuração do produto sulfite deve conter um ID inteiro.') from exc
        if product_id <= 0:
            raise ValueError('A configuração do produto sulfite deve conter um ID inteiro positivo.')

        response = supabase_db.rpc(
            'relatorio_consumo_mensal_produto', {'p_produto_id': product_id}
        ).execute()
        if response is None or getattr(response, 'data', None) is None:
            raise RuntimeError('Não foi possível confirmar o relatório de consumo no ledger.')

        rows = response.data or []
        monthly = {str(row['periodo']): float(row['consumo_liquido']) for row in rows}
        details = {str(row['periodo']): row.get('movimentos') or [] for row in rows}
        return {
            'monthly': dict(sorted(monthly.items())),
            'movements_by_month': details,
            'period_start': min(monthly) if monthly else None,
            'period_end': max(monthly) if monthly else None,
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'source': 'confirmed_stock_movements',
            'product_id': product_id,
        }

    except Exception:
        logging.exception('Erro ao gerar relatório de consumo de sulfite')
        raise


def get_producao_history(page=1, per_page=20):
    """
    Retorna o histórico detalhado de logs de produção da tabela logs_producao_diaria.
    """
    try:
        page = max(1, int(page))
        per_page = max(1, min(100, int(per_page)))
        offset = (page - 1) * per_page

        response = supabase_db.table('logs_producao_diaria')\
            .select("*")\
            .neq("deleted", True)\
            .order("data_registro", desc=True)\
            .order("id", desc=True)\
            .range(offset, offset + per_page - 1)\
            .execute()

        count_response = supabase_db.table('logs_producao_diaria')\
            .select("id", count='exact')\
            .neq("deleted", True)\
            .execute()
        if response is None or getattr(response, 'data', None) is None or count_response is None:
            raise RuntimeError('Não foi possível confirmar o histórico de produção.')
        total = int(getattr(count_response, 'count', 0) or 0)
        has_next = offset + len(response.data) < total

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
            'has_next': has_next,
            'page': page,
            'per_page': per_page,
            'total': total,
            'generated_at': datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        logging.exception('Erro ao buscar histórico de produção')
        raise

