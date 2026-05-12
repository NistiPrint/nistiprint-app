-- Remove unicidade global legada e materializa pedidos que ficaram parados
-- no espelho Bling por falha de upsert antes da criacao em public.pedidos.

ALTER TABLE public.pedidos_bling
  DROP CONSTRAINT IF EXISTS pedidos_bling_numero_pedido_key;

ALTER TABLE public.pedidos_bling
  DROP CONSTRAINT IF EXISTS unique_numero_pedido;

WITH latest_webhook AS (
  SELECT DISTINCT ON (we.bling_id)
    we.bling_id,
    we.company_id,
    we.raw_payload #> '{data}' AS payload,
    NULLIF(we.raw_payload #>> '{data,loja,id}', '') AS loja_id
  FROM public.webhook_events we
  WHERE we.bling_id IS NOT NULL
  ORDER BY we.bling_id, we.received_at DESC
),
resolved AS (
  SELECT
    pb.id AS pedido_bling_id,
    pb.bling_id,
    pb.numero_pedido,
    pb.numero_loja,
    COALESCE(pb.loja_id::text, latest_webhook.loja_id) AS loja_id,
    latest_webhook.payload,
    bi.id AS bling_integration_id,
    cc.marketplace_integration_id,
    cc.channel_id AS canal_venda_id,
    COALESCE(
      NULLIF(latest_webhook.payload #>> '{situacao,id}', ''),
      pb.situacao_id::text
    ) AS situacao_bling_id,
    CASE
      WHEN pb.contato IS NOT NULL AND pb.contato ~ '^\\s*[\\{\\[]' THEN pb.contato::jsonb
      ELSE COALESCE(latest_webhook.payload #> '{contato}', '{}'::jsonb)
    END AS contato_json,
    NULLIF(latest_webhook.payload->>'total', '')::numeric AS total_pedido,
    NULLIF(latest_webhook.payload->>'data', '')::timestamp AS data_venda
  FROM public.pedidos_bling pb
  JOIN latest_webhook ON latest_webhook.bling_id = pb.bling_id
  LEFT JOIN LATERAL public.find_bling_integration_by_company_id(latest_webhook.company_id) bi ON true
  LEFT JOIN public.channel_connections cc
    ON cc.aggregator_store_id = COALESCE(pb.loja_id::text, latest_webhook.loja_id)
   AND cc.is_active = true
   AND (bi.id IS NULL OR cc.bling_integration_id = bi.id)
  WHERE NOT EXISTS (
    SELECT 1
    FROM public.pedidos p
    WHERE p.pedido_bling_id = pb.id
       OR p.codigo_pedido_externo = pb.numero_loja
  )
    AND pb.numero_pedido IS NOT NULL
    AND pb.numero_loja IS NOT NULL
),
updated_bling AS (
  UPDATE public.pedidos_bling pb
  SET
    bling_integration_id = COALESCE(pb.bling_integration_id, resolved.bling_integration_id),
    loja_id = COALESCE(pb.loja_id, resolved.loja_id::integer),
    updated_at = now()
  FROM resolved
  WHERE pb.id = resolved.pedido_bling_id
    AND (pb.bling_integration_id IS NULL OR pb.loja_id IS NULL)
    AND resolved.loja_id ~ '^[0-9]+$'
  RETURNING pb.id
)
INSERT INTO public.pedidos (
  numero_pedido,
  codigo_pedido_externo,
  origem,
  informacoes_cliente,
  situacao_pedido_id,
  total_pedido,
  moeda,
  data_venda,
  cliente_nome,
  cliente_documento,
  canal_venda_id,
  pedido_bling_id,
  marketplace_integration_id,
  bling_integration_id,
  status_original,
  is_flex,
  modalidade_logistica,
  updated_at
)
SELECT
  resolved.numero_pedido::varchar,
  resolved.numero_loja::varchar,
  'BLING',
  COALESCE(resolved.contato_json, '{}'::jsonb),
  ism.internal_situacao_pedido_id,
  resolved.total_pedido,
  'BRL',
  COALESCE(resolved.data_venda, now()),
  resolved.contato_json->>'nome',
  resolved.contato_json->>'numeroDocumento',
  resolved.canal_venda_id,
  resolved.pedido_bling_id,
  resolved.marketplace_integration_id,
  resolved.bling_integration_id,
  resolved.situacao_bling_id,
  false,
  'STANDARD',
  now()
FROM resolved
LEFT JOIN public.integration_status_mappings ism
  ON ism.module_id = 'bling'
 AND ism.external_status_id = resolved.situacao_bling_id
ON CONFLICT (codigo_pedido_externo) DO NOTHING;
