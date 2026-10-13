-- O contrato legado retorna snapshot_id. Vincular esse identificador ao
-- operation_id torna a resposta idempotente e referencia a linha persistida.
CREATE OR REPLACE FUNCTION public.vincular_snapshot_operacao()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $function$
BEGIN
    NEW.id := NEW.operation_id;
    RETURN NEW;
END;
$function$;

DROP TRIGGER IF EXISTS trg_vincular_snapshot_operacao
    ON public.snapshots_reconciliacao;
CREATE TRIGGER trg_vincular_snapshot_operacao
    BEFORE INSERT ON public.snapshots_reconciliacao
    FOR EACH ROW EXECUTE FUNCTION public.vincular_snapshot_operacao();

REVOKE ALL ON FUNCTION public.vincular_snapshot_operacao() FROM PUBLIC, anon, authenticated;
