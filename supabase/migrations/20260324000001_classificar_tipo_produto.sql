-- Migration: 20260324000001_classificar_tipo_produto.sql
-- Data: 2026-03-24
-- Propósito: Popular tipo_produto a partir do campo existente tipo_material
-- 
-- OBS: O campo tipo_material já existe na tabela produtos com valores:
--   - 'materia_prima'
--   - 'intermediario' 
--   - 'produto_acabado'
--   - 'servico'

-- ============================================================
-- 1. CRIAR ENUM TIPO_PRODUTO (se não existir)
-- ============================================================

DO $$ BEGIN
    CREATE TYPE public.tipo_produto_enum AS ENUM (
        'MATERIA_PRIMA',
        'INTERMEDIARIO',
        'PRODUTO_ACABADO',
        'SERVICO'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- ============================================================
-- 2. ADICIONAR COLUNA TIPO_PRODUTO (se não existir)
-- ============================================================

ALTER TABLE public.produtos 
ADD COLUMN IF NOT EXISTS tipo_produto public.tipo_produto_enum;

-- ============================================================
-- 3. POPULAR TIPO_PRODUTO A PARTIR DE TIPO_MATERIAL
-- ============================================================

-- Converter valores de tipo_material para tipo_produto
UPDATE public.produtos
SET tipo_produto = CASE
    WHEN tipo_material = 'materia_prima' THEN 'MATERIA_PRIMA'::tipo_produto_enum
    WHEN tipo_material = 'intermediario' THEN 'INTERMEDIARIO'::tipo_produto_enum
    WHEN tipo_material = 'produto_acabado' THEN 'PRODUTO_ACABADO'::tipo_produto_enum
    WHEN tipo_material = 'servico' THEN 'SERVICO'::tipo_produto_enum
    ELSE NULL
END
WHERE tipo_produto IS NULL
  AND tipo_material IS NOT NULL;

-- ============================================================
-- 4. RELATÓRIO DE CLASSIFICAÇÃO
-- ============================================================

DO $$
DECLARE
    total_produtos INTEGER;
    total_classificados INTEGER;
    total_nao_classificados INTEGER;
    total_mp INTEGER;
    total_int INTEGER;
    total_pa INTEGER;
    total_svc INTEGER;
    rec RECORD;
BEGIN
    -- Contar totais
    SELECT COUNT(*) INTO total_produtos FROM public.produtos;
    SELECT COUNT(*) INTO total_classificados FROM public.produtos WHERE tipo_produto IS NOT NULL;
    SELECT COUNT(*) INTO total_nao_classificados FROM public.produtos WHERE tipo_produto IS NULL;
    SELECT COUNT(*) INTO total_mp FROM public.produtos WHERE tipo_produto = 'MATERIA_PRIMA';
    SELECT COUNT(*) INTO total_int FROM public.produtos WHERE tipo_produto = 'INTERMEDIARIO';
    SELECT COUNT(*) INTO total_pa FROM public.produtos WHERE tipo_produto = 'PRODUTO_ACABADO';
    SELECT COUNT(*) INTO total_svc FROM public.produtos WHERE tipo_produto = 'SERVICO';
    
    RAISE NOTICE '';
    RAISE NOTICE '==================================================';
    RAISE NOTICE 'CLASSIFICAÇÃO DE TIPO_PRODUTO CONCLUÍDA';
    RAISE NOTICE '==================================================';
    RAISE NOTICE 'Total de produtos: %', total_produtos;
    RAISE NOTICE '';
    RAISE NOTICE 'Classificados via tipo_material:';
    RAISE NOTICE '  - MATERIA_PRIMA:    %', total_mp;
    RAISE NOTICE '  - INTERMEDIARIO:    %', total_int;
    RAISE NOTICE '  - PRODUTO_ACABADO:  %', total_pa;
    RAISE NOTICE '  - SERVICO:          %', total_svc;
    RAISE NOTICE '  -------------------------';
    RAISE NOTICE '  Total classificados: %', total_classificados;
    RAISE NOTICE '';
    RAISE NOTICE 'Não classificados (tipo_material NULL): %', total_nao_classificados;
    RAISE NOTICE '==================================================';
    
    -- Se houver não classificados, listar os primeiros 10
    IF total_nao_classificados > 0 THEN
        RAISE NOTICE '';
        RAISE NOTICE 'Produtos sem classificação (primeiros 10):';
        FOR rec IN 
            SELECT p.id, p.sku, p.nome, p.tipo_material
            FROM public.produtos p
            WHERE p.tipo_produto IS NULL
            LIMIT 10
        LOOP
            RAISE NOTICE '  ID: % | SKU: % | Nome: % | tipo_material: %', 
                rec.id, rec.sku, rec.nome, rec.tipo_material;
        END LOOP;
        
        IF total_nao_classificados > 10 THEN
            RAISE NOTICE '  ... e mais % produtos', total_nao_classificados - 10;
        END IF;
    END IF;
    
    RAISE NOTICE '==================================================';
END $$;

-- ============================================================
-- 5. CRIAR VIEW DE AUDITORIA
-- ============================================================

CREATE OR REPLACE VIEW public.view_auditoria_tipo_produto AS
SELECT 
    p.id,
    p.nome as produto_nome,
    p.sku,
    p.tipo_material,
    p.tipo_produto,
    CASE 
        WHEN p.tipo_produto IS NULL AND p.tipo_material IS NOT NULL THEN 'ERRO_CONVERSAO'
        WHEN p.tipo_produto IS NULL AND p.tipo_material IS NULL THEN 'SEM_CLASSIFICACAO'
        WHEN p.tipo_material IS NULL AND p.tipo_produto IS NOT NULL THEN 'OK_MANUAL'
        WHEN (
            (p.tipo_material = 'materia_prima' AND p.tipo_produto = 'MATERIA_PRIMA') OR
            (p.tipo_material = 'intermediario' AND p.tipo_produto = 'INTERMEDIARIO') OR
            (p.tipo_material = 'produto_acabado' AND p.tipo_produto = 'PRODUTO_ACABADO') OR
            (p.tipo_material = 'servico' AND p.tipo_produto = 'SERVICO')
        ) THEN 'OK'
        ELSE 'DIVERGENTE'
    END as status_conferencia,
    p.updated_at
FROM public.produtos p
ORDER BY p.id;

COMMENT ON VIEW public.view_auditoria_tipo_produto IS
'Auditoria da conversão de tipo_material para tipo_produto.';

-- ============================================================
-- 6. CRIAR TRIGGER PARA SINCRONIA FUTURA
-- ============================================================

CREATE OR REPLACE FUNCTION public.sincronizar_tipo_produto()
RETURNS TRIGGER AS $$
BEGIN
    -- Se tipo_material mudou, atualizar tipo_produto
    IF NEW.tipo_material IS DISTINCT FROM OLD.tipo_material THEN
        NEW.tipo_produto := CASE
            WHEN NEW.tipo_material = 'materia_prima' THEN 'MATERIA_PRIMA'::tipo_produto_enum
            WHEN NEW.tipo_material = 'intermediario' THEN 'INTERMEDIARIO'::tipo_produto_enum
            WHEN NEW.tipo_material = 'produto_acabado' THEN 'PRODUTO_ACABADO'::tipo_produto_enum
            WHEN NEW.tipo_material = 'servico' THEN 'SERVICO'::tipo_produto_enum
            ELSE NULL
        END;
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Aplicar trigger
DROP TRIGGER IF EXISTS trg_sincronizar_tipo_produto ON public.produtos;
CREATE TRIGGER trg_sincronizar_tipo_produto
    BEFORE INSERT OR UPDATE ON public.produtos
    FOR EACH ROW
    EXECUTE FUNCTION public.sincronizar_tipo_produto();

-- ============================================================
-- 7. ADICIONAR VALOR DEFAULT PARA NOVOS PRODUTOS
-- ============================================================

-- Se tipo_material for NULL em novo produto, usar MATERIA_PRIMA como default
ALTER TABLE public.produtos 
ALTER COLUMN tipo_produto SET DEFAULT 'MATERIA_PRIMA'::tipo_produto_enum;

-- ============================================================
-- FIM DA MIGRATION
-- ============================================================
