-- ============================================
-- Filtros Contextuais para Pedidos - UX Aprimorada
-- ============================================
-- Data: 2026-03-31
-- Descrição: Cria função para buscar canais com horário de coleta
-- mais próximo do horário atual, permitindo filtros contextuais
-- inteligentes na tela de pedidos.
-- ============================================

-- ============================================================================
-- 1. FUNÇÃO: fn_canais_proximos_coleta()
-- ============================================================================
-- Retorna os canais ativos com horário de coleta mais próximo do horário atual.
-- Considera wrap-around do dia (ex: se atual for 22:00 e coleta for 08:00,
-- a coleta é do dia seguinte).
-- CORREÇÃO: Retornar horario_coleta como TEXT para evitar problemas de tipo

CREATE OR REPLACE FUNCTION "public"."fn_canais_proximos_coleta"(
    p_limit integer DEFAULT 2
)
RETURNS TABLE (
    fn_id integer,
    fn_nome character varying,
    fn_horario_coleta text,
    fn_flex boolean,
    fn_fulfillment boolean,
    fn_color character varying,
    fn_dist_min integer,
    fn_is_proximo boolean
)
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    v_horario_atual time;
    v_horario_atual_minutos integer;
BEGIN
    -- Obter horário atual (time only)
    SELECT CURRENT_TIME INTO v_horario_atual;

    -- Converter para minutos
    v_horario_atual_minutos := EXTRACT(HOUR FROM v_horario_atual) * 60 + EXTRACT(MINUTE FROM v_horario_atual);

    RETURN QUERY
    WITH canais_com_horario AS (
        SELECT
            c.id AS c_id,
            c.nome AS c_nome,
            c.horario_coleta,
            c.flex,
            c.fulfillment,
            c.color,
            -- Calcular minutos até a coleta (CAST PARA INTEGER)
            CASE
                -- Se horário de coleta >= horário atual: mesmo dia
                WHEN EXTRACT(HOUR FROM c.horario_coleta) * 60 + EXTRACT(MINUTE FROM c.horario_coleta) >= v_horario_atual_minutos
                THEN ((EXTRACT(HOUR FROM c.horario_coleta) * 60 + EXTRACT(MINUTE FROM c.horario_coleta)) - v_horario_atual_minutos)::integer
                -- Se horário de coleta < horário atual: dia seguinte
                ELSE ((24 * 60 - v_horario_atual_minutos) + (EXTRACT(HOUR FROM c.horario_coleta) * 60 + EXTRACT(MINUTE FROM c.horario_coleta)))::integer
            END AS dist_min
        FROM
            public.canais_venda c
        WHERE
            c.ativo = true
            AND c.horario_coleta IS NOT NULL
    ),
    canais_ordenados AS (
        SELECT
            c_id,
            c_nome,
            TO_CHAR(horario_coleta, 'HH24:MI') AS horario_coleta_text,
            flex,
            fulfillment,
            color,
            dist_min,
            ROW_NUMBER() OVER (ORDER BY dist_min ASC) AS rn
        FROM
            canais_com_horario
    )
    SELECT
        c.c_id AS fn_id,
        c.c_nome AS fn_nome,
        c.horario_coleta_text AS fn_horario_coleta,
        c.flex,
        c.fulfillment,
        c.color,
        c.dist_min AS fn_dist_min,
        -- Marcar como "próximo" os N primeiros (default 2)
        (c.rn <= p_limit) AS fn_is_proximo
    FROM
        canais_ordenados c
    WHERE
        c.rn <= p_limit
    ORDER BY
        c.dist_min ASC;
END;
$$;

COMMENT ON FUNCTION "public"."fn_canais_proximos_coleta"(integer) IS
'Retorna os canais ativos com horário de coleta mais próximo do horário atual. 
Útil para filtros contextuais na tela de pedidos.
Considera wrap-around do dia (coletas do dia seguinte).';

-- ============================================================================
-- 2. FUNÇÃO: fn_contar_pedidos_por_canal()
-- ============================================================================
-- Conta pedidos por canal com filtros básicos (sem demanda, período)
-- para exibir contagens nos filtros contextuais.
-- Usa a tabela pivot demandas_pedidos para verificar se pedido tem demanda.

CREATE OR REPLACE FUNCTION "public"."fn_contar_pedidos_por_canal"(
    p_canal_venda_id integer DEFAULT NULL,
    p_dias integer DEFAULT 7,
    p_has_demanda boolean DEFAULT NULL
)
RETURNS TABLE (
    canal_venda_id integer,
    canal_venda_nome character varying,
    total_pedidos bigint,
    pedidos_sem_demanda bigint,
    pedidos_com_demanda bigint
)
LANGUAGE plpgsql
STABLE
AS $$
BEGIN
    RETURN QUERY
    SELECT
        c.id AS canal_venda_id,
        c.nome AS canal_venda_nome,
        COUNT(p.id) AS total_pedidos,
        COUNT(DISTINCT CASE WHEN dp.pedido_id IS NULL THEN p.id END) AS pedidos_sem_demanda,
        COUNT(DISTINCT CASE WHEN dp.pedido_id IS NOT NULL THEN p.id END) AS pedidos_com_demanda
    FROM
        public.canais_venda c
    LEFT JOIN
        public.pedidos p ON p.canal_venda_id = c.id
            AND p.created_at >= (CURRENT_DATE - (p_dias || ' days')::interval)
    LEFT JOIN
        public.demandas_pedidos dp ON dp.pedido_id = p.id
    WHERE
        c.ativo = true
        AND (p_canal_venda_id IS NULL OR c.id = p_canal_venda_id)
        AND (
            p_has_demanda IS NULL OR
            (p_has_demanda = false AND dp.pedido_id IS NULL) OR
            (p_has_demanda = true AND dp.pedido_id IS NOT NULL)
        )
    GROUP BY
        c.id, c.nome
    ORDER BY
        total_pedidos DESC;
END;
$$;

COMMENT ON FUNCTION "public"."fn_contar_pedidos_por_canal"(integer, integer, boolean) IS
'Conta pedidos por canal de venda. Usa tabela pivot demandas_pedidos para verificar demanda.';

-- ============================================================================
-- 3. VIEW: v_canais_coleta_dia
-- ============================================================================
-- View com todos os canais ativos que possuem horário de coleta definido.

CREATE OR REPLACE VIEW "public"."v_canais_coleta_dia" AS
SELECT
    c.id,
    c.nome,
    TO_CHAR(c.horario_coleta, 'HH24:MI') AS horario_coleta,
    c.flex,
    c.fulfillment,
    c.color,
    c.plataforma_id,
    p.nome AS plataforma_nome,
    -- Classificação do horário
    CASE
        WHEN EXTRACT(HOUR FROM c.horario_coleta) BETWEEN 6 AND 12 THEN 'MANHA'
        WHEN EXTRACT(HOUR FROM c.horario_coleta) BETWEEN 13 AND 18 THEN 'TARDE'
        ELSE 'NOITE'
    END AS periodo_coleta,
    -- Ordenação para UI
    EXTRACT(HOUR FROM c.horario_coleta) * 60 + EXTRACT(MINUTE FROM c.horario_coleta) AS horario_minutos
FROM
    public.canais_venda c
LEFT JOIN
    public.plataformas p ON c.plataforma_id = p.id
WHERE
    c.ativo = true
    AND c.horario_coleta IS NOT NULL;

COMMENT ON VIEW "public"."v_canais_coleta_dia" IS
'View com todos os canais ativos que possuem horário de coleta definido.
Útil para listagens e caches no frontend.';

-- ============================================================================
-- 4. ÍNDICES DE PERFORMANCE
-- ============================================================================

-- Índice para otimizar busca por horário de coleta
CREATE INDEX IF NOT EXISTS "idx_canais_venda_horario_coleta"
ON "public"."canais_venda"("horario_coleta")
WHERE "ativo" = true AND "horario_coleta" IS NOT NULL;

-- Índice composto para filtros comuns
CREATE INDEX IF NOT EXISTS "idx_canais_venda_ativo_horario"
ON "public"."canais_venda"("ativo", "horario_coleta")
WHERE "ativo" = true;

-- ============================================================================
-- 5. PERMISSÕES (RLS)
-- ============================================================================

-- Garantir que a função seja acessível para usuários autenticados
-- (ajustar conforme política de segurança do projeto)

-- Exemplo (se RLS estiver habilitado):
-- GRANT EXECUTE ON FUNCTION "public"."fn_canais_proximos_coleta"(integer) TO authenticated;
-- GRANT EXECUTE ON FUNCTION "public"."fn_contar_pedidos_por_canal"(integer, integer, boolean) TO authenticated;
-- GRANT SELECT ON "public"."v_canais_coleta_dia" TO authenticated;
