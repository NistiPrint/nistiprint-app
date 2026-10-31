ALTER TABLE public.marketplace_pedidos_coleta ADD COLUMN IF NOT EXISTS operation_id uuid;

CREATE FUNCTION public.marketplace_pedidos_backfill_operacao(p_account integer,p_operation uuid,p_days integer DEFAULT 90)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE queued boolean;
BEGIN
 IF p_operation IS NULL THEN RAISE EXCEPTION 'OPERATION_REQUIRED' USING ERRCODE='22023'; END IF;
 queued:=public.marketplace_pedidos_backfill(p_account,p_days);
 IF queued THEN UPDATE public.marketplace_pedidos_coleta SET operation_id=p_operation WHERE account_id=p_account; END IF;
 RETURN queued;
END $$;
REVOKE ALL ON FUNCTION public.marketplace_pedidos_backfill_operacao(integer,uuid,integer) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.marketplace_pedidos_backfill_operacao(integer,uuid,integer) TO service_role;

CREATE OR REPLACE FUNCTION public.marketplace_pedidos_claim(p_account integer) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE result jsonb;
BEGIN
 INSERT INTO public.marketplace_pedidos_coleta(account_id) VALUES(p_account) ON CONFLICT DO NOTHING;
 UPDATE public.marketplace_pedidos_coleta SET owner_token=gen_random_uuid(),lease_until=now()+interval '5 minutes',
  window_end=CASE WHEN status IN ('idle','complete') THEN now() ELSE window_end END,
  window_start=CASE WHEN status IN ('idle','complete') THEN now()-interval '72 hours' ELSE window_start END,
  cursor=CASE WHEN status IN ('idle','complete') THEN '{}'::jsonb ELSE cursor END,
  operation_id=CASE WHEN status IN ('idle','complete') THEN NULL ELSE operation_id END,
  status='running',error_code=NULL,updated_at=now()
 WHERE account_id=p_account AND lease_until<now() AND next_attempt_at<=now()
 RETURNING jsonb_build_object('owner_token',owner_token,'window_start',window_start,'window_end',window_end,'cursor',cursor,'operation_id',operation_id) INTO result;
 RETURN coalesce(result,jsonb_build_object('status','busy'));
END $$;
