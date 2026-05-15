-- =============================================================
-- MIGRATION: Logistica de Coleta por Integracao (canonica)
-- Data: 2026-05-15
-- =============================================================

CREATE TABLE IF NOT EXISTS public.regras_logisticas_integracao (
    id BIGSERIAL PRIMARY KEY,
    marketplace_integration_id INTEGER NOT NULL
        REFERENCES public.installed_integrations(id) ON DELETE CASCADE,
    modalidade VARCHAR(50) NOT NULL,
    tipo_envio VARCHAR(50) NOT NULL CHECK (tipo_envio IN ('COLETA_LOCAL', 'PONTO_COLETA')),
    horario_limite TIME NOT NULL,
    ponto_coleta_id INTEGER REFERENCES public.pontos_coleta(id) ON DELETE SET NULL,
    dias_semana SMALLINT[] DEFAULT ARRAY[1,2,3,4,5,6,7],
    prioridade_uso INTEGER DEFAULT 1,
    ativo BOOLEAN DEFAULT true,
    descricao TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_regras_logisticas_integracao_lookup
ON public.regras_logisticas_integracao (marketplace_integration_id, modalidade, ativo, prioridade_uso DESC);

CREATE INDEX IF NOT EXISTS idx_regras_logisticas_integracao_ponto
ON public.regras_logisticas_integracao (ponto_coleta_id)
WHERE ponto_coleta_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_regras_logisticas_integracao_unique
ON public.regras_logisticas_integracao (
    marketplace_integration_id,
    modalidade,
    tipo_envio,
    horario_limite,
    COALESCE(ponto_coleta_id, -1)
)
WHERE ativo = true;

CREATE OR REPLACE TRIGGER update_regras_logisticas_integracao_updated_at
BEFORE UPDATE ON public.regras_logisticas_integracao
FOR EACH ROW
EXECUTE FUNCTION public.update_updated_at_column();

COMMENT ON TABLE public.regras_logisticas_integracao IS
'Regras logisticas canonicas por instancia marketplace instalada.';

COMMENT ON COLUMN public.regras_logisticas_integracao.dias_semana IS
'Dias validos para a regra (1=segunda ... 7=domingo).';

ALTER TABLE public.regras_logisticas_integracao ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "authenticated_select_regras_logisticas_integracao" ON public.regras_logisticas_integracao;
CREATE POLICY "authenticated_select_regras_logisticas_integracao"
ON public.regras_logisticas_integracao
FOR SELECT TO authenticated
USING (true);

DROP POLICY IF EXISTS "authenticated_insert_regras_logisticas_integracao" ON public.regras_logisticas_integracao;
CREATE POLICY "authenticated_insert_regras_logisticas_integracao"
ON public.regras_logisticas_integracao
FOR INSERT TO authenticated
WITH CHECK (true);

DROP POLICY IF EXISTS "authenticated_update_regras_logisticas_integracao" ON public.regras_logisticas_integracao;
CREATE POLICY "authenticated_update_regras_logisticas_integracao"
ON public.regras_logisticas_integracao
FOR UPDATE TO authenticated
USING (true);

DROP POLICY IF EXISTS "authenticated_delete_regras_logisticas_integracao" ON public.regras_logisticas_integracao;
CREATE POLICY "authenticated_delete_regras_logisticas_integracao"
ON public.regras_logisticas_integracao
FOR DELETE TO authenticated
USING (true);

GRANT ALL ON TABLE public.regras_logisticas_integracao TO anon;
GRANT ALL ON TABLE public.regras_logisticas_integracao TO authenticated;
GRANT ALL ON TABLE public.regras_logisticas_integracao TO service_role;
GRANT ALL ON SEQUENCE public.regras_logisticas_integracao_id_seq TO anon;
GRANT ALL ON SEQUENCE public.regras_logisticas_integracao_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.regras_logisticas_integracao_id_seq TO service_role;

-- Backfill inicial a partir do legado por canal -> marketplace_integration_id.
INSERT INTO public.regras_logisticas_integracao (
    marketplace_integration_id,
    modalidade,
    tipo_envio,
    horario_limite,
    ponto_coleta_id,
    dias_semana,
    prioridade_uso,
    ativo,
    descricao
)
SELECT
    cc.marketplace_integration_id,
    rlc.modalidade,
    rlc.tipo_envio,
    rlc.horario_limite,
    rlc.ponto_coleta_id,
    ARRAY[1,2,3,4,5,6,7]::smallint[],
    COALESCE(rlc.prioridade_uso, 1),
    true,
    'Backfill automatico de regras_logisticas_canal'
FROM public.regras_logisticas_canal rlc
JOIN public.channel_connections cc
    ON cc.channel_id = rlc.canal_venda_id
   AND cc.is_active = true
   AND cc.marketplace_integration_id IS NOT NULL
ON CONFLICT DO NOTHING;

