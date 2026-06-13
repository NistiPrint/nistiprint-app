-- Register marketplace webhook workers in the dynamic Celery schedule config.

UPDATE public.configuracoes_aplicacao
SET valor = jsonb_set(
    jsonb_set(
        CASE
            WHEN jsonb_typeof(valor) = 'string' THEN (valor #>> '{}')::jsonb
            ELSE valor
        END,
        '{task_schedules,consumir-fila-shopee}',
        '{
            "enabled": true,
            "schedule_seconds": 30,
            "description": "Consome fila de webhooks da Shopee no Redis",
            "task_name": "nistiprint_shared.services.redis_queue_tasks.consumir_fila_shopee"
        }'::jsonb,
        true
    ),
    '{task_schedules,consumir-fila-mercadolivre}',
    '{
        "enabled": true,
        "schedule_seconds": 30,
        "description": "Consome fila de webhooks do Mercado Livre no Redis",
        "task_name": "nistiprint_shared.services.redis_queue_tasks.consumir_fila_mercadolivre"
    }'::jsonb,
    true
)
WHERE nome = 'celery_task_schedules';
