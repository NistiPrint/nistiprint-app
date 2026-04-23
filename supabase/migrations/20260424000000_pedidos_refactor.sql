-- 1.3.1 Colunas de link em pedidos
ALTER TABLE pedidos
    ADD COLUMN IF NOT EXISTS pedido_bling_id BIGINT REFERENCES pedidos_bling(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS pedido_shopee_id BIGINT REFERENCES pedidos_shopee(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS modalidade_logistica TEXT,
    ADD COLUMN IF NOT EXISTS shop_id_shopee BIGINT;

CREATE UNIQUE INDEX IF NOT EXISTS ux_pedidos_pedido_bling_id
    ON pedidos (pedido_bling_id) WHERE pedido_bling_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_pedidos_pedido_shopee_id
    ON pedidos (pedido_shopee_id) WHERE pedido_shopee_id IS NOT NULL;

-- 1.3.2 Garantir colunas em pedidos_shopee
ALTER TABLE pedidos_shopee
    ADD COLUMN IF NOT EXISTS fulfillment_flag TEXT,
    ADD COLUMN IF NOT EXISTS shipping_carrier TEXT,
    ADD COLUMN IF NOT EXISTS package_list JSONB,
    ADD COLUMN IF NOT EXISTS pay_time TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS recipient_address JSONB,
    ADD COLUMN IF NOT EXISTS item_list JSONB,
    ADD COLUMN IF NOT EXISTS shop_id BIGINT,
    ADD COLUMN IF NOT EXISTS raw_payload JSONB,
    ADD COLUMN IF NOT EXISTS enriched_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS ix_pedidos_shopee_shop_id ON pedidos_shopee(shop_id);

-- 1.3.3 Garantir colunas em pedidos_bling
ALTER TABLE pedidos_bling
    ADD COLUMN IF NOT EXISTS situacao_id INT,
    ADD COLUMN IF NOT EXISTS situacao_valor INT,
    ADD COLUMN IF NOT EXISTS contato JSONB,
    ADD COLUMN IF NOT EXISTS transporte JSONB,
    ADD COLUMN IF NOT EXISTS intermediador_cnpj TEXT,
    ADD COLUMN IF NOT EXISTS loja_id BIGINT,
    ADD COLUMN IF NOT EXISTS observacoes TEXT,
    ADD COLUMN IF NOT EXISTS observacoes_internas TEXT,
    ADD COLUMN IF NOT EXISTS raw_payload JSONB,
    ADD COLUMN IF NOT EXISTS integracao_instancia_id BIGINT REFERENCES installed_integrations(id);

CREATE INDEX IF NOT EXISTS ix_pedidos_bling_loja_id ON pedidos_bling(loja_id);
CREATE INDEX IF NOT EXISTS ix_pedidos_bling_integracao ON pedidos_bling(integracao_instancia_id);

-- 1.3.4 (MAPEAMENTO LOJA BLING → SHOPEE: usa channel_connections)
CREATE TABLE IF NOT EXISTS channel_connections (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    channel_id integer NOT NULL REFERENCES canais_venda(id),
    integration_id integer REFERENCES installed_integrations(id),
    aggregator_store_id varchar(255), -- ex: bling_loja_id
    aggregator_store_name varchar(255),
    bling_integration_id integer REFERENCES installed_integrations(id),
    marketplace_integration_id integer REFERENCES installed_integrations(id),
    config jsonb DEFAULT '{}'::jsonb,
    is_active boolean DEFAULT true,
    last_sync timestamp with time zone,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);

-- Confirmar que os índices abaixo existem; criar se faltarem:
CREATE INDEX IF NOT EXISTS ix_channel_conn_aggregator
    ON channel_connections (bling_integration_id, aggregator_store_id)
    WHERE is_active = true;

-- 1.3.5 Regras parametrizáveis de classificação Flex por instância
CREATE TABLE IF NOT EXISTS flex_classification_rules (
    id BIGSERIAL PRIMARY KEY,
    integracao_instancia_id BIGINT REFERENCES installed_integrations(id) ON DELETE CASCADE,
    canal_venda_id BIGINT REFERENCES canais_venda(id) ON DELETE CASCADE,
    campo TEXT NOT NULL,              -- 'shipping_carrier' | 'servico_logistico' | 'fulfillment_flag'
    operador TEXT NOT NULL,           -- 'ILIKE' | 'EQUALS' | 'ILIKE_NORMALIZED'
    padrao TEXT NOT NULL,             -- 'entrega rápida' | 'entrega rapida'
    is_flex BOOLEAN NOT NULL,
    modalidade TEXT,                  -- 'FLEX' | 'STANDARD' | 'FULL' ...
    prioridade INT DEFAULT 100,       -- menor = maior prioridade
    ativo BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CHECK (integracao_instancia_id IS NOT NULL OR canal_venda_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS ix_flex_rules_instancia ON flex_classification_rules(integracao_instancia_id, ativo);
CREATE INDEX IF NOT EXISTS ix_flex_rules_canal ON flex_classification_rules(canal_venda_id, ativo);

-- 1.3.6 DROP triggers legadas que interferem em is_flex
DROP TRIGGER IF EXISTS trg_calcular_is_flex ON pedidos;
DROP FUNCTION IF EXISTS calcular_is_flex();

-- O fn_snapshot_channel_on_insert NÃO deve mais tocar is_flex:
-- Vamos recriar a função sem a linha que toca is_flex
CREATE OR REPLACE FUNCTION public.fn_snapshot_channel_on_insert()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE
    v_config jsonb;
BEGIN
    SELECT config INTO v_config
      FROM canais_venda
     WHERE id = NEW.canal_venda_id;

    NEW.channel_snapshot := v_config;
    -- NEW.is_flex := (NEW.channel_snapshot->>'flex')::boolean; -- REMOVIDO conforme plano
    RETURN NEW;
END;
$function$;

-- 1.3.7a RPC de lookup de conexão Shopee
CREATE OR REPLACE FUNCTION find_shopee_connection(
    p_bling_integration_id BIGINT,
    p_aggregator_store_id  TEXT
) RETURNS TABLE (
    marketplace_integration_id INT,
    channel_id                 INT,
    shopee_config              JSONB,
    shopee_credentials         JSONB
) AS $$
    SELECT cc.marketplace_integration_id,
           cc.channel_id,
           ii.config      AS shopee_config,
           ii.credentials AS shopee_credentials
      FROM channel_connections cc
      JOIN installed_integrations ii
           ON ii.id = cc.marketplace_integration_id
     WHERE cc.bling_integration_id = p_bling_integration_id
       AND cc.aggregator_store_id  = p_aggregator_store_id
       AND cc.is_active = true
     LIMIT 1;
$$ LANGUAGE sql STABLE;

-- 1.3.7 Seed inicial de flex_classification_rules
INSERT INTO flex_classification_rules
    (canal_venda_id, campo, operador, padrao, is_flex, modalidade, prioridade)
SELECT id, 'servico_logistico', 'ILIKE_NORMALIZED', 'entrega rapida', true, 'FLEX', 10
  FROM canais_venda WHERE plataforma = 'shopee';

INSERT INTO flex_classification_rules
    (canal_venda_id, campo, operador, padrao, is_flex, modalidade, prioridade)
SELECT id, 'shipping_carrier', 'ILIKE_NORMALIZED', 'entrega rapida', true, 'FLEX', 10
  FROM canais_venda WHERE plataforma = 'shopee';

-- Fallback: qualquer coisa Shopee que não caiu em regra acima vai como STANDARD
INSERT INTO flex_classification_rules
    (canal_venda_id, campo, operador, padrao, is_flex, modalidade, prioridade)
SELECT id, 'shipping_carrier', 'ILIKE', '%', false, 'STANDARD', 9999
  FROM canais_venda WHERE plataforma = 'shopee';

-- 2.3 Tabela de progresso Sync Status
CREATE TABLE IF NOT EXISTS sync_status_batches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pedido_ids BIGINT[] NOT NULL,
    total INT NOT NULL,
    sucesso INT DEFAULT 0,
    falha INT DEFAULT 0,
    status TEXT DEFAULT 'PENDENTE',  -- PENDENTE, RODANDO, CONCLUIDO, ERRO
    iniciado_em TIMESTAMPTZ DEFAULT NOW(),
    finalizado_em TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS sync_status_errors (
    id BIGSERIAL PRIMARY KEY,
    batch_id UUID REFERENCES sync_status_batches(id) ON DELETE CASCADE,
    pedido_id BIGINT NOT NULL,
    bling_id BIGINT,
    erro TEXT,
    tentado_em TIMESTAMPTZ DEFAULT NOW()
);

-- 3.3 Tabelas de controle IA Batch
CREATE TABLE IF NOT EXISTS execucoes_ai_batch (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    criado_em TIMESTAMPTZ DEFAULT NOW(),
    pedido_ids BIGINT[] NOT NULL,
    total INT NOT NULL,
    processados INT DEFAULT 0,
    sucesso INT DEFAULT 0,
    falha INT DEFAULT 0,
    status TEXT DEFAULT 'PENDENTE',
    finalizado_em TIMESTAMPTZ,
    iniciado_por TEXT
);

CREATE TABLE IF NOT EXISTS execucoes_ai_item (
    id BIGSERIAL PRIMARY KEY,
    batch_id UUID REFERENCES execucoes_ai_batch(id) ON DELETE CASCADE,
    pedido_id BIGINT NOT NULL,
    status TEXT NOT NULL,   -- 'OK' | 'ERRO' | 'IGNORADO'
    erro TEXT,
    duracao_ms INT,
    criado_em TIMESTAMPTZ DEFAULT NOW()
);

-- 3.5 RPC de incremento atômico IA
CREATE OR REPLACE FUNCTION incrementar_batch_ia(
    p_batch_id UUID,
    p_sucesso INT,
    p_falha INT
) RETURNS VOID AS $$
DECLARE
    v_total INT;
    v_proc INT;
BEGIN
    UPDATE execucoes_ai_batch
       SET processados = processados + 1,
           sucesso     = sucesso + p_sucesso,
           falha       = falha + p_falha
     WHERE id = p_batch_id
    RETURNING total, processados INTO v_total, v_proc;

    IF v_proc >= v_total THEN
        UPDATE execucoes_ai_batch
           SET status = 'CONCLUIDO',
               finalizado_em = NOW()
         WHERE id = p_batch_id;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- 4.2 Idempotency key para movimentações de estoque
ALTER TABLE movimentacoes_estoque
    ADD COLUMN IF NOT EXISTS idempotency_key TEXT UNIQUE;
