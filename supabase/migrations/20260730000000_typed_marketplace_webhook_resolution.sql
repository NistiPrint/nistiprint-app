BEGIN;

ALTER TABLE public.webhook_events
  ADD COLUMN IF NOT EXISTS provider_resource_type TEXT,
  ADD COLUMN IF NOT EXISTS provider_resource_id TEXT,
  ADD COLUMN IF NOT EXISTS resolution_status TEXT,
  ADD COLUMN IF NOT EXISTS resolved_order_ids JSONB NOT NULL DEFAULT '[]'::jsonb;

UPDATE public.webhook_events
SET resolved_order_ids = jsonb_build_array(resolved_order_id)
WHERE resolved_order_id IS NOT NULL
  AND resolved_order_ids = '[]'::jsonb;

ALTER TABLE public.webhook_events
  DROP CONSTRAINT IF EXISTS webhook_events_resolved_order_ids_array;
ALTER TABLE public.webhook_events
  ADD CONSTRAINT webhook_events_resolved_order_ids_array
  CHECK (jsonb_typeof(resolved_order_ids) = 'array');

DROP INDEX IF EXISTS public.ux_marketplace_order_transition_provider_event;
CREATE UNIQUE INDEX IF NOT EXISTS ux_marketplace_order_transition_provider_order
  ON public.marketplace_order_transitions(
    module_id,
    provider_event_id,
    external_order_id
  )
  WHERE provider_event_id IS NOT NULL;

CREATE OR REPLACE FUNCTION public.apply_marketplace_order_event(
  p_order JSONB,
  p_snapshot JSONB DEFAULT NULL,
  p_refs JSONB DEFAULT '[]'::jsonb,
  p_event JSONB DEFAULT '{}'::jsonb,
  p_projection_enabled BOOLEAN DEFAULT false
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = ''
AS $$
DECLARE
  v_module_id TEXT := lower(NULLIF(p_order->>'marketplace_module_id', ''));
  v_external_order_id TEXT := NULLIF(p_order->>'marketplace_order_id', '');
  v_existing_id BIGINT;
  v_pedido_id BIGINT;
  v_previous_status INTEGER;
  v_target_status INTEGER := NULLIF(p_event->>'target_situacao_pedido_id', '')::INTEGER;
  v_applied_status INTEGER;
  v_stage TEXT := COALESCE(NULLIF(p_event->>'lifecycle_stage', ''), 'unknown');
  v_provider_updated_at TIMESTAMPTZ := NULLIF(p_event->>'observed_at', '')::TIMESTAMPTZ;
  v_current_provider_updated_at TIMESTAMPTZ;
  v_decision TEXT := 'external_state_only';
  v_transition_id BIGINT;
BEGIN
  IF v_module_id IS NULL OR v_external_order_id IS NULL THEN
    RAISE EXCEPTION 'marketplace_module_id and marketplace_order_id are required';
  END IF;

  SELECT id, situacao_pedido_id INTO v_existing_id, v_previous_status
  FROM public.pedidos
  WHERE marketplace_module_id = v_module_id
    AND marketplace_order_id = v_external_order_id
  FOR UPDATE;

  v_pedido_id := public.upsert_canonical_order(
    p_order - 'situacao_pedido_id',
    p_snapshot,
    p_refs
  );

  SELECT situacao_pedido_id, marketplace_status_updated_at
  INTO v_previous_status, v_current_provider_updated_at
  FROM public.pedidos WHERE id = v_pedido_id FOR UPDATE;

  IF v_provider_updated_at IS NOT NULL
     AND v_current_provider_updated_at IS NOT NULL
     AND v_provider_updated_at < v_current_provider_updated_at THEN
    v_decision := 'ignored_stale';
  ELSE
    UPDATE public.pedidos SET
      marketplace_order_status = COALESCE(NULLIF(p_event->>'order_status', ''), marketplace_order_status),
      marketplace_payment_status = COALESCE(NULLIF(p_event->>'payment_status', ''), marketplace_payment_status),
      marketplace_shipping_status = COALESCE(NULLIF(p_event->>'shipping_status', ''), marketplace_shipping_status),
      marketplace_shipping_substatus = COALESCE(NULLIF(p_event->>'shipping_substatus', ''), marketplace_shipping_substatus),
      marketplace_lifecycle_stage = v_stage,
      marketplace_status_updated_at = COALESCE(v_provider_updated_at, marketplace_status_updated_at, now()),
      informacoes_cliente = CASE
        WHEN COALESCE(p_order->'informacoes_cliente', p_order->'customer', '{}'::jsonb) = '{}'::jsonb
          THEN informacoes_cliente
        ELSE COALESCE(p_order->'informacoes_cliente', p_order->'customer')
      END,
      updated_at = now()
    WHERE id = v_pedido_id;

    IF (v_existing_id IS NULL OR p_projection_enabled) AND v_target_status IS NOT NULL THEN
      v_applied_status := CASE
        WHEN v_target_status = 8 THEN 8
        WHEN v_previous_status = 8 THEN 8
        WHEN v_target_status = 7 AND v_previous_status IN (5, 6) THEN 8
        WHEN v_target_status = 7 THEN 7
        WHEN v_previous_status IN (6, 7) THEN v_previous_status
        WHEN v_target_status = 6 THEN 6
        WHEN v_target_status = 5 THEN 5
        WHEN v_target_status = 4 AND v_previous_status = 3 THEN 3
        WHEN v_target_status = 4 AND COALESCE(v_previous_status, 1) IN (1, 2, 4) THEN 4
        WHEN v_target_status = 2 AND COALESCE(v_previous_status, 1) IN (1, 2) THEN 2
        WHEN v_target_status = 1 AND COALESCE(v_previous_status, 1) = 1 THEN 1
        ELSE v_previous_status
      END;
      IF v_applied_status IS DISTINCT FROM v_previous_status THEN
        UPDATE public.pedidos
        SET situacao_pedido_id = v_applied_status, updated_at = now()
        WHERE id = v_pedido_id;
        v_decision := 'applied';
      ELSE
        v_decision := 'ignored_regression';
      END IF;
    ELSIF v_target_status IS NULL THEN
      v_decision := 'unmapped';
    END IF;
  END IF;

  SELECT situacao_pedido_id INTO v_applied_status
  FROM public.pedidos WHERE id = v_pedido_id;

  INSERT INTO public.marketplace_order_transitions (
    pedido_id, webhook_event_id, provider_event_id, module_id,
    external_order_id, lifecycle_stage, previous_situacao_pedido_id,
    requested_situacao_pedido_id, applied_situacao_pedido_id, decision,
    reason, provider_updated_at, provider_state
  ) VALUES (
    v_pedido_id, NULLIF(p_event->>'webhook_event_id', '')::BIGINT,
    NULLIF(p_event->>'provider_event_id', ''), v_module_id,
    v_external_order_id, v_stage, v_previous_status, v_target_status,
    v_applied_status, v_decision, p_event->>'reason',
    v_provider_updated_at, p_event
  )
  ON CONFLICT (module_id, provider_event_id, external_order_id)
    WHERE provider_event_id IS NOT NULL
  DO UPDATE SET webhook_event_id = COALESCE(
    EXCLUDED.webhook_event_id,
    public.marketplace_order_transitions.webhook_event_id
  )
  RETURNING id INTO v_transition_id;

  IF v_decision = 'applied' AND v_applied_status IN (7, 8) THEN
    INSERT INTO public.marketplace_order_effects (
      pedido_id, transition_id, effect_type, payload
    ) VALUES (
      v_pedido_id, v_transition_id, 'alert_active_demands',
      jsonb_build_object(
        'situacao_pedido_id', v_applied_status,
        'lifecycle_stage', v_stage,
        'external_order_id', v_external_order_id
      )
    )
    ON CONFLICT (transition_id, effect_type) DO NOTHING;
  END IF;

  RETURN jsonb_build_object(
    'pedido_id', v_pedido_id, 'transition_id', v_transition_id,
    'decision', v_decision,
    'previous_situacao_pedido_id', v_previous_status,
    'situacao_pedido_id', v_applied_status,
    'lifecycle_stage', v_stage
  );
END;
$$;

ALTER TABLE public.webhook_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.marketplace_order_transitions ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.webhook_events FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.marketplace_order_transitions FROM PUBLIC, anon, authenticated;
GRANT ALL ON TABLE public.webhook_events TO service_role;
GRANT ALL ON TABLE public.marketplace_order_transitions TO service_role;

REVOKE ALL ON FUNCTION public.apply_marketplace_order_event(
  JSONB, JSONB, JSONB, JSONB, BOOLEAN
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.apply_marketplace_order_event(
  JSONB, JSONB, JSONB, JSONB, BOOLEAN
) TO service_role;

COMMENT ON COLUMN public.webhook_events.resolved_order_ids IS
  'Ordered unique provider order IDs resolved from the typed webhook resource.';
COMMENT ON COLUMN public.webhook_events.resolution_status IS
  'Typed adapter resolution outcome; does not imply domain processing success.';

COMMIT;
