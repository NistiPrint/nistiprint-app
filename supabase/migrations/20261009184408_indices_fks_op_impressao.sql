-- Cobertura dos FKs usados nos fluxos de OP e rastreio da impressão.
CREATE INDEX IF NOT EXISTS ix_componentes_op_ordem
    ON public.componentes_ordem_producao(ordem_producao_id);
CREATE INDEX IF NOT EXISTS ix_componentes_op_produto
    ON public.componentes_ordem_producao(componente_id)
    WHERE componente_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_impressao_envios_arte
    ON public.impressao_capas_envios(arte_id)
    WHERE arte_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_impressao_envios_retry_of
    ON public.impressao_capas_envios(retry_of)
    WHERE retry_of IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_ordens_producao_bom_version
    ON public.ordens_producao(bom_version_id)
    WHERE bom_version_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_ordens_producao_produto
    ON public.ordens_producao(produto_id)
    WHERE produto_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_ordens_producao_responsavel
    ON public.ordens_producao(responsavel_id)
    WHERE responsavel_id IS NOT NULL;
