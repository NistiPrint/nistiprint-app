-- Repeated order and chat updates can enqueue the same key many times.
-- Keep the accumulated flags without writing an identical tuple on conflict.
CREATE OR REPLACE FUNCTION public.enqueue_operational_read_model_event(
    p_key text,
    p_personalized boolean DEFAULT false,
    p_dispatch boolean DEFAULT false,
    p_backfill boolean DEFAULT false,
    p_dispatch_calendar boolean DEFAULT false
)
RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
    INSERT INTO public.operational_read_model_outbox
        (event_key, personalized, dispatch, backfill, dispatch_calendar)
    VALUES (p_key, p_personalized, p_dispatch, p_backfill, p_dispatch_calendar)
    ON CONFLICT (event_key) DO UPDATE SET
        personalized = operational_read_model_outbox.personalized OR EXCLUDED.personalized,
        dispatch = operational_read_model_outbox.dispatch OR EXCLUDED.dispatch,
        backfill = operational_read_model_outbox.backfill OR EXCLUDED.backfill,
        dispatch_calendar = operational_read_model_outbox.dispatch_calendar OR EXCLUDED.dispatch_calendar
    WHERE (EXCLUDED.personalized AND NOT operational_read_model_outbox.personalized)
       OR (EXCLUDED.dispatch AND NOT operational_read_model_outbox.dispatch)
       OR (EXCLUDED.backfill AND NOT operational_read_model_outbox.backfill)
       OR (EXCLUDED.dispatch_calendar AND NOT operational_read_model_outbox.dispatch_calendar);
$$;
