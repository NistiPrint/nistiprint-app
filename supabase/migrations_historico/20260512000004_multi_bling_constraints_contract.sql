-- Contrato multi-Bling:
-- - numero_pedido e numeroLoja nao sao unicos globalmente entre contas Bling.
-- - loja/origem deve ser resolvida no escopo da conta Bling.
-- - company_id pode ter aliases em installed_integrations.config.company_ids.

ALTER TABLE public.pedidos
  DROP CONSTRAINT IF EXISTS pedidos_numero_pedido_key;

CREATE INDEX IF NOT EXISTS ix_pedidos_numero_pedido
  ON public.pedidos (numero_pedido);

CREATE INDEX IF NOT EXISTS ix_pedidos_bling_codigo_externo
  ON public.pedidos (bling_integration_id, codigo_pedido_externo)
  WHERE bling_integration_id IS NOT NULL;

ALTER TABLE public.integracao_canais_config
  DROP CONSTRAINT IF EXISTS integracao_canais_config_canal_venda_id_bling_loja_id_key;

DROP INDEX IF EXISTS public.integracao_canais_config_canal_venda_id_bling_loja_id_key;

CREATE UNIQUE INDEX IF NOT EXISTS ux_channel_connections_active_bling_store
  ON public.channel_connections (bling_integration_id, aggregator_store_id)
  WHERE is_active = true
    AND bling_integration_id IS NOT NULL
    AND aggregator_store_id IS NOT NULL;

CREATE OR REPLACE FUNCTION public.find_bling_integration_by_company_id(p_company_id TEXT)
RETURNS SETOF public.installed_integrations
LANGUAGE sql
STABLE
AS $$
    SELECT ii.*
      FROM public.installed_integrations ii
     WHERE ii.module_id = 'bling'
       AND ii.is_active = true
       AND (
            ii.config->>'company_id' = p_company_id
            OR EXISTS (
                SELECT 1
                  FROM jsonb_array_elements_text(
                    CASE
                      WHEN jsonb_typeof(ii.config->'company_ids') = 'array'
                        THEN ii.config->'company_ids'
                      ELSE '[]'::jsonb
                    END
                  ) AS alias(company_id)
                 WHERE alias.company_id = p_company_id
            )
       )
     ORDER BY ii.is_default DESC NULLS LAST, ii.id
     LIMIT 1;
$$;

GRANT EXECUTE ON FUNCTION public.find_bling_integration_by_company_id(TEXT)
TO authenticated, anon, service_role;

CREATE OR REPLACE FUNCTION public.find_marketplace_by_bling_loja(
    p_loja_id TEXT,
    p_bling_integration_id INTEGER DEFAULT NULL
)
RETURNS SETOF public.installed_integrations
LANGUAGE sql
STABLE
AS $$
    SELECT ii.*
      FROM public.channel_connections cc
      JOIN public.installed_integrations ii ON ii.id = cc.marketplace_integration_id
     WHERE cc.aggregator_store_id = p_loja_id
       AND cc.is_active = true
       AND ii.is_active = true
       AND cc.marketplace_integration_id IS NOT NULL
       AND (
            p_bling_integration_id IS NULL
            OR cc.bling_integration_id = p_bling_integration_id
       )
     ORDER BY
       CASE WHEN cc.bling_integration_id = p_bling_integration_id THEN 0 ELSE 1 END,
       cc.updated_at DESC NULLS LAST
     LIMIT 1;
$$;

GRANT EXECUTE ON FUNCTION public.find_marketplace_by_bling_loja(TEXT, INTEGER)
TO authenticated, anon, service_role;
