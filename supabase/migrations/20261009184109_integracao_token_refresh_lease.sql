-- Lease independente da tipagem histórica do ID da integração, usado por todo refresh.
CREATE TABLE IF NOT EXISTS public.integration_token_refresh_leases (
    integration_id text PRIMARY KEY,
    lease_token uuid NOT NULL,
    lease_until timestamptz NOT NULL,
    acquired_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.integration_token_refresh_leases ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.integration_token_refresh_leases FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.integration_token_refresh_leases TO service_role;

CREATE OR REPLACE FUNCTION public.claim_integration_token_refresh(
    p_integration_id text,p_lease_token uuid,p_lease_seconds integer DEFAULT 900
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE v_claimed boolean;
BEGIN
    IF nullif(trim(p_integration_id),'') IS NULL OR p_lease_token IS NULL
       OR p_lease_seconds<30 OR p_lease_seconds>1800 THEN
        RAISE EXCEPTION 'Lease de renovação inválido' USING ERRCODE='22023';
    END IF;
    INSERT INTO public.integration_token_refresh_leases(integration_id,lease_token,lease_until,acquired_at)
    VALUES(p_integration_id,p_lease_token,now()+make_interval(secs=>p_lease_seconds),now())
    ON CONFLICT(integration_id) DO UPDATE SET lease_token=excluded.lease_token,
        lease_until=excluded.lease_until,acquired_at=now()
    WHERE public.integration_token_refresh_leases.lease_until<=now()
       OR public.integration_token_refresh_leases.lease_token=p_lease_token
    RETURNING true INTO v_claimed;
    RETURN coalesce(v_claimed,false);
END; $$;

CREATE OR REPLACE FUNCTION public.release_integration_token_refresh(
    p_integration_id text,p_lease_token uuid
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE v_count integer;
BEGIN
    DELETE FROM public.integration_token_refresh_leases
     WHERE integration_id=p_integration_id AND lease_token=p_lease_token;
    GET DIAGNOSTICS v_count=ROW_COUNT;
    RETURN v_count=1;
END; $$;

REVOKE ALL ON FUNCTION public.claim_integration_token_refresh(text,uuid,integer) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.release_integration_token_refresh(text,uuid) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.claim_integration_token_refresh(text,uuid,integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.release_integration_token_refresh(text,uuid) TO service_role;
