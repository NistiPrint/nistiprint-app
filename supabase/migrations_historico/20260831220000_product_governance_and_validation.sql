-- Governança e validações do cadastro. Nenhum dado existente é transformado.

CREATE OR REPLACE FUNCTION public.validar_gtin(p_gtin text)
RETURNS boolean LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
  v text := btrim(p_gtin);
  soma integer := 0;
  i integer;
  digito integer;
  esperado integer;
BEGIN
  IF v = 'SEM GTIN' THEN RETURN true; END IF;
  IF v !~ '^[0-9]+$' OR length(v) NOT IN (8, 12, 13, 14) THEN RETURN false; END IF;
  FOR i IN 1..length(v)-1 LOOP
    digito := substr(v, length(v)-i, 1)::integer;
    soma := soma + digito * CASE WHEN i % 2 = 1 THEN 3 ELSE 1 END;
  END LOOP;
  esperado := (10 - (soma % 10)) % 10;
  RETURN esperado = right(v, 1)::integer;
END $$;

ALTER TABLE public.produtos
  ADD CONSTRAINT produtos_status_estagio_ck
  CHECK (status <> 'ativo' OR estagio = 'PUBLICADO') NOT VALID;
ALTER TABLE public.produtos VALIDATE CONSTRAINT produtos_status_estagio_ck;

ALTER TABLE public.produtos
  ADD CONSTRAINT produtos_fiscal_dimensoes_ck CHECK (
    (ncm IS NULL OR ncm ~ '^[0-9]{8}$') AND
    (cest IS NULL OR cest ~ '^[0-9]{7}$') AND
    (origem_mercadoria IS NULL OR origem_mercadoria BETWEEN 0 AND 8) AND
    (gtin IS NULL OR public.validar_gtin(gtin)) AND
    (gtin_embalagem IS NULL OR public.validar_gtin(gtin_embalagem)) AND
    (peso_liquido IS NULL OR peso_liquido >= 0) AND
    (peso_bruto IS NULL OR peso_bruto >= 0) AND
    (comprimento IS NULL OR comprimento >= 0) AND
    (largura IS NULL OR largura >= 0) AND
    (altura IS NULL OR altura >= 0) AND
    (garantia_meses IS NULL OR garantia_meses >= 0)
  ) NOT VALID;
ALTER TABLE public.produtos VALIDATE CONSTRAINT produtos_fiscal_dimensoes_ck;

CREATE OR REPLACE FUNCTION public.auditar_cadastro_produto()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
  entidade text := TG_TABLE_NAME;
  registro bigint;
BEGIN
  registro := COALESCE((to_jsonb(NEW)->>'id')::bigint, (to_jsonb(OLD)->>'id')::bigint);
  INSERT INTO public.eventos_auditoria
    (tipo_evento, descricao, entidade_afetada, registro_id, dados_anteriores, dados_novos)
  VALUES (
    lower(TG_OP) || '_' || entidade,
    'Alteração no cadastro de produto/integracao',
    entidade,
    registro::integer,
    CASE WHEN TG_OP IN ('UPDATE','DELETE') THEN to_jsonb(OLD) ELSE NULL END,
    CASE WHEN TG_OP IN ('UPDATE','INSERT') THEN to_jsonb(NEW) ELSE NULL END
  );
  RETURN COALESCE(NEW, OLD);
END $$;

DROP TRIGGER IF EXISTS trg_auditoria_produtos ON public.produtos;
CREATE TRIGGER trg_auditoria_produtos
  AFTER INSERT OR UPDATE OR DELETE ON public.produtos
  FOR EACH ROW EXECUTE FUNCTION public.auditar_cadastro_produto();

DROP TRIGGER IF EXISTS trg_auditoria_produto_anuncios ON public.produto_anuncios;
CREATE TRIGGER trg_auditoria_produto_anuncios
  AFTER INSERT OR UPDATE OR DELETE ON public.produto_anuncios
  FOR EACH ROW EXECUTE FUNCTION public.auditar_cadastro_produto();

DROP TRIGGER IF EXISTS trg_auditoria_produto_precos ON public.produto_precos;
CREATE TRIGGER trg_auditoria_produto_precos
  AFTER INSERT OR UPDATE OR DELETE ON public.produto_precos
  FOR EACH ROW EXECUTE FUNCTION public.auditar_cadastro_produto();