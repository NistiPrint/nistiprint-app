-- Índices para os relacionamentos adicionados ao núcleo de integridade.
CREATE INDEX IF NOT EXISTS ix_demanda_alocacoes_deposito
    ON public.demanda_alocacoes_estoque(deposito_id);
CREATE INDEX IF NOT EXISTS ix_demanda_alocacoes_movimento
    ON public.demanda_alocacoes_estoque(movimento_id)
    WHERE movimento_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_eventos_producao_demanda
    ON public.eventos_producao_v2(demanda_id)
    WHERE demanda_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_eventos_producao_usuario
    ON public.eventos_producao_v2(usuario_id)
    WHERE usuario_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_snapshots_reconciliacao_demanda
    ON public.snapshots_reconciliacao(demanda_id)
    WHERE demanda_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_snapshots_reconciliacao_bom_version
    ON public.snapshots_reconciliacao(bom_version_id)
    WHERE bom_version_id IS NOT NULL;
