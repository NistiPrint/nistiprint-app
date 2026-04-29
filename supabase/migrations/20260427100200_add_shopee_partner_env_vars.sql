-- =============================================================
-- MIGRATION: Add Shopee Partner ID/Key from Environment
-- Data: 2026-04-27
-- Escopo: Atualizar config da integração Shopee com partner_id e partner_key
--          obtidos de variáveis de ambiente (SHOPEE_PARTNER_ID, SHOPEE_PARTNER_KEY)
-- =============================================================

-- NOTA: Esta migration deve ser executada com as variáveis de ambiente definidas
-- Execute manualmente após definir SHOPEE_PARTNER_ID e SHOPEE_PARTNER_KEY no .env

-- Atualizar config da integração Shopee (id=6) com partner_id e partner_key
-- Os valores são substituídos pelo Supabase durante a execução se definidos como ${VAR}
UPDATE installed_integrations
SET config = jsonb_set(
    jsonb_set(
        config,
        '{partner_id}',
        to_jsonb('${SHOPEE_PARTNER_ID}'::text)
    ),
    '{partner_key}',
    to_jsonb('${SHOPEE_PARTNER_KEY}'::text)
)
WHERE module_id = 'shopee'
  AND id = 6;

-- Se as variáveis não estiverem definidas, execute manualmente:
-- UPDATE installed_integrations
-- SET config = config || '{"partner_id": "SEU_PARTNER_ID", "partner_key": "SUA_PARTNER_KEY"}'
-- WHERE module_id = 'shopee' AND id = 6;
