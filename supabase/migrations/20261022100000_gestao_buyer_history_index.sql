-- The cold dashboard report joins every selected buyer to all of that buyer's
-- eligible order history. Index the JSON identity used by that join.
CREATE INDEX IF NOT EXISTS gestao_fatos_buyer_history
  ON public.gestao_fatos_pedido ((payload->>'buyer_key'), sold_on, pedido_id)
  WHERE (payload->>'eligible')::boolean
    AND payload->>'buyer_key' IS NOT NULL;
