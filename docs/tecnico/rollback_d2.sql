-- =====================================================================
-- ROLLBACK da Fase D2 — Sprint 5 (Plano de Otimizacao)
-- Aplicado em: 2026-08-25 · Projeto cfknrplrqvyirjxovuvi
--
-- Escopo final: 7 tabelas + 1 funcao orfa.
-- Criterio aplicado (revisado): zero insercoes desde 2025-12-08
--   E zero linhas vivas
--   E nenhuma funcao/trigger no banco que as referencie
--   E nenhuma referencia no codigo (apps/api, apps/worker, frontend, packages).
--
-- Todas estavam vazias no momento do drop: este arquivo restaura a
-- estrutura; nao ha dados a recuperar. PKs, indices e FKs nao estao
-- reproduzidos — recupere-os de supabase/migrations se necessario.
-- =====================================================================

-- --- Feedback da IA (funcionalidade nunca ativada) -------------------
CREATE TABLE public.feedbacks_execucao_ia (id bigint NOT NULL, order_sn text NOT NULL, feedback smallint NOT NULL, feedback_notes text, created_at timestamp with time zone DEFAULT now());
CREATE TABLE public.feedbacks_negativo (id bigint NOT NULL, order_sn text NOT NULL, order_data jsonb, messages_data jsonb, execution_logs jsonb, created_at timestamp with time zone DEFAULT now());

-- --- Vendas: duplicata de `pedidos`, sem consumidor ------------------
CREATE TABLE public.vendas (id serial NOT NULL, venda_id character varying(255) NOT NULL, plataforma character varying(100), status character varying(50), valor_total numeric(10,2), moeda character varying(10), informacoes_cliente jsonb, endereco_entrega jsonb, itens jsonb, data_venda timestamp without time zone, created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP, updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP, total_amount numeric(10,2), currency character varying(10), cliente_info jsonb);
CREATE TABLE public.itens_venda (id serial NOT NULL, venda_id integer NOT NULL, produto_id integer, sku character varying(100), descricao character varying(500), quantidade integer, preco_unitario numeric(10,2), subtotal numeric(10,2), personalizacao jsonb, created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP, updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP);
-- Codigo correspondente movido para _to_delete/sprint5-d2/:
--   packages/shared/nistiprint_shared/services/sales_service.py

-- --- Identidade de pedido: tabela de conflitos nunca escrita ----------
CREATE TABLE public.order_identity_conflicts (id bigserial NOT NULL, marketplace_module_id text, marketplace_order_id text, pedido_ids bigint[] NOT NULL, conflict_kind text NOT NULL, details jsonb DEFAULT '{}'::jsonb NOT NULL, resolved_at timestamp with time zone, created_at timestamp with time zone DEFAULT now() NOT NULL);

-- --- Motor de estoque v1: saldo consolidado --------------------------
CREATE TABLE public.estoque_consolidado (produto_id integer NOT NULL, saldo_total numeric(15,4) DEFAULT 0 NOT NULL, reservado numeric(15,4) DEFAULT 0 NOT NULL, ultimo_processamento_evento_id uuid, updated_at timestamp with time zone DEFAULT now());

CREATE OR REPLACE FUNCTION public.atualizar_estoque_consolidado(p_produto_id integer, p_delta numeric)
RETURNS void LANGUAGE plpgsql AS $BODY$
BEGIN
    INSERT INTO public.estoque_consolidado (produto_id, saldo_total)
    VALUES (p_produto_id, p_delta)
    ON CONFLICT (produto_id)
    DO UPDATE SET saldo_total = public.estoque_consolidado.saldo_total + p_delta,
                  updated_at = NOW();
END;
$BODY$;

-- --- Motor de estoque v1: eventos (substituida por eventos_producao_v2)
-- Continha 2 linhas orfas, escritas pelo caminho removido no ajuste B2.
CREATE TABLE public.eventos_producao (id uuid DEFAULT gen_random_uuid() NOT NULL, item_demanda_id integer NOT NULL, demanda_id integer NOT NULL, estagio character varying(50) NOT NULL, quantidade_reportada numeric(15,4) DEFAULT 0 NOT NULL, quantidade_efetiva numeric(15,4), tipo_evento character varying(20) DEFAULT 'SINAL'::character varying NOT NULL, processado boolean DEFAULT false NOT NULL, correlation_id character varying(100), created_at timestamp with time zone DEFAULT now(), processed_at timestamp with time zone);


-- =====================================================================
-- NAO REMOVIDAS — o criterio "tabela vazia" se mostrou insuficiente.
-- Cada uma esta vazia hoje, mas tem codigo vivo ou historico de escrita.
--
-- Encheram e esvaziaram (staging ativo):
--   itens_pedido_bling            18.955 ins / 11.083 del · 134.498 seq scans
--   logs_execucao_ia              15.277 ins / 10.461 del
--   fila_processamento_estoque       292 ins ·  605.657 seq scans (Motor B)
--   previsao_consumo_demanda         639 ins · servico importado em 8 modulos
--
-- Vazias, mas com codigo vivo que escreve nelas:
--   archive_manifests        finalize_ingest_archive_batch <- ingest_archive_service.py
--   snapshots_reconciliacao  reconciliar_estoque_v2 <- motor_estoque_v2.py (Motor C)
--   execucoes_ai_batch/item  ai_personalization_service.py
--   ordens_compra / itens_ordem_compra   blueprint ordem_compra — Compras e roadmap (CF-3)
--
-- Vazias, mas muito lidas:
--   canal_modalidade_mapeamento   238.519 leituras por indice
--   regras_logisticas_canal       176.419 seq scans
--   print_jobs                       787 leituras por indice
--   integracao_canais_config       7 linhas vivas — em uso
--   order_identity_corrections    42 insercoes
-- =====================================================================


-- =====================================================================
-- ROLLBACK da Fase D2.1 — aposentadoria dos motores B e C
-- Aplicado em: 2026-08-25 (migracao d2_aposenta_motores_legados_estoque)
--
-- Ambas as tabelas estavam VAZIAS: isto restaura estrutura, nao dados.
-- O codigo correspondente esta em _to_delete/sprint5-d2/ e no historico do git.
-- =====================================================================

-- --- Motor B: fila do motor de estoque v1 ---------------------------
CREATE TABLE public.fila_processamento_estoque (id uuid DEFAULT gen_random_uuid() NOT NULL, demanda_id integer, item_id integer, quantidade numeric(15,4) NOT NULL, status text DEFAULT 'PENDENTE'::text, tentativas integer DEFAULT 0, mensagem_erro text, user_id text, created_at timestamp with time zone DEFAULT now(), processed_at timestamp with time zone, campo text, metadata jsonb, proxima_execucao_at timestamp with time zone DEFAULT now(), locked_at timestamp with time zone, worker_id text, produto_id integer, correlation_id uuid, tipo_operacao character varying(50) DEFAULT 'CONSUMO_BOM'::character varying, prioridade integer DEFAULT 10);

-- --- Motor C: trilha de auditoria da reconciliacao sincrona ----------
CREATE TABLE public.snapshots_reconciliacao (id uuid DEFAULT gen_random_uuid() NOT NULL, item_demanda_id integer, demanda_id integer, qtd_finalizada numeric(15,4), bom_necessario jsonb DEFAULT '[]'::jsonb, ledger_anterior jsonb DEFAULT '[]'::jsonb, deltas_calculados jsonb DEFAULT '{}'::jsonb, movimentos_gerados jsonb DEFAULT '[]'::jsonb, efetivas_calculadas jsonb DEFAULT '{}'::jsonb, correlation_id character varying(100), status character varying(20) DEFAULT 'SUCESSO'::character varying, erro_detalhes text, created_at timestamp with time zone DEFAULT now());

-- --- Funcoes removidas ----------------------------------------------
-- reconciliar_estoque_v2(integer, jsonb, jsonb, jsonb, uuid, varchar)  -- RPC do Motor C
-- fetch_and_lock_stock_tasks(text, integer)                            -- lock da fila
-- force_fetch_all_tasks(text, integer)                                 -- lock da fila
-- Recupere o corpo destas tres em supabase/migrations (ou no historico do git).
--
-- registrar_movimentacao_primaria foi REESCRITA, nao removida: o passo 3,
-- que enfileirava CONSUMO_BOM/ESTORNO_BOM em fila_processamento_estoque,
-- saiu. Para reverter, reponha o bloco:
--
--   IF p_origem_tipo IN (1, 3) THEN
--       INSERT INTO public.fila_processamento_estoque (produto_id, quantidade,
--           correlation_id, user_id, status, tipo_operacao)
--       VALUES (p_produto_id, ABS(p_quantidade), p_correlation_id,
--               p_usuario_id::TEXT, 'PENDENTE', 'CONSUMO_BOM');
--   ELSIF p_origem_tipo = 2 THEN
--       INSERT INTO public.fila_processamento_estoque (produto_id, quantidade,
--           correlation_id, user_id, status, tipo_operacao)
--       VALUES (p_produto_id, ABS(p_quantidade), p_correlation_id,
--               p_usuario_id::TEXT, 'PENDENTE', 'ESTORNO_BOM');
--   END IF;
-- =====================================================================
