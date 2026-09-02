-- Migration: Registrar tarefa de consolidação em lote no Celery Beat
-- Created at: 2026-05-15
-- Description: Adiciona a task de consolidação periódica de pedidos pendentes

-- Atualizar a configuração de tarefas agendadas para incluir a nova task
-- Tratamento especial: garante que 'valor' seja um objeto jsonb (caso esteja como string)
UPDATE configuracoes_aplicacao
SET valor = jsonb_set(
    (CASE 
        WHEN jsonb_typeof(valor) = 'string' THEN (valor #>> '{}')::jsonb 
        ELSE valor 
    END),
    '{task_schedules, consolidar-pedidos-pendentes}',
    '{
        "enabled": false,
        "schedule_seconds": 300,
        "description": "Consolida pedidos pendentes em demandas de produção (em lote a cada 5 min)",
        "task_name": "tasks.auto_consolidation_tasks.consolidar_pedidos_pendentes"
    }'::jsonb,
    true -- true para criar a chave se não existir
)
WHERE nome = 'celery_task_schedules';

-- Comentário para auditoria
COMMENT ON COLUMN configuracoes_aplicacao.valor IS 'Configurações da aplicação. task_schedules gerencia o Celery Beat dinâmico.';
