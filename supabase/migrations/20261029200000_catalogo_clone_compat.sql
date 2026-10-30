-- Deployed clone definition captured via MCP HTTP; canonicalization remains atomic.
CREATE OR REPLACE FUNCTION public.clonar_produto_interno(p_produto_id integer, p_novo_sku text, p_novo_nome text DEFAULT NULL::text, p_child_skus jsonb DEFAULT '{}'::jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SET search_path TO 'public'
AS $function$
DECLARE
    v_origem public.produtos%ROWTYPE;
    v_filho public.produtos%ROWTYPE;
    v_clone public.produtos%ROWTYPE;
    v_novo_filho public.produtos%ROWTYPE;
    v_sku_filho text;
    v_sufixo text;
    v_nome text;
    v_skus text[];
    v_ids_filhos integer[] := ARRAY[]::integer[];
    v_sku_pai text;
BEGIN
    p_novo_sku := btrim(p_novo_sku);
    p_novo_nome := NULLIF(btrim(p_novo_nome), '');
    IF p_novo_sku IS NULL OR p_novo_sku = '' OR length(p_novo_sku) > 100 THEN
        RAISE EXCEPTION 'Novo SKU deve ter entre 1 e 100 caracteres' USING ERRCODE = '22023';
    END IF;
    IF p_novo_nome IS NOT NULL AND length(p_novo_nome) > 255 THEN
        RAISE EXCEPTION 'Novo nome deve ter ate 255 caracteres' USING ERRCODE = '22023';
    END IF;
    SELECT * INTO v_origem FROM public.produtos WHERE id = p_produto_id FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Produto nao encontrado' USING ERRCODE = 'P0002';
    END IF;
    IF EXISTS (SELECT 1 FROM public.produtos WHERE upper(btrim(sku)) = upper(p_novo_sku)) THEN
        RAISE EXCEPTION 'SKU % ja esta em uso', p_novo_sku USING ERRCODE = '22023';
    END IF;
    IF p_child_skus IS NULL OR jsonb_typeof(p_child_skus) <> 'object' THEN
        RAISE EXCEPTION 'Informe o SKU de cada variacao da familia' USING ERRCODE = '22023';
    END IF;
    v_nome := COALESCE(p_novo_nome, v_origem.nome || ' (Cópia)');
    IF length(v_nome) > 255 THEN
        RAISE EXCEPTION 'Novo nome deve ter ate 255 caracteres' USING ERRCODE = '22023';
    END IF;
    v_skus := ARRAY[upper(btrim(p_novo_sku))];
    -- Checa todos os SKUs da familia antes da primeira insercao.
    IF v_origem.parent_id IS NULL THEN
        FOR v_filho IN SELECT * FROM public.produtos WHERE parent_id = p_produto_id ORDER BY id FOR SHARE LOOP
            v_ids_filhos := array_append(v_ids_filhos, v_filho.id);
            v_sku_filho := NULLIF(btrim(p_child_skus->>v_filho.id::text), '');
            IF v_sku_filho IS NULL OR length(v_sku_filho) > 100 THEN
                RAISE EXCEPTION 'Informe um SKU valido para a variacao %', v_filho.sku USING ERRCODE = '22023';
            END IF;
            IF upper(btrim(v_sku_filho)) = ANY(v_skus)
               OR EXISTS (SELECT 1 FROM public.produtos WHERE upper(btrim(sku)) = upper(btrim(v_sku_filho))) THEN
                RAISE EXCEPTION 'SKU de variacao invalido ou repetido: %', v_sku_filho USING ERRCODE = '22023';
            END IF;
            v_skus := array_append(v_skus, upper(btrim(v_sku_filho)));
        END LOOP;
        IF (SELECT count(*) FROM jsonb_object_keys(p_child_skus)) <> cardinality(v_ids_filhos) THEN
            RAISE EXCEPTION 'A lista de SKUs deve corresponder exatamente as variacoes da familia' USING ERRCODE = '22023';
        END IF;
    ELSIF (SELECT count(*) FROM jsonb_object_keys(p_child_skus)) <> 0 THEN
        RAISE EXCEPTION 'Este produto nao possui variacoes para mapear' USING ERRCODE = '22023';
    END IF;
    v_sku_pai := v_origem.sku_pai;
    IF v_origem.parent_id IS NOT NULL THEN
        SELECT sku INTO v_sku_pai FROM public.produtos WHERE id = v_origem.parent_id;
    END IF;
    INSERT INTO public.produtos (
        nome, sku, descricao, categoria_id, tags, atributos, precificacao,
        preco_custo, preco_venda, estoque_minimo, estoque_maximo, tipo_material,
        tipo_produto, unidade_medida_id, sku_pai, parent_id, status, formato,
        herdar_dados_pai, herdar_bom_pai, setor_responsavel_id,
        estoque_seguranca_dias, ponto_ressuprimento, lote_economico, curva_abc
    ) VALUES (
        v_nome, p_novo_sku, v_origem.descricao, v_origem.categoria_id,
        v_origem.tags,
        CASE WHEN v_origem.parent_id IS NULL
             THEN COALESCE(v_origem.atributos, '{}'::jsonb) - 'external_product_links'
             ELSE (COALESCE(v_origem.atributos, '{}'::jsonb) - 'external_product_links' - 'variation_values')
                  || '{"cloned_variation_draft": true}'::jsonb
        END,
        v_origem.precificacao, v_origem.preco_custo, v_origem.preco_venda,
        v_origem.estoque_minimo, v_origem.estoque_maximo, v_origem.tipo_material,
        v_origem.tipo_produto, v_origem.unidade_medida_id, v_sku_pai,
        v_origem.parent_id, 'rascunho', v_origem.formato,
        v_origem.herdar_dados_pai, v_origem.herdar_bom_pai,
        v_origem.setor_responsavel_id, v_origem.estoque_seguranca_dias,
        v_origem.ponto_ressuprimento, v_origem.lote_economico, v_origem.curva_abc
    ) RETURNING * INTO v_clone;
    INSERT INTO public.ficha_tecnica (
        produto_pai_id, componente_id, quantidade_necessaria,
        unidade_medida, sku_produto_pai, sku_componente
    )
    SELECT v_clone.id, componente_id, quantidade_necessaria,
           unidade_medida, v_clone.sku, sku_componente
      FROM public.ficha_tecnica WHERE produto_pai_id = v_origem.id;
    IF v_origem.parent_id IS NULL THEN
        FOR v_filho IN SELECT * FROM public.produtos WHERE id = ANY(v_ids_filhos) ORDER BY id LOOP
            v_sku_filho := btrim(p_child_skus->>v_filho.id::text);
            INSERT INTO public.produtos (
                nome, sku, descricao, categoria_id, tags, atributos, precificacao,
                preco_custo, preco_venda, estoque_minimo, estoque_maximo, tipo_material,
                tipo_produto, unidade_medida_id, sku_pai, parent_id, status, formato,
                herdar_dados_pai, herdar_bom_pai, setor_responsavel_id,
                estoque_seguranca_dias, ponto_ressuprimento, lote_economico, curva_abc
            ) VALUES (
                CASE WHEN left(v_filho.nome, length(v_origem.nome)) = v_origem.nome
                     THEN v_clone.nome || substring(v_filho.nome FROM length(v_origem.nome) + 1)
                     ELSE v_filho.nome END,
                v_sku_filho, v_filho.descricao, v_filho.categoria_id, v_filho.tags,
                COALESCE(v_filho.atributos, '{}'::jsonb) - 'external_product_links',
                v_filho.precificacao, v_filho.preco_custo, v_filho.preco_venda,
                v_filho.estoque_minimo, v_filho.estoque_maximo, v_filho.tipo_material,
                v_filho.tipo_produto, v_filho.unidade_medida_id, v_clone.sku,
                v_clone.id, 'rascunho', v_filho.formato,
                v_filho.herdar_dados_pai, v_filho.herdar_bom_pai,
                v_filho.setor_responsavel_id, v_filho.estoque_seguranca_dias,
                v_filho.ponto_ressuprimento, v_filho.lote_economico, v_filho.curva_abc
            ) RETURNING * INTO v_novo_filho;
            -- Instalacoes com a tabela normalizada de atributos tambem a preservam.
            IF to_regclass('public.produto_valores_variacao') IS NOT NULL THEN
                EXECUTE 'INSERT INTO public.produto_valores_variacao (produto_id, valor_id)
                         SELECT $1, valor_id FROM public.produto_valores_variacao WHERE produto_id = $2'
                  USING v_novo_filho.id, v_filho.id;
            END IF;
            INSERT INTO public.ficha_tecnica (
                produto_pai_id, componente_id, quantidade_necessaria,
                unidade_medida, sku_produto_pai, sku_componente
            )
            SELECT v_novo_filho.id, componente_id, quantidade_necessaria,
                   unidade_medida, v_novo_filho.sku, sku_componente
              FROM public.ficha_tecnica WHERE produto_pai_id = v_filho.id;
        END LOOP;
    END IF;

    IF v_origem.parent_id IS NULL THEN
      UPDATE public.produtos SET papel_catalogo=v_origem.papel_catalogo,estrutura=v_origem.estrutura WHERE id=v_clone.id;
      IF v_origem.papel_catalogo='modelo' THEN
        PERFORM public.catalogo_salvar_familia(v_clone.id,v_clone.catalogo_versao,
          coalesce((SELECT jsonb_agg(jsonb_build_object('eixo_id',pe.eixo_id,'posicao',pe.posicao,
            'opcao_ids',(SELECT jsonb_agg(opcao_id) FROM produto_pai_eixo_opcoes po WHERE po.produto_pai_id=p_produto_id AND po.eixo_id=pe.eixo_id)))
            FROM produto_pai_eixos pe WHERE pe.produto_pai_id=p_produto_id),'[]'),
          coalesce((SELECT jsonb_agg(jsonb_build_object('produto_id',id,'variation_values',atributos->'variation_values'))
            FROM produtos WHERE parent_id=v_clone.id),'[]'),'{}',NULL);
      END IF;
    ELSE
      PERFORM public.catalogo_salvar_familia(v_origem.parent_id,(SELECT catalogo_versao FROM produtos WHERE id=v_origem.parent_id),
        coalesce((SELECT jsonb_agg(jsonb_build_object('eixo_id',pe.eixo_id,'posicao',pe.posicao,
          'opcao_ids',(SELECT jsonb_agg(opcao_id) FROM produto_pai_eixo_opcoes po WHERE po.produto_pai_id=v_origem.parent_id AND po.eixo_id=pe.eixo_id)))
          FROM produto_pai_eixos pe WHERE pe.produto_pai_id=v_origem.parent_id),'[]'),
        jsonb_build_array(jsonb_build_object('produto_id',v_clone.id,'valores','[]'::jsonb)),'{}',NULL);
    END IF;
    SELECT * INTO v_clone FROM produtos WHERE id=v_clone.id;
    RETURN to_jsonb(v_clone);
END;
$function$;
