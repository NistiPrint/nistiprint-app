ALTER TABLE public.marketplace_pedidos_coleta ADD COLUMN initial_scan_completed boolean NOT NULL DEFAULT false;

CREATE OR REPLACE FUNCTION public.marketplace_pedidos_claim(p_account integer) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE result jsonb;
BEGIN
 INSERT INTO public.marketplace_pedidos_coleta(account_id) VALUES(p_account) ON CONFLICT DO NOTHING;
 UPDATE public.marketplace_pedidos_coleta SET owner_token=gen_random_uuid(),lease_until=now()+interval '5 minutes',
  window_end=CASE WHEN status IN ('idle','complete') THEN now() ELSE window_end END,
  window_start=CASE WHEN status IN ('idle','complete') THEN now()-CASE WHEN initial_scan_completed THEN interval '72 hours' ELSE interval '90 days' END ELSE window_start END,
  cursor=CASE WHEN status IN ('idle','complete') THEN '{}'::jsonb ELSE cursor END,
  operation_id=CASE WHEN status IN ('idle','complete') THEN NULL ELSE operation_id END,
  status='running',error_code=NULL,updated_at=now()
 WHERE account_id=p_account AND lease_until<now() AND next_attempt_at<=now()
 RETURNING jsonb_build_object('owner_token',owner_token,'window_start',window_start,'window_end',window_end,'cursor',cursor,'operation_id',operation_id) INTO result;
 RETURN coalesce(result,jsonb_build_object('status','busy'));
END $$;

CREATE OR REPLACE FUNCTION public.marketplace_pedidos_finish(p_account integer,p_token uuid,p_cursor jsonb,p_complete boolean,p_error text DEFAULT NULL,p_retry_after integer DEFAULT NULL)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
BEGIN
 UPDATE public.marketplace_pedidos_coleta SET cursor=CASE WHEN p_error IS NULL THEN coalesce(p_cursor,'{}') ELSE cursor END,
  status=CASE WHEN p_error IN ('provider_pagination_limit','account_identity_missing','provider_access_forbidden','credential_action_required') THEN 'unavailable' WHEN p_error IS NOT NULL THEN 'failed' WHEN p_complete THEN 'complete' ELSE 'available' END,
  initial_scan_completed=initial_scan_completed OR (p_complete AND p_error IS NULL AND window_end-window_start>=interval '90 days'),
  last_complete_at=CASE WHEN p_complete AND p_error IS NULL THEN now() ELSE last_complete_at END,
  next_attempt_at=CASE WHEN p_error IN ('provider_pagination_limit','account_identity_missing','provider_access_forbidden','credential_action_required') THEN 'infinity'::timestamptz WHEN p_error IS NOT NULL THEN now()+make_interval(secs=>greatest(300,coalesce(p_retry_after,0))) WHEN p_complete THEN now()+interval '15 minutes' ELSE now() END,
  error_code=left(p_error,100),owner_token=NULL,lease_until='-infinity',updated_at=now()
 WHERE account_id=p_account AND owner_token=p_token AND lease_until>now();
 RETURN FOUND;
END $$;
