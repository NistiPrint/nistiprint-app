-- Persist rotated secrets and the corresponding token-free installation
-- projection under the same refresh lease and database transaction.
DROP FUNCTION public.persistir_tokens_integracao_sob_lease(text, uuid, jsonb, jsonb, text);

CREATE FUNCTION public.persistir_tokens_integracao_sob_lease(
    p_integration_id text,
    p_lease_token uuid,
    p_access_token jsonb,
    p_refresh_token jsonb,
    p_schema_name text DEFAULT 'public',
    p_installation_patch jsonb DEFAULT NULL
) RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path=public,pg_temp
AS $$
DECLARE
    v_lease public.integration_token_refresh_leases%ROWTYPE;
    v_secret jsonb;
    v_kind text;
BEGIN
    IF p_schema_name NOT IN ('public','private') THEN
        RAISE EXCEPTION 'Schema de secrets não permitido' USING ERRCODE='22023';
    END IF;

    SELECT * INTO v_lease
      FROM public.integration_token_refresh_leases
     WHERE integration_id=p_integration_id
     FOR UPDATE;

    IF NOT FOUND OR v_lease.lease_token IS DISTINCT FROM p_lease_token
       OR v_lease.lease_until <= now() THEN
        RETURN false;
    END IF;

    IF p_installation_patch IS NOT NULL THEN
        IF p_integration_id !~ '^[0-9]+$'
           OR jsonb_typeof(p_installation_patch) IS DISTINCT FROM 'object'
           OR p_installation_patch - ARRAY[
                'config','credentials','expires_at','last_refresh_attempt','refresh_error'
              ]::text[] <> '{}'::jsonb
           OR jsonb_typeof(p_installation_patch->'config') IS DISTINCT FROM 'object'
           OR jsonb_typeof(p_installation_patch->'credentials') IS DISTINCT FROM 'object'
           OR (p_installation_patch->'credentials') ?| ARRAY['access_token','refresh_token']
           OR NOT (p_installation_patch ?& ARRAY[
                'config','credentials','expires_at','last_refresh_attempt','refresh_error'
              ]) THEN
            RAISE EXCEPTION 'Projeção da instalação inválida' USING ERRCODE='22023';
        END IF;

        UPDATE public.installed_integrations
           SET config=p_installation_patch->'config',
               credentials=p_installation_patch->'credentials',
               access_token=NULL,
               refresh_token=NULL,
               expires_at=nullif(p_installation_patch->>'expires_at','')::timestamptz,
               last_refresh_attempt=nullif(p_installation_patch->>'last_refresh_attempt','')::timestamptz,
               refresh_error=p_installation_patch->>'refresh_error',
               updated_at=now()
         WHERE id=p_integration_id::integer;
        IF NOT FOUND THEN
            RETURN false;
        END IF;
    END IF;

    FOR v_kind, v_secret IN
        SELECT 'access_token', p_access_token WHERE p_access_token IS NOT NULL
        UNION ALL
        SELECT 'refresh_token', p_refresh_token WHERE p_refresh_token IS NOT NULL
    LOOP
        IF nullif(v_secret->>'encrypted_value','') IS NULL
           OR nullif(v_secret->>'nonce','') IS NULL
           OR nullif(v_secret->>'key_version','') IS NULL THEN
            RAISE EXCEPTION 'Credencial criptografada incompleta: %', v_kind
                USING ERRCODE='22023';
        END IF;

        EXECUTE format(
            'INSERT INTO %I.integration_secret_values(
                owner_type, owner_id, secret_kind, encrypted_value, nonce,
                key_version, created_at, updated_at, rotated_at
            ) VALUES ($1,$2,$3,$4,$5,$6,now(),now(),
                CASE WHEN $3=''refresh_token'' THEN now() ELSE NULL END
            ) ON CONFLICT(owner_type,owner_id,secret_kind) DO UPDATE SET
                encrypted_value=excluded.encrypted_value,
                nonce=excluded.nonce,
                key_version=excluded.key_version,
                updated_at=now(),
                rotated_at=CASE WHEN $3=''refresh_token'' THEN now()
                                ELSE integration_secret_values.rotated_at END',
            p_schema_name
        ) USING 'installed_integration', p_integration_id, v_kind,
                v_secret->>'encrypted_value', v_secret->>'nonce', v_secret->>'key_version';
    END LOOP;
    RETURN true;
END;
$$;

REVOKE ALL ON FUNCTION public.persistir_tokens_integracao_sob_lease(text,uuid,jsonb,jsonb,text,jsonb)
    FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.persistir_tokens_integracao_sob_lease(text,uuid,jsonb,jsonb,text,jsonb)
    TO service_role;
