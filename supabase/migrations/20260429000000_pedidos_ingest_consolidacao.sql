-- =============================================================
-- MIGRATION: CONSOLIDAÇÃO DO INGEST DE PEDIDOS
-- Data: 2026-04-29
-- Escopo: Garantir constraints para upsert idempotente e
--         adicionar colunas faltantes na tabela pedidos
-- =============================================================

-- 1. UNIQUE em pedidos_bling.bling_id (sem isso, on_conflict='bling_id'
--    do worker quebra com 42P10 - "no unique or exclusion constraint
--    matching the ON CONFLICT specification").
ALTER TABLE public.pedidos_bling
    DROP CONSTRAINT IF EXISTS pedidos_bling_numero_pedido_key;
ALTER TABLE public.pedidos_bling
    DROP CONSTRAINT IF EXISTS pedidos_bling_bling_id_key;
ALTER TABLE public.pedidos_bling
    ADD CONSTRAINT pedidos_bling_bling_id_key UNIQUE (bling_id);

-- numero_pedido deixa de ser UNIQUE global porque o mesmo `numero` pode
-- aparecer em instâncias Bling diferentes. Se for necessário garantir,
-- criar UNIQUE (bling_integration_id, numero_pedido) em fase posterior
-- após backfill.

-- 2. Garantir colunas em pedidos que a tela já consome mas o ingest
--    novo ainda não preenche. (Várias já existem por migrations anteriores;
--    repetimos com IF NOT EXISTS por idempotência.)
ALTER TABLE public.pedidos
    ADD COLUMN IF NOT EXISTS cliente_documento  varchar(20),
    ADD COLUMN IF NOT EXISTS cliente_telefone   varchar(50),
    ADD COLUMN IF NOT EXISTS cliente_email      varchar(255),
    ADD COLUMN IF NOT EXISTS data_limite_envio  timestamptz,
    ADD COLUMN IF NOT EXISTS servico_logistico  varchar(255),
    ADD COLUMN IF NOT EXISTS buyer_username     varchar(255),
    ADD COLUMN IF NOT EXISTS shipping_carrier   varchar(255),
    ADD COLUMN IF NOT EXISTS message_to_seller  text,
    ADD COLUMN IF NOT EXISTS status_original    varchar(50);

-- 3. (Opcional) Confirmar UNIQUE em pedidos.codigo_pedido_externo (já existe).
--    Não recria.

-- 4. Tabela de auditoria pedido_ingest_log (já criada na migration
--    'arquitetura_definitiva'; só garantir que existe)
CREATE TABLE IF NOT EXISTS pedido_ingest_log (
    id BIGSERIAL PRIMARY KEY,
    pedido_id BIGINT,
    bling_id  BIGINT,
    marketplace_integration_id INT,
    is_flex BOOLEAN,
    flex_motivo TEXT,
    matched_rule_id INT,
    raw_decision JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Índice para consultas de auditoria
CREATE INDEX IF NOT EXISTS idx_pedido_ingest_log_bling_id ON pedido_ingest_log(bling_id);
CREATE INDEX IF NOT EXISTS idx_pedido_ingest_log_pedido_id ON pedido_ingest_log(pedido_id);
CREATE INDEX IF NOT EXISTS idx_pedido_ingest_log_created_at ON pedido_ingest_log(created_at);
