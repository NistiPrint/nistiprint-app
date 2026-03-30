-- Migration: Atualiza situações de pedido para mapeamento correto com Bling
-- Data: 2026-03-28
-- 
-- Mapeamento Bling -> Interno:
-- Bling 6 (Em Aberto)     -> Interno 1 (Em Aberto/Pendente)
-- Bling 15 (Em Andamento) -> Interno 2 (Em Andamento/Produção)
-- Bling 9 (Atendido)      -> Interno 5 (Atendido/Enviado)
-- Bling 12 (Cancelado)    -> Interno 7 (Cancelado)
-- Bling 18 (Arquivado)    -> Interno 5 (Atendido/Enviado)

-- Garante que as situações existem com IDs fixos
INSERT INTO public.situacoes_pedido (id, nome, descricao, flag_reserva_estoque, flag_fatura, flag_cancelado, cor_status, created_at, updated_at)
VALUES 
    (1, 'Em Aberto', 'Pedido realizado mas ainda não pago', true, false, false, '#f59e0b', NOW(), NOW()),
    (2, 'Em Andamento', 'Pedido pago, em produção para envio', true, false, false, '#3b82f6', NOW(), NOW()),
    (3, 'Produzido', 'Pedido produzido, aguardando envio', true, false, false, '#8b5cf6', NOW(), NOW()),
    (4, 'Pronto para Envio', 'Pedido separado e etiquetado', true, false, false, '#06b6d4', NOW(), NOW()),
    (5, 'Enviado', 'Pedido foi produzido e enviado ao cliente', false, true, false, '#10b981', NOW(), NOW()),
    (6, 'Entregue', 'Pedido entregue ao cliente', false, true, false, '#059669', NOW(), NOW()),
    (7, 'Cancelado', 'Pedido cancelado', false, false, true, '#ef4444', NOW(), NOW())
ON CONFLICT (id) DO UPDATE SET
    nome = EXCLUDED.nome,
    descricao = EXCLUDED.descricao,
    flag_reserva_estoque = EXCLUDED.flag_reserva_estoque,
    flag_fatura = EXCLUDED.flag_fatura,
    flag_cancelado = EXCLUDED.flag_cancelado,
    cor_status = EXCLUDED.cor_status,
    updated_at = NOW();

-- Reseta a sequência para evitar conflitos
SELECT setval('public.situacoes_pedido_id_seq', (SELECT MAX(id) FROM public.situacoes_pedido));

-- Comenta as situações antigas que não são mais usadas (se existirem)
-- UPDATE public.situacoes_pedido SET nome = CONCAT(nome, ' [LEGADO]') WHERE id NOT IN (1, 2, 3, 4, 5, 6, 7);
