-- A2: semeia anúncios a partir do histórico de pedidos.
-- Somente relações já confirmadas por itens_pedido.produto_id recebem produto_id.
-- Nenhuma linha de pedido é alterada.

INSERT INTO public.produto_anuncios (
  produto_id, integration_id, item_externo_id, variacao_externa_id,
  sku_anuncio, titulo, preco_publicado, sincronizado_em
)
SELECT
  CASE WHEN count(DISTINCT i.produto_id) FILTER (WHERE i.produto_id IS NOT NULL) = 1
       THEN min(i.produto_id) FILTER (WHERE i.produto_id IS NOT NULL)
       ELSE NULL END,
  p.marketplace_integration_id,
  i.item_externo_id,
  NULLIF(NULLIF(btrim(i.variacao_externa_id), '0'), ''),
  min(i.sku_externo),
  min(i.titulo_anuncio),
  min(i.preco_unitario),
  max(i.updated_at)
FROM public.itens_pedido i
LEFT JOIN public.pedidos p ON p.id = i.pedido_id
WHERE i.item_externo_id IS NOT NULL
  AND btrim(i.item_externo_id) <> ''
GROUP BY p.marketplace_integration_id, i.item_externo_id,
         NULLIF(NULLIF(btrim(i.variacao_externa_id), '0'), '')
ON CONFLICT (integration_id, item_externo_id, COALESCE(variacao_externa_id, ''))
DO UPDATE SET
  produto_id = COALESCE(public.produto_anuncios.produto_id, EXCLUDED.produto_id),
  sku_anuncio = COALESCE(public.produto_anuncios.sku_anuncio, EXCLUDED.sku_anuncio),
  titulo = COALESCE(public.produto_anuncios.titulo, EXCLUDED.titulo),
  preco_publicado = COALESCE(public.produto_anuncios.preco_publicado, EXCLUDED.preco_publicado),
  sincronizado_em = GREATEST(public.produto_anuncios.sincronizado_em, EXCLUDED.sincronizado_em),
  updated_at = now();

-- As tabelas novas não devem ficar expostas às roles públicas.
ALTER TABLE public.perfis_fiscais ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.produto_eixos ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.produto_eixo_opcoes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.produto_eixo_opcao_componentes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.produto_pai_eixos ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.produto_variacao_valores ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.produto_sku_historico ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.produto_tags ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.produto_anuncios ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.produto_precos ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.produto_alias_conflitos ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE
  tabela text;
BEGIN
  FOREACH tabela IN ARRAY ARRAY[
    'perfis_fiscais', 'produto_eixos', 'produto_eixo_opcoes',
    'produto_eixo_opcao_componentes', 'produto_pai_eixos',
    'produto_variacao_valores', 'produto_sku_historico', 'produto_tags',
    'produto_anuncios', 'produto_precos', 'produto_alias_conflitos'
  ] LOOP
    EXECUTE format('DROP POLICY IF EXISTS %I_authenticated_all ON public.%I', tabela, tabela);
    EXECUTE format(
      'CREATE POLICY %I_authenticated_all ON public.%I FOR ALL TO authenticated USING (true) WITH CHECK (true)',
      tabela, tabela
    );
  END LOOP;
END $$;