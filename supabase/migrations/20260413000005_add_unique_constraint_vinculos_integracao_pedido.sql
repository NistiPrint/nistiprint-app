-- Add unique constraint on (plataforma, id_na_plataforma) to support upsert operations
-- This is needed for the API's ON CONFLICT clause when syncing integration links

-- First, check if there are any duplicate values that would prevent the constraint
DO $$
DECLARE
    duplicate_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO duplicate_count
    FROM (
        SELECT plataforma, id_na_plataforma, COUNT(*)
        FROM vinculos_integracao_pedido
        GROUP BY plataforma, id_na_plataforma
        HAVING COUNT(*) > 1
    ) dupes;
    
    IF duplicate_count > 0 THEN
        RAISE EXCEPTION 'Cannot add unique constraint: Found % duplicate (plataforma, id_na_plataforma) combinations. Please resolve duplicates first.', duplicate_count;
    END IF;
END $$;

-- Add the unique constraint
ALTER TABLE "public"."vinculos_integracao_pedido"
    ADD CONSTRAINT "vinculos_integracao_pedido_plataforma_id_na_plataforma_key" UNIQUE ("plataforma", "id_na_plataforma");

-- Add comment to document the constraint
COMMENT ON CONSTRAINT "vinculos_integracao_pedido_plataforma_id_na_plataforma_key" ON "public"."vinculos_integracao_pedido" IS 'Ensures each platform order ID is unique within its platform. Used for upsert operations via API.';
