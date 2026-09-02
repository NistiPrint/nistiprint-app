-- ============================================
-- Migração: Flags de Personalizado
-- Data: 2026-04-09
-- Objetivo: Adicionar campo personalizado em itens_pedido e produtos,
--           e fazer backfill dos dados existentes.
-- ============================================

-- ── 1. ADICIONAR COLUNAS ────────────────────

-- Campo personalizado em itens_pedido (modelo unificado)
ALTER TABLE itens_pedido
ADD COLUMN IF NOT EXISTS personalizado BOOLEAN DEFAULT false;

-- Campo personalizado em produtos (cadastro interno)
ALTER TABLE produtos
ADD COLUMN IF NOT EXISTS personalizado BOOLEAN DEFAULT false;


-- ── 2. ÍNDICES PARCIAIS (só indexar true) ───

CREATE INDEX IF NOT EXISTS idx_itens_pedido_personalizado
ON itens_pedido(personalizado) WHERE personalizado = true;

CREATE INDEX IF NOT EXISTS idx_produtos_personalizado
ON produtos(personalizado) WHERE personalizado = true;


-- ── 3. BACKFILL: produtos existentes ─────────

-- Marcar produtos internos como personalizados baseado em itens_pedido_bling
-- (produtos cujos itens em pedidos foram marcados como personalizados)
UPDATE produtos p
SET personalizado = true
WHERE EXISTS (
    SELECT 1
    FROM itens_pedido_bling ipb
    WHERE ipb.personalizado = true
      AND ipb.produto->>'id' = p.id::text
);


-- ── 4. BACKFILL: itens_pedido existentes ─────

-- Marcar itens_pedido como personalizados baseado em itens_pedido_bling
-- (quando o mesmo pedido + descrição existe no modelo unificado)
UPDATE itens_pedido ip
SET personalizado = true
WHERE EXISTS (
    SELECT 1
    FROM itens_pedido_bling ipb
    JOIN pedidos_bling pb ON ipb.pedido_bling_id = pb.id
    WHERE ipb.personalizado = true
      AND ipb.descricao = ip.descricao
      AND ip.pedido_id = (
          SELECT p2.id
          FROM pedidos p2
          WHERE p2.codigo_pedido_externo = pb.numero_loja
          LIMIT 1
      )
);


-- ── 5. VALIDAÇÃO (logs) ─────────────────────

-- Contar resultados do backfill (remover em produção se desejar)
DO $$
DECLARE
    v_produtos integer;
    v_itens integer;
BEGIN
    SELECT COUNT(*) INTO v_produtos FROM produtos WHERE personalizado = true;
    SELECT COUNT(*) INTO v_itens FROM itens_pedido WHERE personalizado = true;

    RAISE NOTICE 'Backfill completo: % produtos marcados, % itens marcados',
        v_produtos, v_itens;
END $$;
