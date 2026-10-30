-- A legacy BEFORE trigger inspected JSON before the family RPC projected it.
-- Validate the final relational state instead, including direct activations.
DROP TRIGGER IF EXISTS trg_validar_ativacao_variacao_clonada ON public.produtos;
CREATE OR REPLACE FUNCTION public.catalog_validate_active_variation() RETURNS trigger
LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
DECLARE current_product public.produtos%ROWTYPE; axis_count integer;
BEGIN
 SELECT * INTO current_product FROM public.produtos WHERE id=NEW.id;
 IF NOT FOUND OR current_product.status<>'ativo' OR current_product.papel_catalogo<>'variacao' THEN RETURN NULL; END IF;
 IF TG_OP='UPDATE' THEN
  IF OLD.status='ativo' AND OLD.parent_id IS NOT DISTINCT FROM NEW.parent_id
   AND OLD.papel_catalogo IS NOT DISTINCT FROM NEW.papel_catalogo THEN RETURN NULL; END IF;
 END IF;
 SELECT count(*) INTO axis_count FROM public.produto_pai_eixos WHERE produto_pai_id=current_product.parent_id;
 IF axis_count=0 OR axis_count<>(SELECT count(*) FROM public.produto_variacao_valores WHERE produto_id=NEW.id)
  OR NOT EXISTS(SELECT 1 FROM public.produto_variacao_combinacoes WHERE produto_id=NEW.id AND produto_pai_id=current_product.parent_id)
  OR EXISTS(SELECT 1 FROM public.produto_variacao_valores v WHERE v.produto_id=NEW.id AND NOT EXISTS(
    SELECT 1 FROM public.produto_pai_eixo_opcoes a WHERE a.produto_pai_id=current_product.parent_id AND a.eixo_id=v.eixo_id AND a.opcao_id=v.opcao_id)) THEN
  RAISE EXCEPTION 'ACTIVE_VARIATION_REQUIRES_COMPLETE_COMBINATION' USING ERRCODE='22023';
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER catalog_validate_active_variation
 AFTER INSERT OR UPDATE ON public.produtos DEFERRABLE INITIALLY DEFERRED
 FOR EACH ROW EXECUTE FUNCTION public.catalog_validate_active_variation();
