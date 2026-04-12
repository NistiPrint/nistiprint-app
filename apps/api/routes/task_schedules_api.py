"""
Task Schedules API Endpoints
Provides endpoints for managing Celery Beat periodic tasks (enable/disable and frequency)
"""
from flask import Blueprint, request, jsonify
from routes.auth import admin_required
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.app_config_service import app_config_service
import logging

logger = logging.getLogger(__name__)

task_schedules_api_bp = Blueprint('task_schedules_api', __name__, url_prefix='/api/v2/admin/task-schedules')


@task_schedules_api_bp.route('', methods=['GET'])
@admin_required
def list_task_schedules():
    """
    Lista todas as tarefas configuráveis com suas configurações atuais.
    """
    try:
        
        config = app_config_service.get_config('celery_task_schedules')
        
        if not config:
            return jsonify({
                'success': True,
                'data': {},
                'message': 'Nenhuma configuração encontrada'
            })
        
        task_schedules = config.get('task_schedules', {})
        
        # Enriquecer com informações de última execução (se disponível)
        enriched_schedules = {}
        for task_name, task_config in task_schedules.items():
            enriched_schedules[task_name] = {
                **task_config,
                'last_execution': None  # TODO: Buscar de task_execution_logs
            }
        
        return jsonify({
            'success': True,
            'data': enriched_schedules
        })
    except Exception as e:
        logger.error(f"Erro ao listar tarefas: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@task_schedules_api_bp.route('/<task_name>', methods=['GET'])
@admin_required
def get_task_schedule(task_name):
    """
    Retorna detalhes de uma tarefa específica.
    """
    try:
        
        config = app_config_service.get_config('celery_task_schedules')
        
        if not config:
            return jsonify({'success': False, 'error': 'Configuração não encontrada'}), 404
        
        task_schedules = config.get('task_schedules', {})
        
        if task_name not in task_schedules:
            return jsonify({'success': False, 'error': 'Tarefa não encontrada'}), 404
        
        return jsonify({
            'success': True,
            'data': task_schedules[task_name]
        })
    except Exception as e:
        logger.error(f"Erro ao buscar tarefa {task_name}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@task_schedules_api_bp.route('/<task_name>', methods=['PUT'])
@admin_required
def update_task_schedule(task_name):
    """
    Atualiza configuração de uma tarefa (enabled e/ou schedule_seconds).
    
    Body:
    {
        "enabled": boolean,
        "schedule_seconds": integer (opcional)
    }
    """
    try:
        
        data = request.get_json()
        
        if not data:
            return jsonify({'success': False, 'error': 'Body vazio'}), 400
        
        config = app_config_service.get_config('celery_task_schedules')
        
        if not config:
            return jsonify({'success': False, 'error': 'Configuração não encontrada'}), 404
        
        task_schedules = config.get('task_schedules', {})
        
        if task_name not in task_schedules:
            return jsonify({'success': False, 'error': 'Tarefa não encontrada'}), 404
        
        # Atualizar campos fornecidos
        if 'enabled' in data:
            task_schedules[task_name]['enabled'] = bool(data['enabled'])
        
        if 'schedule_seconds' in data:
            schedule_seconds = int(data['schedule_seconds'])
            if schedule_seconds < 1:
                return jsonify({'success': False, 'error': 'schedule_seconds deve ser >= 1'}), 400
            task_schedules[task_name]['schedule_seconds'] = schedule_seconds
        
        # Salvar configuração atualizada
        app_config_service.set_config('celery_task_schedules', config)
        
        logger.info(f"Tarefa {task_name} atualizada: {task_schedules[task_name]}")
        
        return jsonify({
            'success': True,
            'message': 'Tarefa atualizada com sucesso',
            'data': task_schedules[task_name],
            'warning': 'Alterações de frequência requerem reinício do worker'
        })
    except Exception as e:
        logger.error(f"Erro ao atualizar tarefa {task_name}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@task_schedules_api_bp.route('/reload', methods=['POST'])
@admin_required
def reload_task_schedules():
    """
    Avisa que as configurações foram alteradas e o worker precisa ser reiniciado.
    
    Na prática, este endpoint apenas registra a intenção. O reinício deve ser
    feito manualmente ou via orquestrador (Docker, Kubernetes, etc).
    """
    try:
        
        # Registrar log de alteração
        logger.warning("Solicitação de recarga de configurações do worker - requer reinício manual")
        
        return jsonify({
            'success': True,
            'message': 'Configurações alteradas. Reinicie o worker para aplicar as mudanças.',
            'instructions': [
                '1. Pare o container do worker',
                '2. Inicie o container do worker novamente',
                '3. As novas configurações serão carregadas automaticamente'
            ]
        })
    except Exception as e:
        logger.error(f"Erro ao solicitar recarga: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
