-- Vínculo explícito: instância Bling + instância marketplace + bling_loja_id
-- integration_id legado permanece (deprecated) para compatibilidade até migração completa do código.

ALTER TABLE "public"."integracao_canais_config"
  ADD COLUMN IF NOT EXISTS "bling_integration_id" integer REFERENCES "public"."installed_integrations"("id") ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS "marketplace_integration_id" integer REFERENCES "public"."installed_integrations"("id") ON DELETE SET NULL;

COMMENT ON COLUMN "public"."integracao_canais_config"."bling_integration_id" IS
  'installed_integrations (module_id=bling) — conta Bling usada para API/token deste vínculo';
COMMENT ON COLUMN "public"."integracao_canais_config"."marketplace_integration_id" IS
  'installed_integrations (shopee, amazon, etc.) — instância marketplace associada a esta loja Bling';
COMMENT ON COLUMN "public"."integracao_canais_config"."integration_id" IS
  'Deprecated: usar bling_integration_id e marketplace_integration_id';

-- Backfill a partir do integration_id único legado
UPDATE "public"."integracao_canais_config" icc
SET "bling_integration_id" = ii.id
FROM "public"."installed_integrations" ii
WHERE icc."integration_id" = ii.id
  AND ii."module_id" = 'bling'
  AND icc."bling_integration_id" IS NULL;

UPDATE "public"."integracao_canais_config" icc
SET "marketplace_integration_id" = ii.id
FROM "public"."installed_integrations" ii
WHERE icc."integration_id" = ii.id
  AND ii."module_id" IS NOT NULL
  AND ii."module_id" <> 'bling'
  AND icc."marketplace_integration_id" IS NULL;

-- Remover UNIQUE antigo (integration_id, bling_loja_id) para permitir dois FKs distintos
ALTER TABLE "public"."integracao_canais_config"
  DROP CONSTRAINT IF EXISTS "integracao_canais_config_integration_id_bling_loja_id_key";

-- Uma mesma loja Bling não pode repetir para a mesma instância Bling (quando informada)
CREATE UNIQUE INDEX IF NOT EXISTS "integracao_canais_config_bling_inst_loja_uq"
  ON "public"."integracao_canais_config" ("bling_integration_id", "bling_loja_id")
  WHERE "bling_integration_id" IS NOT NULL AND "bling_loja_id" IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS "integracao_canais_config_mp_inst_loja_uq"
  ON "public"."integracao_canais_config" ("marketplace_integration_id", "bling_loja_id")
  WHERE "marketplace_integration_id" IS NOT NULL AND "bling_loja_id" IS NOT NULL;

CREATE INDEX IF NOT EXISTS "idx_integracao_canais_bling_integration_id"
  ON "public"."integracao_canais_config" ("bling_integration_id")
  WHERE "is_active" = true;

CREATE INDEX IF NOT EXISTS "idx_integracao_canais_marketplace_integration_id"
  ON "public"."integracao_canais_config" ("marketplace_integration_id")
  WHERE "is_active" = true;
