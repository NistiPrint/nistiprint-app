-- Regressao de leitura: executar com psql -v ON_ERROR_STOP=1 -f este_arquivo.
-- Nao altera pedidos. A previsao de miolos so e confiavel se os lotes dela forem
-- exatamente os cards da Torre, com exatamente os pedidos que o clique abre.
BEGIN;

DO $test$
DECLARE
    v_data CONSTANT date := DATE '2026-10-05';
    v_todos CONSTANT text[] := ARRAY['atrasado', 'hoje', 'amanha', 'depois', 'sem_prazo'];
    falhas integer;
BEGIN
    -- 1. Mesmo agrupamento da timeline, nos dois sentidos.
    SELECT count(*) INTO falhas FROM (
        (SELECT integration_id, modalidade_id, data_limite_dia, bucket_prazo, qtd_pedidos
           FROM public.despacho_lotes_timeline(v_data)
          EXCEPT
         SELECT integration_id, modalidade_id, data_limite_dia, bucket_prazo, qtd_pedidos
           FROM public.despacho_previsao_lotes(v_data, v_todos))
        UNION ALL
        (SELECT integration_id, modalidade_id, data_limite_dia, bucket_prazo, qtd_pedidos
           FROM public.despacho_previsao_lotes(v_data, v_todos)
          EXCEPT
         SELECT integration_id, modalidade_id, data_limite_dia, bucket_prazo, qtd_pedidos
           FROM public.despacho_lotes_timeline(v_data))
    ) divergencias;
    IF falhas > 0 THEN
        RAISE EXCEPTION 'Previsao divergiu da timeline da Torre em % lotes', falhas;
    END IF;

    -- 2. Os ids do lote sao ordenados, unicos e tantos quanto o lote anuncia.
    SELECT count(*) INTO falhas
      FROM public.despacho_previsao_lotes(v_data, v_todos) l
     WHERE cardinality(l.pedido_ids) <> l.qtd_pedidos
        OR l.pedido_ids <> ARRAY(SELECT DISTINCT x FROM unnest(l.pedido_ids) x ORDER BY x);
    IF falhas > 0 THEN
        RAISE EXCEPTION 'Ids de pedido inconsistentes com a contagem em % lotes', falhas;
    END IF;

    -- 3. Por (conta, modalidade, bucket), os pedidos sao os que o clique abre.
    -- Pedido sem data_limite_envio fica de fora de proposito: a timeline (e esta
    -- previsao) o agrupa como sem_prazo, enquanto despacho_escopo_lote o classifica
    -- pela proxima coleta. A diferenca ja existe na Torre.
    WITH previsao AS (
        SELECT l.integration_id, l.modalidade_id, l.bucket_prazo, unnest(l.pedido_ids) AS pedido_id
          FROM public.despacho_previsao_lotes(v_data, v_todos) l
         WHERE l.bucket_prazo <> 'sem_prazo'
    ), escopos AS (
        SELECT DISTINCT integration_id, modalidade_id, bucket_prazo FROM previsao
    ), abertos AS (
        SELECT e.integration_id, e.modalidade_id, e.bucket_prazo, s AS pedido_id
          FROM escopos e
         CROSS JOIN LATERAL public.despacho_escopo_lote(
             e.integration_id,
             CASE WHEN e.modalidade_id IS NULL THEN NULL ELSE ARRAY[e.modalidade_id] END,
             ARRAY[e.bucket_prazo], v_data
         ) s
         JOIN public.pedidos p ON p.id = s AND p.data_limite_envio IS NOT NULL
    )
    SELECT count(*) INTO falhas FROM (
        (SELECT * FROM previsao EXCEPT SELECT * FROM abertos)
        UNION ALL
        (SELECT * FROM abertos EXCEPT SELECT * FROM previsao)
    ) divergencias;
    IF falhas > 0 THEN
        RAISE EXCEPTION 'Pedidos da previsao diferem do escopo aberto pela Torre em % linhas', falhas;
    END IF;

    -- 4. O horizonte recorta e o vazio nao devolve nada.
    IF EXISTS (SELECT 1 FROM public.despacho_previsao_lotes(v_data, ARRAY['hoje']) WHERE bucket_prazo <> 'hoje') THEN
        RAISE EXCEPTION 'Horizonte hoje devolveu outro bucket';
    END IF;
    IF EXISTS (SELECT 1 FROM public.despacho_previsao_lotes(v_data, ARRAY[]::text[])) THEN
        RAISE EXCEPTION 'Horizonte vazio devolveu lotes';
    END IF;

    -- 5. A variante com status explicito, sem Pronto, le o mesmo que a padrao.
    IF (SELECT count(*) FROM public.despacho_previsao_lotes(v_data, v_todos, false))
       <> (SELECT count(*) FROM public.despacho_previsao_lotes(v_data, v_todos)) THEN
        RAISE EXCEPTION 'Variante sem Pronto divergiu da padrao';
    END IF;
END
$test$;

ROLLBACK;
