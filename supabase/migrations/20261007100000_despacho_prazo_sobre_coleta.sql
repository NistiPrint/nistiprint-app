-- O prazo de postagem salvo define a urgencia. A coleta so classifica pedidos
-- sem prazo; compromisso logistico isolado nao substitui nenhum dos dois.
CREATE OR REPLACE FUNCTION public.despacho_bucket_operacional(
    p_prazo timestamptz, p_coleta timestamptz, p_compromisso timestamptz, p_data date
) RETURNS text LANGUAGE sql IMMUTABLE SET search_path TO public, pg_temp AS $$
    SELECT public.despacho_bucket_prazo(COALESCE(p_prazo, p_coleta), p_data);
$$;

COMMENT ON FUNCTION public.despacho_bucket_operacional(timestamptz,timestamptz,timestamptz,date) IS
    'Classifica pelo prazo salvo; sem prazo, usa a coleta prevista. Sem ambos, o pedido fica sem prazo.';
