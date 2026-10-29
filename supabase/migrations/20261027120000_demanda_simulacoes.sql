-- Cenários de demonstração são independentes de demandas, pedidos e estoque.
CREATE TABLE IF NOT EXISTS public.demanda_simulacoes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    pedido_ids integer[] NOT NULL,
    snapshot jsonb NOT NULL,
    state jsonb NOT NULL,
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (jsonb_typeof(snapshot) = 'object' AND jsonb_typeof(state) = 'object')
);

CREATE TABLE IF NOT EXISTS public.demanda_simulacao_eventos (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    simulacao_id uuid NOT NULL REFERENCES public.demanda_simulacoes(id) ON DELETE CASCADE,
    operation_id uuid NOT NULL UNIQUE,
    request_hash text NOT NULL,
    action text NOT NULL,
    actor text NOT NULL,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS demanda_simulacao_eventos_simulacao_idx
    ON public.demanda_simulacao_eventos(simulacao_id, id);

ALTER TABLE public.demanda_simulacoes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.demanda_simulacao_eventos ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.demanda_simulacoes, public.demanda_simulacao_eventos FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.demanda_simulacoes, public.demanda_simulacao_eventos TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.demanda_simulacao_eventos_id_seq TO service_role;

CREATE OR REPLACE FUNCTION public.demanda_simulacao_fingerprint(p_pedido_ids integer[])
RETURNS text LANGUAGE sql VOLATILE SET search_path = public, pg_temp AS $$
    SELECT md5(
        coalesce((SELECT jsonb_agg(jsonb_build_object(
                    'id', p.id, 'numero', p.numero_pedido,
                    'codigo', p.codigo_pedido_externo, 'cliente', p.cliente_nome,
                    'marketplace', p.marketplace_order_id,
                    'situacao', p.situacao_pedido_id, 'despachado_em', p.despachado_em
                  ) ORDER BY p.id)::text
                  FROM public.pedidos p WHERE p.id = ANY(p_pedido_ids)), '[]')
        || '|' || coalesce((SELECT jsonb_agg(to_jsonb(c) ORDER BY to_jsonb(c)::text)::text
                          FROM public.despacho_consolidar_pedidos(p_pedido_ids) c), '[]')
    );
$$;

CREATE OR REPLACE FUNCTION public.demanda_simulacao_criar(
    p_pedido_ids integer[], p_fingerprint text, p_snapshot jsonb, p_state jsonb, p_actor text
) RETURNS public.demanda_simulacoes
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
DECLARE v_row public.demanda_simulacoes%ROWTYPE;
BEGIN
    IF p_pedido_ids IS NULL OR cardinality(p_pedido_ids) = 0
       OR cardinality(p_pedido_ids) <> (SELECT count(DISTINCT u.pedido_id) FROM unnest(p_pedido_ids) AS u(pedido_id))
       OR p_snapshot IS NULL OR p_state IS NULL
       OR jsonb_typeof(p_snapshot) <> 'object' OR jsonb_typeof(p_state) <> 'object'
       OR p_fingerprint IS NULL THEN
        RAISE EXCEPTION 'SIMULACAO_INVALIDA' USING ERRCODE = '22023';
    END IF;
    PERFORM 1 FROM public.pedidos WHERE id = ANY(p_pedido_ids) ORDER BY id FOR SHARE;
    IF (SELECT count(DISTINCT id) FROM public.vw_pedidos_pendentes_despacho
        WHERE id = ANY(p_pedido_ids)) <> cardinality(p_pedido_ids)
       OR public.demanda_simulacao_fingerprint(p_pedido_ids) <> p_fingerprint THEN
        RAISE EXCEPTION 'SIMULACAO_ORIGEM_ALTERADA' USING ERRCODE = '40001';
    END IF;
    INSERT INTO public.demanda_simulacoes(pedido_ids, snapshot, state, created_by)
    VALUES(p_pedido_ids, p_snapshot, p_state, p_actor) RETURNING * INTO v_row;
    RETURN v_row;
END;
$$;

CREATE OR REPLACE FUNCTION public.demanda_simulacao_alterar(
    p_id uuid, p_expected_version integer, p_state jsonb, p_action text,
    p_details jsonb, p_operation_id uuid, p_request_hash text, p_actor text
) RETURNS public.demanda_simulacoes
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
DECLARE v_row public.demanda_simulacoes%ROWTYPE; v_existing record;
BEGIN
    SELECT * INTO v_row FROM public.demanda_simulacoes WHERE id = p_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'SIMULACAO_NAO_ENCONTRADA' USING ERRCODE = 'P0002'; END IF;
    SELECT * INTO v_existing FROM public.demanda_simulacao_eventos WHERE operation_id = p_operation_id;
    IF FOUND THEN
        IF v_existing.simulacao_id <> p_id OR v_existing.request_hash <> p_request_hash THEN
            RAISE EXCEPTION 'SIMULACAO_OPERACAO_REUTILIZADA' USING ERRCODE = '23505';
        END IF;
        RETURN v_row;
    END IF;
    IF v_row.version <> p_expected_version THEN
        RAISE EXCEPTION 'SIMULACAO_VERSAO_CONFLITANTE' USING ERRCODE = '40001';
    END IF;
    IF p_state IS NULL OR jsonb_typeof(p_state) <> 'object' OR p_operation_id IS NULL
       OR p_request_hash IS NULL OR p_action IS NULL THEN
        RAISE EXCEPTION 'SIMULACAO_INVALIDA' USING ERRCODE = '22023';
    END IF;
    UPDATE public.demanda_simulacoes SET state = p_state, version = version + 1, updated_at = now()
      WHERE id = p_id RETURNING * INTO v_row;
    INSERT INTO public.demanda_simulacao_eventos
      (simulacao_id, operation_id, request_hash, action, actor, details)
    VALUES(p_id, p_operation_id, p_request_hash, p_action, p_actor, coalesce(p_details, '{}'::jsonb));
    RETURN v_row;
END;
$$;

CREATE OR REPLACE FUNCTION public.demanda_simulacao_excluir(p_id uuid, p_expected_version integer)
RETURNS boolean LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
DECLARE v_version integer;
BEGIN
    SELECT version INTO v_version FROM public.demanda_simulacoes WHERE id = p_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'SIMULACAO_NAO_ENCONTRADA' USING ERRCODE = 'P0002'; END IF;
    IF v_version <> p_expected_version THEN
        RAISE EXCEPTION 'SIMULACAO_VERSAO_CONFLITANTE' USING ERRCODE = '40001';
    END IF;
    DELETE FROM public.demanda_simulacoes WHERE id = p_id;
    RETURN true;
END;
$$;

REVOKE ALL ON FUNCTION public.demanda_simulacao_fingerprint(integer[]) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.demanda_simulacao_criar(integer[],text,jsonb,jsonb,text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.demanda_simulacao_alterar(uuid,integer,jsonb,text,jsonb,uuid,text,text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.demanda_simulacao_excluir(uuid,integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.demanda_simulacao_fingerprint(integer[]) TO service_role;
GRANT EXECUTE ON FUNCTION public.demanda_simulacao_criar(integer[],text,jsonb,jsonb,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.demanda_simulacao_alterar(uuid,integer,jsonb,text,jsonb,uuid,text,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.demanda_simulacao_excluir(uuid,integer) TO service_role;
NOTIFY pgrst, 'reload schema';
