-- Personalization context identity and efficient seven-day chat fallback.
ALTER TABLE public.pedidos ADD COLUMN IF NOT EXISTS buyer_user_id bigint;
UPDATE public.pedidos p
SET buyer_user_id = ps.buyer_user_id,
    contact_marketplace_id = COALESCE(p.contact_marketplace_id, ps.buyer_user_id::text)
FROM public.pedidos_shopee ps
WHERE p.pedido_shopee_id = ps.id
  AND ps.buyer_user_id IS NOT NULL
  AND (p.buyer_user_id IS NULL OR p.contact_marketplace_id IS NULL);
CREATE INDEX IF NOT EXISTS idx_mensagem_chat_shopee_to_id_created_at
  ON public.mensagem_chat_shopee (installed_integration_id, to_id, created_at DESC)
  WHERE to_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_pedidos_personalizados_ativos
  ON public.pedidos (marketplace_integration_id, situacao_pedido_id, data_venda DESC, id DESC)
  WHERE situacao_pedido_id = 2 AND personalizado = true;
COMMENT ON COLUMN public.pedidos.buyer_user_id IS
  'Shopee buyer_user_id usado para escopo exato do Webchat; username permanece fallback.';