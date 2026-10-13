-- Reconciliação observável entre o saldo atual e o último saldo declarado no ledger.
-- Compara somente pares com movimento e um saldo_depois conhecido: linhas sem
-- histórico suficiente não são classificadas como divergência.
CREATE OR REPLACE VIEW public.v_estoque_saldo_ledger_divergencias
WITH (security_invoker = true) AS
WITH ultimo_movimento AS (
    SELECT DISTINCT ON (produto_id, deposito_id)
        produto_id,
        deposito_id,
        id AS movimento_id,
        saldo_depois AS saldo_ultimo_movimento,
        COALESCE(created_at, data_movimentacao) AS movimento_registrado_em
    FROM public.movimentacoes_estoque
    WHERE saldo_depois IS NOT NULL
    ORDER BY
        produto_id,
        deposito_id,
        COALESCE(created_at, data_movimentacao) DESC NULLS LAST,
        id DESC
)
SELECT
    atual.produto_id,
    produto.sku AS produto_sku,
    produto.nome AS produto_nome,
    atual.deposito_id,
    deposito.nome AS deposito_nome,
    atual.saldo_atual,
    movimento.saldo_ultimo_movimento,
    atual.saldo_atual - movimento.saldo_ultimo_movimento AS diferenca,
    movimento.movimento_id,
    movimento.movimento_registrado_em
FROM public.estoque_atual AS atual
JOIN ultimo_movimento AS movimento
  ON movimento.produto_id = atual.produto_id
 AND movimento.deposito_id = atual.deposito_id
JOIN public.produtos AS produto
  ON produto.id = atual.produto_id
JOIN public.depositos AS deposito
  ON deposito.id = atual.deposito_id
WHERE atual.saldo_atual IS DISTINCT FROM movimento.saldo_ultimo_movimento;

REVOKE ALL ON public.v_estoque_saldo_ledger_divergencias FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.v_estoque_saldo_ledger_divergencias TO service_role;
