-- Conta Shopee configuration is isolated while retaining the effective legacy defaults.
CREATE TABLE IF NOT EXISTS public.shopee_personalization_ai_config (
  marketplace_integration_id integer PRIMARY KEY
    REFERENCES public.installed_integrations(id) ON DELETE CASCADE,
  prompt_template text,
  provider text NOT NULL DEFAULT 'gemini' CHECK (provider IN ('gemini','openrouter')),
  model_name text NOT NULL DEFAULT 'gemini-2.5-flash',
  fallback_provider text CHECK (fallback_provider IS NULL OR fallback_provider IN ('gemini','openrouter')),
  timeout_seconds integer NOT NULL DEFAULT 60 CHECK (timeout_seconds BETWEEN 1 AND 600),
  max_processing integer NOT NULL DEFAULT 50 CHECK (max_processing BETWEEN 1 AND 500),
  updated_by bigint,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.shopee_personalization_ai_config ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.shopee_personalization_ai_config FROM PUBLIC, anon, authenticated;
GRANT ALL ON public.shopee_personalization_ai_config TO service_role;

INSERT INTO public.shopee_personalization_ai_config
  (marketplace_integration_id, prompt_template, provider, model_name, fallback_provider,
   timeout_seconds, max_processing)
SELECT ii.id,
       COALESCE((SELECT COALESCE(c.valor->>'text', c.valor #>> '{}') FROM public.configuracoes_aplicacao c WHERE c.nome='prompt_template' LIMIT 1), ''),
       COALESCE((SELECT c.valor #>> '{}' FROM public.configuracoes_aplicacao c WHERE c.nome='ia_provider' LIMIT 1), 'gemini'),
       COALESCE((SELECT c.valor #>> '{}' FROM public.configuracoes_aplicacao c WHERE c.nome IN ('ia_model','model_name') ORDER BY CASE c.nome WHEN 'ia_model' THEN 0 ELSE 1 END LIMIT 1), 'gemini-2.5-flash'),
       NULLIF(COALESCE((SELECT c.valor #>> '{}' FROM public.configuracoes_aplicacao c WHERE c.nome='ia_fallback_provider' LIMIT 1), ''), ''),
       COALESCE((SELECT NULLIF(c.valor #>> '{}','')::integer FROM public.configuracoes_aplicacao c WHERE c.nome='ia_timeout_seconds' LIMIT 1), 60),
       COALESCE((SELECT NULLIF(c.valor #>> '{}','')::integer FROM public.configuracoes_aplicacao c WHERE c.nome='max_processing' LIMIT 1), 50)
FROM public.installed_integrations ii
WHERE lower(ii.module_id)='shopee'
ON CONFLICT (marketplace_integration_id) DO NOTHING;

-- Daily extraction is the only user-facing pause switch for Mercado Livre.
ALTER TABLE public.mercadolivre_personalization_config
  ADD COLUMN IF NOT EXISTS schedule_enabled boolean NOT NULL DEFAULT true;
ALTER TABLE public.mercadolivre_personalization_config
  ALTER COLUMN enabled SET DEFAULT true,
  ALTER COLUMN capture_enabled SET DEFAULT true,
  ALTER COLUMN extraction_enabled SET DEFAULT true;

-- Structured metadata keeps existing log readers compatible while providing
-- queue, account and execution context to the task center.
ALTER TABLE public.task_execution_logs
  ADD COLUMN IF NOT EXISTS marketplace_integration_id integer REFERENCES public.installed_integrations(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS celery_task_id text,
  ADD COLUMN IF NOT EXISTS queue_name text,
  ADD COLUMN IF NOT EXISTS execution_origin text,
  ADD COLUMN IF NOT EXISTS progress_at timestamptz,
  ADD COLUMN IF NOT EXISTS duration_ms bigint;
CREATE INDEX IF NOT EXISTS ix_task_execution_logs_scope_created
  ON public.task_execution_logs(marketplace_integration_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_task_execution_logs_queue_status
  ON public.task_execution_logs(queue_name, status, created_at DESC);

COMMENT ON COLUMN public.mercadolivre_personalization_config.schedule_enabled IS
  'The daily extraction job can be paused here; message capture, reconciliation and manual extraction remain active.';
