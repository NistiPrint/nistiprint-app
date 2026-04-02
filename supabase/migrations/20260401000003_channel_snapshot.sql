-- ============================================
-- Migration: Channel Snapshot (Fase 4)
-- ============================================
-- Adiciona channel_snapshot em pedidos e demandas_producao
-- Cria trigger para capturar estado do canal no momento da criação
-- Garante rastreabilidade de flags (flex, fulfillment, horario_coleta)
-- ============================================

-- 1. Adicionar channel_snapshot em pedidos
ALTER TABLE "public"."pedidos"
ADD COLUMN IF NOT EXISTS "channel_snapshot" jsonb DEFAULT '{}';

COMMENT ON COLUMN "public"."pedidos"."channel_snapshot" IS 
  'Snapshot do estado do canal no momento da criação do pedido.
   Armazena: { flex, fulfillment, horario_coleta, color, canal_nome }.
   Usado para auditoria e para garantir consistência histórica.';

-- 2. Adicionar channel_snapshot em demandas_producao
ALTER TABLE "public"."demandas_producao"
ADD COLUMN IF NOT EXISTS "channel_snapshot" jsonb DEFAULT '{}';

COMMENT ON COLUMN "public"."demandas_producao"."channel_snapshot" IS 
  'Snapshot do estado do canal no momento da criação da demanda.
   Armazena: { flex, fulfillment, horario_coleta, color, canal_nome }.
   Usado para auditoria e para garantir consistência histórica.';

-- 3. Criar função para capturar snapshot do canal
CREATE OR REPLACE FUNCTION "public"."fn_snapshot_channel_on_insert"()
RETURNS TRIGGER AS $$
BEGIN
    -- Capturar dados do canal de venda
    SELECT jsonb_build_object(
        'flex',           sc.flex,
        'fulfillment',    sc.fulfillment,
        'horario_coleta', sc.horario_coleta,
        'color',          sc.color,
        'canal_nome',     sc.nome,
        'canal_id',       sc.id
    ) INTO NEW.channel_snapshot
    FROM "public"."canais_venda" sc
    WHERE sc.id = NEW.canal_venda_id;

    -- Para pedidos: manter is_flex denormalizado sincronizado com o snapshot
    -- (performance de query, mas sempre preenchido pelo trigger, nunca manualmente)
    IF TG_TABLE_NAME = 'pedidos' THEN
        NEW.is_flex := (NEW.channel_snapshot->>'flex')::boolean;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 4. Criar trigger para pedidos
DROP TRIGGER IF EXISTS "trg_snapshot_channel_before_order_insert" ON "public"."pedidos";
CREATE TRIGGER "trg_snapshot_channel_before_order_insert"
    BEFORE INSERT ON "public"."pedidos"
    FOR EACH ROW
    WHEN (NEW.canal_venda_id IS NOT NULL)
    EXECUTE FUNCTION "public"."fn_snapshot_channel_on_insert"();

COMMENT ON TRIGGER "trg_snapshot_channel_before_order_insert" ON "public"."pedidos" IS 
  'Captura snapshot do canal no momento da criação do pedido.
   Sincroniza is_flex denormalizado com o snapshot.';

-- 5. Criar trigger para demandas_producao
DROP TRIGGER IF EXISTS "trg_snapshot_channel_before_demand_insert" ON "public"."demandas_producao";
CREATE TRIGGER "trg_snapshot_channel_before_demand_insert"
    BEFORE INSERT ON "public"."demandas_producao"
    FOR EACH ROW
    WHEN (NEW.canal_venda_id IS NOT NULL)
    EXECUTE FUNCTION "public"."fn_snapshot_channel_on_insert"();

COMMENT ON TRIGGER "trg_snapshot_channel_before_demand_insert" ON "public"."demandas_producao" IS 
  'Captura snapshot do canal no momento da criação da demanda.';

-- 6. Backfill: Preencher channel_snapshot para registros existentes (pedidos)
-- Nota: Executar em lote para evitar lock prolongado
DO $$
DECLARE
    r RECORD;
    snapshot_data jsonb;
BEGIN
    FOR r IN 
        SELECT p.id, p.canal_venda_id, cv.flex, cv.fulfillment, cv.horario_coleta, cv.color, cv.nome as canal_nome
        FROM "public"."pedidos" p
        LEFT JOIN "public"."canais_venda" cv ON cv.id = p.canal_venda_id
        WHERE p.channel_snapshot IS NULL OR p.channel_snapshot = '{}'::jsonb
        AND p.canal_venda_id IS NOT NULL
        LIMIT 10000  -- Batch size
    LOOP
        snapshot_data := jsonb_build_object(
            'flex',           r.flex,
            'fulfillment',    r.fulfillment,
            'horario_coleta', r.horario_coleta,
            'color',          r.color,
            'canal_nome',     r.canal_nome,
            'canal_id',       r.canal_venda_id
        );
        
        UPDATE "public"."pedidos"
        SET channel_snapshot = snapshot_data
        WHERE id = r.id;
    END LOOP;
END $$;

-- 7. Backfill: Preencher channel_snapshot para registros existentes (demandas_producao)
DO $$
DECLARE
    r RECORD;
    snapshot_data jsonb;
BEGIN
    FOR r IN 
        SELECT d.id, d.canal_venda_id, cv.flex, cv.fulfillment, cv.horario_coleta, cv.color, cv.nome as canal_nome
        FROM "public"."demandas_producao" d
        LEFT JOIN "public"."canais_venda" cv ON cv.id = d.canal_venda_id
        WHERE d.channel_snapshot IS NULL OR d.channel_snapshot = '{}'::jsonb
        AND d.canal_venda_id IS NOT NULL
        LIMIT 10000  -- Batch size
    LOOP
        snapshot_data := jsonb_build_object(
            'flex',           r.flex,
            'fulfillment',    r.fulfillment,
            'horario_coleta', r.horario_coleta,
            'color',          r.color,
            'canal_nome',     r.canal_nome,
            'canal_id',       r.canal_venda_id
        );
        
        UPDATE "public"."demandas_producao"
        SET channel_snapshot = snapshot_data
        WHERE id = r.id;
    END LOOP;
END $$;

-- Nota: Para backfill completo, executar múltiplas vezes até zerar registros pendentes
-- Ou executar script Python dedicado para backfill em lote

-- 8. Criar índices para query de snapshot
CREATE INDEX IF NOT EXISTS "idx_pedidos_channel_snapshot_flex" 
ON "public"."pedidos"((channel_snapshot->>'flex')) 
WHERE channel_snapshot IS NOT NULL AND channel_snapshot != '{}'::jsonb;

CREATE INDEX IF NOT EXISTS "idx_demandas_channel_snapshot_flex" 
ON "public"."demandas_producao"((channel_snapshot->>'flex')) 
WHERE channel_snapshot IS NOT NULL AND channel_snapshot != '{}'::jsonb;

-- 9. Atualizar OrderService para remover atribuição manual de is_flex
-- Arquivo: packages/shared/nistiprint_shared/services/order_service.py
-- Remover: order.is_flex = canal.flex (se existir)
-- O trigger agora é responsável por sincronizar is_flex

-- 10. Atualizar DemandaProducaoService para remover atribuição manual de flags
-- Arquivo: packages/shared/nistiprint_shared/services/demanda_producao_service.py
-- Remover: demanda.is_flex = canal.flex (se existir)
-- O trigger agora é responsável por capturar o snapshot
