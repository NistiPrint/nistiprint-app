-- Previa da consolidacao editavel pelo operador.
--
-- O que o operador precisa fazer, e que hoje nao tem como: ver a linha do kit,
-- decidir que ela nao vai para a fabrica como kit, e passar a quantidade dele
-- para os produtos que o compoem.
--
--   | produto            | sku            | miolo  | qtde |
--   | kit vacinacao      | CMB_VACMNO_... | VACMNO |   2  |   <- remover
--   | caderneta vacinacao| VACMNO_...     | VACMNO |   5  |   -> 7
--   | livro de bebe      | LIVR_...       | LIVRBB |   5  |   -> 7
--
-- Por que isso NAO e feito automaticamente no SQL: a explosao automatica
-- (20260831210000) tirava do operador justamente a linha que ele precisa ver
-- para decidir, e obrigava a consolidacao a exigir produto interno resolvido —
-- o que descartava 94,6% dos itens. A explosao passa a ser um ato do operador,
-- com o kit visivel antes e depois.
--
-- O ajuste NAO e um segundo caminho de consolidacao. A consolidacao canonica
-- roda igual; os ajustes sao aplicados sobre o resultado dela, ficam gravados
-- em `escopo_despacho.ajustes` e carimbam `editado_pelo_usuario`.

-- ---------------------------------------------------------------------------
-- 1. Ordem deterministica
-- ---------------------------------------------------------------------------
-- A ordenacao nao tinha desempate final: duas linhas com o mesmo miolo, mesma
-- quantidade, mesmo SKU e mesma variacao (mudando so o titulo do anuncio)
-- trocavam de posicao entre execucoes. A previa e a demanda materializada
-- podiam mostrar ordens diferentes para o mesmo lote. `titulo` fecha o criterio.

CREATE OR REPLACE FUNCTION public.despacho_consolidar_pedidos(p_pedido_ids integer[])
RETURNS TABLE(ordem integer, miolo text, miolo_chave text, miolo_rank integer,
              miolo_total numeric, titulo_anuncio text, sku_externo text,
              variacao text, quantidade numeric, produto_id integer,
              produto_nome text, id_produto_miolo integer, miolo_origem text,
              contabiliza_estoque boolean, pedidos_origem integer[], itens_origem integer[])
LANGUAGE sql STABLE SET search_path TO public, pg_temp AS $fn$
WITH cfg AS (
    SELECT coalesce((SELECT (valor #>> '{}') FROM public.configuracoes_aplicacao
                      WHERE nome = 'producao_miolos_category_id'), '6')::integer AS cat_miolo
),
base AS (
    SELECT ip.id AS item_id, ip.pedido_id,
           coalesce(nullif(btrim(ip.titulo_anuncio), ''),
                    nullif(btrim(ip.descricao), ''), '-')        AS titulo,
           coalesce(nullif(btrim(ip.sku_externo), ''), '-')      AS sku,
           coalesce(nullif(btrim(ip.variacao_externa), ''), '-') AS variacao,
           public.miolo_do_sku(ip.sku_externo)                   AS miolo_chave,
           ip.quantidade,
           ip.produto_id                                         AS produto_vinculado
      FROM public.itens_pedido ip
     WHERE ip.pedido_id = ANY(p_pedido_ids)
),
resolvido AS (
    SELECT b.*, coalesce(b.produto_vinculado, pe.produto_id, pr.id) AS produto_final
      FROM base b
      LEFT JOIN LATERAL (
            SELECT x.produto_id FROM public.produtos_externos x
             WHERE b.produto_vinculado IS NULL
               AND upper(btrim(x.codigo_externo)) = upper(b.sku)
             ORDER BY CASE x.tipo WHEN 'SKU' THEN 1 WHEN 'ID' THEN 2 ELSE 3 END,
                      CASE WHEN x.plataforma IS NULL THEN 1 ELSE 0 END
             LIMIT 1
      ) pe ON true
      LEFT JOIN LATERAL (
            SELECT x.id FROM public.produtos x
             WHERE b.produto_vinculado IS NULL AND pe.produto_id IS NULL
               AND upper(btrim(x.sku)) = upper(b.sku)
             LIMIT 1
      ) pr ON true
),
com_bom AS (
    SELECT r.*, bom.componente_id AS miolo_produto_id, bom.componente_nome AS miolo_bom,
           p.nome AS produto_nome
      FROM resolvido r
      CROSS JOIN cfg
      LEFT JOIN public.produtos p ON p.id = r.produto_final
      LEFT JOIN LATERAL (
            SELECT c.id AS componente_id, c.nome AS componente_nome
              FROM public.bom_efetiva_produto(r.produto_final) ft
              JOIN public.produtos c ON c.id = ft.componente_id
             WHERE c.categoria_id = cfg.cat_miolo
             ORDER BY ft.id LIMIT 1
      ) bom ON r.produto_final IS NOT NULL
),
ranks AS (
    SELECT miolo_chave, sum(quantidade) AS total,
           row_number() OVER (ORDER BY sum(quantidade) DESC, miolo_chave)::integer AS rank
      FROM com_bom GROUP BY miolo_chave
),
linhas AS (
    SELECT cb.titulo, cb.sku, cb.variacao, cb.miolo_chave,
           sum(cb.quantidade) AS qtd,
           max(cb.miolo_bom) AS miolo_bom, max(cb.miolo_produto_id) AS miolo_produto_id,
           max(cb.produto_final) AS produto_id, max(cb.produto_nome) AS produto_nome,
           array_agg(DISTINCT cb.pedido_id) AS pedidos,
           array_agg(cb.item_id ORDER BY cb.item_id) AS itens
      FROM com_bom cb
     GROUP BY cb.titulo, cb.sku, cb.variacao, cb.miolo_chave
)
SELECT (row_number() OVER (ORDER BY r.rank, l.qtd DESC, l.sku, l.variacao, l.titulo))::integer,
       coalesce(l.miolo_bom, l.miolo_chave), l.miolo_chave, r.rank, r.total,
       l.titulo, l.sku, l.variacao, l.qtd, l.produto_id, l.produto_nome,
       l.miolo_produto_id,
       CASE WHEN l.miolo_bom IS NOT NULL THEN 'BOM' ELSE 'SKU' END,
       (l.produto_id IS NOT NULL), l.pedidos, l.itens
  FROM linhas l JOIN ranks r ON r.miolo_chave = l.miolo_chave
 ORDER BY r.rank, l.qtd DESC, l.sku, l.variacao, l.titulo;
$fn$;

-- ---------------------------------------------------------------------------
-- 2. O que um kit explode
-- ---------------------------------------------------------------------------
-- Le a ficha efetiva do kit e devolve so os componentes que sao produto
-- acabado, com o miolo de cada um ja resolvido. E o que a tela precisa para
-- mostrar "este kit vira estes produtos" antes de o operador confirmar.

CREATE OR REPLACE FUNCTION public.despacho_kit_componentes(p_produto_id integer)
RETURNS TABLE (produto_id integer, sku text, nome text, quantidade numeric,
               id_produto_miolo integer, miolo_nome text, miolo_chave text)
LANGUAGE sql STABLE SECURITY INVOKER SET search_path TO public AS $fn$
  WITH cfg AS (
    SELECT coalesce((SELECT (valor #>> '{}') FROM public.configuracoes_aplicacao
                      WHERE nome = 'producao_miolos_category_id'), '6')::integer AS cat_miolo
  )
  SELECT c.id, c.sku::text, c.nome::text, ft.quantidade_necessaria,
         m.id, m.nome::text, public.miolo_do_sku(c.sku)
    FROM public.bom_efetiva_produto(p_produto_id) ft
    JOIN public.produtos c ON c.id = ft.componente_id
    CROSS JOIN cfg
    LEFT JOIN LATERAL (
      SELECT mc.id, mc.nome
        FROM public.bom_efetiva_produto(c.id) f2
        JOIN public.produtos mc ON mc.id = f2.componente_id
       WHERE mc.categoria_id = cfg.cat_miolo
       ORDER BY f2.id LIMIT 1
    ) m ON true
   WHERE c.tipo_produto = 'PRODUTO_ACABADO'
   ORDER BY c.id;
$fn$;

COMMENT ON FUNCTION public.despacho_kit_componentes(integer) IS
  'Produtos acabados que compoem um kit, com o miolo de cada um. Alimenta a explosao de kit na previa.';

-- ---------------------------------------------------------------------------
-- 3. Materializacao com ajustes do operador
-- ---------------------------------------------------------------------------
-- `p_ajustes` e opcional e tem DEFAULT: todos os chamadores atuais continuam
-- valendo, e com NULL o resultado e byte a byte o de antes — inclusive a
-- numeracao de `ordem`, que so e recalculada quando ha ajuste.
--
-- Vocabulario, deliberadamente pequeno. A linha e identificada pela mesma
-- chave que a consolidacao usa para agrupar — (sku, variacao, miolo_chave) —
-- e nunca por um id volatil que muda a cada previa:
--
--   {"op":"remover",    "sku":"...", "variacao":"-", "miolo_chave":"..."}
--   {"op":"quantidade", "sku":"...", "variacao":"-", "miolo_chave":"...", "valor":7}
--   {"op":"explodir",   "sku":"...", "variacao":"-", "miolo_chave":"..."}
--
-- `explodir` faz a coisa inteira em um passo, e e por isso que ela existe como
-- operacao e nao como um par remover+quantidade montado no cliente: so aqui da
-- para transferir `itens_origem` da linha do kit para as linhas dos produtos.
-- Sem essa transferencia, `demandas_item_origem` perderia o vinculo entre a
-- linha de producao e o item de pedido que a originou — que e o que faz o
-- cancelamento de um pedido alcancar a producao.

-- A versao de 2 argumentos precisa sair antes: manter as duas tornaria
-- `despacho_materializar_itens(x, y)` ambiguo para os chamadores atuais.
DROP FUNCTION IF EXISTS public.despacho_materializar_itens(integer, integer[]);

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
    v_total    numeric := 0;
    v_op       jsonb;
    v_acao     text;
    v_sku      text;
    v_var      text;
    v_miolo    text;
    v_linha    record;
    v_comp     record;
    v_qtd      numeric;
    v_houve    boolean := false;
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

        SELECT * INTO v_linha FROM _cons_lote c
         WHERE c.sku_externo = v_sku
           AND c.variacao    = v_var
           AND c.miolo_chave IS NOT DISTINCT FROM v_miolo
         LIMIT 1;

        IF NOT FOUND THEN
          RAISE EXCEPTION 'Ajuste referencia uma linha que nao existe no lote: % / % / %',
            v_sku, v_var, coalesce(v_miolo, '(sem miolo)')
            USING ERRCODE = 'no_data_found';
        END IF;

        IF v_acao = 'remover' THEN
          DELETE FROM _cons_lote c
           WHERE c.sku_externo = v_sku AND c.variacao = v_var
             AND c.miolo_chave IS NOT DISTINCT FROM v_miolo;
          v_houve := true;

        ELSIF v_acao = 'quantidade' THEN
          v_qtd := coalesce((v_op ->> 'valor')::numeric, 0);
          IF v_qtd <= 0 THEN
            RAISE EXCEPTION 'Quantidade ajustada deve ser maior que zero (linha %)', v_sku
              USING ERRCODE = 'check_violation';
          END IF;
          UPDATE _cons_lote c SET quantidade = v_qtd
           WHERE c.sku_externo = v_sku AND c.variacao = v_var
             AND c.miolo_chave IS NOT DISTINCT FROM v_miolo;
          v_houve := true;

        ELSIF v_acao = 'explodir' THEN
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

            -- Soma na linha que ja existir para o mesmo produto interno; o
            -- vinculo de origem do kit passa a valer tambem para ela.
            UPDATE _cons_lote c
               SET quantidade     = c.quantidade + v_qtd,
                   itens_origem   = ARRAY(SELECT DISTINCT unnest(c.itens_origem   || v_linha.itens_origem)   ORDER BY 1),
                   pedidos_origem = ARRAY(SELECT DISTINCT unnest(c.pedidos_origem || v_linha.pedidos_origem) ORDER BY 1)
             WHERE c.produto_id = v_comp.produto_id;

            IF NOT FOUND THEN
              INSERT INTO _cons_lote (
                ordem, miolo, miolo_chave, miolo_rank, miolo_total, titulo_anuncio,
                sku_externo, variacao, quantidade, produto_id, produto_nome,
                id_produto_miolo, miolo_origem, contabiliza_estoque,
                pedidos_origem, itens_origem
              ) VALUES (
                0,
                coalesce(v_comp.miolo_nome, v_comp.miolo_chave),
                coalesce(v_comp.miolo_chave, v_linha.miolo_chave),
                0, 0, v_comp.nome, v_comp.sku, '-', v_qtd,
                v_comp.produto_id, v_comp.nome, v_comp.id_produto_miolo,
                CASE WHEN v_comp.id_produto_miolo IS NOT NULL THEN 'BOM' ELSE 'SKU' END,
                true, v_linha.pedidos_origem, v_linha.itens_origem
              );
            END IF;
          END LOOP;

          DELETE FROM _cons_lote c
           WHERE c.sku_externo = v_sku AND c.variacao = v_var
             AND c.miolo_chave IS NOT DISTINCT FROM v_miolo;
          v_houve := true;

        ELSE
          RAISE EXCEPTION 'Operacao de ajuste desconhecida: %', v_acao
            USING ERRCODE = 'check_violation';
        END IF;
      END LOOP;
    END IF;

    -- Renumera SOMENTE quando houve ajuste. Sem ajuste, `ordem` e a que a
    -- consolidacao entregou — a previa e a demanda continuam identicas.
    IF v_houve THEN
      WITH r AS (
        SELECT miolo_chave, sum(quantidade) AS total,
               row_number() OVER (ORDER BY sum(quantidade) DESC, miolo_chave)::integer AS rank
          FROM _cons_lote GROUP BY miolo_chave
      )
      UPDATE _cons_lote c
         SET miolo_rank = r.rank, miolo_total = r.total
        FROM r WHERE r.miolo_chave IS NOT DISTINCT FROM c.miolo_chave;

      WITH o AS (
        SELECT ctid,
               row_number() OVER (ORDER BY miolo_rank, quantidade DESC,
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
        SELECT
            p_demanda_id, c.ordem, c.produto_id, c.sku_externo, c.sku_externo,
            c.titulo_anuncio, c.variacao, c.quantidade, c.quantidade,
            c.miolo, c.miolo_chave, c.miolo_origem, c.id_produto_miolo,
            c.contabiliza_estoque,
            jsonb_build_object(
                'miolo_rank',   c.miolo_rank,
                'miolo_carga',  c.miolo_total,
                'produto_nome', c.produto_nome
            )
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

COMMENT ON FUNCTION public.despacho_materializar_itens(integer, integer[], jsonb) IS
  'Materializa os itens da demanda a partir da consolidacao canonica. p_ajustes NULL reproduz o comportamento anterior byte a byte; com ajustes, aplica remover/quantidade/explodir sobre o resultado e renumera a ordem.';

-- ---------------------------------------------------------------------------
-- 4. Aplicar os ajustes num rascunho ja lancado
-- ---------------------------------------------------------------------------
-- `despacho_lancar_lote` e `despacho_lancar_pedidos` NAO mudam de assinatura
-- nem de corpo. O operador lanca como sempre; se editou a previa, a API chama
-- esta funcao em seguida, que refaz os itens do mesmo conjunto de pedidos
-- aplicando os ajustes.
--
-- Refazer, e nao editar linha a linha, e o que mantem `miolo_rank` e a ordem de
-- producao coerentes com o lote inteiro: mexer numa linha muda a carga do
-- miolo, e a ordem e derivada dela.

CREATE OR REPLACE FUNCTION public.despacho_reaplicar_itens(
    p_demanda_id integer,
    p_ajustes    jsonb,
    p_user_id    text DEFAULT 'System'
)
RETURNS numeric
LANGUAGE plpgsql
SET search_path TO 'public', 'pg_temp'
AS $fn$
DECLARE
    v_status text;
    v_ids    integer[];
    v_total  numeric;
BEGIN
    SELECT d.status INTO v_status FROM public.demandas_producao d WHERE d.id = p_demanda_id;
    IF v_status IS NULL THEN
        RAISE EXCEPTION 'Demanda % nao encontrada', p_demanda_id USING ERRCODE = 'no_data_found';
    END IF;
    IF v_status <> 'RASCUNHO' THEN
        RAISE EXCEPTION 'Demanda % ja foi publicada; a lista de itens nao pode mais ser editada', p_demanda_id
            USING ERRCODE = 'check_violation';
    END IF;

    SELECT array_agg(dp.pedido_id ORDER BY dp.pedido_id) INTO v_ids
      FROM public.demandas_pedidos dp WHERE dp.demanda_id = p_demanda_id;

    IF coalesce(array_length(v_ids, 1), 0) = 0 THEN
        RAISE EXCEPTION 'Demanda % nao tem pedidos vinculados', p_demanda_id
            USING ERRCODE = 'no_data_found';
    END IF;

    DELETE FROM public.demandas_item_origem
     WHERE demanda_item_id IN (SELECT id FROM public.itens_demanda WHERE demanda_id = p_demanda_id);
    DELETE FROM public.itens_demanda WHERE demanda_id = p_demanda_id;

    v_total := public.despacho_materializar_itens(p_demanda_id, v_ids, p_ajustes);

    UPDATE public.demandas_producao
       SET escopo_despacho = coalesce(escopo_despacho, '{}'::jsonb)
                             || jsonb_build_object('ajustes', coalesce(p_ajustes, '[]'::jsonb),
                                                   'ajustado_por', p_user_id,
                                                   'ajustado_em', now()),
           editado_pelo_usuario = (p_ajustes IS NOT NULL AND jsonb_array_length(coalesce(p_ajustes,'[]'::jsonb)) > 0),
           editado_em = now(),
           updated_at = now()
     WHERE id = p_demanda_id;

    RETURN v_total;
END;
$fn$;

COMMENT ON FUNCTION public.despacho_reaplicar_itens(integer, jsonb, text) IS
  'Refaz os itens de um rascunho aplicando os ajustes do operador. Recusa demanda ja publicada.';

REVOKE ALL ON FUNCTION public.despacho_reaplicar_itens(integer, jsonb, text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.despacho_reaplicar_itens(integer, jsonb, text) TO service_role, authenticated;
GRANT EXECUTE ON FUNCTION public.despacho_kit_componentes(integer) TO service_role, authenticated;
