CREATE TABLE IF NOT EXISTS public.integration_app_profiles (
    id BIGSERIAL PRIMARY KEY,
    module_id VARCHAR(100) NOT NULL,
    name VARCHAR(255) NOT NULL,
    environment VARCHAR(50) NOT NULL DEFAULT 'production',
    redirect_uri TEXT NOT NULL,
    auth_base_url TEXT,
    token_url TEXT,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_integration_app_profiles_default_per_module
    ON public.integration_app_profiles (module_id, environment)
    WHERE is_default = TRUE;

ALTER TABLE public.installed_integrations
    ADD COLUMN IF NOT EXISTS app_profile_id BIGINT REFERENCES public.integration_app_profiles(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS public.integration_secret_values (
    id BIGSERIAL PRIMARY KEY,
    owner_type VARCHAR(50) NOT NULL,
    owner_id VARCHAR(255) NOT NULL,
    secret_kind VARCHAR(100) NOT NULL,
    encrypted_value TEXT NOT NULL,
    nonce TEXT NOT NULL,
    key_version VARCHAR(20) NOT NULL DEFAULT 'V1',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    rotated_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_integration_secret_values_owner_kind
    ON public.integration_secret_values (owner_type, owner_id, secret_kind);

CREATE TABLE IF NOT EXISTS public.oauth_authorization_sessions (
    id BIGSERIAL PRIMARY KEY,
    state_hash VARCHAR(128) NOT NULL,
    module_id VARCHAR(100) NOT NULL,
    app_profile_id BIGINT REFERENCES public.integration_app_profiles(id) ON DELETE SET NULL,
    installed_integration_id INTEGER NOT NULL REFERENCES public.installed_integrations(id) ON DELETE CASCADE,
    redirect_uri TEXT NOT NULL,
    code_verifier_encrypted TEXT,
    return_to TEXT,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_oauth_authorization_sessions_state_hash
    ON public.oauth_authorization_sessions (state_hash);

ALTER TABLE public.integration_app_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.integration_secret_values ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.oauth_authorization_sessions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS integration_app_profiles_deny_all ON public.integration_app_profiles;
CREATE POLICY integration_app_profiles_deny_all
    ON public.integration_app_profiles
    AS RESTRICTIVE
    FOR ALL
    TO anon, authenticated
    USING (FALSE)
    WITH CHECK (FALSE);

DROP POLICY IF EXISTS oauth_authorization_sessions_deny_all ON public.oauth_authorization_sessions;
CREATE POLICY oauth_authorization_sessions_deny_all
    ON public.oauth_authorization_sessions
    AS RESTRICTIVE
    FOR ALL
    TO anon, authenticated
    USING (FALSE)
    WITH CHECK (FALSE);

DROP POLICY IF EXISTS integration_secret_values_deny_all ON public.integration_secret_values;
CREATE POLICY integration_secret_values_deny_all
    ON public.integration_secret_values
    AS RESTRICTIVE
    FOR ALL
    TO anon, authenticated
    USING (FALSE)
    WITH CHECK (FALSE);

REVOKE ALL ON TABLE public.integration_app_profiles FROM anon, authenticated;
REVOKE ALL ON TABLE public.oauth_authorization_sessions FROM anon, authenticated;
REVOKE ALL ON TABLE public.integration_secret_values FROM anon, authenticated;

GRANT ALL ON TABLE public.integration_app_profiles TO service_role;
GRANT ALL ON TABLE public.oauth_authorization_sessions TO service_role;
GRANT ALL ON TABLE public.integration_secret_values TO service_role;
