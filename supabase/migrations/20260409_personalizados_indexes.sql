-- ============================================
-- Migração: Índices e Config de Personalizados
-- Data: 2026-04-09
-- Objetivo: Performance + Configurações iniciais de IA
-- ============================================

-- ── ÍNDICES DE PERFORMANCE ──────────────────

-- Busca de personalizações por order_sn
CREATE INDEX IF NOT EXISTS idx_personalizacoes_shopee_order_sn
    ON personalizacoes_pedido(shopee_order_sn);

-- Filtro por status de extração
CREATE INDEX IF NOT EXISTS idx_personalizacoes_status
    ON personalizacoes_pedido(status);

-- Busca de chat por username (FROM)
CREATE INDEX IF NOT EXISTS idx_chat_from_user
    ON mensagem_chat_shopee(from_user_name);

-- Busca de chat por username (TO)
CREATE INDEX IF NOT EXISTS idx_chat_to_user
    ON mensagem_chat_shopee(to_user_name);

-- Ordenação de chat por data
CREATE INDEX IF NOT EXISTS idx_chat_created_at
    ON mensagem_chat_shopee(created_at DESC);

-- Feedback por pedido
CREATE INDEX IF NOT EXISTS idx_feedback_pedido_codigo
    ON feedback_pedido(codigo_pedido);

-- Logs de IA por order_sn
CREATE INDEX IF NOT EXISTS idx_logs_ia_order_sn
    ON logs_execucao_ia(order_sn);

-- Configurações por categoria
CREATE INDEX IF NOT EXISTS idx_config_categoria
    ON configuracoes_aplicacao(categoria);

-- Configurações por nome (busca direta)
CREATE INDEX IF NOT EXISTS idx_config_nome
    ON configuracoes_aplicacao(nome);


-- ── CONFIGURAÇÕES INICIAIS DE IA ─────────────

-- Prompt template (carregado do arquivo legado)
INSERT INTO configuracoes_aplicacao (nome, valor, tipo_valor, descricao)
VALUES (
    'prompt_template',
    '{"text": "**Role**: You are a highly specialized AI assistant for an e-commerce operation. Your primary function is to act as a data extractor and processor for customer orders, with an extreme focus on accuracy.\n\n**Context**: We sell customized planners on Shopee. After placing an order, customers use the Shopee chat to specify the name and, occasionally, an initial they want to be printed on the planner(s) they purchased. Your task is to analyze the complete order data, the list of items purchased, and the full chat conversation to accurately extract these personalization details. Each chat message will have a unique ID at the beginning of the line (e.g., [msg_id]).\n\n**Objective**: For a given order, identify how many customizable items there are and extract the corresponding name and/or initial for each item from the chat messages. You must extract the name with strict adherence to the customer original spelling and determine their final decision, even if they change their mind. The final output must be a clean JSON object for our production system.\n\n**Mandatory Output Format**: Return ONLY a JSON object with order_id, shopee_order_sn, status, reasoning, and personalized_items array."}'::jsonb,
    'json',
    'Prompt template para extração de nomes de personalização via IA'
)
ON CONFLICT (nome) DO NOTHING;

-- Modelo Gemini a ser usado
INSERT INTO configuracoes_aplicacao (nome, valor, tipo_valor, descricao)
VALUES (
    'model_name',
    '"gemini-2.5-flash"',
    'string',
    'Modelo Google Gemini para extração de personalizações'
)
ON CONFLICT (nome) DO NOTHING;

-- Limite padrão de processamento
INSERT INTO configuracoes_aplicacao (nome, valor, tipo_valor, descricao)
VALUES (
    'max_processing',
    '50',
    'number',
    'Limite padrão de pedidos por processamento de IA'
)
ON CONFLICT (nome) DO NOTHING;
