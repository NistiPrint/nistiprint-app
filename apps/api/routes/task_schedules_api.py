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

CRON_FIELDS = ('minute', 'hour', 'day_of_week', 'day_of_month', 'month_of_year')


def _normalizar_cron(valor):
    """Valida a configuracao de cron antes de ela chegar ao beat.

    O agendador roda em outro processo e so le esta configuracao no start: um
    cron invalido gravado aqui nao da erro agora, da uma task que simplesmente
    nao aparece no proximo restart do worker. Por isso a validacao acontece na
    escrita, com `crontab()` — a mesma classe que o beat usa — em vez de um
    regex proprio que aceitaria coisas que o Celery recusa.

    Retorna (cron_normalizado, erro). `None` para o cron significa "remover o
    cron e voltar ao intervalo em segundos".
    """
    if valor in (None, '', {}):
        return None, None

    if isinstance(valor, str):
        partes = valor.split()
        if len(partes) != 5:
            return None, "cron em texto deve ter cinco campos: 'minuto hora dia_do_mes mes dia_da_semana'"
        minuto, hora, dia_mes, mes, dia_semana = partes
        valor = {
            'minute': minuto,
            'hour': hora,
            'day_of_month': dia_mes,
            'month_of_year': mes,
            'day_of_week': dia_semana,
        }

    if not isinstance(valor, dict):
        return None, 'cron deve ser um objeto ou uma string de cinco campos'

    desconhecidos = set(valor) - set(CRON_FIELDS)
    if desconhecidos:
        return None, f"campos de cron nao reconhecidos: {', '.join(sorted(desconhecidos))}"

    campos = {campo: valor[campo] for campo in CRON_FIELDS if valor.get(campo) is not None}
    # Mesma normalizacao do beat: hora sem minuto vira minuto zero, senao
    # "todo dia as 12h" seria gravado como "a cada minuto entre 12h e 13h".
    if 'hour' in campos and 'minute' not in campos:
        campos['minute'] = 0
    if not campos:
        return None, 'cron precisa de pelo menos um campo preenchido'

    try:
        from celery.schedules import crontab
        crontab(**campos)
    except (ValueError, TypeError, KeyError) as exc:
        return None, f'cron invalido: {exc}'

    return campos, None


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
    Atualiza configuração de uma tarefa (enabled, schedule_seconds e/ou cron).

    Body:
    {
        "enabled": boolean,
        "schedule_seconds": integer (opcional),
        "cron": {"hour": 12, "minute": 0} | "0 12 * * *" | null (opcional)
    }

    `cron` e `schedule_seconds` são excludentes: gravar um limpa o outro.
    Enviar "cron": null volta a tarefa para o modo intervalo.
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
            # Intervalo e horario sao excludentes no beat, e `cron` tem
            # precedencia na leitura. Deixar os dois gravados faria a tela
            # mostrar "a cada 1h" numa task que na verdade roda so ao meio-dia.
            task_schedules[task_name].pop('cron', None)
            task_schedules[task_name].pop('crontab', None)

        if 'cron' in data:
            cron, erro = _normalizar_cron(data['cron'])
            if erro:
                return jsonify({'success': False, 'error': erro}), 400
            if cron is None:
                task_schedules[task_name].pop('cron', None)
                task_schedules[task_name].pop('crontab', None)
            else:
                task_schedules[task_name]['cron'] = cron
                task_schedules[task_name].pop('crontab', None)
        
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
