BEGIN;

DO $migration$
DECLARE
  v_definition TEXT;
  v_old_rule TEXT := 'WHEN v_target_status = 7 AND v_previous_status IN (5, 6) THEN 8';
  v_new_rule TEXT := 'WHEN v_target_status = 7 AND v_previous_status IN (5, 6) THEN v_previous_status';
BEGIN
  SELECT pg_get_functiondef(
    'public.apply_marketplace_order_event(jsonb,jsonb,jsonb,jsonb,boolean)'::regprocedure
  ) INTO v_definition;

  IF position(v_new_rule IN v_definition) > 0 THEN
    RETURN;
  END IF;
  IF position(v_old_rule IN v_definition) = 0 THEN
    RAISE EXCEPTION 'apply_marketplace_order_event projection rule not found';
  END IF;

  EXECUTE replace(v_definition, v_old_rule, v_new_rule);
END;
$migration$;

REVOKE ALL ON FUNCTION public.apply_marketplace_order_event(
  JSONB, JSONB, JSONB, JSONB, BOOLEAN
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.apply_marketplace_order_event(
  JSONB, JSONB, JSONB, JSONB, BOOLEAN
) TO service_role;

COMMIT;