CREATE TABLE public.marketplace_pedidos_coleta (
 account_id integer PRIMARY KEY REFERENCES public.installed_integrations(id),
 window_start timestamptz,window_end timestamptz,cursor jsonb NOT NULL DEFAULT '{}'::jsonb,
 status text NOT NULL DEFAULT 'idle',owner_token uuid,lease_until timestamptz NOT NULL DEFAULT '-infinity',
 last_complete_at timestamptz,next_attempt_at timestamptz NOT NULL DEFAULT now(),error_code text,
 updated_at timestamptz NOT NULL DEFAULT now());
ALTER TABLE public.marketplace_pedidos_coleta ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.marketplace_pedidos_coleta FROM PUBLIC,anon,authenticated;
GRANT SELECT ON public.marketplace_pedidos_coleta TO service_role;

CREATE FUNCTION public.marketplace_pedidos_claim(p_account integer) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE result jsonb;
BEGIN
 INSERT INTO public.marketplace_pedidos_coleta(account_id) VALUES(p_account) ON CONFLICT DO NOTHING;
 UPDATE public.marketplace_pedidos_coleta SET owner_token=gen_random_uuid(),lease_until=now()+interval '5 minutes',
  window_end=CASE WHEN status IN ('idle','complete') THEN now() ELSE window_end END,
  window_start=CASE WHEN status IN ('idle','complete') THEN now()-interval '72 hours' ELSE window_start END,
  cursor=CASE WHEN status IN ('idle','complete') THEN '{}'::jsonb ELSE cursor END,
  status='running',error_code=NULL,updated_at=now()
 WHERE account_id=p_account AND lease_until<now() AND next_attempt_at<=now()
 RETURNING jsonb_build_object('owner_token',owner_token,'window_start',window_start,'window_end',window_end,'cursor',cursor) INTO result;
 RETURN coalesce(result,jsonb_build_object('status','busy'));
END $$;

CREATE FUNCTION public.marketplace_pedidos_finish(p_account integer,p_token uuid,p_cursor jsonb,p_complete boolean,p_error text DEFAULT NULL,p_retry_after integer DEFAULT NULL)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
BEGIN
 UPDATE public.marketplace_pedidos_coleta SET cursor=CASE WHEN p_error IS NULL THEN coalesce(p_cursor,'{}') ELSE cursor END,
  status=CASE WHEN p_error IN ('provider_pagination_limit','account_identity_missing','provider_access_forbidden','credential_action_required') THEN 'unavailable' WHEN p_error IS NOT NULL THEN 'failed' WHEN p_complete THEN 'complete' ELSE 'available' END,
  last_complete_at=CASE WHEN p_complete AND p_error IS NULL THEN now() ELSE last_complete_at END,
  next_attempt_at=CASE WHEN p_error IN ('provider_pagination_limit','account_identity_missing','provider_access_forbidden','credential_action_required') THEN 'infinity'::timestamptz WHEN p_error IS NOT NULL THEN now()+make_interval(secs=>greatest(300,coalesce(p_retry_after,0))) WHEN p_complete THEN now()+interval '15 minutes' ELSE now() END,
  error_code=left(p_error,100),owner_token=NULL,lease_until='-infinity',updated_at=now()
 WHERE account_id=p_account AND owner_token=p_token AND lease_until>now();
 RETURN FOUND;
END $$;
REVOKE ALL ON FUNCTION public.marketplace_pedidos_claim(integer),public.marketplace_pedidos_finish(integer,uuid,jsonb,boolean,text,integer) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.marketplace_pedidos_claim(integer),public.marketplace_pedidos_finish(integer,uuid,jsonb,boolean,text,integer) TO service_role;

CREATE FUNCTION public.marketplace_pedidos_backfill(p_account integer,p_days integer DEFAULT 90)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
BEGIN
 IF p_days<1 OR p_days>90 THEN RAISE EXCEPTION 'INVALID_BACKFILL_WINDOW' USING ERRCODE='22023'; END IF;
 INSERT INTO public.marketplace_pedidos_coleta(account_id) VALUES(p_account) ON CONFLICT DO NOTHING;
 UPDATE public.marketplace_pedidos_coleta SET window_start=now()-make_interval(days=>p_days),window_end=now(),
  cursor='{}',status='available',owner_token=NULL,lease_until='-infinity',next_attempt_at=now(),error_code=NULL,updated_at=now()
 WHERE account_id=p_account AND lease_until<now() AND status IN ('idle','complete','failed','unavailable');
 RETURN FOUND;
END $$;
REVOKE ALL ON FUNCTION public.marketplace_pedidos_backfill(integer,integer) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.marketplace_pedidos_backfill(integer,integer) TO service_role;
