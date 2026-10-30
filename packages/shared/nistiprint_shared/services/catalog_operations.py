"""Mirror manual catalog jobs in the existing Operations Center."""
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def create_operation(owner_id, account_id=None, title='Sincronização do catálogo'):
    from .async_operation_service import async_operation_service
    return async_operation_service.create_operation(
        owner_user_id=owner_id,categoria='INTEGRACAO',titulo=title,
        referencia_tipo='integracao' if account_id else 'gestao',referencia_id=account_id,
        rota_destino='/anuncios',progresso_total=0,
        dados_adicionais={'account_id':account_id},
    )['id']


def progress(operation_id, result):
    if not operation_id:
        return
    try:
        from .async_operation_service import async_operation_service
        from ..database.supabase_db_service import supabase_db
        rows = supabase_db.table('operacoes_assincronas').select('progresso_atual,created_at,dados_adicionais').eq('id',operation_id).execute().data or []
        if not rows:
            return
        previous = rows[0]
        status = result.get('status')
        failed = status in {'unavailable','account_missing','lease_lost','failed'} and not result.get('retryable')
        complete = status == 'complete' or (status is None and result.get('has_more') is False)
        details = {**(previous.get('dados_adicionais') or {}),**result}
        started = datetime.fromisoformat(previous['created_at'].replace('Z','+00:00'))
        details['duration_ms'] = int((datetime.now(timezone.utc)-started).total_seconds()*1000)
        count = int(previous.get('progresso_atual') or 0) + int(result.get('items',result.get('processed',0)))
        async_operation_service.update_operation(operation_id,
            status='ERRO' if failed else 'CONCLUIDO' if complete else 'EM_ANDAMENTO',
            progresso_atual=count,progresso_total=count if complete else None,
            mensagem=f'{count} registros processados',erro_resumo=result.get('error_code'),
            dados_adicionais=details,
        )
    except Exception:
        logger.exception('Falha ao atualizar operação de catálogo %s',operation_id)
