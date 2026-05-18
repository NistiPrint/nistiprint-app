-- Migration: Add MercadoLivre Enrichment
-- Date: 2026-05-17

CREATE TABLE IF NOT EXISTS "public"."pedidos_mercadolivre" (
    "id" SERIAL PRIMARY KEY,
    "codigo_pedido" character varying(255) NOT NULL,
    "shipment_id" bigint,
    "status" character varying(100),
    "mode" character varying(50),
    "shipping_type" character varying(50),
    "shipping_option_name" character varying(100),
    "expected_date" timestamp with time zone,
    "buyer_nickname" character varying(255),
    "raw_order" jsonb,
    "raw_shipment" jsonb,
    "raw_sla" jsonb,
    "marketplace_integration_id" integer REFERENCES "public"."installed_integrations"("id"),
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_pedidos_meli_codigo_pedido ON public.pedidos_mercadolivre(codigo_pedido);

ALTER TABLE "public"."pedidos" 
    ADD COLUMN IF NOT EXISTS "pedido_mercadolivre_id" integer REFERENCES "public"."pedidos_mercadolivre"("id") ON DELETE SET NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_pedidos_pedido_meli_id
    ON "public"."pedidos" ("pedido_mercadolivre_id") 
    WHERE "pedido_mercadolivre_id" IS NOT NULL;
