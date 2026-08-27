# ===========================================
# CELERY APP CONFIGURATION
# ===========================================
# Configuração centralizada do Celery
# ===========================================

import os
import logging
from celery import Celery
from celery.schedules import crontab

# Configuração de Logs Silenciosos para bibliotecas barulhentas
for _noisy_logger in ("httpx", "httpcore", "hpack", "urllib3", "postgrest", "supabase"):
    logging.getLogger(_noisy_logger).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# --- Inicialização da Infraestrutura ---
try:
    from nistiprint_shared.utils.env_loader import load_nistiprint_env
    from nistiprint_shared.database.initializer import setup_mock_query_interface
    
    # Garante que variáveis de ambiente estejam carregadas
    load_nistiprint_env()
    # Garante que a interface de banco (Supabase/Mock) esteja pronta
    setup_mock_query_interface()
except ImportError:
    from dotenv import load_dotenv
    load_dotenv()

# Configuração do broker Redis
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://redis-celery:6379/0')
CELERY_RESULT_BACKEND = None

def get_default_schedules():
    """Fallback usado APENAS quando `celery_task_schedules` nao existe no banco.

    Enquanto a configuracao existir — e ela existe em producao — estes valores
    nao tem efeito nenhum. Sao mantidos como rede de seguranca para um ambiente
    novo, nao como documentacao do que roda. Consultar o banco, nunca este
    dicionario, para saber o que esta ativo.

    Os intervalos abaixo espelham a configuracao de producao de propositio: um
    default divergente vira armadilha, porque quem le o codigo conclui uma coisa
    e o beat faz outra.
    """
    return {
        'reconcile-pending-erp-references': {
            'task': 'nistiprint_shared.services.order_erp_reference_service.reconcile_pending',
            'schedule': 60,
        },
        'process-marketplace-lifecycle-effects': {
            'task': 'nistiprint_shared.services.marketplace_lifecycle_tasks.process_pending_effects',
            'schedule': 30,
        },
        'processar-eventos-producao-periodic': {
            'task': 'tasks.eventos_tasks.process_eventos_producao',
            'schedule': 300,
        },
        'renew-app-managed-credentials': {
            'task': 'tasks.token_renewal_tasks.renew_app_managed_credentials',
            'schedule': 7200,
        },
        'processar-personalizados-diario': {
            'task': 'services.ai_personalization.processar_pendentes',
            'schedule': crontab(hour=12, minute=0),
            'options': {'queue': 'ai_personalization'},
        },
        'recolher-lotes-ia-parados': {
            'task': 'services.ai_personalization.recolher_lotes_parados',
            'schedule': 300,
            'options': {'queue': 'ai_personalization'},
        },
    }

CRON_FIELDS = ("minute", "hour", "day_of_week", "day_of_month", "month_of_year")


def build_schedule(task_name, task_config):
    """Traduz a configuracao do banco no schedule que o beat entende.

    Duas formas convivem de proposito. `schedule_seconds` continua sendo a
    forma certa para tarefas que so precisam rodar "de tempos em tempos" — a
    reconciliacao de ERP nao se importa se roda 09:00:03 ou 09:00:47. Ja uma
    rotina que existe para acontecer num horario — o lote diario de
    personalizados ao meio-dia — nao pode ser expressa como intervalo: um
    `86400` deriva a cada reinicio do beat e, depois de algumas semanas,
    "meio-dia" virou madrugada sem ninguem mexer em nada.

    Aceita `cron` como dict ({"hour": 12, "minute": 0}) ou como string de
    cinco campos ("0 12 * * *"), porque a tela grava dict e quem edita o JSON
    na mao tende a escrever a forma classica.

    Retorna None quando a configuracao de cron e invalida: cair no intervalo
    default seria pior que nao agendar, porque uma task diaria passaria a
    rodar de minuto em minuto sem aviso.
    """
    cron = task_config.get("cron", task_config.get("crontab"))

    if isinstance(cron, str) and cron.strip():
        partes = cron.split()
        if len(partes) != 5:
            logger.error(
                "Cron invalido em '%s': %r nao tem os cinco campos. Task nao agendada.",
                task_name, cron,
            )
            return None
        minuto, hora, dia_mes, mes, dia_semana = partes
        cron = {
            "minute": minuto,
            "hour": hora,
            "day_of_month": dia_mes,
            "month_of_year": mes,
            "day_of_week": dia_semana,
        }

    if isinstance(cron, dict) and cron:
        campos = {campo: cron[campo] for campo in CRON_FIELDS if cron.get(campo) is not None}
        # "as 12h" quer dizer 12:00, nao sessenta disparos ao longo da hora.
        # O default do Celery para `minute` e `*`, entao omitir o minuto num
        # cron com hora produziria exatamente o oposto do que se configurou.
        if "hour" in campos and "minute" not in campos:
            campos["minute"] = 0
        if not campos:
            logger.error(
                "Cron de '%s' nao tem nenhum campo reconhecido (%s). Task nao agendada.",
                task_name, ", ".join(CRON_FIELDS),
            )
            return None
        try:
            return crontab(**campos)
        except (ValueError, TypeError) as exc:
            logger.error("Cron invalido em '%s': %s. Task nao agendada.", task_name, exc)
            return None

    segundos = task_config.get("schedule_seconds", 60)
    try:
        return max(1, int(segundos))
    except (TypeError, ValueError):
        logger.error(
            "schedule_seconds invalido em '%s': %r. Task nao agendada.", task_name, segundos,
        )
        return None


def describe_schedule(schedule):
    """Rotulo curto para o log de startup — 'as 12:00' diz mais que um objeto."""
    if isinstance(schedule, crontab):
        return f"cron {schedule._orig_minute} {schedule._orig_hour} {schedule._orig_day_of_month} {schedule._orig_month_of_year} {schedule._orig_day_of_week}"
    return f"{schedule}s"


def load_dynamic_schedules():
    """Carrega agendamentos do banco de dados (tabela configuracoes_aplicacao)."""
    try:
        from nistiprint_shared.services.app_config_service import app_config_service
        
        config = app_config_service.get_config('celery_task_schedules')
        if not config:
            logger.warning("Configuração 'celery_task_schedules' não encontrada no banco. Usando padrões.")
            return get_default_schedules()
            
        task_schedules_config = config.get('task_schedules', {})
        schedules = {}
        
        obsolete_webhook_tasks = {
            'sync-firestore-tokens', 'process-pending-webhooks',
            'drain-bling-webhook-failures', 'consumir-fila-bling', 'consumir_fila_bling',
            'consumir-fila-shopee', 'consumir_fila_shopee',
            'consumir-fila-mercadolivre', 'consumir_fila_mercadolivre',
        }
        for task_name, task_config in task_schedules_config.items():
            configured_task = task_config.get('task_name', task_name)
            if task_name in obsolete_webhook_tasks or any(
                marker in configured_task for marker in (
                    'consumir_fila_bling', 'consumir_fila_shopee',
                    'consumir_fila_mercadolivre', 'process_pending_webhooks',
                    'drain_bling_webhook_failures'
                )
            ):
                logger.info(
                    "Task periodica obsoleta ignorada: %s. "
                    "As credenciais Bling agora sao gerenciadas pelo app.",
                    configured_task,
                )
                continue
            if task_config.get('enabled', True):
                schedule = build_schedule(task_name, task_config)
                if schedule is None:
                    # build_schedule ja explicou o motivo no log. Pular e
                    # deliberado: agendar com um default inventado faria a task
                    # rodar numa cadencia que ninguem configurou.
                    continue
                entry = {
                    'task': task_config.get('task_name', task_name),
                    'schedule': schedule,
                }
                # `kwargs`/`args` eram descartados silenciosamente: uma task
                # configurada como `dry_run: true` no banco rodava com os
                # defaults da assinatura. Configuracao que nao chega na execucao
                # e pior que configuracao ausente, porque parece estar valendo.
                kwargs = task_config.get('kwargs')
                if isinstance(kwargs, dict) and kwargs:
                    entry['kwargs'] = kwargs
                args = task_config.get('args')
                if isinstance(args, (list, tuple)) and args:
                    entry['args'] = list(args)
                queue = task_config.get('queue')
                if isinstance(queue, str) and queue.strip():
                    entry['options'] = {'queue': queue.strip()}
                schedules[task_name] = entry
                logger.info(
                    "Task periódica ativa: %s (%s)%s",
                    task_name,
                    describe_schedule(schedule),
                    f" kwargs={sorted(kwargs)}" if entry.get('kwargs') else "",
                )
            else:
                logger.info(f"Task periódica desativada via banco: {task_name}")
                
        schedules.update(load_janela_despacho_schedules())
        return schedules
    except Exception as e:
        logger.error(f"Erro ao carregar tasks dinâmicas: {e}. Usando padrões de código.")
        return get_default_schedules()


def load_janela_despacho_schedules():
    """Uma entrada de beat por horário de corte e de coleta cadastrado.

    Gerado a partir de `regras_logisticas_integracao` — a aba Logística — e não
    de constante em código: cadastrar uma modalidade nova não pode exigir
    deploy, e essa promessa vale também para o agendador.

    A contrapartida é que o schedule é lido no start do beat. Editar um horário
    na tela não reagenda o processo em execução. Isso é tolerável porque a task
    não depende do instante exato: ela pergunta ao banco quais janelas venceram
    e ainda não foram processadas (`janelas_despacho_vencidas`) e recupera o que
    tiver ficado para trás. O cron diz "olhe agora"; o banco diz o que fazer.

    Entradas duplicadas são deduplicadas pela chave: dois marketplaces com corte
    às 13:00 geram um disparo só, e a task fecha as duas janelas.
    """
    from nistiprint_shared.database.supabase_db_service import supabase_db

    entradas = {}
    try:
        regras = (
            supabase_db.table('regras_logisticas_integracao')
            .select('horario_corte,horario_coleta,ativo')
            .eq('ativo', True)
            .execute()
            .data
            or []
        )
    except Exception as exc:
        logger.error(
            "Falha ao carregar janelas de despacho para o beat: %s. "
            "O fechamento automático não será agendado; a torre continua correta "
            "porque calcula corte e coleta na leitura.", exc,
        )
        return {}

    horarios = set()
    for regra in regras:
        for campo in ('horario_corte', 'horario_coleta'):
            valor = regra.get(campo)
            if not valor:
                continue
            try:
                hora, minuto = str(valor)[:5].split(':')
                horarios.add((int(hora), int(minuto)))
            except (ValueError, TypeError):
                logger.warning("Horário logístico ilegível ignorado: %r", valor)

    for hora, minuto in sorted(horarios):
        entradas[f'fechar-janela-despacho-{hora:02d}{minuto:02d}'] = {
            'task': 'nistiprint_shared.services.despacho_janela_service.fechar_janelas',
            'schedule': crontab(hour=hora, minute=minuto),
        }

    logger.info(
        "Fechamento de janela agendado em %s horários: %s",
        len(entradas), sorted(f'{h:02d}:{m:02d}' for h, m in horarios),
    )
    return entradas

# Criação do App Celery
celery_app = Celery(
    'nistiprint',
    broker=CELERY_BROKER_URL,
    include=[
        'nistiprint_shared.services.redis_queue_tasks',
        'tasks.eventos_tasks',
        'tasks.consolidation_tasks',
        'tasks.pedidos_fetch_tasks',
        'tasks.token_renewal_tasks',
        'nistiprint_shared.services.bling_status_sync_service',
        'nistiprint_shared.services.ai_personalization_service',
        'nistiprint_shared.services.order_erp_reference_service',
        'nistiprint_shared.services.marketplace_lifecycle_tasks',
        'nistiprint_shared.services.marketplace_payment_reprocess_service',
        'nistiprint_shared.services.ressincronizacao_service',
        'nistiprint_shared.services.despacho_janela_service',
    ]
)
celery_app.conf.update(
    task_ignore_result=True,
    task_store_errors_even_if_ignored=False,
)

# Roteamento e Filas
celery_app.conf.task_queues = {
    'celery': {'exchange': 'celery', 'routing_key': 'celery'},
    'ai_personalization': {'exchange': 'ai', 'routing_key': 'ai.personalization'},
    'bling_status_sync':  {'exchange': 'bling', 'routing_key': 'bling.status'},
}

celery_app.conf.task_routes = {
    'services.ai_personalization.processar_batch': {'queue': 'ai_personalization'},
    'services.ai_personalization.processar_pedido': {'queue': 'ai_personalization'},
    'services.ai_personalization.processar_pendentes': {'queue': 'ai_personalization'},
    'services.ai_personalization.recolher_lotes_parados': {'queue': 'ai_personalization'},
    'services.bling_status_sync.sync_batch': {'queue': 'bling_status_sync'},
}

# Configurações Gerais Otimizadas
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    timezone='America/Sao_Paulo',
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_queue='celery',
    task_default_exchange='celery',
    task_default_routing_key='celery',
    broker_connection_retry_on_startup=True,
    beat_schedule=load_dynamic_schedules()
)

@celery_app.task(bind=True)
def debug_task(self):
    """Task de debug para testar conexão Celery"""
    logger.info(f'Request: {self.request!r}')
    return 'Celery worker is running!'
