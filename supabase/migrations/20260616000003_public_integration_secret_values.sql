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

CREATE UNIQUE INDEX IF NOT EXISTS ux_public_integration_secret_values_owner_kind
    ON public.integration_secret_values (owner_type, owner_id, secret_kind);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'private'
          AND table_name = 'integration_secret_values'
    ) THEN
        INSERT INTO public.integration_secret_values (
            owner_type,
            owner_id,
            secret_kind,
            encrypted_value,
            nonce,
            key_version,
            created_at,
            updated_at,
            rotated_at
        )
        SELECT
            owner_type,
            owner_id,
            secret_kind,
            encrypted_value,
            nonce,
            key_version,
            created_at,
            updated_at,
            rotated_at
        FROM private.integration_secret_values
        ON CONFLICT (owner_type, owner_id, secret_kind) DO UPDATE SET
            encrypted_value = EXCLUDED.encrypted_value,
            nonce = EXCLUDED.nonce,
            key_version = EXCLUDED.key_version,
            updated_at = EXCLUDED.updated_at,
            rotated_at = EXCLUDED.rotated_at;
    END IF;
END $$;

ALTER TABLE public.integration_secret_values ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS integration_secret_values_deny_all ON public.integration_secret_values;
CREATE POLICY integration_secret_values_deny_all
    ON public.integration_secret_values
    AS RESTRICTIVE
    FOR ALL
    TO anon, authenticated
    USING (FALSE)
    WITH CHECK (FALSE);

REVOKE ALL ON TABLE public.integration_secret_values FROM anon, authenticated;
GRANT ALL ON TABLE public.integration_secret_values TO service_role;
