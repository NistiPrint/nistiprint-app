-- Migration to create system task execution logs table
-- Created at: 2026-03-19
-- Description: Unifies tracking for system tasks like token refresh and syncs

CREATE TABLE IF NOT EXISTS public.task_execution_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_name VARCHAR(100) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'PENDING',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    error_message TEXT
);

-- Index for faster filtering by status and date
CREATE INDEX IF NOT EXISTS idx_task_execution_logs_status ON public.task_execution_logs(status);
CREATE INDEX IF NOT EXISTS idx_task_execution_logs_created_at ON public.task_execution_logs(created_at DESC);

-- Grant permissions (adjust based on your roles)
GRANT ALL ON public.task_execution_logs TO service_role;
GRANT SELECT, INSERT, UPDATE ON public.task_execution_logs TO authenticated;
GRANT SELECT, INSERT, UPDATE ON public.task_execution_logs TO anon;
