-- Migration: Enhance Integration Modules and Functional Delegation
-- Date: 2026-03-26

-- 1. Ensure category is well-defined in integration_modules (already exists, but adding check)
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'integration_category') THEN
        CREATE TYPE integration_category AS ENUM ('ERP', 'Marketplace', 'E-commerce', 'Logistics', 'Payment', 'Other');
    END IF;
END $$;

-- Update the column type if it's text (optional, but good for data integrity)
-- ALTER TABLE "public"."integration_modules" ALTER COLUMN "category" TYPE integration_category USING category::integration_category;

-- 2. Enhance installed_integrations with linking and delegation
ALTER TABLE "public"."installed_integrations" 
ADD COLUMN IF NOT EXISTS "parent_integration_id" integer REFERENCES "public"."installed_integrations"("id") ON DELETE SET NULL,
ADD COLUMN IF NOT EXISTS "is_default" boolean DEFAULT false,
ADD COLUMN IF NOT EXISTS "functional_scopes" jsonb DEFAULT '[]'::jsonb;

-- 3. Add indexes for better performance
CREATE INDEX IF NOT EXISTS idx_installed_integrations_parent ON "public"."installed_integrations" (parent_integration_id);
CREATE INDEX IF NOT EXISTS idx_installed_integrations_is_default ON "public"."installed_integrations" (is_default) WHERE is_default = true;

-- 4. Comments for clarity
COMMENT ON COLUMN "public"."installed_integrations"."parent_integration_id" IS 'Links this integration (e.g. Marketplace) to a parent integration (e.g. ERP)';
COMMENT ON COLUMN "public"."installed_integrations"."is_default" IS 'True if this is the default integration for its category and functional scope';
COMMENT ON COLUMN "public"."installed_integrations"."functional_scopes" IS 'JSON list of delegated responsibilities (e.g. ["INVOICING", "ORDER_IMPORT", "STOCK_SYNC"])';

-- 5. Update integration_account_routing to allow more granular control if needed
-- (This table already exists from migration 20260310000000)
ALTER TABLE "public"."integration_account_routing"
ADD COLUMN IF NOT EXISTS "priority" integer DEFAULT 0;

-- 6. Pre-categorize existing modules based on name
UPDATE "public"."integration_modules" SET "category" = 'ERP' WHERE "id" = 'bling';
UPDATE "public"."integration_modules" SET "category" = 'Marketplace' WHERE "id" IN ('shopee', 'amazon', 'mercadolivre', 'shein', 'tiktokshop');
UPDATE "public"."integration_modules" SET "category" = 'E-commerce' WHERE "id" = 'lojaintegrada';
