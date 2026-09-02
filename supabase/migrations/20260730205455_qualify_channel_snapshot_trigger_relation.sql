BEGIN;

-- apply_marketplace_order_event deliberately runs with an empty search_path.
-- Trigger functions invoked by it inherit that setting, so every relation used
-- by the trigger must be schema-qualified.
CREATE OR REPLACE FUNCTION public.fn_snapshot_channel_on_insert()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = ''
AS $$
DECLARE
    v_config jsonb;
BEGIN
    SELECT cv.configuracao
      INTO v_config
      FROM public.canais_venda AS cv
     WHERE cv.id = NEW.canal_venda_id;

    NEW.channel_snapshot := v_config;
    RETURN NEW;
END;
$$;

COMMIT;
