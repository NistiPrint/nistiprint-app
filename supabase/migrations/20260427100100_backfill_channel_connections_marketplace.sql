-- =============================================================
-- MIGRATION: Backfill channel_connections.marketplace_integration_id
-- Data: 2026-04-27
-- Escopo: Popular marketplace_integration_id em channel_connections
--          usando mapeamento canais_venda.nome -> integration_modules.slug
-- =============================================================

-- Backfill: mapear canais_venda.nome para integration_modules.slug
-- Exemplo: "Amazon" -> "amazon", "Mercado Livre" -> "mercadolivre", "Shein" -> "shein"
UPDATE channel_connections cc
   SET marketplace_integration_id = ii.id
  FROM canais_venda cv
  JOIN integration_modules im ON LOWER(REPLACE(cv.nome, ' ', '')) = im.slug
  JOIN installed_integrations ii 
    ON ii.module_id = im.id 
   AND ii.is_active = true
 WHERE cc.channel_id = cv.id
   AND cc.marketplace_integration_id IS NULL;

-- TODO operacional: criar channel_connection para loja 205665302 (Mercado Livre? confirmar com cliente)
-- Esta loja_id aparece em pedidos novos mas não está mapeada em channel_connections

-- Verificar resultado (executar manualmente após migration):
-- SELECT cc.aggregator_store_id, ii.instance_name 
--   FROM channel_connections cc
--   JOIN installed_integrations ii ON ii.id = cc.marketplace_integration_id;
