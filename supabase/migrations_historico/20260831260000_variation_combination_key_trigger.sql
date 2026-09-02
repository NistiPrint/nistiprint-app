-- Mantém a chave da combinação consistente independentemente do cliente.
CREATE OR REPLACE FUNCTION public.atualizar_chave_combinacao_variacao()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  UPDATE public.produtos p
     SET combinacao_chave = (
       SELECT string_agg(e.codigo || '=' || o.codigo, '|' ORDER BY e.ordem_sku, e.id)
         FROM public.produto_variacao_valores vv
         JOIN public.produto_eixos e ON e.id = vv.eixo_id
         JOIN public.produto_eixo_opcoes o ON o.id = vv.opcao_id
        WHERE vv.produto_id = COALESCE(NEW.produto_id, OLD.produto_id)
     )
   WHERE p.id = COALESCE(NEW.produto_id, OLD.produto_id);
  RETURN COALESCE(NEW, OLD);
END $$;

DROP TRIGGER IF EXISTS trg_atualizar_chave_combinacao ON public.produto_variacao_valores;
CREATE TRIGGER trg_atualizar_chave_combinacao
  AFTER INSERT OR UPDATE OR DELETE ON public.produto_variacao_valores
  FOR EACH ROW EXECUTE FUNCTION public.atualizar_chave_combinacao_variacao();

REVOKE ALL ON FUNCTION public.atualizar_chave_combinacao_variacao() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.atualizar_chave_combinacao_variacao() TO service_role;