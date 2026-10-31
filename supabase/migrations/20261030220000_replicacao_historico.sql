ALTER TABLE public.marketplace_pedidos_coleta ADD COLUMN search_field text NOT NULL DEFAULT 'updated' CHECK (search_field IN ('updated','created'));

CREATE OR REPLACE FUNCTION public.marketplace_pedidos_backfill(p_account integer,p_days integer DEFAULT 90)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
BEGIN
 IF p_days<1 OR p_days>90 THEN RAISE EXCEPTION 'INVALID_BACKFILL_WINDOW' USING ERRCODE='22023'; END IF;
 INSERT INTO public.marketplace_pedidos_coleta(account_id) VALUES(p_account) ON CONFLICT DO NOTHING;
 UPDATE public.marketplace_pedidos_coleta SET window_start=now()-make_interval(days=>p_days),window_end=now(),search_field='updated',
  cursor='{}',status='available',owner_token=NULL,lease_until='-infinity',next_attempt_at=now(),error_code=NULL,updated_at=now()
 WHERE account_id=p_account AND lease_until<now() AND status IN ('idle','complete','failed','unavailable');
 RETURN FOUND;
END $$;

CREATE FUNCTION public.marketplace_pedidos_historico_operacao(p_account integer,p_operation uuid,p_start timestamptz)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
BEGIN
 IF p_start IS NULL OR p_start < '2025-01-01 03:00:00+00'::timestamptz OR p_start >= now() OR p_operation IS NULL THEN
  RAISE EXCEPTION 'INVALID_HISTORY_WINDOW' USING ERRCODE='22023';
 END IF;
 INSERT INTO public.marketplace_pedidos_coleta(account_id) VALUES(p_account) ON CONFLICT DO NOTHING;
 UPDATE public.marketplace_pedidos_coleta SET window_start=p_start,window_end=now(),search_field='created',
  cursor='{}',status='available',owner_token=NULL,lease_until='-infinity',next_attempt_at=now(),error_code=NULL,
  operation_id=p_operation,updated_at=now()
 WHERE account_id=p_account AND lease_until<now() AND status IN ('idle','complete','failed','unavailable');
 RETURN FOUND;
END $$;
REVOKE ALL ON FUNCTION public.marketplace_pedidos_historico_operacao(integer,uuid,timestamptz) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.marketplace_pedidos_historico_operacao(integer,uuid,timestamptz) TO service_role;

CREATE OR REPLACE FUNCTION public.marketplace_pedidos_claim(p_account integer) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE result jsonb;
BEGIN
 INSERT INTO public.marketplace_pedidos_coleta(account_id) VALUES(p_account) ON CONFLICT DO NOTHING;
 UPDATE public.marketplace_pedidos_coleta SET owner_token=gen_random_uuid(),lease_until=now()+interval '5 minutes',
  window_end=CASE WHEN status IN ('idle','complete') THEN now() ELSE window_end END,
  window_start=CASE WHEN status IN ('idle','complete') THEN
   CASE WHEN initial_scan_completed THEN least(now()-interval '72 hours',coalesce(window_end,now())-interval '1 hour')
        ELSE now()-interval '90 days' END ELSE window_start END,
  search_field=CASE WHEN status IN ('idle','complete') THEN 'updated' ELSE search_field END,
  cursor=CASE WHEN status IN ('idle','complete') THEN '{}'::jsonb ELSE cursor END,
  operation_id=CASE WHEN status IN ('idle','complete') THEN NULL ELSE operation_id END,
  status='running',error_code=NULL,updated_at=now()
 WHERE account_id=p_account AND lease_until<now() AND next_attempt_at<=now()
 RETURNING jsonb_build_object('owner_token',owner_token,'window_start',window_start,'window_end',window_end,'cursor',cursor,'operation_id',operation_id,'search_field',search_field) INTO result;
 RETURN coalesce(result,jsonb_build_object('status','busy'));
END $$;
