-- Seeds: Dados iniciais para consolidação por evento
-- Created: 2026-04-02
--
-- Instruções:
-- 1. Primeiro, cadastre canais de venda reais e anote os IDs
-- 2. Substitua os IDs de exemplo (1, 2, 3) pelos IDs reais
-- 3. Execute este script

-- ============================================================================
-- 1. REGRAS GLOBAIS DE CONSOLIDAÇÃO (fallback para todos os canais)
-- ============================================================================

-- Regra global padrão: janela de 4 horas, agrupa por tudo
INSERT INTO public.regras_consolidacao_canal
  (canal_venda_id, modalidade, janela_agrupamento_horas,
   agrupar_por_produto, agrupar_por_miolo, agrupar_por_data_entrega,
   comportamento_pos_edicao, comportamento_pos_publicacao)
VALUES
  (NULL, NULL, 4, true, true, true, 'ADICIONAR_COM_SINALIZACAO', 'CRIAR_NOVO_RASCUNHO')
ON CONFLICT DO NOTHING;

-- ============================================================================
-- 2. MAPEAMENTOS DE MODALIDADE POR CANAL
-- ============================================================================

-- ATENÇÃO: Substitua os IDs de canal (1, 2, 3, 4) pelos IDs reais do seu banco

-- Canal: Shopee Principal (substituir canal_venda_id = 1 pelo ID real)
INSERT INTO public.canal_modalidade_mapeamento
  (canal_venda_id, padrao_servico, modalidade, prioridade)
VALUES
  -- Shopee Flex / Entrega Rápida (prioridade alta)
  (1, '%flex%', 'EXPRESS', 10),
  (1, '%rápida%', 'EXPRESS', 10),
  (1, '%rapida%', 'EXPRESS', 10),
  (1, 'Entrega Rápida', 'EXPRESS', 10),
  (1, 'Entrega Flex', 'EXPRESS', 10),
  
  -- Shopee Normal / Padrão (prioridade média)
  (1, '%normal%', 'STANDARD', 5),
  (1, '%padrão%', 'STANDARD', 5),
  (1, '%padrao%', 'STANDARD', 5),
  (1, 'Entrega Padrão', 'STANDARD', 5),
  (1, 'Entrega Normal', 'STANDARD', 5),
  
  -- Shopee Fulfillment (prioridade alta)
  (1, '%full%', 'FULFILLMENT', 8),
  (1, '%fulfillment%', 'FULFILLMENT', 8),
  
  -- Shopee Retirada
  (1, '%retirada%', 'RETIRADA', 5),
  (1, 'Retirada Local', 'RETIRADA', 5)
ON CONFLICT DO NOTHING;

-- Canal: Mercado Livre (substituir canal_venda_id = 2 pelo ID real)
INSERT INTO public.canal_modalidade_mapeamento
  (canal_venda_id, padrao_servico, modalidade, prioridade)
VALUES
  -- ML Flex
  (2, '%flex%', 'EXPRESS', 10),
  (2, 'Mercado Envio Flex', 'EXPRESS', 10),
  
  -- ML Normal / Clássico
  (2, '%normal%', 'STANDARD', 5),
  (2, '%clássico%', 'STANDARD', 5),
  (2, '%classico%', 'STANDARD', 5),
  (2, 'Mercado Envio Clássico', 'STANDARD', 5),
  
  -- ML Full
  (2, '%full%', 'FULFILLMENT', 8),
  (2, 'Mercado Envio Full', 'FULFILLMENT', 8)
ON CONFLICT DO NOTHING;

-- Canal: Amazon (substituir canal_venda_id = 3 pelo ID real)
INSERT INTO public.canal_modalidade_mapeamento
  (canal_venda_id, padrao_servico, modalidade, prioridade)
VALUES
  -- Amazon Prime
  (3, '%prime%', 'EXPRESS', 10),
  (3, 'Entrega Prime', 'EXPRESS', 10),
  
  -- Amazon Standard
  (3, '%standard%', 'STANDARD', 5),
  (3, 'Entrega Padrão', 'STANDARD', 5),
  
  -- Amazon Fulfillment
  (3, '%fulfillment%', 'FULFILLMENT', 8)
ON CONFLICT DO NOTHING;

-- Canal: Shein (substituir canal_venda_id = 4 pelo ID real)
INSERT INTO public.canal_modalidade_mapeamento
  (canal_venda_id, padrao_servico, modalidade, prioridade)
VALUES
  -- Shein Express
  (4, '%express%', 'EXPRESS', 10),
  (4, 'Entrega Expressa', 'EXPRESS', 10),
  
  -- Shein Standard
  (4, '%standard%', 'STANDARD', 5),
  (4, 'Entrega Padrão', 'STANDARD', 5)
ON CONFLICT DO NOTHING;

-- ============================================================================
-- 3. REGRAS ESPECÍFICAS POR CANAL E MODALIDADE
-- ============================================================================

-- Shopee Flex: janela menor (2h) por ser urgente
INSERT INTO public.regras_consolidacao_canal
  (canal_venda_id, modalidade, janela_agrupamento_horas,
   agrupar_por_produto, agrupar_por_miolo, agrupar_por_data_entrega)
VALUES
  (1, 'EXPRESS', 2, true, true, true)
ON CONFLICT (canal_venda_id, modalidade) DO NOTHING;

-- Shopee Fulfillment: cria demanda direta por pedido (janela = 0)
INSERT INTO public.regras_consolidacao_canal
  (canal_venda_id, modalidade, janela_agrupamento_horas,
   agrupar_por_produto, agrupar_por_miolo, agrupar_por_data_entrega)
VALUES
  (1, 'FULFILLMENT', 0, false, false, false)
ON CONFLICT (canal_venda_id, modalidade) DO NOTHING;

-- Mercado Livre Flex: janela de 3h
INSERT INTO public.regras_consolidacao_canal
  (canal_venda_id, modalidade, janela_agrupamento_horas)
VALUES
  (2, 'EXPRESS', 3)
ON CONFLICT (canal_venda_id, modalidade) DO NOTHING;

-- ============================================================================
-- 4. VERIFICAÇÃO PÓS-INSERT
-- ============================================================================

-- Verificar quantos mapeamentos foram criados
-- SELECT canal_venda_id, modalidade, COUNT(*) 
-- FROM public.canal_modalidade_mapeamento 
-- GROUP BY canal_venda_id, modalidade 
-- ORDER BY canal_venda_id, modalidade;

-- Verificar regras de consolidação
-- SELECT canal_venda_id, modalidade, janela_agrupamento_horas 
-- FROM public.regras_consolidacao_canal 
-- ORDER BY canal_venda_id NULLS LAST, modalidade NULLS LAST;

-- ============================================================================
-- 5. COMANDOS ÚTEIS PARA ADMINISTRAÇÃO
-- ============================================================================

-- Adicionar novo padrão para um canal existente:
-- INSERT INTO public.canal_modalidade_mapeamento
--   (canal_venda_id, padrao_servico, modalidade, prioridade)
-- VALUES
--   (1, '%nova_string%', 'EXPRESS', 10);

-- Verificar pedidos não classificados (após sistema em produção):
-- SELECT pnc.*, p.servico_logistico
-- FROM public.pedidos_nao_classificados pnc
-- JOIN public.pedidos p ON p.id = pnc.pedido_id
-- WHERE pnc.resolvido = false
-- ORDER BY pnc.created_at DESC;

-- Resolver pedido não classificado e adicionar padrão:
-- 1. Adicionar padrão faltante:
--    INSERT INTO public.canal_modalidade_mapeamento
--      (canal_venda_id, padrao_servico, modalidade, prioridade)
--    VALUES
--      (1, 'Entrega Rápida Plus', 'EXPRESS', 10);
--
-- 2. Marcar como resolvido:
--    UPDATE public.pedidos_nao_classificados
--    SET resolvido = true,
--        resolvido_em = NOW(),
--        resolvido_por = 1,  -- ID do usuário
--        modalidade_atribuida = 'EXPRESS'
--    WHERE id = 123;
--
-- 3. Re-processar o pedido (chamar consolidação manualmente)
