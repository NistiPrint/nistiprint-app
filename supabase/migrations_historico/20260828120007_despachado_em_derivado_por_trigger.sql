-- `pedidos.despachado_em` passa a ser derivado, mantido por trigger.
-- Contrato: docs/specs/02-domains/despacho/spec.md, docs/specs/02-domains/despacho/data-model.md
--
-- ## O bug que esta migration fecha
--
-- `despachado_em` era escrito em exatamente um lugar (a publicacao da demanda)
-- e apagado em nenhum. Deletar ou cancelar a demanda derrubava o vinculo em
-- `demandas_pedidos` por CASCADE, mas o carimbo ficava. O pedido sumia da torre
-- para sempre: nao estava em nenhuma demanda e nao aparecia como pendente.
--
-- Em 27/08 isso tirou 68 pedidos Shopee da conferencia enquanto o painel do
-- marketplace continuava mostrando os mesmos 68 a enviar. E o desbatimento que
-- o operador viu.
--
-- ## Por que trigger e nao mais uma chamada na rota de delete
--
-- Consertar so a rota de exclusao deixaria a mesma armadilha de pe para o
-- proximo caminho que desfaz um lote — cancelamento, desvinculo de um pedido
-- avulso, correcao manual em SQL. `despachado_em` e uma projecao de
-- `demandas_pedidos` + status da demanda, e a unica forma de ela nao divergir e
-- o banco recalcula-la sozinho, sem depender de quem escreveu a chamada.
--
-- O campo continua existindo (e o predicado do indice parcial que a arvore
-- precisa; derivar de `demandas_pedidos` a cada consulta impede o indice).
-- Muda so quem e responsavel por mante-lo.
--
-- ## Definicao de "despachado"
--
-- Pertencer a pelo menos uma demanda publicada — status diferente de RASCUNHO,
-- CANCELADO e Cancelado. Palavra por palavra o predicado de
-- `vw_pedidos_pendentes_despacho`, de proposito: se divergirem, a torre volta a
-- prometer um total que o lancamento nao entrega.
--
-- Rascunho nao carimba: o lote ainda nao foi assumido e o pedido continua na
-- torre. Cancelamento devolve.

-- ============================================================================
-- 1. Recalculo pontual
-- ============================================================================

CREATE OR REPLACE FUNCTION public.despacho_sincronizar_carimbo(p_pedido_ids integer[])
RETURNS integer
LANGUAGE plpgsql
AS $fn$
DECLARE
    v_alterados integer;
BEGIN
    IF COALESCE(array_length(p_pedido_ids, 1), 0) = 0 THEN
        RETURN 0;
    END IF;

    WITH alvo AS (
        SELECT p.id,
               p.despachado_em,
               EXISTS (
                   SELECT 1
                     FROM public.demandas_pedidos dp
                     JOIN public.demandas_producao d ON d.id = dp.demanda_id
                    WHERE dp.pedido_id = p.id
                      AND d.status NOT IN ('RASCUNHO', 'CANCELADO', 'Cancelado')
               ) AS deveria_estar_despachado
          FROM public.pedidos p
         WHERE p.id = ANY(p_pedido_ids)
    ),
    aplicado AS (
        UPDATE public.pedidos p
           -- Carimbo existente e preservado: a data em que o galpao assumiu o
           -- lote e fato historico e nao pode ser reescrita por um recalculo.
           SET despachado_em = CASE WHEN a.deveria_estar_despachado THEN now() END
          FROM alvo a
         WHERE p.id = a.id
           AND a.deveria_estar_despachado <> (a.despachado_em IS NOT NULL)
        RETURNING p.id
    )
    SELECT count(*) INTO v_alterados FROM aplicado;

    RETURN v_alterados;
END;
$fn$;

COMMENT ON FUNCTION public.despacho_sincronizar_carimbo(integer[]) IS
  'Recalcula pedidos.despachado_em a partir de demandas_pedidos + status da demanda. Carimbo ja existente e preservado; so a transicao e escrita.';

-- ============================================================================
-- 2. Triggers
-- ============================================================================

-- Vinculo criado ou desfeito. O DELETE cobre tambem a exclusao da demanda: o
-- CASCADE de demandas_pedidos dispara este mesmo gatilho.
CREATE OR REPLACE FUNCTION public.trg_demandas_pedidos_sincroniza_carimbo()
RETURNS trigger
LANGUAGE plpgsql
AS $fn$
DECLARE
    v_ids integer[];
BEGIN
    IF TG_OP = 'INSERT' THEN
        SELECT array_agg(DISTINCT pedido_id) INTO v_ids FROM novos;
    ELSE
        SELECT array_agg(DISTINCT pedido_id) INTO v_ids FROM antigos;
    END IF;

    PERFORM public.despacho_sincronizar_carimbo(v_ids);
    RETURN NULL;
END;
$fn$;

DROP TRIGGER IF EXISTS demandas_pedidos_sincroniza_carimbo_ins ON public.demandas_pedidos;
CREATE TRIGGER demandas_pedidos_sincroniza_carimbo_ins
    AFTER INSERT ON public.demandas_pedidos
    REFERENCING NEW TABLE AS novos
    FOR EACH STATEMENT
    EXECUTE FUNCTION public.trg_demandas_pedidos_sincroniza_carimbo();

DROP TRIGGER IF EXISTS demandas_pedidos_sincroniza_carimbo_del ON public.demandas_pedidos;
CREATE TRIGGER demandas_pedidos_sincroniza_carimbo_del
    AFTER DELETE ON public.demandas_pedidos
    REFERENCING OLD TABLE AS antigos
    FOR EACH STATEMENT
    EXECUTE FUNCTION public.trg_demandas_pedidos_sincroniza_carimbo();

-- Status da demanda mudou: publicar tira da torre, cancelar devolve. Sem lista
-- de colunas no CREATE TRIGGER porque o Postgres recusa tabela de transicao com
-- lista de colunas; o filtro de status fica no corpo.
CREATE OR REPLACE FUNCTION public.trg_demandas_producao_sincroniza_carimbo()
RETURNS trigger
LANGUAGE plpgsql
AS $fn$
DECLARE
    v_ids integer[];
BEGIN
    SELECT array_agg(DISTINCT dp.pedido_id) INTO v_ids
      FROM public.demandas_pedidos dp
      JOIN novos n ON n.id = dp.demanda_id
      JOIN antigos a ON a.id = n.id
     WHERE n.status IS DISTINCT FROM a.status;

    PERFORM public.despacho_sincronizar_carimbo(v_ids);
    RETURN NULL;
END;
$fn$;

DROP TRIGGER IF EXISTS demandas_producao_sincroniza_carimbo ON public.demandas_producao;
CREATE TRIGGER demandas_producao_sincroniza_carimbo
    AFTER UPDATE ON public.demandas_producao
    REFERENCING NEW TABLE AS novos OLD TABLE AS antigos
    FOR EACH STATEMENT
    EXECUTE FUNCTION public.trg_demandas_producao_sincroniza_carimbo();

-- ============================================================================
-- 3. Checagem de consistencia
-- ============================================================================
--
-- Pedida no data-model.md como mitigacao do risco "despachado_em fora de
-- sincronia". Escopo restrito ao pedido ainda aberto: o historico anterior a
-- esta migration carrega carimbos de demandas que ja nao existem, e reescreve-los
-- apagaria a unica marca de que aquele pedido um dia saiu da torre.

CREATE OR REPLACE VIEW public.vw_despacho_carimbo_inconsistente AS
SELECT p.id AS pedido_id,
       p.numero_pedido,
       p.codigo_pedido_externo,
       p.situacao_pedido_id,
       p.despachado_em,
       EXISTS (
           SELECT 1 FROM public.demandas_pedidos dp
             JOIN public.demandas_producao d ON d.id = dp.demanda_id
            WHERE dp.pedido_id = p.id
              AND d.status NOT IN ('RASCUNHO', 'CANCELADO', 'Cancelado')
       ) AS em_demanda_publicada
  FROM public.pedidos p
 WHERE p.situacao_pedido_id IN (2, 3, 4)
   AND (p.despachado_em IS NOT NULL) <> EXISTS (
           SELECT 1 FROM public.demandas_pedidos dp
             JOIN public.demandas_producao d ON d.id = dp.demanda_id
            WHERE dp.pedido_id = p.id
              AND d.status NOT IN ('RASCUNHO', 'CANCELADO', 'Cancelado')
       );

COMMENT ON VIEW public.vw_despacho_carimbo_inconsistente IS
  'Pedido aberto cujo despachado_em nao bate com demandas_pedidos. Deve estar sempre vazia; linha aqui significa pedido escondido da torre ou contado duas vezes.';

GRANT SELECT ON public.vw_despacho_carimbo_inconsistente TO anon, authenticated;
