-- Migration: 20260508000002_view_auditoria_variacoes_tipo_divergente.sql
-- Data: 2026-05-08
-- Proposito: Auditar variacoes (parent_id IS NOT NULL) cujo tipo_produto
--            diverge do tipo_produto do pai. Apenas LEITURA — nao altera dados.
--
-- Contexto: A modelagem atual permite que uma variacao tenha tipo_produto
-- diferente do pai (ex: pai = MATERIA_PRIMA, variacao = PRODUTO_ACABADO).
-- Isso quebra o motor de reconciliacao de estoque, pois a guarda de BOM
-- (validar_componente_ficha_tecnica) bloqueia componentes PRODUTO_ACABADO.
--
-- Esta migration cria apenas a view de auditoria. O backfill e o trigger
-- de invariante serao aplicados em migrations subsequentes, apos revisao
-- do resultado desta auditoria.

-- ============================================================
-- 1. View de auditoria: variacoes com tipo_produto divergente do pai
-- ============================================================

CREATE OR REPLACE VIEW public.v_auditoria_variacoes_tipo_divergente AS
SELECT
  v.id              AS variacao_id,
  v.sku             AS variacao_sku,
  v.nome            AS variacao_nome,
  v.tipo_produto    AS variacao_tipo_produto,
  v.tipo_material   AS variacao_tipo_material,
  v.status          AS variacao_status,
  p.id              AS pai_id,
  p.sku             AS pai_sku,
  p.nome            AS pai_nome,
  p.tipo_produto    AS pai_tipo_produto,
  p.tipo_material   AS pai_tipo_material,
  v.formato         AS variacao_formato,
  v.herdar_dados_pai,
  v.created_at      AS variacao_created_at,
  v.updated_at      AS variacao_updated_at
FROM public.produtos v
JOIN public.produtos p
  ON p.id = v.parent_id
WHERE v.parent_id IS NOT NULL
  AND v.tipo_produto IS DISTINCT FROM p.tipo_produto;

COMMENT ON VIEW public.v_auditoria_variacoes_tipo_divergente IS
'Auditoria: lista variacoes cujo tipo_produto difere do pai. Usada antes do '
'backfill (passo 2) e do trigger de invariante (passo 3). Apenas leitura.';

-- ============================================================
-- 2. Relatorio de execucao (mostra contagem ao aplicar a migration)
-- ============================================================

DO $$
DECLARE
  total_variacoes      INTEGER;
  total_divergentes    INTEGER;
  total_pa_em_mp       INTEGER;
  total_mp_em_pa       INTEGER;
  total_outros         INTEGER;
  total_ativos_div     INTEGER;
  rec RECORD;
BEGIN
  SELECT COUNT(*) INTO total_variacoes
    FROM public.produtos WHERE parent_id IS NOT NULL;

  SELECT COUNT(*) INTO total_divergentes
    FROM public.v_auditoria_variacoes_tipo_divergente;

  -- Casos mais perigosos: variacao classificada como PRODUTO_ACABADO,
  -- mas pai eh MATERIA_PRIMA ou INTERMEDIARIO (= a causa do bug do motor).
  SELECT COUNT(*) INTO total_pa_em_mp
    FROM public.v_auditoria_variacoes_tipo_divergente
   WHERE variacao_tipo_produto = 'PRODUTO_ACABADO'
     AND pai_tipo_produto IN ('MATERIA_PRIMA', 'INTERMEDIARIO');

  -- Caso inverso: pai PA, variacao MP/INT.
  SELECT COUNT(*) INTO total_mp_em_pa
    FROM public.v_auditoria_variacoes_tipo_divergente
   WHERE variacao_tipo_produto IN ('MATERIA_PRIMA', 'INTERMEDIARIO')
     AND pai_tipo_produto = 'PRODUTO_ACABADO';

  total_outros := total_divergentes - total_pa_em_mp - total_mp_em_pa;

  SELECT COUNT(*) INTO total_ativos_div
    FROM public.v_auditoria_variacoes_tipo_divergente
   WHERE variacao_status = 'ativo';

  RAISE NOTICE '';
  RAISE NOTICE '==================================================';
  RAISE NOTICE 'AUDITORIA: VARIACOES COM TIPO DIVERGENTE DO PAI';
  RAISE NOTICE '==================================================';
  RAISE NOTICE 'Total de variacoes (parent_id NOT NULL): %', total_variacoes;
  RAISE NOTICE 'Total divergentes do pai:                %', total_divergentes;
  RAISE NOTICE '  - das quais ATIVAS (status=ativo):     %', total_ativos_div;
  RAISE NOTICE '';
  RAISE NOTICE 'Distribuicao do desvio:';
  RAISE NOTICE '  - variacao=PA, pai=MP/INT (CRITICO):   %', total_pa_em_mp;
  RAISE NOTICE '  - variacao=MP/INT, pai=PA:             %', total_mp_em_pa;
  RAISE NOTICE '  - outros desvios:                      %', total_outros;
  RAISE NOTICE '==================================================';

  -- Lista os 20 primeiros casos criticos (PA em pai MP/INT) para inspecao
  IF total_pa_em_mp > 0 THEN
    RAISE NOTICE '';
    RAISE NOTICE 'Primeiros 20 casos CRITICOS (variacao=PA, pai=MP/INT):';
    RAISE NOTICE '  variacao_id | variacao_sku | variacao_tipo -> pai_tipo | pai_sku';
    FOR rec IN
      SELECT variacao_id, variacao_sku, variacao_tipo_produto,
             pai_tipo_produto, pai_sku
        FROM public.v_auditoria_variacoes_tipo_divergente
       WHERE variacao_tipo_produto = 'PRODUTO_ACABADO'
         AND pai_tipo_produto IN ('MATERIA_PRIMA', 'INTERMEDIARIO')
       ORDER BY variacao_id
       LIMIT 20
    LOOP
      RAISE NOTICE '  % | % | % -> % | %',
        rec.variacao_id, rec.variacao_sku,
        rec.variacao_tipo_produto, rec.pai_tipo_produto, rec.pai_sku;
    END LOOP;

    IF total_pa_em_mp > 20 THEN
      RAISE NOTICE '  ... e mais % caso(s) critico(s).', total_pa_em_mp - 20;
    END IF;
  END IF;

  RAISE NOTICE '==================================================';
  RAISE NOTICE 'Para inspecionar todos os registros:';
  RAISE NOTICE '  SELECT * FROM public.v_auditoria_variacoes_tipo_divergente';
  RAISE NOTICE '  ORDER BY pai_id, variacao_id;';
  RAISE NOTICE '==================================================';
END $$;

-- ============================================================
-- FIM DA MIGRATION
-- Proximas etapas (em migrations separadas, apos revisao):
--   2. Snapshot + backfill: copiar tipo_produto do pai p/ variacoes divergentes.
--   3. Trigger de invariante: auto-corrigir tipo_produto da variacao no
--      INSERT/UPDATE para sempre seguir o pai.
--   4. Limpeza Python: remover fallback "produto_acabado" em create_variant.
-- ============================================================
