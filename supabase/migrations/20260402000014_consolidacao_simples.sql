-- MIGRATION: Consolidação de Demandas
-- Execute no SQL Editor do Supabase
-- ============================================

-- 1. Drop apenas functions (não dependem de tabelas)
DROP FUNCTION IF EXISTS public.contar_pedidos_novos_apos_edicao(BIGINT);
DROP FUNCTION IF EXISTS public.rascunho_expirado(BIGINT);
DROP FUNCTION IF EXISTS public.get_regras_consolidacao_canal(BIGINT, VARCHAR);
DROP FUNCTION IF EXISTS public.derivar_modalidade_logistica(BIGINT, TEXT);
DROP FUNCTION IF EXISTS public.fn_atualizar_requer_revisao();

-- 2. Drop trigger de demandas_producao (tabela existe)
DROP TRIGGER IF EXISTS trg_atualizar_requer_revisao ON public.demandas_producao;

-- 3. Drop trigger de regras_consolidacao_canal (tabela existe)
DROP TRIGGER IF EXISTS update_regras_consolidacao_canal_updated_at ON public.regras_consolidacao_canal;

-- 4. Drop policies de regras_consolidacao_canal (tabela existe)
DROP POLICY IF EXISTS "authenticated_view_regras_consolidacao" ON public.regras_consolidacao_canal;
DROP POLICY IF EXISTS "authenticated_insert_regras_consolidacao" ON public.regras_consolidacao_canal;
DROP POLICY IF EXISTS "authenticated_update_regras_consolidacao" ON public.regras_consolidacao_canal;
DROP POLICY IF EXISTS "authenticated_delete_regras_consolidacao" ON public.regras_consolidacao_canal;

-- 5. Drop ONLY a tabela com schema antigo
DROP TABLE IF EXISTS public.regras_consolidacao_canal;

-- ============================================
-- 6. CRIAR TABELAS
-- ============================================

CREATE TABLE public.canal_modalidade_mapeamento (
    id BIGSERIAL PRIMARY KEY,
    canal_venda_id BIGINT NOT NULL REFERENCES public.canais_venda(id) ON DELETE CASCADE,
    padrao_servico VARCHAR(255) NOT NULL,
    modalidade VARCHAR(50) NOT NULL CHECK (modalidade IN ('STANDARD', 'EXPRESS', 'FULFILLMENT', 'RETIRADA')),
    prioridade INTEGER DEFAULT 0,
    ativo BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_canal_modalidade_padraes UNIQUE (canal_venda_id, padrao_servico, modalidade)
);

CREATE TABLE public.regras_consolidacao_canal (
    id BIGSERIAL PRIMARY KEY,
    canal_venda_id BIGINT REFERENCES public.canais_venda(id) ON DELETE CASCADE,
    modalidade VARCHAR(50) CHECK (modalidade IN ('STANDARD', 'EXPRESS', 'FULFILLMENT', 'RETIRADA')),
    agrupar_por_produto BOOLEAN DEFAULT true,
    agrupar_por_miolo BOOLEAN DEFAULT true,
    agrupar_por_data_entrega BOOLEAN DEFAULT true,
    janela_agrupamento_horas INTEGER DEFAULT 4,
    comportamento_pos_edicao VARCHAR(30) DEFAULT 'ADICIONAR_COM_SINALIZACAO'
        CHECK (comportamento_pos_edicao IN ('ADICIONAR_COM_SINALIZACAO', 'CRIAR_NOVO_RASCUNHO')),
    comportamento_pos_publicacao VARCHAR(30) DEFAULT 'CRIAR_NOVO_RASCUNHO'
        CHECK (comportamento_pos_publicacao IN ('CRIAR_NOVO_RASCUNHO', 'SUGERIR_FUSAO')),
    ativo BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE (canal_venda_id, modalidade)
);

CREATE TABLE public.pedidos_nao_classificados (
    id BIGSERIAL PRIMARY KEY,
    pedido_id BIGINT NOT NULL REFERENCES public.pedidos(id) ON DELETE CASCADE,
    canal_venda_id BIGINT NOT NULL REFERENCES public.canais_venda(id) ON DELETE CASCADE,
    servico_logistico_recebido VARCHAR(500) NOT NULL,
    tentativas_classificacao INTEGER DEFAULT 1,
    resolvido BOOLEAN DEFAULT false,
    resolvido_em TIMESTAMP WITH TIME ZONE,
    resolvido_por INTEGER REFERENCES public.usuarios(id),
    modalidade_atribuida VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_pedidos_nao_classificados_pedido UNIQUE (pedido_id)
);

-- ============================================
-- 7. ÍNDICES
-- ============================================

CREATE INDEX idx_canal_modalidade_canal ON public.canal_modalidade_mapeamento(canal_venda_id) WHERE ativo = true;
CREATE INDEX idx_canal_modalidade_canal_modalidade ON public.canal_modalidade_mapeamento(canal_venda_id, modalidade) WHERE ativo = true;
CREATE INDEX idx_regras_consolidacao_canal ON public.regras_consolidacao_canal(canal_venda_id) WHERE ativo = true AND canal_venda_id IS NOT NULL;
CREATE INDEX idx_regras_consolidacao_global ON public.regras_consolidacao_canal(modalidade) WHERE ativo = true AND canal_venda_id IS NULL;
CREATE INDEX idx_pedidos_nao_classificados_canal ON public.pedidos_nao_classificados(canal_venda_id) WHERE resolvido = false;
CREATE INDEX idx_pedidos_nao_classificados_pendentes ON public.pedidos_nao_classificados(created_at DESC) WHERE resolvido = false;

-- ============================================
-- 8. COLUNAS EM demandas_producao
-- ============================================

ALTER TABLE public.demandas_producao ADD COLUMN IF NOT EXISTS rascunho_expira_em TIMESTAMP WITH TIME ZONE;
ALTER TABLE public.demandas_producao ADD COLUMN IF NOT EXISTS editado_pelo_usuario BOOLEAN DEFAULT false;
ALTER TABLE public.demandas_producao ADD COLUMN IF NOT EXISTS editado_em TIMESTAMP WITH TIME ZONE;
ALTER TABLE public.demandas_producao ADD COLUMN IF NOT EXISTS editado_por INTEGER REFERENCES public.usuarios(id);
ALTER TABLE public.demandas_producao ADD COLUMN IF NOT EXISTS pedidos_apos_edicao_qtd INTEGER DEFAULT 0;
ALTER TABLE public.demandas_producao ADD COLUMN IF NOT EXISTS requer_revisao BOOLEAN DEFAULT false;
ALTER TABLE public.demandas_producao ADD COLUMN IF NOT EXISTS publicado_em TIMESTAMP WITH TIME ZONE;
ALTER TABLE public.demandas_producao ADD COLUMN IF NOT EXISTS publicado_por INTEGER REFERENCES public.usuarios(id);

-- ============================================
-- 9. COLUNAS EM demandas_pedidos
-- ============================================

ALTER TABLE public.demandas_pedidos ADD COLUMN IF NOT EXISTS adicionado_apos_edicao BOOLEAN DEFAULT false;
ALTER TABLE public.demandas_pedidos ADD COLUMN IF NOT EXISTS adicionado_em TIMESTAMP WITH TIME ZONE DEFAULT NOW();

-- ============================================
-- 10. FUNÇÕES
-- ============================================

CREATE OR REPLACE FUNCTION public.derivar_modalidade_logistica(p_canal_venda_id BIGINT, p_servico_logistico TEXT)
RETURNS VARCHAR(50) AS $$
DECLARE v_modalidade VARCHAR(50); v_padrao TEXT;
BEGIN
    FOR v_modalidade, v_padrao IN
        SELECT cmm.modalidade, cmm.padrao_servico FROM public.canal_modalidade_mapeamento cmm
        WHERE cmm.canal_venda_id = p_canal_venda_id AND cmm.ativo = true
        ORDER BY cmm.prioridade DESC, cmm.created_at DESC
    LOOP IF p_servico_logistico ILIKE v_padrao THEN RETURN v_modalidade; END IF; END LOOP;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE;

CREATE OR REPLACE FUNCTION public.get_regras_consolidacao_canal(p_canal_venda_id BIGINT, p_modalidade VARCHAR(50) DEFAULT NULL)
RETURNS TABLE (canal_venda_id BIGINT, modalidade VARCHAR(50), agrupar_por_produto BOOLEAN, agrupar_por_miolo BOOLEAN, agrupar_por_data_entrega BOOLEAN, janela_agrupamento_horas INTEGER, comportamento_pos_edicao VARCHAR(30), comportamento_pos_publicacao VARCHAR(30)) AS $$
BEGIN
    RETURN QUERY SELECT rc.canal_venda_id, rc.modalidade, rc.agrupar_por_produto, rc.agrupar_por_miolo, rc.agrupar_por_data_entrega, rc.janela_agrupamento_horas, rc.comportamento_pos_edicao, rc.comportamento_pos_publicacao
    FROM public.regras_consolidacao_canal rc WHERE rc.ativo = true AND (rc.canal_venda_id IS NULL OR rc.canal_venda_id = p_canal_venda_id) AND (rc.modalidade IS NULL OR rc.modalidade = p_modalidade)
    ORDER BY CASE WHEN rc.canal_venda_id = p_canal_venda_id THEN 0 ELSE 1 END, CASE WHEN rc.modalidade = p_modalidade THEN 0 ELSE 1 END, rc.created_at DESC LIMIT 1;
END;
$$ LANGUAGE plpgsql STABLE;

CREATE OR REPLACE FUNCTION public.rascunho_expirado(p_demanda_id BIGINT) RETURNS BOOLEAN AS $$
DECLARE v_status VARCHAR(50); v_expira_em TIMESTAMP WITH TIME ZONE;
BEGIN SELECT status, rascunho_expira_em INTO v_status, v_expira_em FROM public.demandas_producao WHERE id = p_demanda_id;
    IF v_status != 'RASCUNHO' THEN RETURN false; END IF; IF v_expira_em IS NULL THEN RETURN false; END IF; RETURN NOW() > v_expira_em;
END;
$$ LANGUAGE plpgsql STABLE;

CREATE OR REPLACE FUNCTION public.contar_pedidos_novos_apos_edicao(p_demanda_id BIGINT) RETURNS INTEGER AS $$
DECLARE v_count INTEGER;
BEGIN SELECT COUNT(*) INTO v_count FROM public.demandas_pedidos dp WHERE dp.demanda_id = p_demanda_id AND dp.adicionado_apos_edicao = true; RETURN v_count; END;
$$ LANGUAGE plpgsql STABLE;

CREATE OR REPLACE FUNCTION public.fn_atualizar_requer_revisao() RETURNS TRIGGER AS $$ BEGIN NEW.requer_revisao = (NEW.pedidos_apos_edicao_qtd > 0); RETURN NEW; END; $$ LANGUAGE plpgsql;

-- ============================================
-- 11. TRIGGERS
-- ============================================

CREATE TRIGGER trg_atualizar_requer_revisao BEFORE INSERT OR UPDATE OF pedidos_apos_edicao_qtd ON public.demandas_producao FOR EACH ROW EXECUTE FUNCTION public.fn_atualizar_requer_revisao();
CREATE TRIGGER update_canal_modalidade_mapeamento_updated_at BEFORE UPDATE ON public.canal_modalidade_mapeamento FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();
CREATE TRIGGER update_regras_consolidacao_canal_updated_at BEFORE UPDATE ON public.regras_consolidacao_canal FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

-- ============================================
-- 12. RLS
-- ============================================

ALTER TABLE public.canal_modalidade_mapeamento ENABLE ROW LEVEL SECURITY;
CREATE POLICY "authenticated_view_canal_modalidade" ON public.canal_modalidade_mapeamento FOR SELECT TO authenticated USING (true);
CREATE POLICY "authenticated_insert_canal_modalidade" ON public.canal_modalidade_mapeamento FOR INSERT TO authenticated WITH CHECK (true);
CREATE POLICY "authenticated_update_canal_modalidade" ON public.canal_modalidade_mapeamento FOR UPDATE TO authenticated USING (true);
CREATE POLICY "authenticated_delete_canal_modalidade" ON public.canal_modalidade_mapeamento FOR DELETE TO authenticated USING (true);

ALTER TABLE public.regras_consolidacao_canal ENABLE ROW LEVEL SECURITY;
CREATE POLICY "authenticated_view_regras_consolidacao" ON public.regras_consolidacao_canal FOR SELECT TO authenticated USING (true);
CREATE POLICY "authenticated_insert_regras_consolidacao" ON public.regras_consolidacao_canal FOR INSERT TO authenticated WITH CHECK (true);
CREATE POLICY "authenticated_update_regras_consolidacao" ON public.regras_consolidacao_canal FOR UPDATE TO authenticated USING (true);
CREATE POLICY "authenticated_delete_regras_consolidacao" ON public.regras_consolidacao_canal FOR DELETE TO authenticated USING (true);

ALTER TABLE public.pedidos_nao_classificados ENABLE ROW LEVEL SECURITY;
CREATE POLICY "authenticated_view_pedidos_nao_classificados" ON public.pedidos_nao_classificados FOR SELECT TO authenticated USING (true);
CREATE POLICY "authenticated_insert_pedidos_nao_classificados" ON public.pedidos_nao_classificados FOR INSERT TO authenticated WITH CHECK (true);
CREATE POLICY "authenticated_update_pedidos_nao_classificados" ON public.pedidos_nao_classificados FOR UPDATE TO authenticated USING (true);
CREATE POLICY "authenticated_delete_pedidos_nao_classificados" ON public.pedidos_nao_classificados FOR DELETE TO authenticated USING (true);

-- ============================================
-- 13. SEED
-- ============================================

INSERT INTO public.regras_consolidacao_canal (canal_venda_id, modalidade, janela_agrupamento_horas) VALUES (NULL, NULL, 4) ON CONFLICT (canal_venda_id, modalidade) DO NOTHING;
