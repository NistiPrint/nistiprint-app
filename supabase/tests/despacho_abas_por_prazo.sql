-- Regressao de leitura: executar com psql -v ON_ERROR_STOP=1 -f este_arquivo.
-- Nao altera pedidos e pode rodar contra uma base com dados existentes.
BEGIN;

DO $test$
DECLARE
    fuso text;
    falhas integer;
BEGIN
    FOREACH fuso IN ARRAY ARRAY['UTC', 'America/Sao_Paulo', 'Pacific/Kiritimati'] LOOP
        PERFORM set_config('TimeZone', fuso, true);
        WITH casos(prazo, esperado) AS (
            VALUES
                (NULL::timestamptz, 'sem_prazo'),
                ('2026-09-15T23:59:59-03:00'::timestamptz, 'atrasado'),
                ('2026-09-16T00:00:00-03:00'::timestamptz, 'hoje'),
                ('2026-09-17T02:59:59Z'::timestamptz, 'hoje'),
                ('2026-09-17T03:00:00Z'::timestamptz, 'amanha'),
                ('2026-09-17T23:59:59-03:00'::timestamptz, 'amanha'),
                ('2026-09-18T03:00:00Z'::timestamptz, 'depois'),
                ('2026-09-19T23:59:59-03:00'::timestamptz, 'depois'),
                ('2026-09-21T23:59:59-03:00'::timestamptz, 'depois')
        )
        SELECT count(*) INTO falhas
          FROM casos
         WHERE public.despacho_bucket_prazo(prazo, DATE '2026-09-16') IS DISTINCT FROM esperado;
        IF falhas > 0 THEN
            RAISE EXCEPTION 'Classificacao incorreta no fuso %: % casos', fuso, falhas;
        END IF;
    END LOOP;

    IF public.despacho_bucket_prazo(NULL, DATE '2026-09-16') <> 'sem_prazo'
       OR public.despacho_aba_do_bucket('sem_prazo') <> 'hoje'
       OR public.despacho_aba_do_bucket('atrasado') <> 'hoje'
       OR public.despacho_aba_do_bucket('depois') <> 'proximos' THEN
        RAISE EXCEPTION 'Mapeamento de buckets para abas incorreto';
    END IF;

    -- O card precisa contar exatamente os pedidos que o clique abre.
    WITH arvore AS MATERIALIZED (
        SELECT * FROM public.despacho_arvore(DATE '2026-09-16')
    )
    SELECT count(*) INTO falhas
      FROM arvore a
     WHERE a.nivel = 2
       AND (
           a.qtd_pedidos <> (
               SELECT count(*) FROM public.despacho_escopo_pedidos(
                   a.integration_id, a.modalidade_id, ARRAY[a.bucket_prazo], DATE '2026-09-16'
               )
           )
           OR a.qtd_pedidos <> (
               SELECT count(*) FROM public.despacho_escopo_lote(
                   a.integration_id,
                   CASE WHEN a.modalidade_id IS NULL THEN NULL ELSE ARRAY[a.modalidade_id] END,
                   ARRAY[a.bucket_prazo], DATE '2026-09-16'
               )
           )
           OR a.qtd_pedidos <> (
               SELECT count(*) FROM public.vw_pedidos_pendentes_despacho p
                WHERE p.marketplace_integration_id IS NOT DISTINCT FROM a.integration_id
                  AND p.modalidade_logistica_id IS NOT DISTINCT FROM a.modalidade_id
                  AND public.despacho_bucket_prazo(p.data_limite_envio, DATE '2026-09-16') = a.bucket_prazo
           )
       );
    IF falhas > 0 THEN
        RAISE EXCEPTION 'Arvore e escopos divergem em % buckets', falhas;
    END IF;

    -- Lotes podem reunir mais de uma modalidade da mesma integracao.
    WITH lotes AS (
        SELECT integration_id, bucket_prazo, array_agg(modalidade_id) AS modalidades,
               sum(qtd_pedidos) AS qtd
          FROM public.despacho_arvore(DATE '2026-09-16')
         WHERE nivel = 2 AND modalidade_id IS NOT NULL
         GROUP BY integration_id, bucket_prazo
    )
    SELECT count(*) INTO falhas FROM lotes l
     WHERE l.qtd <> (
         SELECT count(*) FROM public.despacho_escopo_lote(
             l.integration_id, l.modalidades, ARRAY[l.bucket_prazo], DATE '2026-09-16'
         )
     );
    IF falhas > 0 THEN
        RAISE EXCEPTION 'Contagens de lotes com varias modalidades divergem: %', falhas;
    END IF;
END;
$test$;

ROLLBACK;
