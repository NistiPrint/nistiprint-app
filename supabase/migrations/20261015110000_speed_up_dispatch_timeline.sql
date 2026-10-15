-- Resolve the next dispatch window from one expanded calendar per group.
-- The previous implementation called janelas_logisticas once per day until
-- it found a result, multiplying rule and JSON processing by up to 32x.
CREATE OR REPLACE FUNCTION public.despacho_lote_proxima_saida(
    p_modalidade_id integer,
    p_integration_id integer,
    p_data_limite date,
    p_tipo_prazo text,
    p_compromisso timestamptz,
    p_agora timestamptz DEFAULT now()
)
RETURNS timestamptz
LANGUAGE sql STABLE SET search_path TO public, pg_temp AS $$
    SELECT CASE
        WHEN p_tipo_prazo = 'RELATIVO' THEN p_compromisso
        WHEN p_modalidade_id IS NULL OR p_data_limite IS NULL THEN NULL
        ELSE (
            SELECT min(janela.coleta_em)
              FROM generate_series(
                    GREATEST(
                        p_data_limite,
                        (p_agora AT TIME ZONE 'America/Sao_Paulo')::date
                    ),
                    GREATEST(
                        p_data_limite,
                        (p_agora AT TIME ZONE 'America/Sao_Paulo')::date
                    ) + 31,
                    interval '1 day'
              ) AS dias(dia)
              CROSS JOIN LATERAL public.janelas_logisticas(
                    p_modalidade_id, p_integration_id, dias.dia::date
              ) janela
             WHERE janela.coleta_em > p_agora
        )
    END;
$$;

REVOKE ALL ON FUNCTION public.despacho_lote_proxima_saida(integer,integer,date,text,timestamptz,timestamptz)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.despacho_lote_proxima_saida(integer,integer,date,text,timestamptz,timestamptz)
    TO service_role;
