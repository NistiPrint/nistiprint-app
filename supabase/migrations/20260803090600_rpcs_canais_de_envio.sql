-- Canais de envio: listar o que a origem realmente mandou, e associar cada um
-- a uma modalidade.
-- Contrato: docs/specs/02-domains/despacho/spec.md
--
-- ## Por que "observado" e nao "cadastrado"
--
-- A pergunta natural e "de onde vem a lista de canais do marketplace?". A
-- resposta tentadora e "de um catalogo que alguem cadastra" ou "de um endpoint
-- da plataforma". As duas envelhecem mal: catalogo desatualiza em silencio, e
-- nem toda plataforma expoe a lista.
--
-- A lista aqui e o distinct do trafego ja ingerido, com contagem. Canal que a
-- plataforma criar amanha aparece sozinho, sem deploy, porque
-- `registrar_metodo_envio_observado` roda no ingest. O sistema nao precisa
-- saber de antemao o que existe — precisa notar o que apareceu.
--
-- Consequencia de design: a tela nunca fica "completa". Ela fica *zerada*,
-- quando nenhum canal esta sem modalidade. E uma fila de trabalho, nao um
-- cadastro.

CREATE OR REPLACE FUNCTION public.canais_envio_observados(
    p_integration_id integer DEFAULT NULL
)
RETURNS TABLE (
    module_id         text,
    integration_id    integer,
    campo_origem      text,
    chave             text,
    rotulo            text,
    ocorrencias       integer,
    pedidos_pendentes integer,
    modalidade_id     integer,
    modalidade_nome   text,
    regra_id          integer,
    primeira_em       timestamptz,
    ultima_em         timestamptz
)
LANGUAGE sql
STABLE
AS $fn$
    SELECT
        o.module_id::text,
        p_integration_id,
        o.campo_origem::text,
        o.valor_bruto,
        o.rotulo_bruto,
        o.ocorrencias,
        COALESCE(pend.qtd, 0)::integer,
        r.modalidade_id,
        m.nome::text,
        r.id,
        o.primeira_ocorrencia_em,
        o.ultima_ocorrencia_em
      FROM public.metodos_envio_observados o
      -- A regra e por (module, alvo, valor), nao por conta: o canal logistico
      -- e da plataforma, e "Shopee Xpress" significa a mesma coisa em toda
      -- conta Shopee. O que varia por conta e a janela de coleta, e essa mora
      -- em regras_logisticas_integracao.
      LEFT JOIN public.regras_classificacao_modalidade r
             ON r.module_id = o.module_id
            AND r.alvo      = 'CHAVE'
            AND lower(r.valor) = o.valor_normalizado
            AND r.ativo
      LEFT JOIN public.modalidades_logisticas m ON m.id = r.modalidade_id
      LEFT JOIN LATERAL (
            SELECT count(*)::integer AS qtd
              FROM public.pedidos p
             WHERE p.metodo_envio_chave = o.valor_bruto
               AND p.marketplace_module_id = o.module_id
               AND p.despachado_em IS NULL
               AND p.situacao_pedido_id IN (2, 3, 4)
               AND (p_integration_id IS NULL
                    OR p.marketplace_integration_id = p_integration_id)
      ) pend ON true
     WHERE p_integration_id IS NULL
        OR o.module_id = (SELECT ii.module_id FROM public.installed_integrations ii
                           WHERE ii.id = p_integration_id)
     -- Nao associados primeiro: a tela existe para zerar essa fila.
     ORDER BY (r.modalidade_id IS NOT NULL), o.ocorrencias DESC;
$fn$;

COMMENT ON FUNCTION public.canais_envio_observados(integer) IS
  'Canais de envio vistos no trafego real, com contagem e a modalidade associada. Nao e catalogo: e o distinct do que a origem mandou.';

-- --------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.associar_canal_modalidade(
    p_module_id     text,
    p_chave         text,
    p_modalidade_id integer,
    p_campo_origem  text DEFAULT NULL
)
RETURNS TABLE (out_regra_id integer, out_pedidos_reclassificados integer)
LANGUAGE plpgsql
AS $fn$
DECLARE
    v_regra_id integer;
    v_campo    text;
    v_qtd      integer := 0;
    r          record;
BEGIN
    IF p_chave IS NULL OR btrim(p_chave) = '' THEN
        RAISE EXCEPTION 'chave do canal e obrigatoria' USING ERRCODE = 'invalid_parameter_value';
    END IF;

    SELECT COALESCE(p_campo_origem, max(o.campo_origem)) INTO v_campo
      FROM public.metodos_envio_observados o
     WHERE o.module_id = p_module_id
       AND o.valor_normalizado = lower(btrim(p_chave));
    v_campo := COALESCE(v_campo, 'metodo_envio');

    IF p_modalidade_id IS NULL THEN
        -- Desassociar desativa a regra, nao apaga. Quem associou o que e
        -- historico de cadastro, e um DELETE aqui apagaria a explicacao de por
        -- que 4 mil pedidos foram para Comum semana passada.
        UPDATE public.regras_classificacao_modalidade
           SET ativo = false, updated_at = now()
         WHERE module_id = p_module_id
           AND alvo = 'CHAVE'
           AND lower(valor) = lower(btrim(p_chave))
        RETURNING id INTO v_regra_id;
    ELSE
        SELECT id INTO v_regra_id
          FROM public.regras_classificacao_modalidade
         WHERE module_id = p_module_id
           AND alvo = 'CHAVE'
           AND lower(valor) = lower(btrim(p_chave))
         LIMIT 1;

        IF v_regra_id IS NULL THEN
            INSERT INTO public.regras_classificacao_modalidade (
                module_id, modalidade_id, campo_origem, alvo, operador, valor, prioridade
            ) VALUES (
                p_module_id, p_modalidade_id, v_campo, 'CHAVE', 'IGUAL', btrim(p_chave), 10
            ) RETURNING id INTO v_regra_id;
        ELSE
            UPDATE public.regras_classificacao_modalidade
               SET modalidade_id = p_modalidade_id, ativo = true, updated_at = now()
             WHERE id = v_regra_id;
        END IF;
    END IF;

    -- Reclassificacao retroativa apenas dos pendentes. Pedido ja despachado nao
    -- muda de lote por mudanca de cadastro: a demanda que o levou para producao
    -- ja existe, e reescrever a modalidade dele reescreveria a historia do lote.
    FOR r IN
        SELECT p.id FROM public.pedidos p
         WHERE p.marketplace_module_id = p_module_id
           AND lower(btrim(p.metodo_envio_chave)) = lower(btrim(p_chave))
           AND p.despachado_em IS NULL
           AND p.situacao_pedido_id IN (2, 3, 4)
    LOOP
        PERFORM public.classificar_pedido_modalidade(r.id);
        v_qtd := v_qtd + 1;
    END LOOP;

    -- `classificar_pedido_modalidade` nunca regride uma classificacao (ver
    -- comentario la). Ao desassociar, a regressao e justamente o que se quer,
    -- entao ela e feita aqui, explicitamente.
    IF p_modalidade_id IS NULL THEN
        UPDATE public.pedidos
           SET modalidade_logistica_id = NULL, modalidade_regra_id = NULL
         WHERE marketplace_module_id = p_module_id
           AND lower(btrim(metodo_envio_chave)) = lower(btrim(p_chave))
           AND despachado_em IS NULL
           AND situacao_pedido_id IN (2, 3, 4);
    END IF;

    RETURN QUERY SELECT v_regra_id, v_qtd;
END;
$fn$;

COMMENT ON FUNCTION public.associar_canal_modalidade(text, text, integer, text) IS
  'Associa um canal de envio observado a uma modalidade e reclassifica os pedidos pendentes que o usam. Modalidade NULL desassocia sem apagar a regra.';
