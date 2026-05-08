-- Migration: 20260508000003_backfill_e_invariante_tipo_produto_variacao.sql
-- Data: 2026-05-08
-- Proposito:
--   Passo 2 (backfill) + passo 3 (invariante) da revisao da arquitetura
--   de produtos com variacoes. Continuacao de
--   20260508000002_view_auditoria_variacoes_tipo_divergente.sql.
--
-- O que faz:
--   1. Cria snapshot da tabela produtos (rollback simples).
--   2. Faz backfill: copia tipo_produto/tipo_material do pai para variacoes
--      cujo tipo diverge do pai.
--   3. Adiciona trigger BEFORE em produtos: auto-corrige tipo_produto/
--      tipo_material da variacao para sempre seguir o pai (so atua quando
--      parent_id IS NOT NULL).
--   4. Adiciona trigger AFTER UPDATE no pai: cascateia mudancas de
--      tipo_produto/tipo_material para todas as variacoes.
--
-- Rollback:
--   UPDATE public.produtos p
--      SET tipo_produto  = s.tipo_produto,
--          tipo_material = s.tipo_material
--     FROM public._snapshot_produtos_tipo_20260508 s
--    WHERE p.id = s.id;
--   DROP TRIGGER trg_validar_tipo_produto_variacao ON public.produtos;
--   DROP TRIGGER trg_cascade_tipo_pai_para_variacoes ON public.produtos;
--   DROP FUNCTION public.validar_tipo_produto_variacao();
--   DROP FUNCTION public.cascade_tipo_pai_para_variacoes();

-- ============================================================
-- 1. Snapshot pre-backfill (rollback)
-- ============================================================

CREATE TABLE IF NOT EXISTS public._snapshot_produtos_tipo_20260508 AS
SELECT id, tipo_produto, tipo_material, parent_id, updated_at
  FROM public.produtos
 WHERE parent_id IS NOT NULL;

COMMENT ON TABLE public._snapshot_produtos_tipo_20260508 IS
'Snapshot dos campos tipo_produto/tipo_material de variacoes antes do backfill '
'aplicado em 2026-05-08. Pode ser removido apos validacao em producao.';

-- ============================================================
-- 2. Backfill: alinhar variacoes ao tipo_produto/tipo_material do pai
-- ============================================================

DO $$
DECLARE
  v_total_atualizadas INTEGER;
  rec RECORD;
BEGIN
  -- Lista os registros que serao alterados (antes de aplicar)
  RAISE NOTICE '';
  RAISE NOTICE '==================================================';
  RAISE NOTICE 'BACKFILL DE TIPO_PRODUTO EM VARIACOES';
  RAISE NOTICE '==================================================';
  RAISE NOTICE 'Registros que serao corrigidos:';
  FOR rec IN
    SELECT v.id   AS variacao_id, v.sku AS variacao_sku,
           v.tipo_produto AS de_tipo_produto,
           v.tipo_material AS de_tipo_material,
           p.tipo_produto AS para_tipo_produto,
           p.tipo_material AS para_tipo_material,
           p.sku AS pai_sku
      FROM public.produtos v
      JOIN public.produtos p ON p.id = v.parent_id
     WHERE v.parent_id IS NOT NULL
       AND (v.tipo_produto IS DISTINCT FROM p.tipo_produto
            OR v.tipo_material IS DISTINCT FROM p.tipo_material)
     ORDER BY v.id
  LOOP
    RAISE NOTICE '  variacao % (%) [pai %]: tipo_produto % -> %, tipo_material % -> %',
      rec.variacao_id, rec.variacao_sku, rec.pai_sku,
      rec.de_tipo_produto, rec.para_tipo_produto,
      rec.de_tipo_material, rec.para_tipo_material;
  END LOOP;

  -- Aplica o backfill
  WITH corrigidas AS (
    UPDATE public.produtos v
       SET tipo_produto = p.tipo_produto,
           tipo_material = p.tipo_material,
           updated_at = CURRENT_TIMESTAMP
      FROM public.produtos p
     WHERE v.parent_id = p.id
       AND v.parent_id IS NOT NULL
       AND (v.tipo_produto IS DISTINCT FROM p.tipo_produto
            OR v.tipo_material IS DISTINCT FROM p.tipo_material)
    RETURNING v.id
  )
  SELECT COUNT(*) INTO v_total_atualizadas FROM corrigidas;

  RAISE NOTICE '';
  RAISE NOTICE 'Backfill concluido: % variacao(oes) corrigida(s).', v_total_atualizadas;
  RAISE NOTICE '==================================================';
END $$;

-- Conferencia: nao deve sobrar nada na view de auditoria apos o backfill.
DO $$
DECLARE
  v_remanescente INTEGER;
BEGIN
  SELECT COUNT(*) INTO v_remanescente
    FROM public.v_auditoria_variacoes_tipo_divergente;

  IF v_remanescente <> 0 THEN
    RAISE EXCEPTION
      'Backfill incompleto: % registro(s) ainda divergente(s) apos o UPDATE. '
      'Verifique public.v_auditoria_variacoes_tipo_divergente.', v_remanescente;
  END IF;

  RAISE NOTICE 'Verificacao OK: 0 registros divergentes restantes.';
END $$;

-- ============================================================
-- 3. Invariante: trigger BEFORE em variacoes (auto-correcao)
-- ============================================================
--
-- Objetivo: sempre que uma variacao for inserida ou atualizada, garantir
-- que tipo_produto/tipo_material casem com os do pai. Nao bloqueia: corrige
-- silenciosamente para evitar quebrar fluxos legados que enviam o tipo errado
-- (ex: create_variant com fallback "produto_acabado" no codigo Python).

CREATE OR REPLACE FUNCTION public.validar_tipo_produto_variacao()
RETURNS trigger AS $$
DECLARE
  v_pai_tipo_produto  public.tipo_produto_enum;
  v_pai_tipo_material text;
BEGIN
  -- So aplica para variacoes
  IF NEW.parent_id IS NULL THEN
    RETURN NEW;
  END IF;

  SELECT tipo_produto, tipo_material
    INTO v_pai_tipo_produto, v_pai_tipo_material
    FROM public.produtos
   WHERE id = NEW.parent_id;

  IF v_pai_tipo_produto IS NOT NULL
     AND NEW.tipo_produto IS DISTINCT FROM v_pai_tipo_produto THEN
    NEW.tipo_produto := v_pai_tipo_produto;
  END IF;

  IF v_pai_tipo_material IS NOT NULL
     AND NEW.tipo_material IS DISTINCT FROM v_pai_tipo_material THEN
    NEW.tipo_material := v_pai_tipo_material;
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_validar_tipo_produto_variacao ON public.produtos;
CREATE TRIGGER trg_validar_tipo_produto_variacao
  BEFORE INSERT OR UPDATE OF tipo_produto, tipo_material, parent_id
  ON public.produtos
  FOR EACH ROW
  EXECUTE FUNCTION public.validar_tipo_produto_variacao();

COMMENT ON FUNCTION public.validar_tipo_produto_variacao() IS
'BEFORE INSERT/UPDATE em produtos: variacoes (parent_id NOT NULL) tem '
'tipo_produto/tipo_material auto-corrigidos para casar com o pai.';

-- ============================================================
-- 4. Cascade: trigger AFTER UPDATE no pai
-- ============================================================
--
-- Quando um produto pai (parent_id IS NULL) altera tipo_produto/tipo_material,
-- propaga para todas as variacoes ativas/inativas. O trigger BEFORE acima
-- garante consistencia em INSERTs novos; este garante consistencia em mudancas
-- posteriores no pai (que antes nao cascateavam).

CREATE OR REPLACE FUNCTION public.cascade_tipo_pai_para_variacoes()
RETURNS trigger AS $$
BEGIN
  -- So cascateia se o registro alterado for um pai (sem parent_id)
  IF NEW.parent_id IS NOT NULL THEN
    RETURN NEW;
  END IF;

  IF NEW.tipo_produto IS DISTINCT FROM OLD.tipo_produto
     OR NEW.tipo_material IS DISTINCT FROM OLD.tipo_material THEN

    UPDATE public.produtos
       SET tipo_produto  = NEW.tipo_produto,
           tipo_material = NEW.tipo_material,
           updated_at    = CURRENT_TIMESTAMP
     WHERE parent_id = NEW.id
       AND (tipo_produto  IS DISTINCT FROM NEW.tipo_produto
         OR tipo_material IS DISTINCT FROM NEW.tipo_material);
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_cascade_tipo_pai_para_variacoes ON public.produtos;
CREATE TRIGGER trg_cascade_tipo_pai_para_variacoes
  AFTER UPDATE OF tipo_produto, tipo_material
  ON public.produtos
  FOR EACH ROW
  EXECUTE FUNCTION public.cascade_tipo_pai_para_variacoes();

COMMENT ON FUNCTION public.cascade_tipo_pai_para_variacoes() IS
'AFTER UPDATE em produtos: quando um pai (parent_id NULL) muda tipo_produto/'
'tipo_material, cascateia o novo valor para todas as variacoes filhas.';

-- ============================================================
-- 5. Relatorio final
-- ============================================================

DO $$
DECLARE
  v_total_variacoes   INTEGER;
  v_total_divergentes INTEGER;
BEGIN
  SELECT COUNT(*) INTO v_total_variacoes
    FROM public.produtos WHERE parent_id IS NOT NULL;

  SELECT COUNT(*) INTO v_total_divergentes
    FROM public.v_auditoria_variacoes_tipo_divergente;

  RAISE NOTICE '';
  RAISE NOTICE '==================================================';
  RAISE NOTICE 'INVARIANTE DE TIPO PRODUTO PAI <-> VARIACAO ATIVA';
  RAISE NOTICE '==================================================';
  RAISE NOTICE 'Total de variacoes:               %', v_total_variacoes;
  RAISE NOTICE 'Divergentes apos backfill:        %', v_total_divergentes;
  RAISE NOTICE 'Trigger BEFORE (auto-correcao):   trg_validar_tipo_produto_variacao';
  RAISE NOTICE 'Trigger AFTER (cascade do pai):   trg_cascade_tipo_pai_para_variacoes';
  RAISE NOTICE 'Snapshot rollback em:             public._snapshot_produtos_tipo_20260508';
  RAISE NOTICE '==================================================';
END $$;

-- ============================================================
-- FIM DA MIGRATION
-- Proximo passo (codigo Python, fora de migration):
--   - product_service.create_variant: trocar fallback "produto_acabado"
--     por "materia_prima" (defesa em profundidade; trigger ja cobre).
-- ============================================================
