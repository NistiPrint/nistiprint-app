-- Smoke-test apply, idempotent replay, rollback, and multi-row cycle detection.
-- Every successful write is rolled back inside the DO block.
DO $test$
DECLARE
    v_products jsonb := '{}'::jsonb;
    v_compositions jsonb := '{}'::jsonb;
    v_product public.produtos%ROWTYPE;
    v_pid integer;
    v_lines jsonb;
    v_op jsonb;
    v_response jsonb;
    v_replay jsonb;
    v_message text;
    v_parent_id integer;
    v_child_id integer;
    v_parent_line_id integer;
BEGIN
    -- Existing intermediate 7 has a direct BOM. Save/update, remove, add, then replay.
    SELECT * INTO STRICT v_product FROM public.produtos WHERE id=7;
    v_products := jsonb_build_object('7', jsonb_build_object(
        'id',v_product.id,'sku',v_product.sku,'nome',v_product.nome,
        'tipo_material',v_product.tipo_material,'formato',v_product.formato,
        'estrutura',v_product.estrutura,'parent_id',v_product.parent_id,
        'herdar_bom_pai',v_product.herdar_bom_pai,'status',v_product.status,
        'unidade_medida_id',v_product.unidade_medida_id,'unidade_medida','un'
    ));
    SELECT coalesce(jsonb_agg(jsonb_build_object(
        'componente_id',b.componente_id,'quantidade_necessaria',b.quantidade_necessaria::text,
        'unidade_medida',b.unidade_medida,'is_inherited',b.is_inherited,
        'grupo',b.grupo,'grupo_persistido',f.grupo,'line_id',b.id,'produto_pai_id',b.produto_pai_id
    ) ORDER BY b.componente_id),'[]'::jsonb)
      INTO v_lines FROM public.bom_efetiva_produto(7) b LEFT JOIN public.ficha_tecnica f ON f.id=b.id;
    v_compositions := jsonb_build_object('7',v_lines);
    v_op := '[{"produto_id":7,"componente_id":5,"acao":"definir","quantidade":"51.5"},'
            '{"produto_id":7,"componente_id":6,"acao":"remover"},'
            '{"produto_id":7,"componente_id":21,"acao":"definir","quantidade":"0.25"}]'::jsonb;
    BEGIN
        v_response := public.aplicar_composicao_lote(
            ARRAY[7],v_op,'{"7":"smoke-token"}'::jsonb,v_compositions,v_products,
            'smoke-review','bom-lote-smoke-idempotency-001',-1
        );
        v_replay := public.aplicar_composicao_lote(
            ARRAY[7],v_op,'{"7":"smoke-token"}'::jsonb,v_compositions,v_products,
            'smoke-review','bom-lote-smoke-idempotency-001',-1
        );
        IF v_response IS DISTINCT FROM v_replay OR v_response->>'lote_id' IS NULL THEN
            RAISE EXCEPTION 'BOM_BATCH_IDEMPOTENCY_SMOKE_FAILED';
        END IF;
        RAISE EXCEPTION 'BOM_BATCH_ROLLBACK_SMOKE' USING ERRCODE='P0002';
    EXCEPTION WHEN SQLSTATE 'P0002' THEN
        GET STACKED DIAGNOSTICS v_message = MESSAGE_TEXT;
        IF v_message <> 'BOM_BATCH_ROLLBACK_SMOKE' THEN RAISE; END IF;
    END;
    IF EXISTS (SELECT 1 FROM public.bom_lotes WHERE idempotency_key='bom-lote-smoke-idempotency-001') THEN
        RAISE EXCEPTION 'BOM_BATCH_ROLLBACK_SMOKE_FAILED';
    END IF;

    -- Two edits that create a cycle only when considered together must be rejected.
    v_products := '{}'::jsonb;
    v_compositions := '{}'::jsonb;
    FOREACH v_pid IN ARRAY ARRAY[7,8] LOOP
        SELECT * INTO STRICT v_product FROM public.produtos WHERE id=v_pid;
        v_products := v_products || jsonb_build_object(v_pid::text,jsonb_build_object(
            'id',v_product.id,'sku',v_product.sku,'nome',v_product.nome,
            'tipo_material',v_product.tipo_material,'formato',v_product.formato,
            'estrutura',v_product.estrutura,'parent_id',v_product.parent_id,
            'herdar_bom_pai',v_product.herdar_bom_pai,'status',v_product.status,
            'unidade_medida_id',v_product.unidade_medida_id,'unidade_medida','un'
        ));
        SELECT coalesce(jsonb_agg(jsonb_build_object(
            'componente_id',b.componente_id,'quantidade_necessaria',b.quantidade_necessaria::text,
            'unidade_medida',b.unidade_medida,'is_inherited',b.is_inherited,
            'grupo',b.grupo,'grupo_persistido',f.grupo,'line_id',b.id,'produto_pai_id',b.produto_pai_id
        ) ORDER BY b.componente_id),'[]'::jsonb)
          INTO v_lines FROM public.bom_efetiva_produto(v_pid) b LEFT JOIN public.ficha_tecnica f ON f.id=b.id;
        v_compositions := v_compositions || jsonb_build_object(v_pid::text,v_lines);
    END LOOP;
    v_op := '[{"produto_id":7,"componente_id":8,"acao":"definir","quantidade":"1"},'
            '{"produto_id":8,"componente_id":7,"acao":"definir","quantidade":"1"}]'::jsonb;
    BEGIN
        PERFORM public.aplicar_composicao_lote(
            ARRAY[7,8],v_op,'{}'::jsonb,v_compositions,v_products,
            'cycle-review','bom-lote-smoke-cycle-001',-1
        );
        RAISE EXCEPTION 'BOM_CYCLE_SMOKE_FAILED: cycle was accepted';
    EXCEPTION WHEN SQLSTATE '22023' THEN
        GET STACKED DIAGNOSTICS v_message = MESSAGE_TEXT;
        IF v_message NOT LIKE '%BOM_CYCLE%' THEN RAISE; END IF;
    END;
    IF EXISTS (SELECT 1 FROM public.bom_lotes WHERE idempotency_key='bom-lote-smoke-cycle-001') THEN
        RAISE EXCEPTION 'BOM_CYCLE_SMOKE_ROLLBACK_FAILED';
    END IF;

    -- Materializing an inherited variation keeps inferred groups provisional and
    -- clones its unresolved review row onto the new child line.
    BEGIN
        INSERT INTO public.produtos(sku,nome,tipo_material,tipo_produto,status,formato,papel_catalogo,estrutura)
        VALUES ('__BOM_BATCH_TEST_PARENT__','Temporary batch test parent','intermediario','INTERMEDIARIO','rascunho','com_variacao','modelo','manufaturado')
        RETURNING id INTO v_parent_id;
        INSERT INTO public.produtos(sku,nome,tipo_material,tipo_produto,status,formato,parent_id,herdar_bom_pai)
        VALUES ('__BOM_BATCH_TEST_CHILD__','Temporary batch test child','intermediario','INTERMEDIARIO','rascunho','variacao',v_parent_id,true)
        RETURNING id INTO v_child_id;
        INSERT INTO public.ficha_tecnica(produto_pai_id,componente_id,quantidade_necessaria,unidade_medida,grupo,sku_produto_pai,sku_componente)
        SELECT v_parent_id, p.id, 2, 'un', NULL, parent.sku, p.sku
          FROM public.produtos p JOIN public.produtos parent ON parent.id=v_parent_id WHERE p.id=5
        RETURNING id INTO v_parent_line_id;
        INSERT INTO public.ficha_tecnica_classificacao_pendente(
            ficha_tecnica_id,produto_pai_id,componente_id,sugestao_grupo,motivo
        ) VALUES (v_parent_line_id,v_parent_id,5,'MIOLO','smoke test pending review');

        SELECT * INTO STRICT v_product FROM public.produtos WHERE id=v_child_id;
        v_products := jsonb_build_object(v_child_id::text,jsonb_build_object(
            'id',v_product.id,'sku',v_product.sku,'nome',v_product.nome,
            'tipo_material',v_product.tipo_material,'formato',v_product.formato,
            'estrutura',v_product.estrutura,'parent_id',v_product.parent_id,
            'herdar_bom_pai',v_product.herdar_bom_pai,'status',v_product.status,
            'unidade_medida_id',v_product.unidade_medida_id,'unidade_medida',NULL
        ));
        SELECT coalesce(jsonb_agg(jsonb_build_object(
            'componente_id',b.componente_id,'quantidade_necessaria',b.quantidade_necessaria::text,
            'unidade_medida',b.unidade_medida,'is_inherited',b.is_inherited,
            'grupo',b.grupo,'grupo_persistido',f.grupo,'line_id',b.id,'produto_pai_id',b.produto_pai_id
        ) ORDER BY b.componente_id),'[]'::jsonb)
          INTO v_lines FROM public.bom_efetiva_produto(v_child_id) b LEFT JOIN public.ficha_tecnica f ON f.id=b.id;
        v_compositions := jsonb_build_object(v_child_id::text,v_lines);
        v_op := jsonb_build_array(jsonb_build_object(
            'produto_id',v_child_id,'componente_id',5,'acao','definir','quantidade','3'
        ));
        v_response := public.aplicar_composicao_lote(
            ARRAY[v_child_id],v_op,'{}'::jsonb,v_compositions,v_products,
            'inherit-review','bom-lote-smoke-inherit-001',-1
        );
        IF (SELECT herdar_bom_pai FROM public.produtos WHERE id=v_child_id) IS DISTINCT FROM false
           OR (SELECT count(*) FROM public.ficha_tecnica WHERE produto_pai_id=v_child_id) <> 1
           OR (SELECT grupo FROM public.ficha_tecnica WHERE produto_pai_id=v_child_id AND componente_id=5) IS NOT NULL
           OR (SELECT count(*) FROM public.ficha_tecnica_classificacao_pendente WHERE ficha_tecnica_id IN
                (SELECT id FROM public.ficha_tecnica WHERE produto_pai_id=v_child_id) AND produto_pai_id=v_child_id) <> 1
           OR NOT EXISTS (SELECT 1 FROM public.ficha_tecnica_classificacao_pendente WHERE ficha_tecnica_id=v_parent_line_id) THEN
            RAISE EXCEPTION 'BOM_INHERIT_MATERIALIZATION_SMOKE_FAILED';
        END IF;
        RAISE EXCEPTION 'BOM_INHERIT_ROLLBACK_SMOKE' USING ERRCODE='P0002';
    EXCEPTION WHEN SQLSTATE 'P0002' THEN
        GET STACKED DIAGNOSTICS v_message = MESSAGE_TEXT;
        IF v_message <> 'BOM_INHERIT_ROLLBACK_SMOKE' THEN RAISE; END IF;
    END;
    IF EXISTS (SELECT 1 FROM public.produtos WHERE sku IN ('__BOM_BATCH_TEST_PARENT__','__BOM_BATCH_TEST_CHILD__')) THEN
        RAISE EXCEPTION 'BOM_INHERIT_ROLLBACK_SMOKE_FAILED';
    END IF;
END;
$test$;
