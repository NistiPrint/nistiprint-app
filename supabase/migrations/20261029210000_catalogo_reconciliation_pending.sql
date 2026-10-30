-- Unapproved aliases remain reviewable even when an exact SKU exists.
CREATE OR REPLACE FUNCTION public.marketplace_anuncio_reconciliar(
 p_account integer,p_unit integer,p_version integer,p_product integer,p_reason text,p_candidates integer[])
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE unit public.produto_anuncios%ROWTYPE;
BEGIN
 SELECT * INTO unit FROM public.produto_anuncios WHERE id=p_unit AND integration_id=p_account FOR UPDATE;
 IF NOT FOUND OR unit.vinculo_versao<>p_version THEN RETURN false; END IF;
 IF p_reason NOT IN ('confirmed','confirmed_conflict','sku','alias','conflict','unmapped','alias_pending') THEN
  RAISE EXCEPTION 'INVALID_RECONCILIATION_REASON' USING ERRCODE='22023';
 END IF;
 IF p_reason IN ('conflict','unmapped','confirmed_conflict','alias_pending') THEN
  INSERT INTO public.marketplace_anuncio_pendencias(unidade_id,integration_id,motivo,candidatos)
   VALUES(p_unit,p_account,p_reason,p_candidates)
   ON CONFLICT(unidade_id) DO UPDATE SET motivo=excluded.motivo,candidatos=excluded.candidatos,resolved_at=NULL,updated_at=now();
 ELSE
  UPDATE public.marketplace_anuncio_pendencias SET resolved_at=now() WHERE unidade_id=p_unit AND resolved_at IS NULL;
 END IF;
 IF p_reason IN ('sku','alias') AND coalesce(unit.origem_vinculo,'') NOT IN ('manual','confirmado') AND unit.produto_id IS DISTINCT FROM p_product THEN
  PERFORM public.marketplace_anuncio_vincular(p_unit,p_product,'Reconciliação inequívoca por '||p_reason,p_reason,NULL,p_version);
 END IF;
 RETURN true;
END $$;

CREATE OR REPLACE FUNCTION public.catalog_validate_product_role() RETURNS trigger
LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
DECLARE parent_product public.produtos%ROWTYPE;
BEGIN
  IF NEW.parent_id IS NULL AND NEW.formato='com_variacao' THEN NEW.papel_catalogo:='modelo'; END IF;
  IF NEW.parent_id IS NOT NULL AND EXISTS(SELECT 1 FROM produtos WHERE parent_id=NEW.id) THEN
    RAISE EXCEPTION 'FAMILY_DEPTH_LIMIT' USING ERRCODE='22023';
  END IF;
  -- Older create/clone RPCs may only set parent_id. Normalize that legacy
  -- insert into the canonical role while preserving the single-level rule.
  IF NEW.parent_id IS NOT NULL AND NEW.papel_catalogo='individual' THEN
    NEW.papel_catalogo:='variacao';
  END IF;
  IF NEW.papel_catalogo='variacao' THEN
    IF NEW.parent_id IS NULL OR NEW.parent_id=NEW.id THEN
      RAISE EXCEPTION 'VARIATION_REQUIRES_MODEL_PARENT' USING ERRCODE='22023';
    END IF;
    SELECT * INTO parent_product FROM public.produtos WHERE id=NEW.parent_id FOR UPDATE;
    IF NOT FOUND OR parent_product.parent_id IS NOT NULL THEN
      RAISE EXCEPTION 'FAMILY_PARENT_MUST_BE_ROOT' USING ERRCODE='22023';
    END IF;
    IF parent_product.papel_catalogo<>'modelo' THEN
      RAISE EXCEPTION 'VARIATION_REQUIRES_MODEL_PARENT' USING ERRCODE='22023';
    END IF;
    NEW.formato:='variacao';
  ELSIF NEW.parent_id IS NOT NULL THEN
    RAISE EXCEPTION 'ONLY_VARIATIONS_CAN_HAVE_PARENT' USING ERRCODE='22023';
  ELSIF NEW.papel_catalogo IN ('individual','modelo') AND EXISTS(
      SELECT 1 FROM public.produtos child WHERE child.parent_id=NEW.id AND child.id<>NEW.id
        AND NEW.papel_catalogo<>'modelo') THEN
    RAISE EXCEPTION 'PRODUCT_WITH_VARIATIONS_MUST_REMAIN_MODEL' USING ERRCODE='22023';
  END IF;
  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION public.catalog_reject_model_unit() RETURNS trigger
LANGUAGE plpgsql SET search_path=public,pg_temp AS $$ BEGIN
 IF NEW.produto_id IS NOT NULL AND EXISTS(SELECT 1 FROM public.produtos WHERE id=NEW.produto_id AND papel_catalogo='modelo') THEN
  RAISE EXCEPTION 'MODEL_CANNOT_RECEIVE_SELLABLE_LINK_OR_STOCK_MOVEMENT' USING ERRCODE='22023';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER catalog_reject_model_unit BEFORE INSERT OR UPDATE OF produto_id ON public.produto_anuncios
 FOR EACH ROW EXECUTE FUNCTION public.catalog_reject_model_unit();
CREATE TRIGGER catalog_reject_model_stock BEFORE INSERT ON public.movimentacoes_estoque
 FOR EACH ROW EXECUTE FUNCTION public.catalog_reject_model_unit();
