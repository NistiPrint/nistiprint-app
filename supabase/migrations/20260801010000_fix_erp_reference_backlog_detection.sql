-- Identidade Bling em pedidos de integracao direta: tres defeitos encadeados.
--
-- 1. O indice unico de reconciliacao usava NULLS NOT DISTINCT sobre
--    (erp_integration_id, erp_order_id, status). Em pedido de marketplace
--    direto erp_order_id e sempre NULL, entao a chave (conta, NULL, 'pending')
--    era a mesma para todos: a fila comportava UM pedido por conta Bling.
--    Os demais levavam 23505, caiam no except de defer_unresolved_erp_order e
--    sumiam. A deduplicacao por pedido ja tem indice proprio
--    (ux_pending_order_reconciliation_order); este so faz sentido quando ha
--    erp_order_id de verdade.
--
-- 2. O trigger de compatibilidade caia para numero_pedido ao preencher
--    erp_order_number, convertendo "nao sei o numero do ERP" em "o numero do
--    ERP e o id do marketplace". Isso mascarava o buraco: nenhuma consulta por
--    erp_order_number IS NULL enxergava o backlog.
--
-- 3. 1470 pedidos ficaram com esse valor falso e fora da fila.
--
-- A task `order_erp_reference_service.reconcile_pending` ja existe e roda a
-- cada 60s (apps/worker/celery_config.py). Ela nao precisava de mudanca —
-- so tinha a fila vazia por causa de (1).

DROP INDEX IF EXISTS public.ux_pending_order_reconciliation_erp_order;

CREATE UNIQUE INDEX ux_pending_order_reconciliation_erp_order
  ON public.pending_order_reconciliations (erp_integration_id, erp_order_id, status)
  WHERE erp_order_id IS NOT NULL;

CREATE OR REPLACE FUNCTION public.sync_canonical_order_compat_fields()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
  IF NEW.marketplace_module_id IS NULL AND NEW.marketplace_integration_id IS NOT NULL THEN
    SELECT lower(ii.module_id)
      INTO NEW.marketplace_module_id
      FROM public.installed_integrations ii
     WHERE ii.id = NEW.marketplace_integration_id;
  END IF;

  NEW.marketplace_module_id := lower(NULLIF(NEW.marketplace_module_id, ''));
  NEW.marketplace_order_id := COALESCE(
    NULLIF(NEW.marketplace_order_id, ''), NEW.codigo_pedido_externo
  );
  NEW.erp_integration_id := COALESCE(
    NEW.erp_integration_id, NEW.bling_integration_id
  );
  NEW.erp_store_id := COALESCE(NULLIF(NEW.erp_store_id, ''), NEW.bling_loja_id);
  NEW.erp_order_id := COALESCE(NEW.erp_order_id, NEW.bling_order_id);
  -- Sem fallback para numero_pedido: ausencia de numero do ERP e um fato, e
  -- precisa continuar visivel para a reconciliacao.
  NEW.erp_order_number := COALESCE(
    NULLIF(NEW.erp_order_number, ''), NEW.bling_order_number
  );

  NEW.codigo_pedido_externo := COALESCE(
    NEW.codigo_pedido_externo, NEW.marketplace_order_id
  );
  NEW.numero_pedido := COALESCE(
    NULLIF(NEW.numero_pedido, ''), NEW.erp_order_number, NEW.marketplace_order_id
  );
  NEW.origem := COALESCE(
    NULLIF(NEW.origem, ''), upper(NEW.marketplace_module_id)
  );
  NEW.informacoes_cliente := COALESCE(NEW.informacoes_cliente, '{}'::jsonb);

  NEW.bling_integration_id := COALESCE(
    NEW.bling_integration_id, NEW.erp_integration_id
  );
  NEW.bling_loja_id := COALESCE(NULLIF(NEW.bling_loja_id, ''), NEW.erp_store_id);
  NEW.bling_order_id := COALESCE(NEW.bling_order_id, NEW.erp_order_id);
  NEW.bling_order_number := COALESCE(
    NULLIF(NEW.bling_order_number, ''), NEW.erp_order_number
  );

  IF TG_OP = 'UPDATE'
     AND OLD.marketplace_module_id IS NOT NULL
     AND OLD.marketplace_order_id IS NOT NULL
     AND (
       OLD.marketplace_module_id IS DISTINCT FROM NEW.marketplace_module_id
       OR OLD.marketplace_order_id IS DISTINCT FROM NEW.marketplace_order_id
     )
     AND COALESCE(current_setting('app.allow_order_identity_correction', true), 'false') <> 'true' THEN
    RAISE EXCEPTION
      'Canonical order identity is immutable; use correct_canonical_order_identity';
  END IF;

  IF TG_OP = 'INSERT'
     AND (NEW.marketplace_module_id IS NULL OR NEW.marketplace_order_id IS NULL) THEN
    RAISE EXCEPTION
      'Canonical order identity is required (marketplace_module_id + marketplace_order_id)';
  END IF;
  RETURN NEW;
END;
$function$;

-- Backfill: limpa o numero falso onde nao ha contrapartida real no Bling.
UPDATE public.pedidos p
SET erp_order_number = NULL,
    bling_order_number = NULL
WHERE p.marketplace_module_id IN ('shopee', 'mercadolivre')
  AND p.erp_order_id IS NULL
  AND p.erp_order_number = p.marketplace_order_id
  AND NOT EXISTS (
    SELECT 1 FROM public.pedidos_bling pb
    WHERE pb.numero_loja = p.marketplace_order_id
  );

-- Enfileira o backlog que o indice defeituoso vinha descartando.
-- Cancelados ficam de fora: nao vao gerar nota.
INSERT INTO public.pending_order_reconciliations (
  pedido_id, erp_integration_id, erp_store_id, erp_order_id,
  marketplace_order_id, marketplace_module_id, reason, status, payload, updated_at
)
SELECT p.id, p.erp_integration_id, p.erp_store_id, NULL,
       p.marketplace_order_id, p.marketplace_module_id,
       'erp_reference_pending', 'pending',
       jsonb_build_object(
         'marketplace_module_id', p.marketplace_module_id,
         'marketplace_integration_id', p.marketplace_integration_id,
         'enqueued_by', 'backfill_20260801'
       ),
       now()
FROM public.pedidos p
WHERE p.marketplace_module_id IN ('shopee', 'mercadolivre')
  AND p.erp_order_id IS NULL
  AND p.erp_order_number IS NULL
  AND p.situacao_pedido_id IS DISTINCT FROM 7
  AND NOT EXISTS (
    SELECT 1 FROM public.pending_order_reconciliations r
    WHERE r.pedido_id = p.id AND r.status = 'pending'
  );
