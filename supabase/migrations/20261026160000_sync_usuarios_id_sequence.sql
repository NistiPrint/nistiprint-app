-- Keep the usuarios serial sequence ahead of restored/imported table rows.
-- A stale sequence makes every subsequent API insert collide with an
-- existing usuarios primary key while the generic insert adapter can hide
-- the underlying error.
DO $$
DECLARE
    sequence_name text;
    max_user_id bigint;
BEGIN
    sequence_name := pg_get_serial_sequence('public.usuarios', 'id');
    IF sequence_name IS NULL THEN
        RETURN;
    END IF;

    SELECT COALESCE(MAX(id), 0) INTO max_user_id FROM public.usuarios;
    IF max_user_id = 0 THEN
        PERFORM setval(sequence_name, 1, false);
    ELSE
        PERFORM setval(sequence_name, max_user_id, true);
    END IF;
END;
$$;
