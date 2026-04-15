-- Migration: Criar view de rastreamento pedido ↔ demanda
-- Data: 2026-04-11
--
-- Objetivo: Permitir rastrear facilmente qual pedido originou qual demanda
-- e quais demandas estão vinculadas a um pedido.
--
-- Fonte de dados: demandas_pedidos (pivot N:N) + pedidos + demandas_producao

CREATE OR REPLACE VIEW public.v_pedido_demanda_rastreamento AS
SELECT
    p.id AS pedido_id,
    p.numero_pedido,
    p.codigo_pedido_externo,
    p.origem AS pedido_origem,
    p.is_flex AS pedido_is_flex,
    p.personalizado AS pedido_personalizado,
    p.data_venda,
    p.cliente_nome,
    p.canal_venda_id,
    p.situacao_pedido_id,

    -- Aggregate: first demanda (para list display)
    (
        SELECT dp.id
        FROM public.demandas_pedidos dpiv
        JOIN public.demandas_producao dp ON dpiv.demanda_id = dp.id
        WHERE dpiv.pedido_id = p.id
        ORDER BY dp.created_at DESC
        LIMIT 1
    ) AS demanda_id,

    -- Human-readable demanda numero (para exibição)
    (
        SELECT dp.demanda_id
        FROM public.demandas_pedidos dpiv
        JOIN public.demandas_producao dp ON dpiv.demanda_id = dp.id
        WHERE dpiv.pedido_id = p.id
        ORDER BY dp.created_at DESC
        LIMIT 1
    ) AS demanda_numero,

    -- Status da primeira demanda (para exibição)
    (
        SELECT dp.status
        FROM public.demandas_pedidos dpiv
        JOIN public.demandas_producao dp ON dpiv.demanda_id = dp.id
        WHERE dpiv.pedido_id = p.id
        ORDER BY dp.created_at DESC
        LIMIT 1
    ) AS demanda_status,

    -- Count how many demands this pedido is linked to
    (
        SELECT COUNT(*)
        FROM public.demandas_pedidos dpiv
        WHERE dpiv.pedido_id = p.id
    ) AS total_demandas,

    cv.nome AS canal_venda_nome,
    sp.nome AS situacao_pedido_nome,
    sp.cor_status AS situacao_pedido_cor

FROM public.pedidos p
LEFT JOIN public.canais_venda cv ON p.canal_venda_id = cv.id
LEFT JOIN public.situacoes_pedido sp ON p.situacao_pedido_id = sp.id;

-- Grants
GRANT SELECT ON public.v_pedido_demanda_rastreamento TO authenticated;
GRANT SELECT ON public.v_pedido_demanda_rastreamento TO anon;

COMMENT ON VIEW public.v_pedido_demanda_rastreamento IS
'Rastreamento bidirecional entre pedidos e demandas de produção.
 Permite: (1) saber quais demandas um pedido originou,
          (2) saber quais pedidos originaram uma demanda.';

-- Testar
-- SELECT * FROM v_pedido_demanda_rastreamento LIMIT 10;
-- SELECT * FROM v_pedido_demanda_rastreamento WHERE pedido_id = 123;
-- SELECT * FROM v_pedido_demanda_rastreamento WHERE demanda_producao_id = 456;
