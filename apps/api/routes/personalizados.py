"""
Endpoints para gestão de pedidos personalizados com IA.

Fluxo:
1. Listar pedidos com itens personalizados
2. Processar com IA (sob demanda, assíncrono via Celery)
3. Visualizar logs de execução
4. Dar feedback sobre extrações
5. Configurar prompt e modelo de IA
"""

from flask import Blueprint, request
from routes.auth import login_required
from nistiprint_shared.services.ai_personalization_service import (
    process_orders,
    get_logs_by_order_sn,
    get_orders_with_chats,
)
from nistiprint_shared.services.app_config_service import app_config_service
from nistiprint_shared.services.orders_query_service import orders_query_service
from nistiprint_shared.database.supabase_db_service import supabase_db
from utils.api_response import ApiResponse
from datetime import datetime
import logging

logger = logging.getLogger("PersonalizadosAPI")

personalizados_api_bp = Blueprint('personalizados_api', __name__, url_prefix='/api/v2/personalizados')


# ─────────────────────────────────────────────────────────────
# LISTAR PEDIDOS PERSONALIZADOS
# ─────────────────────────────────────────────────────────────
@personalizados_api_bp.route('', methods=['GET'])
@login_required
def listar_personalizados():
    """
    Lista pedidos com itens personalizados.
    Reusa a view view_vendas_personalizadas que filtra por personalizado=true.
    
    Query params:
    - order_sn: str (filtrar por pedido específico)
    - limit: int (limitar quantidade)
    """
    try:
        order_sn = request.args.get('order_sn')
        limit = request.args.get('limit', type=int)
        
        orders = get_orders_with_chats(order_sn=order_sn, limit=limit)
        return ApiResponse.success({'orders': orders, 'total': len(orders)})
    except Exception as e:
        logger.error(f"Erro ao listar personalizados: {e}", exc_info=True)
        return ApiResponse.error(str(e), 500)


# ─────────────────────────────────────────────────────────────
# PROCESSAR COM IA (SOB DEMANDA)
# ─────────────────────────────────────────────────────────────
@personalizados_api_bp.route('/processar', methods=['POST'])
@login_required
def processar_personalizados():
    """
    Dispara processamento de IA sob demanda.
    
    Body (opcional):
    - order_sn: str (processar apenas 1 pedido)
    - limit: int (limitar quantidade, default 50)
    
    Retorna:
    - success: bool
    - message: str
    - total_processed: int
    """
    try:
        data = request.get_json() or {}
        order_sn = data.get('order_sn')
        limit = data.get('limit', 50)

        # Tentar processar via Celery (se disponível)
        try:
            from tasks.personalizados_tasks import processar_personalizacoes_task
            task = processar_personalizacoes_task.delay(order_sn=order_sn, limit=limit)
            return ApiResponse.success({
                'task_id': task.id,
                'status': 'queued',
                'message': 'Processamento iniciado em background'
            })
        except ImportError:
            # Fallback: processar síncrono
            logger.warning("Celery task não disponível, processando síncrono")
            success, message = process_orders(order_sn=order_sn, limit=limit)
            return ApiResponse.success({
                'success': success,
                'message': message,
                'mode': 'sync'
            })

    except Exception as e:
        logger.error(f"Erro ao processar personalizados: {e}", exc_info=True)
        return ApiResponse.error(str(e), 500)


# ─────────────────────────────────────────────────────────────
# STATUS DA TASK CELERY
# ─────────────────────────────────────────────────────────────
@personalizados_api_bp.route('/status/<task_id>', methods=['GET'])
@login_required
def status_task(task_id):
    """Verifica status de uma task de processamento."""
    try:
        from celery.result import AsyncResult
        task = AsyncResult(task_id)

        response = {
            'task_id': task_id,
            'status': task.status,  # PENDING, PROCESSING, SUCCESS, FAILURE
        }
        if task.ready():
            response['result'] = task.result

        return ApiResponse.success(response)
    except Exception as e:
        return ApiResponse.error(str(e), 500)


# ─────────────────────────────────────────────────────────────
# REPROCESSAR UM PEDIDO
# ─────────────────────────────────────────────────────────────
@personalizados_api_bp.route('/reprocessar/<order_sn>', methods=['POST'])
@login_required
def reprocessar(order_sn):
    """
    Reprocessa um pedido específico.
    Deleta extrações anteriores e executa IA novamente.
    """
    try:
        # Deletar extrações anteriores
        supabase_db.table('personalizacoes_pedido').delete().eq('shopee_order_sn', order_sn).execute()

        # Processar novamente
        success, message = process_orders(order_sn=order_sn)

        return ApiResponse.success({'success': success, 'message': message})
    except Exception as e:
        logger.error(f"Erro ao reprocessar {order_sn}: {e}", exc_info=True)
        return ApiResponse.error(str(e), 500)


# ─────────────────────────────────────────────────────────────
# LOGS DE EXECUÇÃO IA
# ─────────────────────────────────────────────────────────────
@personalizados_api_bp.route('/logs', methods=['GET'])
@login_required
def get_all_logs():
    """
    Retorna logs de execução da IA com filtros.
    Usado pela tela de ferramentas/utilitários.

    Query params:
    - order_sn: str (filtrar por pedido específico)
    - status: str (success, error, db_error, no_response)
    - limit: int (default 100)
    - offset: int (default 0)
    """
    try:
        order_sn = request.args.get('order_sn')
        status = request.args.get('status')
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)

        query = supabase_db.table('logs_execucao_ia').select('*', count='exact')

        if order_sn:
            query = query.eq('order_sn', order_sn)
        if status:
            query = query.eq('status', status)

        response = query \
            .order('executed_at', desc=True) \
            .range(offset, offset + limit - 1) \
            .execute()

        return ApiResponse.success({
            'logs': response.data or [],
            'total': response.count or 0,
            'limit': limit,
            'offset': offset
        })
    except Exception as e:
        logger.error(f"Erro ao buscar logs: {e}", exc_info=True)
        return ApiResponse.error(str(e), 500)


@personalizados_api_bp.route('/logs/<order_sn>', methods=['GET'])
@login_required
def get_logs(order_sn):
    """Retorna logs de execução da IA para um pedido específico."""
    try:
        logs = get_logs_by_order_sn(order_sn)
        return ApiResponse.success({'logs': logs, 'total': len(logs)})
    except Exception as e:
        logger.error(f"Erro ao buscar logs para {order_sn}: {e}", exc_info=True)
        return ApiResponse.error(str(e), 500)


# ─────────────────────────────────────────────────────────────
# FEEDBACK DO USUÁRIO
# ─────────────────────────────────────────────────────────────
@personalizados_api_bp.route('/feedback', methods=['POST'])
@login_required
def salvar_feedback():
    """
    Salva feedback do usuário sobre extração.
    
    Body:
    - order_sn: str (obrigatório)
    - avaliacao: int 1-5 (obrigatório, 1=negativo, 5=positivo)
    - texto_feedback: str (opcional)
    """
    try:
        data = request.get_json()
        
        if not data.get('order_sn') or not data.get('avaliacao'):
            return ApiResponse.error('order_sn e avaliacao são obrigatórios', 400)

        supabase_db.table('feedback_pedido').insert({
            'codigo_pedido': data['order_sn'],
            'avaliacao': int(data['avaliacao']),
            'texto_feedback': data.get('texto_feedback', ''),
            'updated_at': datetime.utcnow().isoformat()
        }).execute()

        return ApiResponse.success({'message': 'Feedback salvo com sucesso'})
    except Exception as e:
        logger.error(f"Erro ao salvar feedback: {e}", exc_info=True)
        return ApiResponse.error(str(e), 500)


# ─────────────────────────────────────────────────────────────
# CONFIGURAÇÃO IA (PROMPT + MODELO)
# ─────────────────────────────────────────────────────────────
@personalizados_api_bp.route('/config', methods=['GET'])
@login_required
def get_config():
    """Obtém configurações de IA (prompt template + modelo)."""
    try:
        configs = app_config_service.get_multiple_configs([
            'prompt_template', 'model_name', 'max_processing'
        ])
        return ApiResponse.success({'config': configs})
    except Exception as e:
        logger.error(f"Erro ao buscar config IA: {e}", exc_info=True)
        return ApiResponse.error(str(e), 500)


@personalizados_api_bp.route('/config', methods=['PUT'])
@login_required
def update_config():
    """
    Atualiza configurações de IA.
    
    Body (campos opcionais):
    - prompt_template: str (texto do prompt)
    - model_name: str (ex: gemini-2.5-flash)
    - max_processing: int (limite padrão)
    """
    try:
        data = request.get_json()
        results = {}

        # Salvar cada configuração
        if 'prompt_template' in data:
            app_config_service.set_config('prompt_template', data['prompt_template'])
            results['prompt_template'] = 'updated'

        if 'model_name' in data:
            app_config_service.set_config('model_name', data['model_name'])
            results['model_name'] = 'updated'

        if 'max_processing' in data:
            app_config_service.set_config('max_processing', int(data['max_processing']))
            results['max_processing'] = 'updated'

        # Recarregar PROMPT_TEMPLATE no service (agora load_prompt_template lê do DB primeiro)
        if 'prompt_template' in data or 'model_name' in data:
            import nistiprint_shared.services.ai_personalization_service as ai_service
            # Recarrega do DB (nova prioridade do load_prompt_template)
            ai_service.PROMPT_TEMPLATE = ai_service.load_prompt_template()
            logger.info("Prompt template recarregado no serviço da API")
            if 'model_name' in data:
                ai_service.model_name = data['model_name']
                logger.info("Modelo atualizado para: %s", data['model_name'])

        return ApiResponse.success({'updated': results})
    except Exception as e:
        logger.error(f"Erro ao atualizar config IA: {e}", exc_info=True)
        return ApiResponse.error(str(e), 500)


# ─────────────────────────────────────────────────────────────
# MENSAGENS DE CHAT
# ─────────────────────────────────────────────────────────────
@personalizados_api_bp.route('/chat/<username>', methods=['GET'])
@login_required
def get_chat(username):
    """Obtém mensagens de chat de um usuário (comprador Shopee)."""
    try:
        limit = request.args.get('limit', type=int, default=200)
        
        msgs = supabase_db.table('view_mensagens_chat') \
            .select('*') \
            .or_(f"from_user_name.eq.{username},to_user_name.eq.{username}") \
            .order('created_at', desc=False) \
            .limit(limit) \
            .execute()

        return ApiResponse.success({'messages': msgs.data or [], 'total': len(msgs.data or [])})
    except Exception as e:
        logger.error(f"Erro ao buscar chat para {username}: {e}", exc_info=True)
        return ApiResponse.error(str(e), 500)
