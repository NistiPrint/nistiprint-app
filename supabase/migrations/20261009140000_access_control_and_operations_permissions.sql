-- Identity and sector-scoped access for the operations center.
ALTER TABLE public.usuarios
    ADD COLUMN IF NOT EXISTS auth_user_id uuid REFERENCES auth.users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS must_change_password boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS session_version integer NOT NULL DEFAULT 0;

-- Preserve the built-in account without touching its credential hash or Auth password.
UPDATE public.usuarios
SET ativo = true, is_admin = true, must_change_password = false
WHERE lower(trim(email)) = 'admin@admin.com'
  AND (ativo IS DISTINCT FROM true
       OR is_admin IS DISTINCT FROM true
       OR must_change_password IS DISTINCT FROM false);

CREATE UNIQUE INDEX IF NOT EXISTS uq_usuarios_auth_user_id
    ON public.usuarios(auth_user_id) WHERE auth_user_id IS NOT NULL;

-- Link existing identities only when the email match is unambiguous.
WITH matches AS (
    SELECT u.id AS user_id, a.id AS auth_id,
           count(*) OVER (PARTITION BY u.id) AS auth_matches,
           count(*) OVER (PARTITION BY a.id) AS local_matches
    FROM public.usuarios u
    JOIN auth.users a ON lower(a.email) = lower(u.email)
    WHERE u.auth_user_id IS NULL
)
UPDATE public.usuarios u
SET auth_user_id = matches.auth_id
FROM matches
WHERE u.id = matches.user_id
  AND matches.auth_matches = 1
  AND matches.local_matches = 1;

-- Keep generated IDs ahead of explicitly seeded IDs before inserts.
LOCK TABLE public.recursos, public.permissoes_setor IN SHARE ROW EXCLUSIVE MODE;
DO $sequence_sync$
DECLARE
    table_name text;
    table_sequence regclass;
    current_sequence_value bigint;
    sequence_is_called boolean;
    max_id bigint;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['public.recursos', 'public.permissoes_setor'] LOOP
        table_sequence := pg_get_serial_sequence(table_name, 'id')::regclass;
        IF table_sequence IS NULL THEN
            CONTINUE;
        END IF;

        EXECUTE format('SELECT coalesce(max(id), 0) FROM %s', table_name::regclass)
            INTO max_id;
        EXECUTE format('SELECT last_value, is_called FROM %s', table_sequence)
            INTO current_sequence_value, sequence_is_called;

        IF current_sequence_value < max_id
           OR (current_sequence_value = max_id
               AND NOT sequence_is_called AND max_id > 0) THEN
            PERFORM setval(table_sequence, max_id, true);
        END IF;
    END LOOP;
END
$sequence_sync$;

INSERT INTO public.recursos (nome, descricao)
VALUES ('central_operacoes', 'Consulta global de operações, filas e execuções'),
       ('auditoria', 'Consulta de eventos de auditoria')
ON CONFLICT (nome) DO NOTHING;

-- The legacy "Administrativo" sector bypassed every resource permission.
-- Freeze those previous operational grants explicitly, while keeping access
-- to the new global operations and audit areas opt-in by sector.
UPDATE public.permissoes_setor ps
SET pode_ler = true, pode_criar = true, pode_editar = true, pode_excluir = true
FROM public.setores s, public.recursos r
WHERE ps.setor_id = s.id
  AND ps.recurso_id = r.id
  AND lower(trim(s.nome)) = 'administrativo'
  AND r.nome NOT IN ('central_operacoes', 'auditoria')
  AND (ps.pode_ler IS DISTINCT FROM true
       OR ps.pode_criar IS DISTINCT FROM true
       OR ps.pode_editar IS DISTINCT FROM true
       OR ps.pode_excluir IS DISTINCT FROM true);

INSERT INTO public.permissoes_setor
    (setor_id, recurso_id, pode_ler, pode_criar, pode_editar, pode_excluir)
SELECT s.id, r.id, true, true, true, true
FROM public.setores s
CROSS JOIN public.recursos r
WHERE lower(trim(s.nome)) = 'administrativo'
  AND r.nome NOT IN ('central_operacoes', 'auditoria')
  AND NOT EXISTS (
      SELECT 1 FROM public.permissoes_setor ps
      WHERE ps.setor_id = s.id AND ps.recurso_id = r.id
  );

CREATE TABLE IF NOT EXISTS public.permissoes_demanda_setor (
    setor_id integer PRIMARY KEY REFERENCES public.setores(id) ON DELETE CASCADE,
    campos_editaveis jsonb NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(campos_editaveis) = 'array'),
    acoes_permitidas jsonb NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(acoes_permitidas) = 'array'),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- Freeze the existing effective sector defaults/configuration by sector ID.
DO $migration$
DECLARE
    sector_row record;
    configured jsonb;
    default_fields jsonb := '{
      "controle de produção":["capas_impressas_qtd","capas_produzidas_qtd","capas_prontas_retirada_qtd"],
      "miolos":["miolos_prontos_retirada_qtd"],
      "capas":["capas_produzidas_qtd"],
      "expedição":["expedicao_capas_retiradas_qtd","expedicao_miolos_retirados_qtd"],
      "administrativo":["capas_impressas_qtd","capas_produzidas_qtd","capas_prontas_retirada_qtd","miolos_prontos_retirada_qtd","expedicao_capas_retiradas_qtd","expedicao_miolos_retirados_qtd"]
    }'::jsonb;
    default_actions jsonb := '{
      "controle de produção":["delete_demand","revert_finalize_item"],
      "miolos":[],
      "capas":[],
      "expedição":["finalize_item","collect_demand"],
      "administrativo":["finalize_item","collect_demand","delete_demand","revert_finalize_item"]
    }'::jsonb;
    sector_key text;
BEGIN
    SELECT valor INTO configured FROM public.configuracoes_aplicacao
    WHERE nome = 'demanda_dashboard_permissions'
      AND entidade_tipo IS NULL AND entidade_id IS NULL
    ORDER BY updated_at DESC NULLS LAST LIMIT 1;

    FOR sector_row IN SELECT id, lower(nome) AS nome FROM public.setores LOOP
        sector_key := sector_row.nome;
        IF configured IS NOT NULL AND jsonb_typeof(configured->'fields') = 'object'
           AND configured->'fields' ? sector_key THEN
            INSERT INTO public.permissoes_demanda_setor(setor_id, campos_editaveis, acoes_permitidas)
            VALUES (sector_row.id, configured->'fields'->sector_key,
                    CASE WHEN jsonb_typeof(configured->'actions') = 'object'
                              AND configured->'actions' ? sector_key
                         THEN configured->'actions'->sector_key ELSE '[]'::jsonb END)
            ON CONFLICT (setor_id) DO NOTHING;
        ELSE
            INSERT INTO public.permissoes_demanda_setor(setor_id, campos_editaveis, acoes_permitidas)
            VALUES (sector_row.id, coalesce(default_fields->sector_key, '[]'::jsonb),
                    coalesce(default_actions->sector_key, '[]'::jsonb))
            ON CONFLICT (setor_id) DO NOTHING;
        END IF;
    END LOOP;
END
$migration$;

-- A terminal event has one durable notification even if concurrent workers
-- race to finalize the same operation.
UPDATE public.notificacoes
SET owner_user_id = (destinatarios->>'user_id')::integer
WHERE owner_user_id IS NULL
  AND jsonb_typeof(destinatarios) = 'object'
  AND coalesce(destinatarios->>'user_id', '') ~ '^[0-9]+$';

ALTER TABLE public.notificacoes
    ADD COLUMN IF NOT EXISTS terminal_notification boolean NOT NULL DEFAULT false;

-- Keep every existing notification while choosing one canonical terminal
-- row per operation/event for the uniqueness guarantee going forward.
WITH ranked AS (
    SELECT id,
           row_number() OVER (
               PARTITION BY operacao_id, event_type
               ORDER BY created_at, id
           ) AS position
    FROM public.notificacoes
    WHERE operacao_id IS NOT NULL
      AND event_type IN ('operation.completed', 'operation.failed')
)
UPDATE public.notificacoes n
SET terminal_notification = (ranked.position = 1)
FROM ranked
WHERE ranked.id = n.id
  AND n.terminal_notification IS DISTINCT FROM (ranked.position = 1);

CREATE UNIQUE INDEX IF NOT EXISTS uq_notificacoes_operacao_terminal
    ON public.notificacoes(operacao_id, event_type)
    WHERE terminal_notification = true;

ALTER TABLE public.permissoes_demanda_setor ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.permissoes_demanda_setor FROM PUBLIC, anon, authenticated;
GRANT ALL ON public.permissoes_demanda_setor TO service_role;
