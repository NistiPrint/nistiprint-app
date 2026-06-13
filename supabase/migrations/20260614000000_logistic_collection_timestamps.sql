-- Separate marketplace order timestamps from operational collection planning.

ALTER TABLE public.pedidos
    ADD COLUMN IF NOT EXISTS data_compra_marketplace TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS data_pagamento_marketplace TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS data_coleta TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS data_envio_marketplace TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS regra_logistica_integracao_id BIGINT
        REFERENCES public.regras_logisticas_integracao(id) ON DELETE SET NULL;

ALTER TABLE public.demandas_producao
    ADD COLUMN IF NOT EXISTS data_coleta TIMESTAMPTZ;

ALTER TABLE public.pedidos_shopee
    ADD COLUMN IF NOT EXISTS pay_time TIMESTAMPTZ;

ALTER TABLE public.pedidos_mercadolivre
    ADD COLUMN IF NOT EXISTS date_approved TIMESTAMPTZ;

ALTER TABLE public.regras_logisticas_integracao
    ADD COLUMN IF NOT EXISTS horario_corte TIME,
    ADD COLUMN IF NOT EXISTS horario_coleta TIME;

UPDATE public.regras_logisticas_integracao
   SET horario_coleta = COALESCE(horario_coleta, horario_limite),
       horario_corte = COALESCE(horario_corte, horario_limite)
 WHERE horario_coleta IS NULL
    OR horario_corte IS NULL;

ALTER TABLE public.regras_logisticas_integracao
    ALTER COLUMN horario_coleta SET NOT NULL,
    ALTER COLUMN horario_corte SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_pedidos_data_coleta
    ON public.pedidos(data_coleta ASC NULLS LAST);

CREATE INDEX IF NOT EXISTS idx_demandas_producao_data_coleta
    ON public.demandas_producao(data_coleta ASC NULLS LAST);

CREATE INDEX IF NOT EXISTS idx_pedidos_data_pagamento_marketplace
    ON public.pedidos(data_pagamento_marketplace ASC NULLS LAST);

CREATE INDEX IF NOT EXISTS idx_regras_logisticas_integracao_cutoff
    ON public.regras_logisticas_integracao (
        marketplace_integration_id,
        modalidade,
        ativo,
        horario_corte,
        horario_coleta
    );

COMMENT ON COLUMN public.pedidos.data_compra_marketplace IS
'Data/hora em que o pedido foi criado/comprado no marketplace.';

COMMENT ON COLUMN public.pedidos.data_pagamento_marketplace IS
'Data/hora do pagamento aprovado no marketplace; usada contra a hora de corte logistica.';

COMMENT ON COLUMN public.pedidos.data_coleta IS
'Data/hora prevista de coleta pela transportadora na empresa ou entrega no ponto de coleta.';

COMMENT ON COLUMN public.pedidos.data_envio_marketplace IS
'Data/hora real de envio/bipagem no sistema do marketplace.';

COMMENT ON COLUMN public.pedidos.regra_logistica_integracao_id IS
'Regra logistica por integracao usada para calcular data_coleta.';

COMMENT ON COLUMN public.demandas_producao.data_coleta IS
'Menor data/hora de coleta dos pedidos vinculados a demanda, usada para ordenar a producao.';

COMMENT ON COLUMN public.regras_logisticas_integracao.horario_corte IS
'Hora limite do pagamento para entrar na coleta do mesmo dia.';

COMMENT ON COLUMN public.regras_logisticas_integracao.horario_coleta IS
'Hora prevista da coleta pela transportadora ou entrega no ponto de coleta.';

INSERT INTO public.regras_logisticas_integracao (
    marketplace_integration_id,
    modalidade,
    tipo_envio,
    horario_corte,
    horario_coleta,
    horario_limite,
    dias_semana,
    prioridade_uso,
    ativo,
    descricao
)
SELECT
    ii.id,
    seed.modalidade,
    seed.tipo_envio,
    seed.horario_corte::time,
    seed.horario_coleta::time,
    seed.horario_coleta::time,
    ARRAY[1,2,3,4,5]::smallint[],
    seed.prioridade_uso,
    true,
    seed.descricao
FROM public.installed_integrations ii
JOIN (
    VALUES
        ('shopee', 'FLEX', 'COLETA_LOCAL', '11:00', '13:00', 300, 'Shopee Flex: corte 11h, coleta/envio 13h'),
        ('mercadolivre', 'FLEX', 'COLETA_LOCAL', '12:00', '14:00', 250, 'Mercado Livre Flex: corte 12h, coleta/envio 14h'),
        ('amazon', 'STANDARD', 'COLETA_LOCAL', '14:00', '17:00', 100, 'Amazon Normal: corte 14h, coleta/envio 17h')
) AS seed(module_id, modalidade, tipo_envio, horario_corte, horario_coleta, prioridade_uso, descricao)
    ON lower(ii.module_id::text) = seed.module_id
WHERE COALESCE(ii.is_active, true) = true
ON CONFLICT DO NOTHING;

UPDATE public.pedidos p
   SET data_compra_marketplace = COALESCE(
           p.data_compra_marketplace,
           CASE
               WHEN (ps.raw_payload->>'create_time') ~ '^[0-9]+$'
               THEN to_timestamp((ps.raw_payload->>'create_time')::bigint)
               ELSE NULLIF(ps.raw_payload->>'create_time', '')::timestamptz
           END,
           ps.data_criacao::timestamptz
       ),
       data_pagamento_marketplace = COALESCE(p.data_pagamento_marketplace, ps.pay_time, ps.data_pagamento::timestamptz)
  FROM public.pedidos_shopee ps
 WHERE p.pedido_shopee_id = ps.id;

UPDATE public.pedidos p
   SET data_compra_marketplace = COALESCE(p.data_compra_marketplace, pm.raw_order->>'date_created'),
       data_pagamento_marketplace = COALESCE(p.data_pagamento_marketplace, pm.date_approved)
  FROM public.pedidos_mercadolivre pm
 WHERE p.pedido_mercadolivre_id = pm.id;

WITH candidates AS (
    SELECT
        p.id AS pedido_id,
        r.id AS regra_id,
        (
            (
                (timezone('America/Sao_Paulo', COALESCE(p.data_pagamento_marketplace, p.data_compra_marketplace, p.data_venda::timestamptz))::date + gs.day_offset)
                + r.horario_coleta
            ) AT TIME ZONE 'America/Sao_Paulo'
        ) AS data_coleta,
        row_number() OVER (
            PARTITION BY p.id
            ORDER BY
                (
                    (
                        (timezone('America/Sao_Paulo', COALESCE(p.data_pagamento_marketplace, p.data_compra_marketplace, p.data_venda::timestamptz))::date + gs.day_offset)
                        + r.horario_coleta
                    ) AT TIME ZONE 'America/Sao_Paulo'
                ) ASC,
                r.prioridade_uso DESC
        ) AS rn
    FROM public.pedidos p
    JOIN public.regras_logisticas_integracao r
      ON r.marketplace_integration_id = p.marketplace_integration_id
     AND r.modalidade = COALESCE(p.modalidade_logistica, 'STANDARD')
     AND r.ativo = true
    CROSS JOIN generate_series(0, 14) AS gs(day_offset)
    WHERE p.data_coleta IS NULL
      AND p.marketplace_integration_id IS NOT NULL
      AND EXTRACT(ISODOW FROM (
            timezone('America/Sao_Paulo', COALESCE(p.data_pagamento_marketplace, p.data_compra_marketplace, p.data_venda::timestamptz))::date + gs.day_offset
          ))::smallint = ANY(r.dias_semana)
      AND (
            gs.day_offset > 0
            OR timezone('America/Sao_Paulo', COALESCE(p.data_pagamento_marketplace, p.data_compra_marketplace, p.data_venda::timestamptz))::time <= r.horario_corte
          )
)
UPDATE public.pedidos p
   SET data_coleta = c.data_coleta,
       regra_logistica_integracao_id = c.regra_id
  FROM candidates c
 WHERE c.rn = 1
   AND p.id = c.pedido_id;

UPDATE public.demandas_producao d
   SET data_coleta = src.data_coleta
  FROM (
      SELECT dp.demanda_id, min(p.data_coleta) AS data_coleta
        FROM public.demandas_pedidos dp
        JOIN public.pedidos p ON p.id = dp.pedido_id
       WHERE p.data_coleta IS NOT NULL
       GROUP BY dp.demanda_id
  ) src
 WHERE d.id = src.demanda_id
   AND d.data_coleta IS NULL;
