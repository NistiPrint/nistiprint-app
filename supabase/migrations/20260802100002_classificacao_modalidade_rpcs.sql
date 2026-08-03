-- Classificacao de modalidade, compromisso logistico e deteccao de metodo novo.
-- Contrato: docs/specs/02-domains/despacho/data-model.md
--
-- Determinismo e requisito, nao detalhe: o desempate da selecao de regra inclui
-- id. Sem isso dois pedidos identicos podem cair em modalidades diferentes
-- conforme o plano de execucao do Postgres.
--
-- Nenhuma funcao aqui bloqueia. Pedido sem match sai com modalidade NULL,
-- continua listavel e lancavel, e recebe compromisso no passado para ordenar no
-- topo. Prazo desconhecido e tratado como a hipotese mais urgente.

-- --------------------------------------------------------------------------
-- 1. Compromisso logistico
-- --------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.resolver_compromisso_logistico(
    p_modalidade_id  integer,
    p_integration_id integer,
    p_data_venda     timestamptz,
    p_agora          timestamptz DEFAULT now()
)
RETURNS timestamptz
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    -- GAP conhecido (spec, Known gaps): fuso e virada de dia operacional para
    -- marketplaces com corte apos meia-noite. Constante ate a decisao.
    c_tz     constant text := 'America/Sao_Paulo';
    v_tipo   text;
    v_offset integer;
    v_corte  time;
    v_base   date;
    v_result timestamptz;
BEGIN
    IF p_modalidade_id IS NULL THEN
        RETURN COALESCE(p_data_venda, p_agora);
    END IF;

    SELECT ml.tipo_prazo,
           ml.offset_etiqueta_min,
           COALESCE(cc.corte_horario, ml.corte_horario)
      INTO v_tipo, v_offset, v_corte
      FROM public.modalidades_logisticas ml
      LEFT JOIN public.modalidade_config_conta cc
             ON cc.modalidade_id  = ml.id
            AND cc.integration_id = p_integration_id
            AND cc.ativo
     WHERE ml.id = p_modalidade_id;

    IF v_tipo IS NULL THEN
        RETURN COALESCE(p_data_venda, p_agora);
    END IF;

    IF v_tipo = 'RELATIVO' THEN
        RETURN COALESCE(p_data_venda, p_agora)
               + make_interval(mins => COALESCE(v_offset, 0));
    END IF;

    v_base   := (p_agora AT TIME ZONE c_tz)::date;
    v_result := ((v_base + v_corte) AT TIME ZONE c_tz);

    IF v_result <= p_agora THEN
        v_result := ((v_base + 1 + v_corte) AT TIME ZONE c_tz);
    END IF;

    RETURN v_result;
END;
$$;

COMMENT ON FUNCTION public.resolver_compromisso_logistico(integer, integer, timestamptz, timestamptz) IS
  'Instante unico de ordenacao. RELATIVO: data_venda + offset. FIXO: proximo corte ainda futuro. Modalidade nula: data_venda, deliberadamente no passado.';

-- --------------------------------------------------------------------------
-- 2. Registro do metodo observado
-- --------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.registrar_metodo_envio_observado(
    p_module_id      varchar,
    p_integration_id integer,
    p_campo_origem   varchar,
    p_chave          text,
    p_rotulo         text,
    p_pedido_id      integer DEFAULT NULL
)
RETURNS integer
LANGUAGE plpgsql
AS $$
DECLARE
    v_id integer;
BEGIN
    IF p_chave IS NULL OR btrim(p_chave) = '' THEN
        RETURN NULL;
    END IF;

    INSERT INTO public.metodos_envio_observados (
        module_id, integration_id, campo_origem,
        valor_bruto, valor_normalizado, rotulo_bruto, pedido_exemplo_id
    )
    VALUES (
        p_module_id, p_integration_id, p_campo_origem,
        p_chave, lower(btrim(p_chave)), p_rotulo, p_pedido_id
    )
    ON CONFLICT (module_id, campo_origem, valor_normalizado) DO UPDATE
       SET ocorrencias          = public.metodos_envio_observados.ocorrencias + 1,
           ultima_ocorrencia_em = now(),
           rotulo_bruto         = COALESCE(EXCLUDED.rotulo_bruto,
                                           public.metodos_envio_observados.rotulo_bruto)
    RETURNING id INTO v_id;

    RETURN v_id;
END;
$$;

COMMENT ON FUNCTION public.registrar_metodo_envio_observado(varchar, integer, varchar, text, text, integer) IS
  'Upsert pela chave normalizada. Nao emite alerta: a emissao e do worker, que le status = NOVO e alerta_emitido_em IS NULL, para nao alertar dentro de transacao de ingest.';

-- --------------------------------------------------------------------------
-- 3. Classificacao de um pedido
-- --------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.classificar_pedido_modalidade(
    p_pedido_id integer,
    p_agora     timestamptz DEFAULT now()
)
RETURNS integer
LANGUAGE plpgsql
AS $$
DECLARE
    v_integration_id integer;
    v_module_id      varchar(100);
    v_chave          text;
    v_rotulo         text;
    v_data_venda     timestamptz;
    v_regra_id       integer;
    v_modalidade_id  integer;
BEGIN
    -- pedidos.marketplace_module_id ja vem carimbado pelo ingest (typed
    -- marketplace webhook resolution), sem precisar de join com
    -- installed_integrations para saber a plataforma.
    SELECT p.marketplace_integration_id,
           p.marketplace_module_id,
           p.metodo_envio_chave,
           p.metodo_envio_rotulo,
           p.data_venda AT TIME ZONE 'America/Sao_Paulo'
      INTO v_integration_id, v_module_id, v_chave, v_rotulo, v_data_venda
      FROM public.pedidos p
     WHERE p.id = p_pedido_id;

    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    IF v_module_id IS NOT NULL THEN
        SELECT r.id, r.modalidade_id
          INTO v_regra_id, v_modalidade_id
          FROM public.regras_classificacao_modalidade r
          JOIN public.modalidades_logisticas m ON m.id = r.modalidade_id AND m.ativo
         CROSS JOIN LATERAL (
            SELECT CASE WHEN r.alvo = 'ROTULO' THEN v_rotulo ELSE v_chave END AS alvo_valor
         ) a
         WHERE r.ativo
           AND r.module_id = v_module_id
           AND (r.integration_id IS NULL OR r.integration_id = v_integration_id)
           AND a.alvo_valor IS NOT NULL
           AND CASE r.operador
                 WHEN 'IGUAL' THEN
                     CASE WHEN r.case_sensitive
                          THEN a.alvo_valor = r.valor
                          ELSE lower(a.alvo_valor) = lower(r.valor) END
                 WHEN 'CONTEM' THEN
                     CASE WHEN r.case_sensitive
                          THEN position(r.valor in a.alvo_valor) > 0
                          ELSE position(lower(r.valor) in lower(a.alvo_valor)) > 0 END
                 WHEN 'PREFIXO' THEN
                     CASE WHEN r.case_sensitive
                          THEN a.alvo_valor LIKE r.valor || '%'
                          ELSE lower(a.alvo_valor) LIKE lower(r.valor) || '%' END
                 WHEN 'REGEX' THEN
                     CASE WHEN r.case_sensitive
                          THEN a.alvo_valor ~ r.valor
                          ELSE a.alvo_valor ~* r.valor END
                 ELSE false
               END
         -- Precedencia: regra de conta antes de regra global; depois prioridade;
         -- id como desempate final para garantir determinismo.
         ORDER BY (r.integration_id IS NULL), r.prioridade, r.id
         LIMIT 1;
    END IF;

    UPDATE public.pedidos
       SET modalidade_logistica_id    = v_modalidade_id,
           modalidade_regra_id        = v_regra_id,
           modalidade_classificada_em = p_agora,
           compromisso_logistico_em   = public.resolver_compromisso_logistico(
                                            v_modalidade_id, v_integration_id,
                                            v_data_venda, p_agora)
     WHERE id = p_pedido_id;

    IF v_modalidade_id IS NOT NULL THEN
        UPDATE public.metodos_envio_observados
           SET status        = 'CLASSIFICADO',
               modalidade_id = v_modalidade_id
         WHERE module_id         = v_module_id
           AND valor_normalizado = lower(btrim(v_chave))
           AND status            = 'NOVO';
    END IF;

    RETURN v_modalidade_id;
END;
$$;

-- --------------------------------------------------------------------------
-- 4. Reclassificacao retroativa em lotes
-- --------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.reclassificar_modalidade_backlog(
    p_limite integer DEFAULT 1000
)
RETURNS integer
LANGUAGE plpgsql
AS $$
DECLARE
    v_id    integer;
    v_total integer := 0;
BEGIN
    FOR v_id IN
        SELECT p.id
          FROM public.pedidos p
         WHERE p.despachado_em IS NULL
           AND p.metodo_envio_chave IS NOT NULL
           AND p.modalidade_logistica_id IS NULL
         ORDER BY p.id
         LIMIT p_limite
    LOOP
        PERFORM public.classificar_pedido_modalidade(v_id);
        v_total := v_total + 1;
    END LOOP;

    RETURN v_total;
END;
$$;

COMMENT ON FUNCTION public.reclassificar_modalidade_backlog(integer) IS
  'Reclassifica apenas pedidos abertos. Pedido ja despachado nunca e tocado: alterar o passado quebraria a rastreabilidade do lote e o compromisso ja gravado. Chamar em lotes; pedidos historico e grande.';
