-- Adiciona/atualiza a tarefa de renovação agendada de tokens Shopee.
-- Regra: executar a cada 2 horas; a task renova tokens que expiram em menos de 1 hora.

UPDATE configuracoes_aplicacao
SET valor = jsonb_set(
    COALESCE(valor, '{}'::jsonb),
    '{task_schedules,renew-shopee-tokens}',
    '{
        "enabled": true,
        "schedule_seconds": 7200,
        "description": "Renova automaticamente tokens Shopee que expiram em menos de 1 hora",
        "task_name": "tasks.token_renewal_tasks.renew_shopee_tokens"
    }'::jsonb,
    true
)
WHERE nome = 'celery_task_schedules';
