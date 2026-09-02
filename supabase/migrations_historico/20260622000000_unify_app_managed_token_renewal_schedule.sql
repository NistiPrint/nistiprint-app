-- Unifica a renovacao automatica de credenciais app_managed
-- em uma unica task periodica e desativa o schedule legado de Shopee.

UPDATE configuracoes_aplicacao
SET valor = jsonb_set(
    jsonb_set(
        COALESCE(valor, '{}'::jsonb),
        '{task_schedules,renew-app-managed-credentials}',
        '{
            "enabled": true,
            "schedule_seconds": 7200,
            "description": "Renova automaticamente credenciais app_managed que expiraram, estao perto de expirar ou estao degradadas por erro pendente",
            "task_name": "tasks.token_renewal_tasks.renew_app_managed_credentials"
        }'::jsonb,
        true
    ),
    '{task_schedules,renew-shopee-tokens,enabled}',
    'false'::jsonb,
    true
)
WHERE nome = 'celery_task_schedules';
