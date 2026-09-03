-- Grade de consolidação editável. Mantém a rastreabilidade das linhas
-- automáticas e permite linhas manuais sem criar uma segunda tabela.
ALTER TABLE public.itens_demanda
  ALTER COLUMN sku TYPE varchar(255),
  ADD COLUMN IF NOT EXISTS ordem integer,
  ADD COLUMN IF NOT EXISTS miolo_chave varchar(255),
  ADD COLUMN IF NOT EXISTS miolo_origem varchar(30),
  ADD COLUMN IF NOT EXISTS contabiliza_estoque boolean NOT NULL DEFAULT true;

UPDATE public.itens_demanda
SET ordem = COALESCE(ordem, id),
    sku_externo = COALESCE(sku_externo, sku),
    quantidade_planejada = COALESCE(quantidade_planejada, quantidade),
    contabiliza_estoque = COALESCE(contabiliza_estoque, produto_id IS NOT NULL)
WHERE ordem IS NULL OR sku_externo IS NULL OR quantidade_planejada IS NULL;

CREATE OR REPLACE FUNCTION public.despacho_publicar_demanda_editada(
  p_demanda_id integer,
  p_user_id text DEFAULT 'System',
  p_previsao_versao text DEFAULT NULL,
  p_linhas jsonb DEFAULT '[]'::jsonb
)
RETURNS TABLE (out_demanda_codigo text, out_total_pedidos integer, out_total_itens numeric, out_sem_vinculo integer)
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $function$
DECLARE
  v_demanda public.demandas_producao%ROWTYPE;
  v_linha jsonb;
  v_item public.itens_demanda%ROWTYPE;
  v_produto public.produtos%ROWTYPE;
  v_miolo public.produtos%ROWTYPE;
  v_ids integer[] := '{}'::integer[];
  v_sku text;
  v_miolo_text text;
  v_produto_count integer;
  v_miolo_count integer;
  v_key text;
  v_status text;
  v_sem_vinculo integer := 0;
BEGIN
  SELECT * INTO v_demanda FROM public.demandas_producao WHERE id = p_demanda_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Demanda nao encontrada'; END IF;
  IF v_demanda.status <> 'RASCUNHO' THEN RAISE EXCEPTION 'so rascunho pode ser publicado'; END IF;
  IF NULLIF(p_previsao_versao, '') IS NULL
     OR COALESCE(v_demanda.escopo_despacho ->> 'previsao_versao', '') <> p_previsao_versao THEN
    RAISE EXCEPTION 'escopo mudou desde a previsao';
  END IF;
  IF p_linhas IS NULL OR jsonb_typeof(p_linhas) <> 'array' OR jsonb_array_length(p_linhas) = 0 THEN
    RAISE EXCEPTION 'A consolidacao precisa ter ao menos uma linha';
  END IF;

  FOR v_linha IN SELECT value FROM jsonb_array_elements(COALESCE(p_linhas, '[]'::jsonb)) LOOP
    IF NULLIF(v_linha ->> 'quantidade', '') IS NULL
       OR (v_linha ->> 'quantidade')::numeric <= 0
       OR (v_linha ->> 'quantidade')::numeric <> trunc((v_linha ->> 'quantidade')::numeric) THEN
      RAISE EXCEPTION 'Quantidade invalida na linha %', v_linha ->> 'ordem';
    END IF;

    v_key := NULLIF(v_linha ->> 'linha_chave', '');
    v_sku := NULLIF(btrim(v_linha ->> 'sku'), '');
    v_miolo_text := NULLIF(btrim(v_linha ->> 'miolo'), '');
    v_produto := NULL;
    v_produto_count := 0;
    IF v_sku IS NOT NULL THEN
      SELECT count(*) INTO v_produto_count FROM public.produtos
       WHERE upper(btrim(sku)) = upper(v_sku);
      IF v_produto_count = 1 THEN
        SELECT * INTO v_produto FROM public.produtos
         WHERE upper(btrim(sku)) = upper(v_sku) LIMIT 1;
      ELSIF v_produto_count = 0 THEN
        SELECT count(DISTINCT produto_id) INTO v_produto_count FROM public.produtos_externos
         WHERE upper(btrim(codigo_externo)) = upper(v_sku);
        IF v_produto_count = 1 THEN
          SELECT p.* INTO v_produto FROM public.produtos p
          JOIN public.produtos_externos pe ON pe.produto_id = p.id
          WHERE upper(btrim(pe.codigo_externo)) = upper(v_sku) LIMIT 1;
        END IF;
      END IF;
    END IF;
    IF v_produto_count <> 1 THEN v_sem_vinculo := v_sem_vinculo + 1; END IF;

    v_miolo := NULL;
    v_miolo_count := 0;
    IF v_miolo_text IS NOT NULL THEN
      SELECT count(*) INTO v_miolo_count FROM public.produtos
       WHERE upper(btrim(sku)) = upper(v_miolo_text) OR upper(btrim(nome)) = upper(v_miolo_text);
      IF v_miolo_count = 1 THEN
        SELECT * INTO v_miolo FROM public.produtos
         WHERE upper(btrim(sku)) = upper(v_miolo_text) OR upper(btrim(nome)) = upper(v_miolo_text) LIMIT 1;
      END IF;
    END IF;

    IF v_key IS NOT NULL THEN
      SELECT * INTO v_item FROM public.itens_demanda
       WHERE demanda_id = p_demanda_id
         AND md5(concat_ws('|', coalesce(produto_id::text, ''), coalesce(sku_externo, sku, ''), coalesce(descricao, ''), coalesce(variacao, ''), coalesce(miolo_chave, miolo_nome, ''))) = v_key
       LIMIT 1 FOR UPDATE;
    ELSE
      v_item := NULL;
    END IF;

    -- Se a linha original manteve o SKU canônico, preserve o vínculo mesmo
    -- quando o texto não está mais encontrável no catálogo atual.
    IF v_produto_count <> 1 AND v_item.id IS NOT NULL
       AND v_item.produto_id IS NOT NULL
       AND upper(btrim(coalesce(v_item.sku_externo, v_item.sku, ''))) = upper(v_sku) THEN
      SELECT * INTO v_produto FROM public.produtos WHERE id = v_item.produto_id;
      IF FOUND THEN v_produto_count := 1; END IF;
    END IF;

    v_status := CASE WHEN v_produto_count = 1 THEN 'resolvido' WHEN v_produto_count > 1 THEN 'ambiguo' ELSE 'nao_resolvido' END;
    IF v_item.id IS NULL THEN
      INSERT INTO public.itens_demanda (demanda_id, produto_id, sku, sku_externo, descricao, quantidade, quantidade_planejada, variacao, miolo_nome, miolo_chave, id_produto_miolo, contabiliza_estoque, ordem, dados_adicionais)
      VALUES (p_demanda_id, NULLIF(v_produto.id, 0), v_sku, v_sku, NULLIF(v_linha ->> 'produto', ''), (v_linha ->> 'quantidade')::numeric, (v_linha ->> 'quantidade')::numeric, NULLIF(v_linha ->> 'variacao', ''), v_miolo_text, v_miolo_text, NULLIF(v_miolo.id, 0), v_produto_count = 1, (v_linha ->> 'ordem')::integer, jsonb_build_object('origem_edicao', 'manual', 'sku_status', v_status, 'editado_por', p_user_id));
    ELSE
      v_ids := array_append(v_ids, v_item.id);
      UPDATE public.itens_demanda SET produto_id = NULLIF(v_produto.id, 0), sku = v_sku, sku_externo = v_sku, descricao = NULLIF(v_linha ->> 'produto', ''), quantidade = (v_linha ->> 'quantidade')::numeric, quantidade_planejada = (v_linha ->> 'quantidade')::numeric, variacao = NULLIF(v_linha ->> 'variacao', ''), miolo_nome = v_miolo_text, miolo_chave = v_miolo_text, id_produto_miolo = NULLIF(v_miolo.id, 0), contabiliza_estoque = v_produto_count = 1, ordem = (v_linha ->> 'ordem')::integer, dados_adicionais = coalesce(dados_adicionais, '{}'::jsonb) || jsonb_build_object('origem_edicao', 'editada', 'sku_status', v_status, 'editado_por', p_user_id) WHERE id = v_item.id;
    END IF;
  END LOOP;

  DELETE FROM public.itens_demanda i
   WHERE i.demanda_id = p_demanda_id
     AND (cardinality(v_ids) = 0 OR NOT (i.id = ANY(v_ids)));
  UPDATE public.demandas_producao SET status = 'AGUARDANDO', publicado_em = now(), updated_at = now(), escopo_despacho = coalesce(escopo_despacho, '{}'::jsonb) || jsonb_build_object('tabela_editada', true, 'editado_por', p_user_id) WHERE id = p_demanda_id;
  UPDATE public.pedidos SET despachado_em = now() WHERE id IN (SELECT pedido_id FROM public.demandas_pedidos WHERE demanda_id = p_demanda_id);
  RETURN QUERY SELECT v_demanda.demanda_id, (SELECT count(*)::integer FROM public.demandas_pedidos WHERE demanda_id = p_demanda_id), (SELECT coalesce(sum(quantidade), 0) FROM public.itens_demanda WHERE demanda_id = p_demanda_id), v_sem_vinculo;
END;
$function$;

REVOKE ALL ON FUNCTION public.despacho_publicar_demanda_editada(integer, text, text, jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.despacho_publicar_demanda_editada(integer, text, text, jsonb) TO service_role;
