-- Normalização da tabela Pedidos para evitar uso excessivo de JSONB e facilitar queries
ALTER TABLE public.pedidos ADD COLUMN IF NOT EXISTS cliente_telefone VARCHAR(50);
ALTER TABLE public.pedidos ADD COLUMN IF NOT EXISTS cliente_email VARCHAR(255);
ALTER TABLE public.pedidos ADD COLUMN IF NOT EXISTS is_flex BOOLEAN DEFAULT FALSE;
ALTER TABLE public.pedidos ADD COLUMN IF NOT EXISTS data_limite_envio TIMESTAMPTZ;
ALTER TABLE public.pedidos ADD COLUMN IF NOT EXISTS servico_logistico VARCHAR(255);
ALTER TABLE public.pedidos ADD COLUMN IF NOT EXISTS canal_venda_id INTEGER REFERENCES public.canais_venda(id);

-- Atualizar View de Consolidação para usar as colunas novas
DROP VIEW IF EXISTS view_pedidos_para_consolidar;
CREATE OR REPLACE VIEW view_pedidos_para_consolidar AS
SELECT 
    p.id AS pedido_id,
    p.numero_pedido,
    p.codigo_pedido_externo,
    p.origem,
    p.cliente_nome,
    p.cliente_telefone,
    p.is_flex,
    p.data_limite_envio,
    p.total_pedido,
    p.situacao_pedido_id,
    s.nome AS situacao_nome,
    cv.nome AS plataforma_nome,
    p.servico_logistico,
    (
        SELECT jsonb_agg(jsonb_build_object(
            'sku_externo', i.sku_externo,
            'descricao', i.descricao,
            'quantidade', i.quantidade
        ))
        FROM public.itens_pedido i
        WHERE i.pedido_id = p.id
    ) AS itens
FROM public.pedidos p
LEFT JOIN public.situacoes_pedido s ON p.situacao_pedido_id = s.id
LEFT JOIN public.canais_venda cv ON p.canal_venda_id = cv.id
WHERE p.situacao_pedido_id IN (1, 2); -- Pendente ou Pago
