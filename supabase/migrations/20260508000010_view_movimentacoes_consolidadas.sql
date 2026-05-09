-- Migration: 20260508000010_view_movimentacoes_consolidadas.sql
-- Data: 2026-05-08
-- Proposito:
--   Criar view de leitura que apresenta movimentacoes de estoque agrupadas
--   por (correlation_id, estagio), com identificacao automatica do produto-foco
--   do bloco e dos componentes consumidos.
--
--   Cada linha da view eh um BLOCO logico de negocio:
--     - FINALIZACAO: estagio finalizados_qtd; produto-foco eh o PROD_ACAB.
--     - JIT:         estagio bom_<X>; produto-foco eh o produto X que sofreu PROD_INT.
--     - CONSUMO:     bloco sem PROD_ACAB nem PROD_INT (consumo direto de estoque).
--
--   "movimentos" eh um jsonb_agg dos movimentos crus do bloco, na ordem
--   cronologica, para detalhamento na UI.
--
--   Premissa: a coluna movimentacoes_estoque.estagio foi adicionada na
--   migration 20260508000009 e a RPC reconciliar_item_estoque grava o valor.

DROP VIEW IF EXISTS public.view_movimentacoes_consolidadas;

CREATE VIEW public.view_movimentacoes_consolidadas AS
WITH grupos AS (
    SELECT
        m.correlation_id,
        COALESCE(m.estagio, 'sem_estagio')                AS estagio,
        m.item_demanda_id,
        d.id                                              AS demanda_id_int,
        d.demanda_id                                      AS demanda_codigo,
        d.descricao                                       AS demanda_descricao,
        MIN(m.data_movimentacao)                          AS data_inicio,
        MAX(m.data_movimentacao)                          AS data_fim,
        -- Usuario "humano" (quando houver). Falamos do mesmo correlation,
        -- entao basta pegar qualquer um nao-nulo.
        MAX(m.usuario_id)                                 AS usuario_id,
        COUNT(*)                                          AS total_movimentos,
        -- Tipo de bloco
        CASE
            WHEN bool_or(m.tipo_movimentacao = 'PROD_ACAB') THEN 'FINALIZACAO'
            WHEN bool_or(m.tipo_movimentacao = 'PROD_INT')  THEN 'JIT'
            ELSE 'CONSUMO'
        END                                               AS tipo_bloco,
        -- Produto-foco: PROD_ACAB > PROD_INT > primeiro produto
        (
            ARRAY_AGG(m.produto_id ORDER BY
                CASE m.tipo_movimentacao
                    WHEN 'PROD_ACAB' THEN 1
                    WHEN 'PROD_INT'  THEN 2
                    ELSE 99
                END,
                m.data_movimentacao,
                m.id
            )
        )[1]                                              AS produto_foco_id,
        (
            ARRAY_AGG(m.produto_nome ORDER BY
                CASE m.tipo_movimentacao
                    WHEN 'PROD_ACAB' THEN 1
                    WHEN 'PROD_INT'  THEN 2
                    ELSE 99
                END,
                m.data_movimentacao,
                m.id
            )
        )[1]                                              AS produto_foco_nome,
        -- Quantidade produzida (PROD_ACAB tem prioridade; senao soma PROD_INT)
        COALESCE(
            SUM(CASE WHEN m.tipo_movimentacao = 'PROD_ACAB' THEN m.quantidade ELSE 0 END),
            0
        )                                                 AS quantidade_acabada,
        COALESCE(
            SUM(CASE WHEN m.tipo_movimentacao = 'PROD_INT'  THEN m.quantidade ELSE 0 END),
            0
        )                                                 AS quantidade_intermediaria,
        -- Detalhe completo dos movimentos do bloco
        jsonb_agg(
            jsonb_build_object(
                'id',           m.id,
                'produto_id',   m.produto_id,
                'produto_nome', m.produto_nome,
                'tipo',         m.tipo_movimentacao,
                'quantidade',   m.quantidade,
                'saldo_antes',  m.saldo_antes,
                'saldo_depois', m.saldo_depois,
                'deposito_id',  m.deposito_id,
                'motivo',       m.motivo,
                'data',         m.data_movimentacao
            )
            ORDER BY m.data_movimentacao, m.id
        )                                                 AS movimentos
    FROM public.movimentacoes_estoque m
    LEFT JOIN public.itens_demanda i        ON i.id  = m.item_demanda_id
    LEFT JOIN public.demandas_producao d    ON d.id  = i.demanda_id
    WHERE m.correlation_id IS NOT NULL
    GROUP BY
        m.correlation_id,
        m.estagio,
        m.item_demanda_id,
        d.id,
        d.demanda_id,
        d.descricao
)
SELECT
    correlation_id,
    estagio,
    item_demanda_id,
    demanda_id_int,
    demanda_codigo,
    demanda_descricao,
    data_inicio,
    data_fim,
    usuario_id,
    total_movimentos,
    tipo_bloco,
    produto_foco_id,
    produto_foco_nome,
    -- Quantidade "principal" do bloco
    CASE tipo_bloco
        WHEN 'FINALIZACAO' THEN quantidade_acabada
        WHEN 'JIT'         THEN quantidade_intermediaria
        ELSE 0
    END                                                   AS quantidade_principal,
    -- Titulo human-readable
    CASE tipo_bloco
        WHEN 'FINALIZACAO' THEN
            'Finalizacao de '
            || TRIM(BOTH '0' FROM TRIM(BOTH '.' FROM TO_CHAR(quantidade_acabada, 'FM999999990.0000')))
            || ' x '
            || COALESCE(produto_foco_nome, 'produto ' || produto_foco_id::text)
        WHEN 'JIT' THEN
            'Producao JIT de '
            || TRIM(BOTH '0' FROM TRIM(BOTH '.' FROM TO_CHAR(quantidade_intermediaria, 'FM999999990.0000')))
            || ' x '
            || COALESCE(produto_foco_nome, 'produto ' || produto_foco_id::text)
        ELSE
            'Movimentacoes do estagio ' || estagio
    END                                                   AS titulo,
    movimentos
FROM grupos
ORDER BY data_inicio DESC, correlation_id, estagio;

COMMENT ON VIEW public.view_movimentacoes_consolidadas IS
'Agrega movimentacoes_estoque por (correlation_id, estagio). Cada linha eh um '
'bloco de negocio: FINALIZACAO (PROD_ACAB), JIT (PROD_INT) ou CONSUMO. Inclui '
'titulo human-readable e o array de movimentos crus em "movimentos" (jsonb).';
