-- ============================================================
-- CLEANUP: DADOS TRANSACIONAIS
-- Data: 2026-03-28 (Revisado)
-- ============================================================
-- Preserva cadastros: produtos, canais, plataformas, configurações, etc.
-- Preserva PEDIDOS (histórico comercial)
-- Preserva INTEGRAÇÕES (configurações de conexão)
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
-- FILA E PROCESSAMENTO
-- ============================================================
SELECT public.truncate_if_exists('fila_processamento_estoque');

-- ============================================================
-- PRODUÇÃO E ENTREGA
-- ============================================================
SELECT public.truncate_if_exists('entrega_producao');
SELECT public.truncate_if_exists('print_jobs');
SELECT public.truncate_if_exists('product_artworks');

-- ============================================================
-- MOTOR DE RECONCILIAÇÃO DE ESTOQUE (EVENT SOURCING)
-- ============================================================
SELECT public.truncate_if_exists('eventos_producao_v2');
SELECT public.truncate_if_exists('estoque_consolidado');
SELECT public.truncate_if_exists('snapshots_reconciliacao');

-- ============================================================
-- ESTOQUE (LIMPAR HISTÓRICO, MANTER ESTRUTURA)
-- ============================================================
SELECT public.truncate_if_exists('movimentacoes_estoque');
SELECT public.truncate_if_exists('estoque_atual');
SELECT public.truncate_if_exists('demanda_estoque_processado');

-- ============================================================
-- ORDENS DE PRODUÇÃO
-- ============================================================
SELECT public.truncate_if_exists('ordens_producao');
SELECT public.truncate_if_exists('componentes_ordem_producao');

-- ============================================================
-- PRODUÇÃO DIÁRIA
-- ============================================================
SELECT public.truncate_if_exists('logs_producao_diaria');

-- ============================================================
-- DEMANDAS E ITENS (PRODUÇÃO)
-- ============================================================
SELECT public.truncate_if_exists('itens_demanda');
SELECT public.truncate_if_exists('demandas_producao');
SELECT public.truncate_if_exists('demandas_item_origem');
SELECT public.truncate_if_exists('demandas_pedidos');

-- ============================================================
-- PREVISÃO E ALOCAÇÕES
-- ============================================================
SELECT public.truncate_if_exists('previsao_consumo_demanda');
SELECT public.truncate_if_exists('demanda_alocacoes_estoque');

-- ============================================================
-- CONSOLIDAÇÕES
-- ============================================================
SELECT public.truncate_if_exists('consolidacoes_pedido');

-- ============================================================
-- LOGS E AUDITORIA
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
-- CHAT E COMUNICAÇÃO
-- ============================================================
SELECT public.truncate_if_exists('grupo_mensagens_chat_shopee');
SELECT public.truncate_if_exists('mensagem_chat_shopee');

-- ============================================================
-- CACHE E NOTIFICAÇÕES
-- ============================================================
SELECT public.truncate_if_exists('cache_dashboard_pedidos');
SELECT public.truncate_if_exists('notificacoes');
SELECT public.truncate_if_exists('agenda_recursos');

-- ============================================================
-- COMPRAS E FORNECEDORES (DADOS TRANSACIONAIS)
-- ============================================================
SELECT public.truncate_if_exists('fornecedor_insumos');
SELECT public.truncate_if_exists('ordens_compra');
SELECT public.truncate_if_exists('itens_ordem_compra');

-- ============================================================
-- PERSONALIZAÇÕES E FEEDBACKS DE PEDIDO
-- (Limpar, mas manter pedidos)
-- ============================================================
SELECT public.truncate_if_exists('personalizacoes_pedido');
SELECT public.truncate_if_exists('feedback_pedido');

-- ============================================================
-- HISTÓRICO DE TRANSIÇÕES DE SITUAÇÃO
-- (Dados de auditoria de pedido - pode ser limpo)
-- ============================================================
SELECT public.truncate_if_exists('transicoes_situacao');

-- ============================================================
-- CACHE DE PEDIDOS POR CANAL (SHAPEE)
-- (Dados replicados - pode ser limpo)
-- ============================================================
SELECT public.truncate_if_exists('pedidos_shopee');

-- ============================================================
-- CACHE DE PEDIDOS BLING
-- (Opcional - descomente se desejar limpar)
-- ============================================================
-- SELECT public.truncate_if_exists('pedidos_bling');
-- SELECT public.truncate_if_exists('itens_pedido_bling');

-- ============================================================
-- TABELAS PRESERVADAS (NÃO LIMPAR)
-- ============================================================
-- ✅ PEDIDOS E VENDAS (histórico comercial)
-- - pedidos
-- - itens_pedido
-- - vendas
-- - itens_venda
--
-- ✅ PRODUTOS E CADASTROS (catálogo)
-- - produtos
-- - produtos_externos
-- - categorias
-- - unidades_medida
-- - tags
-- - identificadores_alternativos
-- - conversoes_uom_produto
--
-- ✅ CANAIS E PLATAFORMAS (configurações)
-- - canais_venda
-- - plataformas
-- - contas_bling
-- - installed_integrations
-- - integration_modules
-- - integracao_canais_config (via service)
--
-- ✅ CONFIGURAÇÕES DO SISTEMA
-- - configuracoes_aplicacao
-- - regras_logisticas_canal
-- - categoria_bom_regras
--
-- ✅ ESTRUTURA ORGANIZACIONAL
-- - setores
-- - usuarios
-- - permissoes_setor
-- - depositos
-- - fornecedores
-- - recursos_produtivos
--
-- ✅ FICHA TÉCNICA (BOM)
-- - ficha_tecnica
-- ============================================================

-- ============================================================
-- DROP DA FUNÇÃO AUXILIAR (opcional - manter se for reutilizar)
-- ============================================================
-- DROP FUNCTION IF EXISTS public.truncate_if_exists(text);
