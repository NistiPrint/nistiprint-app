-- Normalize verified existing billing evidence without altering settlement or payout.
CREATE FUNCTION public.gestao_ml_taxa_extrair(p_evidence jsonb,p_order text) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE SET search_path=public,pg_temp AS $$
DECLARE matched jsonb; fee jsonb;
BEGIN
 IF p_order IS NULL OR jsonb_typeof(p_evidence->'results') IS DISTINCT FROM 'array'
  OR jsonb_typeof(p_evidence->'errors') IS DISTINCT FROM 'array' THEN RETURN NULL; END IF;
 IF jsonb_array_length(p_evidence->'errors')<>0 OR coalesce(p_evidence->>'total','') !~ '^[0-9]+$' THEN RETURN NULL; END IF;
 IF (p_evidence->>'total')::numeric<>jsonb_array_length(p_evidence->'results') THEN RETURN NULL; END IF;
 SELECT coalesce(jsonb_agg(value),'[]') INTO matched FROM jsonb_array_elements(p_evidence->'results') WHERE value->>'order_id'=p_order;
 IF jsonb_array_length(matched)<>1 THEN RETURN NULL; END IF;
 fee:=matched->0->'sale_fee'->'net';
 IF jsonb_typeof(fee) IS DISTINCT FROM 'number' THEN RETURN NULL; END IF;
 IF (fee #>> '{}')::numeric<0 THEN RETURN NULL; END IF;
 RETURN fee;
END $$;
REVOKE ALL ON FUNCTION public.gestao_ml_taxa_extrair(jsonb,text) FROM PUBLIC,anon,authenticated;

CREATE FUNCTION public.gestao_ml_taxa_observada() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE external_id text; fee jsonb;
BEGIN
 IF NEW.source<>'ml_billing' THEN RETURN NEW; END IF;
 SELECT codigo_pedido_externo INTO external_id FROM public.pedidos WHERE id=NEW.pedido_id;
 fee:=public.gestao_ml_taxa_extrair(NEW.evidence,external_id);
 NEW.components:=coalesce(NEW.components,'{}'::jsonb)-'sale_fee';
 IF fee IS NOT NULL THEN NEW.components:=NEW.components||jsonb_build_object('sale_fee',fee); END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.gestao_ml_taxa_observada() FROM PUBLIC,anon,authenticated;
CREATE TRIGGER trg_gestao_ml_taxa_observada BEFORE INSERT OR UPDATE ON public.gestao_financeiro
 FOR EACH ROW EXECUTE FUNCTION public.gestao_ml_taxa_observada();
