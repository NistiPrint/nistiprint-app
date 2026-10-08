-- Persist per-user background operation state and notification history.
ALTER TABLE public.execucoes_ai_batch
    ADD COLUMN IF NOT EXISTS iniciado_por text;

CREATE TABLE IF NOT EXISTS public.operacoes_assincronas (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id integer NOT NULL REFERENCES public.usuarios(id) ON DELETE CASCADE,
    categoria text NOT NULL,
    titulo text NOT NULL,
    mensagem text NOT NULL DEFAULT '',
    status text NOT NULL CHECK (status IN ('AGUARDANDO', 'EM_ANDAMENTO', 'CONCLUIDO', 'ERRO')),
    referencia_tipo text,
    referencia_id text,
    rota_destino text,
    etapa text,
    progresso_atual integer CHECK (progresso_atual IS NULL OR progresso_atual >= 0),
    progresso_total integer CHECK (progresso_total IS NULL OR progresso_total >= 0),
    erro_resumo text,
    origem_tipo text,
    origem_id text,
    dados_adicionais jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    finalizado_em timestamptz
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_operacoes_assincronas_origem
    ON public.operacoes_assincronas(origem_tipo, origem_id)
    WHERE origem_tipo IS NOT NULL AND origem_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_operacoes_assincronas_usuario_atualizacao
    ON public.operacoes_assincronas(owner_user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS ix_operacoes_assincronas_usuario_status
    ON public.operacoes_assincronas(owner_user_id, status, updated_at DESC);

ALTER TABLE public.notificacoes
    ADD COLUMN IF NOT EXISTS owner_user_id integer REFERENCES public.usuarios(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS operacao_id uuid REFERENCES public.operacoes_assincronas(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS event_type text,
    ADD COLUMN IF NOT EXISTS read_at timestamptz;

-- Preserve personal notifications created before owner_user_id was introduced.
UPDATE public.notificacoes
SET owner_user_id = CASE
    WHEN coalesce(destinatarios->>'user_id', '') ~ '^[0-9]+$'
    THEN (destinatarios->>'user_id')::integer
    ELSE NULL
END
WHERE owner_user_id IS NULL
  AND jsonb_typeof(destinatarios) = 'object'
  AND coalesce(destinatarios->>'user_id', '') ~ '^[0-9]+$';

CREATE INDEX IF NOT EXISTS ix_notificacoes_usuario_created
    ON public.notificacoes(owner_user_id, created_at DESC)
    WHERE owner_user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_notificacoes_operacao
    ON public.notificacoes(operacao_id)
    WHERE operacao_id IS NOT NULL;

ALTER TABLE public.operacoes_assincronas ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notificacoes ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.operacoes_assincronas FROM PUBLIC, anon, authenticated;
REVOKE ALL ON public.notificacoes FROM PUBLIC, anon, authenticated;
GRANT ALL ON public.operacoes_assincronas TO service_role;
GRANT ALL ON public.notificacoes TO service_role;

COMMENT ON TABLE public.operacoes_assincronas IS
    'Visão unificada e durável dos processos assíncronos iniciados por usuários.';
COMMENT ON COLUMN public.operacoes_assincronas.origem_tipo IS
    'Tipo do registro de domínio que continua sendo a fonte de verdade do processamento.';
COMMENT ON COLUMN public.operacoes_assincronas.origem_id IS
    'Identificador do registro de domínio associado a esta operação.';
