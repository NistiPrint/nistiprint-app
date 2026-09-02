-- Migration para configurar tarefas Celery Beat dinamicamente
-- Created at: 2026-04-12
-- Description: Configuração inicial de tarefas periódicas gerenciáveis via UI

-- Inserir configuração de tarefas agendadas
INSERT INTO configuracoes_aplicacao (nome, valor, descricao, categoria, protegido, tipo_valor) 
VALUES (
    'celery_task_schedules',
    '{
        "task_schedules": {
            "sync-firestore-tokens": {
                "enabled": true,
                "schedule_seconds": 1800,
                "description": "Sincroniza tokens Bling do Firestore para Supabase",
                "task_name": "nistiprint_shared.services.redis_queue_tasks.sync_firestore_tokens"
            },
            "consumir-fila-bling": {
                "enabled": true,
                "schedule_seconds": 30,
                "description": "Consome fila de webhooks do Bling no Redis",
                "task_name": "nistiprint_shared.services.redis_queue_tasks.consumir_fila_bling"
            },
            "processar-eventos-producao-periodic": {
                "enabled": true,
                "schedule_seconds": 10,
                "description": "Processa eventos de produção (Event Sourcing) e fila de estoque",
                "task_name": "tasks.eventos_tasks.process_eventos_producao"
            }
        }
    }'::jsonb,
    'Configuração de tarefas periódicas do Celery Beat (habilitar/desabilitar e frequência)',
    'TASK_SCHEDULING',
    true,
    'json'
) ON CONFLICT (nome) DO NOTHING;
