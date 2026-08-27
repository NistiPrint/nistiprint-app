-- =====================================================================
-- ROLLBACK da Fase D0 — Sprint 1 (Plano de Otimização)
-- Aplicado em: 2026-08-25
-- Projeto: cfknrplrqvyirjxovuvi (nistiprint-supabase)
--
-- Este arquivo recria EXATAMENTE tudo que a migração
-- 'd0_higiene_indices_triggers' removeu. Executar por inteiro
-- restaura o estado anterior do schema.
--
-- Nada aqui altera dados. Índices e gatilhos de updated_at não
-- carregam informação — apenas estrutura de acesso.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. Índices duplicados (7 pares) — o par sobrevivente está indicado
-- ---------------------------------------------------------------------
-- par com idx_demandas_classificacao
CREATE INDEX idx_demandas_producao_classificacao_cliente ON public.demandas_producao USING btree (classificacao_cliente);
-- par com idx_demandas_modalidade
CREATE INDEX idx_demandas_producao_modalidade_logistica ON public.demandas_producao USING btree (modalidade_logistica);
-- par com idx_ai_logs_order_sn
CREATE INDEX idx_logs_ia_order_sn ON public.logs_execucao_ia USING btree (order_sn);
-- par com ix_pil_bling_id
CREATE INDEX idx_pedido_ingest_log_bling_id ON public.pedido_ingest_log USING btree (bling_id);
-- par com ix_pil_pedido_id
CREATE INDEX idx_pedido_ingest_log_pedido_id ON public.pedido_ingest_log USING btree (pedido_id);
-- par com idx_personalizacoes_shopee_order_sn
CREATE INDEX idx_personalizacoes_shopee_sn ON public.personalizacoes_pedido USING btree (shopee_order_sn);
-- par com a constraint UNIQUE preferencias_ux_usuario_user_id_key
CREATE UNIQUE INDEX idx_preferencias_ux_user_id ON public.preferencias_ux_usuario USING btree (user_id);

-- ---------------------------------------------------------------------
-- 2. Índices sem uso registrado (13) — zero scans desde 2025-12-08
-- ---------------------------------------------------------------------
CREATE INDEX idx_pedido_snapshots_platform_fields_gin ON public.pedido_snapshots USING gin (platform_fields);           -- 33 MB
CREATE INDEX ix_webhook_events_source_status_attempt ON public.webhook_events USING btree (source, last_status, last_attempt_at DESC);
CREATE INDEX idx_entity_correlation_correlation ON public.entity_correlation_mapping USING btree (correlation_id);
CREATE INDEX idx_pedido_snapshots_identity_gin ON public.pedido_snapshots USING gin (identity);
CREATE INDEX ix_pil_status ON public.pedido_ingest_log USING btree (status);
CREATE INDEX ix_webhook_event_attempts_correlation_id ON public.webhook_event_attempts USING btree (correlation_id);
CREATE INDEX ix_webhook_events_correlation_id ON public.webhook_events USING btree (correlation_id);
CREATE INDEX idx_pedidos_purchase_order ON public.pedidos USING btree (effective_purchase_date(data_compra_marketplace, data_venda, created_at) DESC, id DESC);
CREATE INDEX idx_pedidos_data_pagamento_marketplace ON public.pedidos USING btree (data_pagamento_marketplace);
CREATE INDEX idx_pedidos_erp_store ON public.pedidos USING btree (erp_integration_id, erp_store_id);
CREATE INDEX ix_pedidos_shopee_buyer_user ON public.pedidos_shopee USING btree (buyer_username);
CREATE INDEX ix_webhook_event_attempts_status ON public.webhook_event_attempts USING btree (status);
CREATE INDEX idx_pedidos_channel_snapshot_flex ON public.pedidos USING btree (((channel_snapshot ->> 'flex'::text))) WHERE ((channel_snapshot IS NOT NULL) AND (channel_snapshot <> '{}'::jsonb));

-- ---------------------------------------------------------------------
-- 3. Gatilhos updated_at duplicados (3)
--    Mantido em cada tabela: set_updated_at -> handle_updated_at(),
--    que também cobre a coluna legada atualizado_em.
-- ---------------------------------------------------------------------
CREATE TRIGGER update_produtos_updated_at BEFORE UPDATE ON public.produtos FOR EACH ROW EXECUTE FUNCTION update_produtos_updated_at_column();
CREATE TRIGGER update_demandas_producao_updated_at BEFORE UPDATE ON public.demandas_producao FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_configuracoes_aplicacao_updated_at BEFORE UPDATE ON public.configuracoes_aplicacao FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- =====================================================================
-- NÃO REMOVIDOS — mantidos deliberadamente para reavaliação na fase D4,
-- apesar de constarem como ociosos. São índices parciais pequenos que
-- codificam um predicado operacional; o ganho não justifica o risco.
--   - ix_pedidos_erp_integration_store  (528 kB, cobre FK erp_integration_id)
--   - ix_webhook_events_backlog         (416 kB, predicado do processador de fila)
--   - ix_pedidos_modalidade_nao_classificada (248 kB, predicado de pendências)
-- =====================================================================
