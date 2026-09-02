-- Task 1: Database Migration for Integration Routing and Order Normalization

-- 1. Create integration_account_routing table
CREATE TABLE IF NOT EXISTS "public"."integration_account_routing" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "module" character varying(50) DEFAULT 'bling' NOT NULL,
    "function_name" character varying(50) NOT NULL, -- ORDER_IMPORT, NFE_EMISSION, CATALOG_SYNC, STOCK_SYNC
    "scope_type" character varying(20) NOT NULL,    -- GLOBAL, PLATFORM, CHANNEL
    "scope_id" character varying(100),              -- NULL for global, platform name or channel_id
    "account_id" character varying(255) NOT NULL,   -- ID of the account in contas_bling or installed_integrations
    "is_active" boolean DEFAULT true,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    CONSTRAINT "integration_account_routing_pkey" PRIMARY KEY ("id")
);

ALTER TABLE "public"."integration_account_routing" OWNER TO "postgres";

-- 2. Alter pedidos table to add canal_venda_id
DO $$ 
BEGIN 
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'pedidos' AND column_name = 'canal_venda_id') THEN
        ALTER TABLE "public"."pedidos" ADD COLUMN "canal_venda_id" integer;
        ALTER TABLE "public"."pedidos" ADD CONSTRAINT "pedidos_canal_venda_id_fkey" FOREIGN KEY ("canal_venda_id") REFERENCES "public"."canais_venda"("id") ON DELETE SET NULL;
    END IF;
END $$;

-- 3. Alter vinculos_integracao_pedido table to add integration_id
DO $$ 
BEGIN 
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'vinculos_integracao_pedido' AND column_name = 'integration_id') THEN
        ALTER TABLE "public"."vinculos_integracao_pedido" ADD COLUMN "integration_id" character varying(255);
    END IF;
END $$;

-- 4. Add index for performance on routing lookups
CREATE INDEX IF NOT EXISTS "idx_routing_lookup" ON "public"."integration_account_routing" ("module", "function_name", "scope_type", "scope_id");

-- 5. Comments
COMMENT ON TABLE "public"."integration_account_routing" IS 'Mapeamento granular de funções de integração para contas específicas (Multi-CNPJ).';
COMMENT ON COLUMN "public"."pedidos"."canal_venda_id" IS 'Referência ao canal de venda de origem para roteamento e relatórios.';
COMMENT ON COLUMN "public"."vinculos_integracao_pedido"."integration_id" IS 'ID da conta de integração específica para evitar colisão de IDs entre múltiplas contas.';
