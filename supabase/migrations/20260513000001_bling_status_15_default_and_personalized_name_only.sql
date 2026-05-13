-- Multi-Bling follow-up:
-- - Garante fallback padrao Bling 15 -> situacao interna 2.
-- - Materializa pedidos ja ingeridos que ficaram sem status interno.

DELETE FROM public.integration_status_mappings
 WHERE module_id = 'bling'
   AND integration_id IS NULL
   AND external_status_id = '15';

INSERT INTO public.integration_status_mappings (
  module_id,
  integration_id,
  external_status_id,
  external_status_name,
  internal_situacao_pedido_id,
  triggers_demand_consolidation,
  is_active,
  config
) VALUES (
  'bling',
  NULL,
  '15',
  'Em Andamento',
  2,
  true,
  true,
  '{"action":"sync_and_consolidate","source":"multi_bling_default"}'::jsonb
);

UPDATE public.pedidos
   SET situacao_pedido_id = 2,
       updated_at = now()
 WHERE bling_integration_id IS NOT NULL
   AND situacao_pedido_id IS NULL
   AND status_original = '15';
