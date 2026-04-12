-- Migration to enhance task_execution_logs table for better monitoring and reprocessing
-- Created at: 2026-04-11
-- Description: Adds columns for task type, correlation tracking, and retry management

-- Add new columns for enhanced task tracking
ALTER TABLE public.task_execution_logs 
ADD COLUMN IF NOT EXISTS task_type VARCHAR(100),
ADD COLUMN IF NOT EXISTS correlation_id VARCHAR(100),
ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS last_retry_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ;

-- Add index on correlation_id for faster lookups
CREATE INDEX IF NOT EXISTS idx_task_execution_logs_correlation_id ON public.task_execution_logs(correlation_id);

-- Add index on task_type for filtering
CREATE INDEX IF NOT EXISTS idx_task_execution_logs_task_type ON public.task_execution_logs(task_type);

-- Add index on status for filtering
CREATE INDEX IF NOT EXISTS idx_task_execution_logs_status ON public.task_execution_logs(status);
