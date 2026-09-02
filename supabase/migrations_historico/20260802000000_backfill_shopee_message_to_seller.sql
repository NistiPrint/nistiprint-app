-- Restore the explicit message projections from the immutable Shopee payload.
-- The raw payload remains the source of truth; this only repairs nullable mirrors.

WITH source_messages AS (
  SELECT
    id,
    NULLIF(BTRIM(raw_payload->>'message_to_seller'), '') AS message_to_seller
  FROM public.pedidos_shopee
  WHERE raw_payload ? 'message_to_seller'
    AND NULLIF(BTRIM(raw_payload->>'message_to_seller'), '') IS NOT NULL
)
UPDATE public.pedidos_shopee AS ps
SET mensagem = source_messages.message_to_seller,
    updated_at = now()
FROM source_messages
WHERE ps.id = source_messages.id
  AND NULLIF(BTRIM(ps.mensagem), '') IS NULL;

UPDATE public.pedidos AS p
SET message_to_seller = ps.mensagem,
    updated_at = now()
FROM public.pedidos_shopee AS ps
WHERE p.pedido_shopee_id = ps.id
  AND NULLIF(BTRIM(ps.mensagem), '') IS NOT NULL
  AND NULLIF(BTRIM(p.message_to_seller), '') IS NULL;