-- =============================================================
-- MIGRATION: Multi-conta Bling (company_id + unicidade correta)
-- Data: 2026-05-12
-- Escopo:
-- 1) Garantir unicidade de pedidos_bling por (bling_integration_id, bling_id)
-- 2) Tornar RPC de company_id resiliente ao schema de integration_modules
-- =============================================================

-- 1) pedidos_bling: remover unique global em bling_id e aplicar unique composto.
ALTER TABLE public.pedidos_bling
    DROP CONSTRAINT IF EXISTS pedidos_bling_bling_id_key;

ALTER TABLE public.pedidos_bling
    DROP CONSTRAINT IF EXISTS pedidos_bling_numero_pedido_key;

ALTER TABLE public.pedidos_bling
    DROP CONSTRAINT IF EXISTS unique_numero_pedido;

ALTER TABLE public.pedidos_bling
    ADD CONSTRAINT pedidos_bling_bling_integration_bling_id_key
    UNIQUE (bling_integration_id, bling_id);

-- 2) RPC robusta: resolve conta Bling por installed_integrations.config->>'company_id'
-- sem depender de colunas variáveis em integration_modules (tipo/slug).
CREATE OR REPLACE FUNCTION public.find_bling_integration_by_company_id(p_company_id TEXT)
RETURNS SETOF public.installed_integrations
LANGUAGE sql
STABLE
AS $$
    SELECT ii.*
      FROM public.installed_integrations ii
     WHERE ii.module_id = 'bling'
       AND ii.is_active = true
       AND ii.config->>'company_id' = p_company_id
     LIMIT 1;
$$;

GRANT EXECUTE ON FUNCTION public.find_bling_integration_by_company_id(TEXT)
TO authenticated, anon, service_role;
