-- =============================================================
-- MIGRATION: ARQUITETURA DEFINITIVA
-- Data: 2026-04-24
-- Escopo: Refatoração de canais de venda para installed_integrations,
--          classificação Flex confiável, sync de status em lote,
--          IA de personalização em lote
-- =============================================================

-- =============================================================
-- 1. PEDIDOS: substituir canal_venda_id por marketplace_integration_id
-- =============================================================
ALTER TABLE pedidos
    ADD COLUMN IF NOT EXISTS marketplace_integration_id INT
        REFERENCES installed_integrations(id),
    ADD COLUMN IF NOT EXISTS bling_integration_id INT
        REFERENCES installed_integrations(id),
    ADD COLUMN IF NOT EXISTS pedido_bling_id BIGINT
        REFERENCES pedidos_bling(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS pedido_shopee_id BIGINT
        REFERENCES pedidos_shopee(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS ix_pedidos_marketplace ON pedidos(marketplace_integration_id);
CREATE INDEX IF NOT EXISTS ix_pedidos_bling_inst   ON pedidos(bling_integration_id);

-- =============================================================
-- 2. INSTALLED_INTEGRATIONS: índice por bling_loja_id (marketplace)
-- =============================================================
CREATE INDEX IF NOT EXISTS ix_install_int_bling_loja_id
    ON installed_integrations ((config->>'bling_loja_id'))
    WHERE is_active = true;

CREATE INDEX IF NOT EXISTS ix_install_int_cnpj
    ON installed_integrations ((config->>'cnpj'))
    WHERE is_active = true;

-- =============================================================
-- 3. REGRAS LOGÍSTICAS: passar a apontar para marketplace
-- =============================================================
ALTER TABLE regras_logisticas_canal
    ADD COLUMN IF NOT EXISTS marketplace_integration_id INT
        REFERENCES installed_integrations(id);

-- Após backfill (item 6 abaixo), tornar a nova coluna NOT NULL e dropar a antiga:
-- ALTER TABLE regras_logisticas_canal DROP COLUMN canal_venda_id;

-- =============================================================
-- 4. FLEX RULES: ajustar escopo para marketplace_integration_id
-- =============================================================
ALTER TABLE flex_classification_rules
    ADD COLUMN IF NOT EXISTS marketplace_integration_id INT
        REFERENCES installed_integrations(id);

CREATE INDEX IF NOT EXISTS ix_flex_rules_marketplace
    ON flex_classification_rules(marketplace_integration_id, ativo);

-- =============================================================
-- 5. PEDIDOS_BLING / PEDIDOS_SHOPEE: garantir colunas
-- =============================================================
ALTER TABLE pedidos_bling
    ADD COLUMN IF NOT EXISTS situacao_id          INT,
    ADD COLUMN IF NOT EXISTS situacao_valor       INT,
    ADD COLUMN IF NOT EXISTS contato              JSONB,
    ADD COLUMN IF NOT EXISTS itens                JSONB,
    ADD COLUMN IF NOT EXISTS transporte           JSONB,
    ADD COLUMN IF NOT EXISTS intermediador_cnpj   TEXT,
    ADD COLUMN IF NOT EXISTS loja_id              BIGINT,
    ADD COLUMN IF NOT EXISTS raw_payload          JSONB,
    ADD COLUMN IF NOT EXISTS bling_integration_id INT
        REFERENCES installed_integrations(id);

CREATE INDEX IF NOT EXISTS ix_pedidos_bling_loja_id ON pedidos_bling(loja_id);
CREATE INDEX IF NOT EXISTS ix_pedidos_bling_inst    ON pedidos_bling(bling_integration_id);

ALTER TABLE pedidos_shopee
    ADD COLUMN IF NOT EXISTS shop_id             BIGINT,
    ADD COLUMN IF NOT EXISTS order_sn            TEXT,
    ADD COLUMN IF NOT EXISTS order_status        TEXT,
    ADD COLUMN IF NOT EXISTS buyer_username      TEXT,
    ADD COLUMN IF NOT EXISTS buyer_user_id       BIGINT,
    ADD COLUMN IF NOT EXISTS fulfillment_flag    TEXT,
    ADD COLUMN IF NOT EXISTS shipping_carrier    TEXT,
    ADD COLUMN IF NOT EXISTS package_list        JSONB,
    ADD COLUMN IF NOT EXISTS item_list           JSONB,
    ADD COLUMN IF NOT EXISTS recipient_address   JSONB,
    ADD COLUMN IF NOT EXISTS pay_time            TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS raw_payload         JSONB,
    ADD COLUMN IF NOT EXISTS enriched_at         TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS marketplace_integration_id INT
        REFERENCES installed_integrations(id);

CREATE INDEX IF NOT EXISTS ix_pedidos_shopee_shop_id     ON pedidos_shopee(shop_id);
CREATE INDEX IF NOT EXISTS ix_pedidos_shopee_order_sn    ON pedidos_shopee(order_sn);
CREATE INDEX IF NOT EXISTS ix_pedidos_shopee_buyer_user  ON pedidos_shopee(buyer_username);

-- =============================================================
-- 6. BACKFILL canais_venda → installed_integrations (marketplace)
-- =============================================================
-- Para cada linha em canais_venda, criar (se não existir) installed_integration
-- de tipo 'marketplace' com config preenchido a partir das colunas.
-- Executar em script Python (ver seção 5.4) por requerer lookup de modules e idempotência.

-- =============================================================
-- 7. REMOVER TRIGGERS LEGADOS DE FLEX
-- =============================================================
DROP TRIGGER  IF EXISTS trg_calcular_is_flex ON pedidos;
DROP FUNCTION IF EXISTS calcular_is_flex();

-- O trigger fn_snapshot_channel_on_insert deve ser reescrito SEM
-- a linha "NEW.is_flex := (NEW.channel_snapshot->>'flex')::boolean;".
-- Recriar a função preservando o restante do snapshot.

-- =============================================================
-- 8. SEED INICIAL DE INTEGRATION MODULES (marketplace)
-- =============================================================
-- Criar modules para marketplaces se não existirem
-- Usando INSERT com id explícito para evitar erro de not-null
INSERT INTO integration_modules (id, slug, name, tipo, is_active)
VALUES
    (100, 'shopee', 'Shopee', 'marketplace', true),
    (101, 'amazon', 'Amazon', 'marketplace', true),
    (102, 'mercadolivre', 'Mercado Livre', 'marketplace', true),
    (103, 'shein', 'Shein', 'marketplace', true)
ON CONFLICT DO NOTHING;

-- =============================================================
-- 9. SEED INICIAL DE FLEX RULES (regra global Shopee)
-- =============================================================
-- Apenas "entrega rápida" e variações são FLEX. Xpress NUNCA.
-- Regra global (sem marketplace_integration_id, sem canal_venda_id):

-- Drop existing check constraint to allow global rules (both columns null)
ALTER TABLE flex_classification_rules DROP CONSTRAINT IF EXISTS flex_classification_rules_check;

INSERT INTO flex_classification_rules
    (campo, operador, padrao, is_flex, modalidade, prioridade)
VALUES
    ('shipping_carrier',   'ILIKE_NORMALIZED', 'entrega rapida', true, 'FLEX',     10),
    ('servico_logistico',  'ILIKE_NORMALIZED', 'entrega rapida', true, 'FLEX',     10),
    ('shipping_carrier',   'ILIKE',            '%',              false, 'STANDARD', 9999)
ON CONFLICT DO NOTHING;

-- Create new check constraint: allow global rules (both null) OR scoped rules (at least one non-null)
ALTER TABLE flex_classification_rules
    ADD CONSTRAINT flex_classification_rules_check
    CHECK (
        (canal_venda_id IS NULL AND marketplace_integration_id IS NULL) OR
        (canal_venda_id IS NOT NULL OR marketplace_integration_id IS NOT NULL)
    );

-- =============================================================
-- 9. RPC PARA RESOLVER INSTÂNCIAS NO WORKER
-- =============================================================

-- 9.1 Resolve instância Bling pelo CNPJ do intermediador (ou do payload)
CREATE OR REPLACE FUNCTION find_bling_integration_by_cnpj(p_cnpj TEXT)
RETURNS SETOF installed_integrations AS $$
    SELECT ii.*
      FROM installed_integrations ii
      JOIN integration_modules im ON im.id = ii.module_id
     WHERE im.tipo = 'aggregator'
       AND im.slug = 'bling'
       AND ii.is_active = true
       AND (ii.config->>'cnpj' = p_cnpj
            OR position(ii.config->>'cnpj' in p_cnpj) > 0)
     LIMIT 1;
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION find_bling_integration_by_company_id(p_company_id TEXT)
RETURNS SETOF installed_integrations AS $$
    SELECT ii.*
      FROM installed_integrations ii
      JOIN integration_modules im ON im.id = ii.module_id
     WHERE im.tipo = 'ERP'
       AND im.slug = 'bling'
       AND ii.is_active = true
       AND ii.config->>'company_id' = p_company_id
     LIMIT 1;
$$ LANGUAGE sql STABLE;

-- 9.2 Resolve instância marketplace pelo bling_loja_id
CREATE OR REPLACE FUNCTION find_marketplace_by_bling_loja(p_loja_id TEXT)
RETURNS SETOF installed_integrations AS $$
    SELECT ii.*
      FROM installed_integrations ii
      JOIN integration_modules im ON im.id = ii.module_id
     WHERE im.tipo = 'marketplace'
       AND ii.is_active = true
       AND ii.config->>'bling_loja_id' = p_loja_id
     LIMIT 1;
$$ LANGUAGE sql STABLE;

-- =============================================================
-- 10. TABELAS DE CONTROLE PARA SYNC DE STATUS BLING
-- =============================================================
CREATE TABLE IF NOT EXISTS sync_status_batches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pedido_ids BIGINT[] NOT NULL,
    total INT NOT NULL,
    sucesso INT DEFAULT 0,
    falha   INT DEFAULT 0,
    status  TEXT DEFAULT 'PENDENTE',  -- PENDENTE|RODANDO|CONCLUIDO|ERRO
    iniciado_em TIMESTAMPTZ DEFAULT NOW(),
    finalizado_em TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS sync_status_errors (
    id BIGSERIAL PRIMARY KEY,
    batch_id UUID REFERENCES sync_status_batches(id) ON DELETE CASCADE,
    pedido_id BIGINT NOT NULL,
    bling_id  BIGINT,
    erro      TEXT,
    tentado_em TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================================
-- 11. TABELAS DE CONTROLE PARA IA DE PERSONALIZAÇÃO
-- =============================================================
CREATE TABLE IF NOT EXISTS execucoes_ai_batch (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    criado_em TIMESTAMPTZ DEFAULT NOW(),
    pedido_ids BIGINT[] NOT NULL,
    total INT NOT NULL,
    processados INT DEFAULT 0,
    sucesso INT DEFAULT 0,
    falha INT DEFAULT 0,
    status TEXT DEFAULT 'PENDENTE',
    finalizado_em TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS execucoes_ai_item (
    id BIGSERIAL PRIMARY KEY,
    batch_id UUID REFERENCES execucoes_ai_batch(id) ON DELETE CASCADE,
    pedido_id BIGINT NOT NULL,
    status TEXT NOT NULL,    -- OK|ERRO|IGNORADO
    erro TEXT,
    duracao_ms INT,
    criado_em TIMESTAMPTZ DEFAULT NOW()
);

CREATE OR REPLACE FUNCTION incrementar_batch_ia(
    p_batch_id UUID, p_sucesso INT, p_falha INT
) RETURNS VOID AS $$
DECLARE v_total INT; v_proc INT;
BEGIN
    UPDATE execucoes_ai_batch
       SET processados = processados + 1,
           sucesso     = sucesso + p_sucesso,
           falha       = falha + p_falha
     WHERE id = p_batch_id
    RETURNING total, processados INTO v_total, v_proc;
    IF v_proc >= v_total THEN
        UPDATE execucoes_ai_batch
           SET status='CONCLUIDO', finalizado_em=NOW()
         WHERE id=p_batch_id;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- =============================================================
-- 12. TABELA DE AUDITORIA DE INGESTÃO (opcional, recomendada)
-- =============================================================
CREATE TABLE IF NOT EXISTS pedido_ingest_log (
    id BIGSERIAL PRIMARY KEY,
    pedido_id BIGINT,
    bling_id  BIGINT,
    marketplace_integration_id INT,
    is_flex BOOLEAN,
    flex_motivo TEXT,            -- string explicativa do classificador
    matched_rule_id INT,
    raw_decision JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
