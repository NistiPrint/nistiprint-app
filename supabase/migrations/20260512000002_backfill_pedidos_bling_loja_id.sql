-- Recupera loja_id em pedidos_bling quando o worker antigo salvou o detalhe
-- sem preservar payload.data.loja.id do webhook/listagem original do Bling.

WITH latest_webhook_loja AS (
  SELECT DISTINCT ON (we.bling_id)
    we.bling_id,
    NULLIF(we.raw_payload #>> '{data,loja,id}', '') AS loja_id,
    we.raw_payload #> '{data,loja}' AS loja_payload
  FROM public.webhook_events we
  WHERE NULLIF(we.raw_payload #>> '{data,loja,id}', '') IS NOT NULL
  ORDER BY we.bling_id, we.received_at DESC
),
backfill AS (
  SELECT
    pb.id,
    lw.loja_id::integer AS loja_id,
    lw.loja_payload
  FROM public.pedidos_bling pb
  JOIN latest_webhook_loja lw ON lw.bling_id = pb.bling_id
  WHERE pb.loja_id IS NULL
    AND lw.loja_id ~ '^[0-9]+$'
)
UPDATE public.pedidos_bling pb
SET
  loja_id = backfill.loja_id,
  raw_payload = CASE
    WHEN pb.raw_payload IS NULL THEN jsonb_build_object('loja', backfill.loja_payload)
    WHEN pb.raw_payload ? 'loja' THEN pb.raw_payload
    ELSE jsonb_set(pb.raw_payload, '{loja}', backfill.loja_payload, true)
  END,
  updated_at = now()
FROM backfill
WHERE pb.id = backfill.id;
