-- E9: preço mínimo como guarda-corpo para preço base/promocional.
CREATE OR REPLACE FUNCTION public.validar_preco_produto()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE minimo numeric;
BEGIN
  IF NEW.tipo IN ('padrao','promocional') THEN
    SELECT max(valor) INTO minimo FROM public.produto_precos
     WHERE produto_id=NEW.produto_id AND tipo='minimo'
       AND (integration_id IS NOT DISTINCT FROM NEW.integration_id)
       AND vigencia_fim IS NULL;
    IF minimo IS NOT NULL AND NEW.valor < minimo THEN
      RAISE EXCEPTION 'Preço % não pode ser menor que o preço mínimo %', NEW.valor, minimo;
    END IF;
  END IF;
  IF NEW.tipo='minimo' THEN
    IF EXISTS (SELECT 1 FROM public.produto_precos p WHERE p.produto_id=NEW.produto_id AND p.tipo IN ('padrao','promocional') AND (p.integration_id IS NOT DISTINCT FROM NEW.integration_id) AND p.vigencia_fim IS NULL AND p.valor < NEW.valor) THEN
      RAISE EXCEPTION 'Preço mínimo não pode superar preço vigente do produto';
    END IF;
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_validar_preco_produto ON public.produto_precos;
CREATE TRIGGER trg_validar_preco_produto BEFORE INSERT OR UPDATE ON public.produto_precos FOR EACH ROW EXECUTE FUNCTION public.validar_preco_produto();
REVOKE ALL ON FUNCTION public.validar_preco_produto() FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.validar_preco_produto() TO service_role;