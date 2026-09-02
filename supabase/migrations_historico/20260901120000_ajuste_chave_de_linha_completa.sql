-- A chave do ajuste era (sku, variacao, miolo_chave), mas a consolidacao agrupa
-- por (titulo, sku, variacao, miolo_chave). O mesmo SKU anunciado com dois
-- titulos diferentes vira DUAS linhas, e o ajuste acertava uma delas em
-- silencio. Verificado em teste com o lote de CMB_ELOA_BRR, que tem duas linhas
-- (76 e 48 pecas): a explosao pegava so a de 48.
--
-- A chave passa a incluir `titulo`. Quando o chamador o omite, o ajuste vale
-- para TODAS as linhas que casam - util para "explodir este kit" - exceto em
-- `quantidade`, onde aplicar o mesmo numero a varias linhas seria adivinhacao:
-- ali a linha precisa ser unica, e a funcao exige o titulo.
--
-- Corrige tambem a soma da explosao: `WHERE c.produto_id = ...` podia casar com
-- mais de uma linha do mesmo produto (titulos diferentes) e somar a quantidade
-- em todas. Passa a somar em UMA linha alvo, escolhida por ctid.
CREATE OR REPLACE FUNCTION public.despacho_materializar_itens(
    p_demanda_id integer,
    p_pedido_ids integer[],
    p_ajustes    jsonb DEFAULT NULL
)
RETURNS numeric
LANGUAGE plpgsql
SET search_path TO 'public', 'pg_temp'
AS $fn$
DECLARE
    v_total  numeric := 0;
    v_op     jsonb;
    v_acao   text;
    v_sku    text;
    v_var    text;
    v_miolo  text;
    v_tit    text;
    v_n      integer;
    v_linha  record;
    v_comp   record;
    v_qtd    numeric;
    v_alvo   tid;
    v_houve  boolean := false;
BEGIN
    DROP TABLE IF EXISTS _cons_lote;
    CREATE TEMP TABLE _cons_lote ON COMMIT DROP AS
      SELECT * FROM public.despacho_consolidar_pedidos(p_pedido_ids);

    IF p_ajustes IS NOT NULL AND jsonb_typeof(p_ajustes) = 'array'
       AND jsonb_array_length(p_ajustes) > 0 THEN

      FOR v_op IN SELECT value FROM jsonb_array_elements(p_ajustes) LOOP
        v_acao  := lower(coalesce(v_op ->> 'op', ''));
        v_sku   := coalesce(v_op ->> 'sku', '-');
        v_var   := coalesce(v_op ->> 'variacao', '-');
        v_miolo := v_op ->> 'miolo_chave';
        v_tit   := nullif(btrim(coalesce(v_op ->> 'titulo', '')), '');

        SELECT count(*) INTO v_n FROM _cons_lote c
         WHERE c.sku_externo = v_sku AND c.variacao = v_var
           AND c.miolo_chave IS NOT DISTINCT FROM v_miolo
           AND (v_tit IS NULL OR c.titulo_anuncio = v_tit);

        IF v_n = 0 THEN
          RAISE EXCEPTION 'Ajuste referencia uma linha que nao existe no lote: % / % / %',
            v_sku, v_var, coalesce(v_miolo, '(sem miolo)') USING ERRCODE = 'no_data_found';
        END IF;

        IF v_acao = 'quantidade' AND v_n > 1 THEN
          RAISE EXCEPTION 'O SKU % tem % linhas neste lote; informe "titulo" para dizer qual delas ajustar',
            v_sku, v_n USING ERRCODE = 'check_violation';
        END IF;

        IF v_acao = 'remover' THEN
          DELETE FROM _cons_lote c
           WHERE c.sku_externo = v_sku AND c.variacao = v_var
             AND c.miolo_chave IS NOT DISTINCT FROM v_miolo
             AND (v_tit IS NULL OR c.titulo_anuncio = v_tit);
          v_houve := true;

        ELSIF v_acao = 'quantidade' THEN
          v_qtd := coalesce((v_op ->> 'valor')::numeric, 0);
          IF v_qtd <= 0 THEN
            RAISE EXCEPTION 'Quantidade ajustada deve ser maior que zero (linha %)', v_sku
              USING ERRCODE = 'check_violation';
          END IF;
          UPDATE _cons_lote c SET quantidade = v_qtd
           WHERE c.sku_externo = v_sku AND c.variacao = v_var
             AND c.miolo_chave IS NOT DISTINCT FROM v_miolo
             AND (v_tit IS NULL OR c.titulo_anuncio = v_tit);
          v_houve := true;

        ELSIF v_acao = 'explodir' THEN
          FOR v_linha IN
            SELECT * FROM _cons_lote c
             WHERE c.sku_externo = v_sku AND c.variacao = v_var
               AND c.miolo_chave IS NOT DISTINCT FROM v_miolo
               AND (v_tit IS NULL OR c.titulo_anuncio = v_tit)
          LOOP
            IF v_linha.produto_id IS NULL THEN
              RAISE EXCEPTION 'Nao da para explodir uma linha sem produto interno vinculado (%)', v_sku
                USING ERRCODE = 'check_violation';
            END IF;
            IF NOT EXISTS (SELECT 1 FROM public.despacho_kit_componentes(v_linha.produto_id)) THEN
              RAISE EXCEPTION 'Produto % nao tem componentes de produto acabado para explodir', v_sku
                USING ERRCODE = 'check_violation';
            END IF;

            FOR v_comp IN SELECT * FROM public.despacho_kit_componentes(v_linha.produto_id) LOOP
              v_qtd := v_linha.quantidade * coalesce(v_comp.quantidade, 1);

              SELECT c.ctid INTO v_alvo FROM _cons_lote c
               WHERE c.produto_id = v_comp.produto_id
               ORDER BY c.quantidade DESC, c.ctid LIMIT 1;

              IF v_alvo IS NOT NULL THEN
                UPDATE _cons_lote c
                   SET quantidade     = c.quantidade + v_qtd,
                       itens_origem   = ARRAY(SELECT DISTINCT unnest(c.itens_origem   || v_linha.itens_origem)   ORDER BY 1),
                       pedidos_origem = ARRAY(SELECT DISTINCT unnest(c.pedidos_origem || v_linha.pedidos_origem) ORDER BY 1)
                 WHERE c.ctid = v_alvo;
              ELSE
                INSERT INTO _cons_lote (
                  ordem, miolo, miolo_chave, miolo_rank, miolo_total, titulo_anuncio,
                  sku_externo, variacao, quantidade, produto_id, produto_nome,
                  id_produto_miolo, miolo_origem, contabiliza_estoque,
                  pedidos_origem, itens_origem
                ) VALUES (
                  0, coalesce(v_comp.miolo_nome, v_comp.miolo_chave),
                  coalesce(v_comp.miolo_chave, v_linha.miolo_chave),
                  0, 0, v_comp.nome, v_comp.sku, '-', v_qtd,
                  v_comp.produto_id, v_comp.nome, v_comp.id_produto_miolo,
                  CASE WHEN v_comp.id_produto_miolo IS NOT NULL THEN 'BOM' ELSE 'SKU' END,
                  true, v_linha.pedidos_origem, v_linha.itens_origem
                );
              END IF;
              v_alvo := NULL;
            END LOOP;

            DELETE FROM _cons_lote c WHERE c.ctid = v_linha.ctid;
          END LOOP;
          v_houve := true;

        ELSE
          RAISE EXCEPTION 'Operacao de ajuste desconhecida: %', v_acao
            USING ERRCODE = 'check_violation';
        END IF;
      END LOOP;
    END IF;

    IF v_houve THEN
      IF NOT EXISTS (SELECT 1 FROM _cons_lote) THEN
        RAISE EXCEPTION 'Os ajustes removeriam todas as linhas do lote'
          USING ERRCODE = 'check_violation';
      END IF;

      WITH r AS (
        SELECT miolo_chave, sum(quantidade) AS total,
               row_number() OVER (ORDER BY sum(quantidade) DESC, miolo_chave)::integer AS rank
          FROM _cons_lote GROUP BY miolo_chave
      )
      UPDATE _cons_lote c
         SET miolo_rank = r.rank, miolo_total = r.total
        FROM r WHERE r.miolo_chave IS NOT DISTINCT FROM c.miolo_chave;

      WITH o AS (
        SELECT ctid, row_number() OVER (ORDER BY miolo_rank, quantidade DESC,
                                        sku_externo, variacao, titulo_anuncio)::integer AS n
          FROM _cons_lote
      )
      UPDATE _cons_lote c SET ordem = o.n FROM o WHERE o.ctid = c.ctid;
    END IF;

    WITH ins AS (
        INSERT INTO public.itens_demanda (
            demanda_id, ordem, produto_id, sku, sku_externo, descricao, variacao,
            quantidade, quantidade_planejada, miolo_nome, miolo_chave, miolo_origem,
            id_produto_miolo, contabiliza_estoque, dados_adicionais
        )
        SELECT p_demanda_id, c.ordem, c.produto_id, c.sku_externo, c.sku_externo,
               c.titulo_anuncio, c.variacao, c.quantidade, c.quantidade,
               c.miolo, c.miolo_chave, c.miolo_origem, c.id_produto_miolo,
               c.contabiliza_estoque,
               jsonb_build_object('miolo_rank', c.miolo_rank,
                                  'miolo_carga', c.miolo_total,
                                  'produto_nome', c.produto_nome)
          FROM _cons_lote c
        RETURNING id, ordem
    )
    INSERT INTO public.demandas_item_origem (
        demanda_item_id, plataforma, pedido_id, pedido_externo_id,
        item_externo_id, sku_externo, quantidade_atendida
    )
    SELECT i.id, p.origem, p.id, p.codigo_pedido_externo,
           ip.item_externo_id, ip.sku_externo, ip.quantidade
      FROM ins i
      JOIN _cons_lote c ON c.ordem = i.ordem
     CROSS JOIN LATERAL unnest(c.itens_origem) AS oi(item_id)
      JOIN public.itens_pedido ip ON ip.id = oi.item_id
      JOIN public.pedidos      p  ON p.id  = ip.pedido_id;

    SELECT COALESCE(sum(quantidade), 0) INTO v_total
      FROM public.itens_demanda WHERE demanda_id = p_demanda_id;

    DROP TABLE IF EXISTS _cons_lote;
    RETURN v_total;
END;
$fn$;
