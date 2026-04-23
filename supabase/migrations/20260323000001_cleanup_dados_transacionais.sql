-- ============================================================
-- CLEANUP: DADOS TRANSACIONAIS
-- Data: 2026-03-23
-- ============================================================
-- Preserva cadastros: produtos, canais, plataformas, configurações, etc.
-- Preserva PEDIDOS (histórico comercial)
-- Limpa: estoque, produção, filas, logs, notificações, etc.
-- ============================================================

-- ============================================================
-- FUNÇÃO AUXILIAR: TRUNCATE SEGURO
-- Executa TRUNCATE apenas se a tabela existir
-- ============================================================
CREATE OR REPLACE FUNCTION public.truncate_if_exists(p_table text)
RETURNS void AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_schema = 'public' AND table_name = p_table
    ) THEN
        EXECUTE format('TRUNCATE TABLE public.%I RESTART IDENTITY CASCADE', p_table);
    END IF;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- Fila e processamento
-- ============================================================
SELECT public.truncate_if_exists('fila_processamento_estoque');

-- ============================================================
-- Produção e entrega
-- ============================================================
SELECT public.truncate_if_exists('entrega_producao');
SELECT public.truncate_if_exists('print_jobs');
SELECT public.truncate_if_exists('product_artworks');

-- ============================================================
-- Logs e auditoria
-- ============================================================
SELECT public.truncate_if_exists('logs_execucao_ia');
SELECT public.truncate_if_exists('feedbacks_execucao_ia');
SELECT public.truncate_if_exists('feedbacks_negativo');
SELECT public.truncate_if_exists('system_events_log');
SELECT public.truncate_if_exists('webhook_logs');
SELECT public.truncate_if_exists('integration_refresh_logs');
SELECT public.truncate_if_exists('eventos_auditoria');
SELECT public.truncate_if_exists('task_execution_logs');

-- ============================================================
-- Chat e comunicação
-- ============================================================
SELECT public.truncate_if_exists('grupo_mensagens_chat_shopee');
SELECT public.truncate_if_exists('mensagem_chat_shopee');

-- ============================================================
-- Cache e notificações
-- ============================================================
SELECT public.truncate_if_exists('cache_dashboard_pedidos');
SELECT public.truncate_if_exists('notificacoes');
SELECT public.truncate_if_exists('agenda_recursos');

-- ============================================================
-- Compras e fornecedores
-- ============================================================
SELECT public.truncate_if_exists('fornecedor_insumos');
SELECT public.truncate_if_exists('ordens_compra');
SELECT public.truncate_if_exists('itens_ordem_compra');

-- ============================================================
-- Estoque (limpar histórico, manter estrutura)
-- ============================================================
SELECT public.truncate_if_exists('movimentacoes_estoque');
SELECT public.truncate_if_exists('estoque_atual');
SELECT public.truncate_if_exists('demanda_estoque_processado');

-- ============================================================
-- Produção diária e ordens
-- ============================================================
SELECT public.truncate_if_exists('logs_producao_diaria');
SELECT public.truncate_if_exists('componentes_ordem_producao');
SELECT public.truncate_if_exists('ordens_producao');

-- ============================================================
-- Demandas e itens (produção)
-- ============================================================
SELECT public.truncate_if_exists('itens_demanda');
SELECT public.truncate_if_exists('demandas_producao');
SELECT public.truncate_if_exists('demandas_item_origem');

-- ============================================================
-- Previsão e alocações
-- ============================================================
SELECT public.truncate_if_exists('previsao_consumo_demanda');
SELECT public.truncate_if_exists('demanda_alocacoes_estoque');

-- ============================================================
-- Personalizações e feedbacks de pedido (limpar, mas manter pedidos)
-- ============================================================
SELECT public.truncate_if_exists('personalizacoes_pedido');
SELECT public.truncate_if_exists('feedback_pedido');

-- ============================================================
-- Eventos e histórico de pedido (limpar histórico de status/transições)
-- OBS: tabela eventos_pedido não existe mais no schema atual
-- ============================================================

-- ============================================================
-- Consolidações
-- ============================================================
SELECT public.truncate_if_exists('consolidacoes_pedido');

-- ============================================================
-- NOVAS TABELAS IDENTIFICADAS (MOTOR DE RECONCILIAÇÃO)
-- Data: 2026-03-24/25
-- ============================================================

-- Motor de reconciliação de estoque (dados temporários de acompanhamento)
SELECT public.truncate_if_exists('eventos_producao');

-- Snapshots de reconciliação (dados temporários de auditoria)
SELECT public.truncate_if_exists('snapshots_reconciliacao');

-- ============================================================
-- NOVAS TABELAS TRANSACIONAIS
-- Data: 2026-03-26
-- ============================================================

-- Novo motor de event sourcing (dados temporários de produção)
SELECT public.truncate_if_exists('eventos_producao_v2');

-- Estoque consolidado (dados derivados/recalculáveis)
SELECT public.truncate_if_exists('estoque_consolidado');

-- Roteamento de integração (dados operacionais)
-- SELECT public.truncate_if_exists('integration_account_routing');

-- Tabela pivô demandas/pedidos (ligação temporária)
SELECT public.truncate_if_exists('demandas_pedidos');

-- Histórico de transições de situação (dados de auditoria de pedido)
SELECT public.truncate_if_exists('transicoes_situacao');

-- Cache de pedidos por canal (Shopee) - dados replicados
-- SELECT public.truncate_if_exists('pedidos_shopee');

-- ============================================================
-- PRESERVAR PEDIDOS E ITENS DE PEDIDO
-- Não limpar: pedidos, itens_pedido, vendas, itens_venda
-- ============================================================

-- ============================================================
-- LIMPEZA: TABELAS DE CACHE DO BLING (OPCIONAL)
-- Descomente as linhas abaixo se desejar limpar também o cache do Bling
-- ============================================================
-- SELECT public.truncate_if_exists('pedidos_bling');
-- SELECT public.truncate_if_exists('itens_pedido_bling');

-- ============================================================
-- DROP DA FUNÇÃO AUXILIAR (opcional - manter se for reutilizar)
-- ============================================================
-- DROP FUNCTION IF EXISTS public.truncate_if_exists(text);
