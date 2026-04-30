-- ============================================================
-- CLEANUP: DADOS TRANSACIONAIS V2
-- Data: 2026-04-30
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
-- PEDIDOS (SERÃO REPOPULADOS PELO REPROCESSAMENTO)
-- ============================================================
SELECT public.truncate_if_exists('pedidos');
SELECT public.truncate_if_exists('pedidos_bling');
SELECT public.truncate_if_exists('itens_pedido');
SELECT public.truncate_if_exists('pedidos_shopee');

-- ============================================================
-- PRODUÇÃO E DEMANDAS
-- ============================================================
SELECT public.truncate_if_exists('demandas_producao');
SELECT public.truncate_if_exists('itens_demanda');
SELECT public.truncate_if_exists('demandas_item_origem');
SELECT public.truncate_if_exists('demandas_pedidos');
SELECT public.truncate_if_exists('demandas_overrides');
SELECT public.truncate_if_exists('pedidos_nao_classificados');

-- ============================================================
-- ESTOQUE
-- ============================================================
SELECT public.truncate_if_exists('estoque_atual');
SELECT public.truncate_if_exists('movimentacoes_estoque');
SELECT public.truncate_if_exists('demanda_estoque_processado');
SELECT public.truncate_if_exists('demanda_alocacoes_estoque');

-- ============================================================
-- ORDENS DE PRODUÇÃO
-- ============================================================
SELECT public.truncate_if_exists('ordens_producao');
SELECT public.truncate_if_exists('componentes_ordem_producao');

-- ============================================================
-- LOGS DE PRODUÇÃO DIÁRIA
-- ============================================================
SELECT public.truncate_if_exists('logs_producao_diaria');

-- ============================================================
-- MOTOR DE RECONCILIAÇÃO DE ESTOQUE (EVENT SOURCING)
-- ============================================================
SELECT public.truncate_if_exists('eventos_producao_v2');
SELECT public.truncate_if_exists('estoque_consolidado');
SELECT public.truncate_if_exists('snapshots_reconciliacao');

-- ============================================================
-- PREVISÃO DE CONSUMO
-- ============================================================
SELECT public.truncate_if_exists('previsao_consumo_demanda');

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
-- ============================================================
SELECT public.truncate_if_exists('personalizacoes_pedido');
SELECT public.truncate_if_exists('feedback_pedido');

-- ============================================================
-- HISTÓRICO DE TRANSIÇÕES DE SITUAÇÃO
-- ============================================================
SELECT public.truncate_if_exists('transicoes_situacao');

-- ============================================================
-- CACHE DE PEDIDOS POR CANAL (SHOPEE)
-- ============================================================
SELECT public.truncate_if_exists('pedidos_shopee');

-- ============================================================
-- FILA DE PROCESSAMENTO DE ESTOQUE
-- ============================================================
SELECT public.truncate_if_exists('fila_processamento_estoque');

-- ============================================================
-- PRODUÇÃO E ENTREGA
-- ============================================================
SELECT public.truncate_if_exists('entrega_producao');
SELECT public.truncate_if_exists('print_jobs');
SELECT public.truncate_if_exists('product_artworks');

-- ============================================================
-- SYNC STATUS BATCHES E ERRORS
-- ============================================================
SELECT public.truncate_if_exists('sync_status_batches');
SELECT public.truncate_if_exists('sync_status_errors');

-- ============================================================
-- EXECUÇÕES AI BATCH E ITEMS
-- ============================================================
SELECT public.truncate_if_exists('execucoes_ai_batch');
SELECT public.truncate_if_exists('execucoes_ai_item');

-- ============================================================
-- PEDIDO INGEST LOG (AUDITORIA DE INGESTÃO)
-- ============================================================
SELECT public.truncate_if_exists('pedido_ingest_log');

-- ============================================================
-- ENTITY CORRELATION MAPPING (AUDITORIA)
-- ============================================================
SELECT public.truncate_if_exists('entity_correlation_mapping');

-- ============================================================
-- TABELAS PRESERVADAS (NÃO LIMPAR)
-- ============================================================
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
-- - integracao_canais_config
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
--
-- ✅ CONFIGURAÇÕES DE INTEGRAÇÃO
-- - integration_status_mappings
-- - flex_classification_rules
-- - channel_connections
-- ============================================================

-- ============================================================
-- DROP DA FUNÇÃO AUXILIAR (opcional - manter se for reutilizar)
-- ============================================================
-- DROP FUNCTION IF EXISTS public.truncate_if_exists(text);
