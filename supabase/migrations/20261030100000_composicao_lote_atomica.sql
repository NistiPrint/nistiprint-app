-- Atomic batch BOM edits, idempotency, and a durable cost-recalculation queue.
CREATE TABLE IF NOT EXISTS public.bom_lotes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key text NOT NULL UNIQUE,
    request_hash text NOT NULL,
    request_data jsonb NOT NULL,
    produto_ids integer[] NOT NULL,
    usuario_id integer,
    revisao text NOT NULL,
    resultado jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.bom_lote_recalculos (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lote_id uuid NOT NULL REFERENCES public.bom_lotes(id) ON DELETE CASCADE,
    produto_ids integer[] NOT NULL,
    status text NOT NULL DEFAULT 'pendente' CHECK (status IN ('pendente','processando','concluido','falhou')),
    tentativas integer NOT NULL DEFAULT 0,
    ultimo_erro text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_bom_lote_recalculos_pendentes
    ON public.bom_lote_recalculos(created_at) WHERE status IN ('pendente','falhou');

ALTER TABLE public.bom_lotes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.bom_lote_recalculos ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.bom_lotes, public.bom_lote_recalculos FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON public.bom_lotes, public.bom_lote_recalculos TO service_role;

CREATE OR REPLACE FUNCTION public.aplicar_composicao_lote(
    p_produto_ids integer[],
    p_operacoes jsonb,
    p_tokens jsonb,
    p_expected_composicoes jsonb,
    p_expected_products jsonb,
    p_revisao text,
    p_idempotency_key text,
    p_usuario_id integer
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
DECLARE
    v_pid integer;
    v_op jsonb;
    v_product public.produtos%ROWTYPE;
    v_component public.produtos%ROWTYPE;
    v_current jsonb;
    v_expected jsonb;
    v_request jsonb;
    v_hash text;
    v_existing public.bom_lotes%ROWTYPE;
    v_lote_id uuid;
    v_recalculo_id uuid;
    v_rows integer;
    v_inserted integer := 0;
    v_removed integer := 0;
    v_affected integer[] := ARRAY[]::integer[];
    v_line record;
    v_new_line_id integer;
    v_pending jsonb;
    v_pending_payload jsonb;
    v_pending_pk text;
    v_pending_columns text;
    v_pending_select text;
    v_old_line_id integer;
BEGIN
    IF coalesce(array_length(p_produto_ids, 1), 0) < 1
       OR array_length(p_produto_ids, 1) > 100
       OR jsonb_typeof(p_operacoes) IS DISTINCT FROM 'array'
       OR jsonb_array_length(p_operacoes) = 0
       OR jsonb_typeof(p_expected_composicoes) IS DISTINCT FROM 'object'
       OR jsonb_typeof(p_expected_products) IS DISTINCT FROM 'object'
       OR p_idempotency_key IS NULL OR length(p_idempotency_key) < 16 OR length(p_idempotency_key) > 128 THEN
        RAISE EXCEPTION 'BOM_BATCH_INVALID_REQUEST' USING ERRCODE = '22023';
    END IF;
    IF cardinality(ARRAY(SELECT DISTINCT x FROM unnest(p_produto_ids) x)) <> cardinality(p_produto_ids) THEN
        RAISE EXCEPTION 'BOM_BATCH_DUPLICATE_PRODUCT' USING ERRCODE = '22023';
    END IF;

    v_request := jsonb_build_object('produto_ids', p_produto_ids, 'operacoes', p_operacoes,
      'tokens', p_tokens, 'expected_composicoes', p_expected_composicoes,
      'expected_products', p_expected_products, 'revisao', p_revisao, 'usuario_id', p_usuario_id);
    v_hash := md5(v_request::text);

    -- Match the advisory lock used by the existing BOM cycle and family guards.
    PERFORM pg_advisory_xact_lock(1250269001, 1);
    SELECT * INTO v_existing FROM public.bom_lotes WHERE idempotency_key = p_idempotency_key FOR UPDATE;
    IF FOUND THEN
        IF v_existing.request_hash <> v_hash THEN
            RAISE EXCEPTION 'BOM_IDEMPOTENCY_CONFLICT' USING ERRCODE = '23505';
        END IF;
        RETURN v_existing.resultado;
    END IF;

    IF (SELECT count(*) FROM public.produtos WHERE id = ANY(p_produto_ids)) <> cardinality(p_produto_ids) THEN
        RAISE EXCEPTION 'BOM_PRODUCT_NOT_FOUND' USING ERRCODE = 'P0002';
    END IF;

    -- Compare complete effective snapshots after taking the same lock as BOM writers.
    FOREACH v_pid IN ARRAY p_produto_ids LOOP
        SELECT * INTO STRICT v_product FROM public.produtos WHERE id = v_pid FOR UPDATE;
        IF (p_expected_products->(v_pid::text)->>'parent_id')::integer IS DISTINCT FROM v_product.parent_id
           OR coalesce((p_expected_products->(v_pid::text)->>'herdar_bom_pai')::boolean, false) IS DISTINCT FROM coalesce(v_product.herdar_bom_pai, false)
           OR p_expected_products->(v_pid::text)->>'tipo_material' IS DISTINCT FROM v_product.tipo_material
           OR p_expected_products->(v_pid::text)->>'formato' IS DISTINCT FROM v_product.formato THEN
            RAISE EXCEPTION 'BOM_CONFLICT:%', v_pid USING ERRCODE = '40001';
        END IF;
        IF v_product.tipo_produto = 'SERVICO'
           OR EXISTS (SELECT 1 FROM public.produtos child WHERE child.parent_id=v_pid) THEN
            RAISE EXCEPTION 'BOM_PRODUCT_NOT_ELIGIBLE:%', v_pid USING ERRCODE = '22023';
        END IF;
        SELECT coalesce(jsonb_agg(jsonb_build_object(
            'componente_id', b.componente_id,
            'quantidade_necessaria', b.quantidade_necessaria::numeric,
            'unidade_medida', coalesce(b.unidade_medida, 'un'),
            'is_inherited', coalesce(b.is_inherited, false),
            'grupo', b.grupo,
            'grupo_persistido', f.grupo,
            'line_id', b.id,
            'produto_pai_id', b.produto_pai_id
        ) ORDER BY b.componente_id), '[]'::jsonb)
          INTO v_current FROM public.bom_efetiva_produto(v_pid) b
          LEFT JOIN public.ficha_tecnica f ON f.id=b.id;
        SELECT coalesce(jsonb_agg(jsonb_build_object(
            'componente_id', (x->>'componente_id')::integer,
            'quantidade_necessaria', (x->>'quantidade_necessaria')::numeric,
            'unidade_medida', coalesce(x->>'unidade_medida', 'un'),
            'is_inherited', coalesce((x->>'is_inherited')::boolean, false),
            'grupo', x->'grupo',
            'grupo_persistido', x->'grupo_persistido',
            'line_id', x->'line_id',
            'produto_pai_id', x->'produto_pai_id'
        ) ORDER BY (x->>'componente_id')::integer), '[]'::jsonb)
          INTO v_expected
          FROM jsonb_array_elements(coalesce(p_expected_composicoes->v_pid::text, '[]'::jsonb)) x;
        IF v_current IS DISTINCT FROM v_expected THEN
            RAISE EXCEPTION 'BOM_CONFLICT:%', v_pid USING ERRCODE = '40001';
        END IF;
    END LOOP;

    -- Reject duplicate cells, invalid quantities, and references outside the row/column sets.
    IF EXISTS (SELECT 1 FROM jsonb_array_elements(p_operacoes) a
               GROUP BY (a->>'produto_id')::integer, (a->>'componente_id')::integer HAVING count(*) > 1) THEN
        RAISE EXCEPTION 'BOM_DUPLICATE_OPERATION' USING ERRCODE = '22023';
    END IF;
    FOR v_op IN SELECT value FROM jsonb_array_elements(p_operacoes) LOOP
        IF NOT ((v_op->>'produto_id')::integer = ANY(p_produto_ids))
           OR (v_op->>'componente_id')::integer IS NULL
           OR v_op->>'acao' NOT IN ('definir','remover') THEN
            RAISE EXCEPTION 'BOM_INVALID_OPERATION' USING ERRCODE = '22023';
        END IF;
        IF v_op->>'acao' = 'definir' THEN
            IF (v_op->>'quantidade') !~ '^([0-9]+)(\.[0-9]{1,6})?$'
               OR (v_op->>'quantidade')::numeric <= 0 OR (v_op->>'quantidade')::numeric >= 1000000000 THEN
                RAISE EXCEPTION 'BOM_INVALID_QUANTITY:%:%', v_op->>'produto_id', v_op->>'componente_id' USING ERRCODE = '22023';
            END IF;
        END IF;
        IF NOT ((v_op->>'produto_id')::integer = ANY(v_affected)) THEN
            v_affected := array_append(v_affected, (v_op->>'produto_id')::integer);
        END IF;
        IF NOT EXISTS (SELECT 1 FROM public.produtos WHERE id = (v_op->>'componente_id')::integer) THEN
            RAISE EXCEPTION 'BOM_COMPONENT_NOT_FOUND:%', v_op->>'componente_id' USING ERRCODE = 'P0002';
        END IF;
        SELECT * INTO STRICT v_product FROM public.produtos WHERE id = (v_op->>'produto_id')::integer;
        SELECT * INTO STRICT v_component FROM public.produtos WHERE id = (v_op->>'componente_id')::integer;
        IF v_component.tipo_produto = 'SERVICO' THEN
            RAISE EXCEPTION 'BOM_COMPONENT_NOT_ELIGIBLE:%', v_component.id USING ERRCODE = '22023';
        END IF;
        IF v_product.formato = 'kit' THEN
            IF v_component.tipo_produto <> 'PRODUTO_ACABADO' OR v_component.formato = 'kit' THEN
                RAISE EXCEPTION 'BOM_KIT_COMPONENT_INVALID:%', v_component.id USING ERRCODE = '22023';
            END IF;
        ELSIF v_component.tipo_produto = 'PRODUTO_ACABADO' THEN
            RAISE EXCEPTION 'BOM_FINISHED_COMPONENT_INVALID:%', v_component.id USING ERRCODE = '22023';
        END IF;
    END LOOP;

    INSERT INTO public.bom_lotes(idempotency_key, request_hash, request_data, produto_ids, usuario_id, revisao)
    VALUES (p_idempotency_key, v_hash, v_request, p_produto_ids, p_usuario_id, p_revisao)
    RETURNING id INTO v_lote_id;

    DROP TABLE IF EXISTS pg_temp._bom_lote_pending_source;
    CREATE TEMP TABLE _bom_lote_pending_source ON COMMIT DROP AS
    SELECT target.produto_id AS destino_id,
           (line->>'componente_id')::integer AS componente_id,
           (line->>'line_id')::integer AS linha_origem_id,
           coalesce((line->>'is_inherited')::boolean, false) AS herdada,
           to_jsonb(pending) AS dados
      FROM unnest(p_produto_ids) AS target(produto_id)
      CROSS JOIN LATERAL jsonb_array_elements(p_expected_composicoes->target.produto_id::text) AS line
      JOIN public.ficha_tecnica_classificacao_pendente pending
        ON pending.ficha_tecnica_id=(line->>'line_id')::integer;

    -- Remove all changed edges first so batch-created cycles are checked against the final graph.
    FOR v_op IN SELECT value FROM jsonb_array_elements(p_operacoes) LOOP
        DELETE FROM public.ficha_tecnica
         WHERE produto_pai_id = (v_op->>'produto_id')::integer
           AND componente_id = (v_op->>'componente_id')::integer;
        GET DIAGNOSTICS v_rows = ROW_COUNT;
        v_removed := v_removed + v_rows;
    END LOOP;

    -- Materialize inherited BOMs only for products with actual edits. Preserve every
    -- effective component and its group, unit, and quantity in the same transaction.
    FOREACH v_pid IN ARRAY v_affected LOOP
        SELECT * INTO STRICT v_product FROM public.produtos WHERE id = v_pid FOR UPDATE;
        IF v_product.parent_id IS NOT NULL AND coalesce(v_product.herdar_bom_pai, false) THEN
            UPDATE public.produtos SET herdar_bom_pai = false WHERE id = v_pid;
        END IF;
    END LOOP;

    -- Build final rows for each edited product from the pre-edit snapshot plus operations.
    -- Inherited rows are copied before the parent relation is changed by using the snapshot JSON.
    FOREACH v_pid IN ARRAY v_affected LOOP
        SELECT * INTO STRICT v_product FROM public.produtos WHERE id = v_pid FOR UPDATE;
        IF EXISTS (SELECT 1 FROM jsonb_array_elements(p_expected_composicoes->v_pid::text) x
                   WHERE coalesce((x->>'is_inherited')::boolean, false)) THEN
            DELETE FROM public.ficha_tecnica WHERE produto_pai_id = v_pid;
            FOR v_line IN SELECT value AS row FROM jsonb_array_elements(p_expected_composicoes->v_pid::text) LOOP
                IF NOT EXISTS (SELECT 1 FROM jsonb_array_elements(p_operacoes) o
                    WHERE (o->>'produto_id')::integer = v_pid
                      AND (o->>'componente_id')::integer = (v_line.row->>'componente_id')::integer
                      AND o->>'acao' = 'remover') THEN
                    INSERT INTO public.ficha_tecnica(produto_pai_id, componente_id, quantidade_necessaria,
                        unidade_medida, grupo, sku_produto_pai, sku_componente)
                    SELECT v_pid, (v_line.row->>'componente_id')::integer,
                        coalesce((SELECT (o->>'quantidade')::numeric FROM jsonb_array_elements(p_operacoes) o
                          WHERE (o->>'produto_id')::integer=v_pid AND (o->>'componente_id')::integer=(v_line.row->>'componente_id')::integer AND o->>'acao'='definir'),
                          (v_line.row->>'quantidade_necessaria')::numeric),
                        coalesce(v_line.row->>'unidade_medida','un'), v_line.row->>'grupo_persistido', v_product.sku, comp.sku
                      FROM public.produtos comp WHERE comp.id=(v_line.row->>'componente_id')::integer;
                    GET DIAGNOSTICS v_rows = ROW_COUNT;
                    v_inserted := v_inserted + v_rows;
                END IF;
            END LOOP;
            -- Add new components absent from the prior effective composition.
            FOR v_op IN SELECT value FROM jsonb_array_elements(p_operacoes)
              WHERE (value->>'produto_id')::integer=v_pid AND value->>'acao'='definir'
                AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(p_expected_composicoes->v_pid::text) old
                  WHERE (old->>'componente_id')::integer=(value->>'componente_id')::integer)
            LOOP
                INSERT INTO public.ficha_tecnica(produto_pai_id, componente_id, quantidade_necessaria, unidade_medida, sku_produto_pai, sku_componente)
                SELECT v_pid, comp.id, (v_op->>'quantidade')::numeric, coalesce(u.abreviacao,'un'), v_product.sku, comp.sku
                  FROM public.produtos comp LEFT JOIN public.unidades_medida u ON u.id=comp.unidade_medida_id
                 WHERE comp.id=(v_op->>'componente_id')::integer;
                v_inserted := v_inserted + 1;
            END LOOP;
        ELSE
            FOR v_op IN SELECT value FROM jsonb_array_elements(p_operacoes)
              WHERE (value->>'produto_id')::integer=v_pid AND value->>'acao'='definir'
            LOOP
                SELECT * INTO STRICT v_component FROM public.produtos WHERE id=(v_op->>'componente_id')::integer;
                INSERT INTO public.ficha_tecnica(produto_pai_id, componente_id, quantidade_necessaria,
                    unidade_medida, grupo, sku_produto_pai, sku_componente)
                SELECT v_pid, v_component.id, (v_op->>'quantidade')::numeric,
                    coalesce((SELECT old->>'unidade_medida' FROM jsonb_array_elements(p_expected_composicoes->v_pid::text) old
                      WHERE (old->>'componente_id')::integer=v_component.id), 'un'),
                    (SELECT old->>'grupo_persistido' FROM jsonb_array_elements(p_expected_composicoes->v_pid::text) old
                      WHERE (old->>'componente_id')::integer=v_component.id), v_product.sku, v_component.sku;
                v_inserted := v_inserted + 1;
            END LOOP;
        END IF;
    END LOOP;

    -- Keep pending group reviews attached to the new line IDs after materialization.
    SELECT a.attname INTO v_pending_pk
      FROM pg_index i
      JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=ANY(i.indkey)
     WHERE i.indrelid='public.ficha_tecnica_classificacao_pendente'::regclass
       AND i.indisprimary LIMIT 1;
    SELECT string_agg(format('%I', a.attname), ',' ORDER BY a.attnum),
           string_agg(format('cloned.%I', a.attname), ',' ORDER BY a.attnum)
      INTO v_pending_columns, v_pending_select
      FROM pg_attribute a
     WHERE a.attrelid='public.ficha_tecnica_classificacao_pendente'::regclass
       AND a.attnum > 0 AND NOT a.attisdropped
       AND (a.attname IS DISTINCT FROM v_pending_pk OR (
            a.attidentity='' AND a.attgenerated='' AND NOT EXISTS (
                SELECT 1 FROM pg_attrdef d WHERE d.adrelid=a.attrelid AND d.adnum=a.attnum
            )))
       AND a.attgenerated='' AND a.attidentity='';
    FOREACH v_pid IN ARRAY v_affected LOOP
        FOR v_line IN
            SELECT * FROM _bom_lote_pending_source WHERE destino_id=v_pid
        LOOP
            v_old_line_id := v_line.linha_origem_id;
            IF v_old_line_id IS NULL THEN CONTINUE; END IF;
            SELECT id INTO v_new_line_id FROM public.ficha_tecnica
             WHERE produto_pai_id=v_pid AND componente_id=v_line.componente_id;
            v_pending := v_line.dados;
            IF v_new_line_id IS NULL THEN
            ELSIF v_line.herdada AND v_pending->>'resolvido_em' IS NOT NULL THEN
                CONTINUE;
            ELSIF NOT v_line.herdada AND v_new_line_id=v_old_line_id THEN
                CONTINUE;
            ELSE
                v_pending_payload := jsonb_set(jsonb_set(v_pending - v_pending_pk,
                  '{ficha_tecnica_id}', to_jsonb(v_new_line_id), true),
                  '{produto_pai_id}', to_jsonb(v_pid), true);
                EXECUTE format(
                  'INSERT INTO public.ficha_tecnica_classificacao_pendente (%s) SELECT %s FROM jsonb_populate_record(NULL::public.ficha_tecnica_classificacao_pendente, $1) AS cloned',
                  v_pending_columns, v_pending_select
                ) USING v_pending_payload;
            END IF;
        END LOOP;
    END LOOP;

    INSERT INTO public.bom_lote_recalculos(lote_id, produto_ids) VALUES (v_lote_id, v_affected)
      RETURNING id INTO v_recalculo_id;
    UPDATE public.bom_lotes SET resultado=jsonb_build_object('lote_id',v_lote_id,'produtos_alterados',cardinality(v_affected),
      'componentes_gravados',v_inserted,'componentes_removidos',v_removed,'custos_status','pendente',
      'recalculo_id',v_recalculo_id) WHERE id=v_lote_id;
    RETURN (SELECT resultado FROM public.bom_lotes WHERE id=v_lote_id);
END;
$function$;
REVOKE ALL ON FUNCTION public.aplicar_composicao_lote(integer[],jsonb,jsonb,jsonb,jsonb,text,text,integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.aplicar_composicao_lote(integer[],jsonb,jsonb,jsonb,jsonb,text,text,integer) TO service_role;
