-- Leitura compatível para a primeira fase do novo domínio.
-- Não altera status, estagio, estrutura comercial nem bloqueia gravações.
CREATE OR REPLACE FUNCTION public.produto_dominio_prontidao(p_produto_id integer)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SET search_path = public
AS $$
DECLARE
    v_produto public.produtos%ROWTYPE;
    v_pai public.produtos%ROWTYPE;
    v_role text;
    v_structure text;
    v_issues jsonb := '[]'::jsonb;
    v_has_bom boolean := false;
    v_bad_bom boolean := false;
    v_has_cycle boolean := false;
    v_has_axes boolean := false;
    v_axes_complete boolean := true;
    v_requires_art boolean := false;
    v_has_blocker boolean := false;
BEGIN
    SELECT * INTO v_produto FROM public.produtos WHERE id = p_produto_id;
    IF NOT FOUND THEN
        RETURN jsonb_build_object(
            'ready', false, 'role', NULL, 'structure', NULL, 'status', NULL,
            'issues', jsonb_build_array(jsonb_build_object(
                'code', 'PRODUCT_NOT_FOUND', 'message', 'Produto não encontrado.', 'blocking', true
            ))
        );
    END IF;

    IF v_produto.parent_id IS NOT NULL THEN
        SELECT * INTO v_pai FROM public.produtos WHERE id = v_produto.parent_id;
        v_role := 'variacao';
    ELSIF v_produto.formato = 'com_variacao'
       OR EXISTS (SELECT 1 FROM public.produtos v WHERE v.parent_id = v_produto.id) THEN
        v_role := 'modelo';
    ELSE
        v_role := 'individual';
    END IF;

    SELECT EXISTS (SELECT 1 FROM public.bom_efetiva_produto(v_produto.id)) INTO v_has_bom;
    IF v_produto.formato = 'kit' THEN
        v_structure := 'kit';
    ELSIF v_produto.formato = 'composicao' OR v_has_bom THEN
        v_structure := 'manufaturado';
    ELSE
        v_structure := 'sem_ficha';
    END IF;

    IF NULLIF(btrim(v_produto.sku), '') IS NULL THEN
        v_issues := v_issues || jsonb_build_array(jsonb_build_object('code','SKU_REQUIRED','message','Informe o SKU.','blocking',true));
    END IF;
    IF NULLIF(btrim(v_produto.nome), '') IS NULL THEN
        v_issues := v_issues || jsonb_build_array(jsonb_build_object('code','NAME_REQUIRED','message','Informe o nome do produto.','blocking',true));
    END IF;
    IF coalesce(v_produto.categoria_id, v_pai.categoria_id) IS NULL THEN
        v_issues := v_issues || jsonb_build_array(jsonb_build_object('code','CATEGORY_REQUIRED','message','Classifique o produto em uma categoria.','blocking',true));
    END IF;
    IF coalesce(nullif(btrim(v_produto.tipo_material),''), nullif(btrim(v_pai.tipo_material),'')) IS NULL THEN
        v_issues := v_issues || jsonb_build_array(jsonb_build_object('code','CLASSIFICATION_REQUIRED','message','Informe a classificação do produto.','blocking',true));
    END IF;
    IF coalesce(v_produto.unidade_medida_id,
                CASE WHEN v_produto.atributos->>'unidade_medida_id' ~ '^\d+$' THEN (v_produto.atributos->>'unidade_medida_id')::integer END,
                CASE WHEN v_produto.atributos->>'unit_of_measure_id' ~ '^\d+$' THEN (v_produto.atributos->>'unit_of_measure_id')::integer END,
                v_pai.unidade_medida_id,
                CASE WHEN v_pai.atributos->>'unidade_medida_id' ~ '^\d+$' THEN (v_pai.atributos->>'unidade_medida_id')::integer END,
                CASE WHEN v_pai.atributos->>'unit_of_measure_id' ~ '^\d+$' THEN (v_pai.atributos->>'unit_of_measure_id')::integer END) IS NULL THEN
        v_issues := v_issues || jsonb_build_array(jsonb_build_object('code','UNIT_REQUIRED','message','Informe a unidade de medida.','blocking',true));
    END IF;

    IF v_role = 'variacao' THEN
        SELECT EXISTS (SELECT 1 FROM public.produto_pai_eixos pe WHERE pe.produto_pai_id = v_produto.parent_id)
          INTO v_has_axes;
        IF v_has_axes THEN
            SELECT NOT EXISTS (
                SELECT 1 FROM public.produto_pai_eixos pe
                 WHERE pe.produto_pai_id = v_produto.parent_id
                   AND NOT EXISTS (SELECT 1 FROM public.produto_variacao_valores vv
                                    WHERE vv.produto_id = v_produto.id AND vv.eixo_id = pe.eixo_id)
            ) INTO v_axes_complete;
        ELSE
            SELECT CASE WHEN jsonb_typeof(v_pai.atributos->'variations_config') = 'array'
                             AND jsonb_array_length(v_pai.atributos->'variations_config') > 0
                        THEN NOT EXISTS (
                            SELECT 1 FROM jsonb_array_elements(v_pai.atributos->'variations_config') cfg
                             WHERE nullif(btrim(v_produto.atributos->'variation_values'->>(cfg->>'name')), '') IS NULL
                        ) ELSE false END
              INTO v_axes_complete;
        END IF;
        IF NOT v_axes_complete THEN
            v_issues := v_issues || jsonb_build_array(jsonb_build_object('code','VARIATION_ATTRIBUTES_INCOMPLETE','message','Preencha todos os atributos da combinação da variação.','blocking',true));
        END IF;
    END IF;

    IF v_structure IN ('manufaturado','kit') AND NOT v_has_bom THEN
        v_issues := v_issues || jsonb_build_array(jsonb_build_object('code','BOM_REQUIRED','message','Inclua ao menos um componente válido na ficha técnica.','blocking',true));
    END IF;

    SELECT EXISTS (
        SELECT 1 FROM public.ficha_tecnica f
         WHERE (f.produto_pai_id = v_produto.id
                OR (v_produto.parent_id IS NOT NULL AND coalesce(v_produto.herdar_bom_pai,false)
                    AND f.produto_pai_id = v_produto.parent_id)
                OR (f.produto_pai_id IS NULL AND f.sku_produto_pai IN (v_produto.sku, v_pai.sku)))
           AND (f.componente_id IS NULL OR f.quantidade_necessaria <= 0
                OR NOT EXISTS (SELECT 1 FROM public.produtos c WHERE c.id=f.componente_id))
    ) INTO v_bad_bom;
    IF v_bad_bom THEN
        v_issues := v_issues || jsonb_build_array(jsonb_build_object('code','BOM_INVALID','message','A ficha contém uma linha sem referência válida ou quantidade positiva.','blocking',true));
    END IF;

    WITH RECURSIVE caminho(produto_id, caminho_ids, ciclo) AS (
        SELECT b.componente_id, ARRAY[v_produto.id, b.componente_id], b.componente_id = v_produto.id
          FROM public.bom_efetiva_produto(v_produto.id) b
        UNION ALL
        SELECT b.componente_id, c.caminho_ids || b.componente_id, b.componente_id = v_produto.id
          FROM caminho c CROSS JOIN LATERAL public.bom_efetiva_produto(c.produto_id) b
         WHERE NOT c.ciclo
    )
    SELECT EXISTS (SELECT 1 FROM caminho WHERE ciclo) INTO v_has_cycle;
    IF v_has_cycle THEN
        v_issues := v_issues || jsonb_build_array(jsonb_build_object('code','BOM_CYCLE','message','A ficha contém uma referência circular.','blocking',true));
    END IF;

    IF EXISTS (SELECT 1 FROM public.ficha_tecnica_classificacao_pendente fp
                WHERE fp.resolvido_em IS NULL
                  AND (fp.produto_pai_id = v_produto.id
                       OR (v_produto.parent_id IS NOT NULL AND fp.produto_pai_id = v_produto.parent_id))) THEN
        v_issues := v_issues || jsonb_build_array(jsonb_build_object('code','BOM_GROUP_REVIEW_PENDING','message','A classificação de grupo da ficha ainda aguarda revisão.','blocking',false));
    END IF;

    SELECT coalesce(c.permite_arte,false)
           OR coalesce((v_produto.atributos->>'requires_personalization')::boolean,false)
           OR EXISTS (SELECT 1 FROM public.bom_efetiva_produto(v_produto.id) b
                       JOIN public.produtos comp ON comp.id=b.componente_id
                       JOIN public.categorias cc ON cc.id=comp.categoria_id WHERE cc.permite_arte)
      INTO v_requires_art
      FROM (SELECT 1) seed
      LEFT JOIN public.categorias c ON c.id=coalesce(v_produto.categoria_id,v_pai.categoria_id);
    IF v_requires_art AND v_produto.arte_confirmada_em IS NULL THEN
        v_issues := v_issues || jsonb_build_array(jsonb_build_object('code','LOCAL_ARTWORK_MISSING','message','Arte local ainda não confirmada.','blocking',false));
    END IF;

    IF NOT EXISTS (SELECT 1 FROM public.produtos_externos e WHERE e.produto_id=v_produto.id) THEN
        v_issues := v_issues || jsonb_build_array(jsonb_build_object('code','CHANNEL_LINK_MISSING','message','Vínculo com canal ainda não informado.','blocking',false));
    END IF;

    SELECT EXISTS (SELECT 1 FROM jsonb_array_elements(v_issues) i WHERE coalesce((i->>'blocking')::boolean,false))
      INTO v_has_blocker;
    RETURN jsonb_build_object(
        'ready', NOT v_has_blocker,
        'role', v_role,
        'structure', v_structure,
        'status', CASE WHEN NOT v_has_blocker THEN 'PRONTO'
                       WHEN NULLIF(btrim(v_produto.sku),'') IS NULL OR NULLIF(btrim(v_produto.nome),'') IS NULL THEN 'RASCUNHO'
                       ELSE 'EM_PREPARO' END,
        'issues', v_issues
    );
END;
$$;

REVOKE ALL ON FUNCTION public.produto_dominio_prontidao(integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.produto_dominio_prontidao(integer) TO service_role;
