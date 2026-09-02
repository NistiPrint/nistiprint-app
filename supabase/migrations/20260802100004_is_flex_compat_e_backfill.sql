-- Compatibilidade do is_flex e backfill de modalidade.
-- Contrato: docs/specs/02-domains/despacho/data-model.md, secao "Transicao do is_flex"
--
-- is_flex e lido hoje em api/routes (pedidos, demandas, impressao, alertas,
-- consolidar, producao_contexto, unified_orders), no worker
-- (consolidation_tasks) e em RPCs. Trocar todos de uma vez e o caminho para
-- quebrar producao.
--
-- Fase 1 (esta migration): coexistencia. Um trigger mantem is_flex sincronizado
-- com modalidade_logistica_id. Nenhum consumidor muda. is_flex deixa de ser
-- escrito por qualquer outro caminho.
-- Fase 2: consumidores migram para modalidade_logistica_id / tipo_prazo.
--         Prioridade para os que decidem agrupamento e prioridade, porque sao
--         os que quebram com o Turbo: consolidation_tasks.py,
--         producao_contexto.py, alertas.py.
-- Fase 3: drop da coluna e do trigger.
--
-- Enquanto is_flex existir, ele nao pode ser criterio de agrupamento em codigo
-- novo. Um booleano nao representa tres modalidades.

-- --------------------------------------------------------------------------
-- 1. Trigger de compatibilidade
-- --------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.tg_pedidos_sync_is_flex()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_codigo varchar(50);
BEGIN
    IF NEW.modalidade_logistica_id IS NULL THEN
        NEW.is_flex := false;
        RETURN NEW;
    END IF;

    SELECT codigo INTO v_codigo
      FROM public.modalidades_logisticas
     WHERE id = NEW.modalidade_logistica_id;

    NEW.is_flex := (v_codigo = 'FLEX');
    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION public.tg_pedidos_sync_is_flex() IS
  'DEPRECATED por construcao. Existe apenas para os consumidores legados de is_flex sobreviverem a fase 1. Turbo e classificado como is_flex = false, o que e correto e insuficiente: por isso a fase 2 existe.';

DROP TRIGGER IF EXISTS tg_pedidos_sync_is_flex ON public.pedidos;
CREATE TRIGGER tg_pedidos_sync_is_flex
    BEFORE INSERT OR UPDATE OF modalidade_logistica_id ON public.pedidos
    FOR EACH ROW EXECUTE FUNCTION public.tg_pedidos_sync_is_flex();

COMMENT ON COLUMN public.pedidos.is_flex IS
  'DEPRECATED: derivado de modalidade_logistica_id pelo trigger tg_pedidos_sync_is_flex. Nao escrever diretamente. Nao usar como criterio de agrupamento em codigo novo.';

-- --------------------------------------------------------------------------
-- 2. Backfill em lotes
-- --------------------------------------------------------------------------

-- Idempotente e limitada. pedidos historico e grande demais para statement
-- unico: chamar em loop ate retornar 0.
CREATE OR REPLACE FUNCTION public.backfill_modalidade_pedidos(
    p_limite integer DEFAULT 1000
)
RETURNS TABLE (processados integer, classificados integer)
LANGUAGE plpgsql
AS $$
DECLARE
    r               record;
    v_processados   integer := 0;
    v_classificados integer := 0;
    v_modalidade_id integer;
BEGIN
    FOR r IN
        SELECT p.id,
               p.marketplace_integration_id,
               p.metodo_envio_chave,
               p.is_flex,
               p.marketplace_module_id AS module_id
          FROM public.pedidos p
         WHERE p.modalidade_logistica_id IS NULL
           AND p.modalidade_classificada_em IS NULL
         ORDER BY p.id DESC
         LIMIT p_limite
    LOOP
        v_processados := v_processados + 1;

        v_modalidade_id := public.classificar_pedido_modalidade(r.id);

        -- Fallback historico: antes do catalogo, Flex era o unico sinal de
        -- modalidade que existia. Aplicado somente quando nenhuma regra casou.
        IF v_modalidade_id IS NULL AND r.is_flex AND r.module_id IS NOT NULL THEN
            SELECT m.id INTO v_modalidade_id
              FROM public.modalidades_logisticas m
             WHERE m.module_id = r.module_id
               AND m.codigo = 'FLEX'
               AND m.ativo;

            IF v_modalidade_id IS NOT NULL THEN
                UPDATE public.pedidos p
                   SET modalidade_logistica_id    = v_modalidade_id,
                       modalidade_classificada_em = now(),
                       compromisso_logistico_em   = public.resolver_compromisso_logistico(
                                                        v_modalidade_id,
                                                        r.marketplace_integration_id,
                                                        p.data_venda AT TIME ZONE 'America/Sao_Paulo',
                                                        now())
                 WHERE p.id = r.id;
            END IF;
        END IF;

        IF v_modalidade_id IS NOT NULL THEN
            v_classificados := v_classificados + 1;
        END IF;
    END LOOP;

    RETURN QUERY SELECT v_processados, v_classificados;
END;
$$;

COMMENT ON FUNCTION public.backfill_modalidade_pedidos(integer) IS
  'ORDER BY id DESC: o backlog aberto e recente e importa primeiro. Pedido que nao casar em nenhuma etapa fica com modalidade nula. Esse e o resultado correto, nao uma falha do backfill.';

-- --------------------------------------------------------------------------
-- 3. Backfill de despachado_em
-- --------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.backfill_despachado_em(
    p_limite integer DEFAULT 5000
)
RETURNS integer
LANGUAGE plpgsql
AS $$
DECLARE
    v_total integer;
BEGIN
    WITH alvo AS (
        SELECT dp.pedido_id, min(d.created_at) AS despachado_em
          FROM public.demandas_pedidos dp
          JOIN public.demandas_producao d ON d.id = dp.demanda_id
          JOIN public.pedidos p ON p.id = dp.pedido_id
         WHERE p.despachado_em IS NULL
           AND COALESCE(d.status, '') <> 'RASCUNHO'
         GROUP BY dp.pedido_id
         LIMIT p_limite
    )
    UPDATE public.pedidos p
       SET despachado_em = alvo.despachado_em
      FROM alvo
     WHERE p.id = alvo.pedido_id;

    GET DIAGNOSTICS v_total = ROW_COUNT;
    RETURN v_total;
END;
$$;

COMMENT ON FUNCTION public.backfill_despachado_em(integer) IS
  'Rascunho nao despacha: demanda em RASCUNHO ainda recebe pedidos compativeis, entao seus pedidos continuam na arvore. Verificar o lexico de status vigente antes de rodar.';
