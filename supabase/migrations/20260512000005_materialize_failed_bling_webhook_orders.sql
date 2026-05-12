-- Materializa pedidos que ficaram apenas em webhook_events porque o detalhe
-- completo do Bling estava indisponivel no momento da ingestao.
-- Usa o payload minimo do webhook e resolve a origem por Bling + loja_id.

WITH latest_webhook AS (
  SELECT DISTINCT ON (we.bling_id)
    we.bling_id,
    we.company_id,
    we.raw_payload #> '{data}' AS payload,
    we.raw_payload #>> '{data,numero}' AS numero_pedido,
    we.raw_payload #>> '{data,numeroLoja}' AS numero_loja,
    NULLIF(we.raw_payload #>> '{data,loja,id}', '') AS loja_id
  FROM public.webhook_events we
  WHERE we.bling_id IS NOT NULL
    AND we.raw_payload #>> '{data,numero}' IN ('457226', '457227', '457228')
  ORDER BY we.bling_id, we.received_at DESC
),
resolved AS (
  SELECT
    latest_webhook.*,
    bi.id AS bling_integration_id,
    cc.channel_id AS canal_venda_id,
    cc.marketplace_integration_id,
    NULLIF(latest_webhook.payload #>> '{situacao,id}', '') AS situacao_bling_id,
    COALESCE(latest_webhook.payload #> '{contato}', '{}'::jsonb) AS contato_json,
    NULLIF(latest_webhook.payload->>'total', '')::numeric AS total_pedido,
    NULLIF(latest_webhook.payload->>'data', '')::timestamp AS data_venda
  FROM latest_webhook
  LEFT JOIN LATERAL public.find_bling_integration_by_company_id(latest_webhook.company_id) bi ON true
  LEFT JOIN public.channel_connections cc
    ON cc.aggregator_store_id = latest_webhook.loja_id
   AND cc.is_active = true
   AND (bi.id IS NULL OR cc.bling_integration_id = bi.id)
),
upsert_bling AS (
  INSERT INTO public.pedidos_bling (
    bling_id,
    numero_pedido,
    numero_loja,
    loja_id,
    situacao_id,
    situacao_valor,
    contato,
    raw_payload,
    bling_integration_id,
    updated_at
  )
  SELECT
    resolved.bling_id,
    resolved.numero_pedido,
    resolved.numero_loja,
    resolved.loja_id::integer,
    resolved.situacao_bling_id::integer,
    NULLIF(resolved.payload #>> '{situacao,valor}', '')::integer,
    resolved.contato_json::text,
    resolved.payload,
    resolved.bling_integration_id,
    now()
  FROM resolved
  WHERE resolved.bling_integration_id IS NOT NULL
    AND resolved.numero_pedido IS NOT NULL
    AND resolved.numero_loja IS NOT NULL
    AND resolved.loja_id ~ '^[0-9]+$'
  ON CONFLICT (bling_integration_id, bling_id)
  DO UPDATE SET
    numero_pedido = EXCLUDED.numero_pedido,
    numero_loja = EXCLUDED.numero_loja,
    loja_id = EXCLUDED.loja_id,
    situacao_id = EXCLUDED.situacao_id,
    situacao_valor = EXCLUDED.situacao_valor,
    contato = EXCLUDED.contato,
    raw_payload = EXCLUDED.raw_payload,
    updated_at = now()
  RETURNING id, bling_id, bling_integration_id
),
pedido_source AS (
  SELECT
    ub.id AS pedido_bling_id,
    resolved.*
  FROM resolved
  JOIN upsert_bling ub
    ON ub.bling_id = resolved.bling_id
   AND ub.bling_integration_id = resolved.bling_integration_id
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
  pedido_source.numero_pedido::varchar,
  pedido_source.numero_loja::varchar,
  'BLING',
  COALESCE(pedido_source.contato_json, '{}'::jsonb),
  ism.internal_situacao_pedido_id,
  pedido_source.total_pedido,
  'BRL',
  COALESCE(pedido_source.data_venda, now()),
  pedido_source.contato_json->>'nome',
  pedido_source.contato_json->>'numeroDocumento',
  pedido_source.canal_venda_id,
  pedido_source.pedido_bling_id,
  pedido_source.marketplace_integration_id,
  pedido_source.bling_integration_id,
  pedido_source.situacao_bling_id,
  false,
  'STANDARD',
  now()
FROM pedido_source
LEFT JOIN public.integration_status_mappings ism
  ON ism.module_id = 'bling'
 AND ism.external_status_id = pedido_source.situacao_bling_id
ON CONFLICT (codigo_pedido_externo)
DO UPDATE SET
  numero_pedido = EXCLUDED.numero_pedido,
  informacoes_cliente = EXCLUDED.informacoes_cliente,
  situacao_pedido_id = EXCLUDED.situacao_pedido_id,
  total_pedido = EXCLUDED.total_pedido,
  data_venda = EXCLUDED.data_venda,
  cliente_nome = EXCLUDED.cliente_nome,
  cliente_documento = EXCLUDED.cliente_documento,
  canal_venda_id = EXCLUDED.canal_venda_id,
  pedido_bling_id = EXCLUDED.pedido_bling_id,
  marketplace_integration_id = EXCLUDED.marketplace_integration_id,
  bling_integration_id = EXCLUDED.bling_integration_id,
  status_original = EXCLUDED.status_original,
  updated_at = now();
