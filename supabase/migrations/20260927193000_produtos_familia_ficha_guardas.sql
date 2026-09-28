-- Protege gravações futuras sem reclassificar dados legados nem mudar status.
-- A auditoria remota de 2026-09-27 encontrou zero famílias multinível,
-- zero ciclos e duas linhas incompletas, preservadas na tabela de revisão.

CREATE OR REPLACE FUNCTION public.validar_produto_familia_nivel_unico()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
    v_parent_parent_id integer;
BEGIN
    PERFORM pg_advisory_xact_lock(1250269001, 1);

    IF NEW.parent_id IS NULL THEN
        RETURN NEW;
    END IF;

    IF NEW.parent_id = NEW.id THEN
        RAISE EXCEPTION 'PRODUCT_FAMILY_SELF_PARENT: produto %', NEW.id USING ERRCODE = '22023';
    END IF;

    SELECT parent.parent_id INTO v_parent_parent_id
      FROM public.produtos parent WHERE parent.id = NEW.parent_id;
    IF NOT FOUND THEN
        RETURN NEW; -- A FK existente apresentará o erro de referência.
    END IF;
    IF v_parent_parent_id IS NOT NULL THEN
        RAISE EXCEPTION 'PRODUCT_FAMILY_DEPTH_LIMIT: pai % já é uma variação', NEW.parent_id USING ERRCODE = '22023';
    END IF;

    IF EXISTS (SELECT 1 FROM public.produtos child WHERE child.parent_id = NEW.id AND child.id <> NEW.id) THEN
        RAISE EXCEPTION 'PRODUCT_FAMILY_DEPTH_LIMIT: produto % já tem variações', NEW.id USING ERRCODE = '22023';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_produtos_familia_nivel_unico ON public.produtos;
CREATE TRIGGER trg_produtos_familia_nivel_unico
BEFORE INSERT OR UPDATE OF parent_id ON public.produtos
FOR EACH ROW EXECUTE FUNCTION public.validar_produto_familia_nivel_unico();

CREATE OR REPLACE FUNCTION public.validar_ficha_tecnica_sem_ciclo()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
    v_cycle integer[];
BEGIN
    PERFORM pg_advisory_xact_lock(1250269001, 1);

    IF NEW.produto_pai_id IS NULL OR NEW.componente_id IS NULL THEN
        RAISE EXCEPTION 'BOM_COMPONENT_REQUIRED: pai e componente são obrigatórios em novas gravações' USING ERRCODE = '22023';
    END IF;
    IF NEW.quantidade_necessaria <= 0 THEN
        RAISE EXCEPTION 'BOM_QUANTITY_INVALID: a quantidade deve ser positiva' USING ERRCODE = '22023';
    END IF;
    IF NEW.produto_pai_id = NEW.componente_id THEN
        RAISE EXCEPTION 'BOM_CYCLE: % -> %', NEW.produto_pai_id, NEW.componente_id USING ERRCODE = '22023';
    END IF;

    WITH RECURSIVE caminho(produto_id, caminho_ids, ciclo) AS (
        SELECT NEW.componente_id, ARRAY[NEW.produto_pai_id, NEW.componente_id],
               NEW.componente_id = NEW.produto_pai_id
        UNION ALL
        SELECT b.componente_id, c.caminho_ids || b.componente_id,
               b.componente_id = NEW.produto_pai_id
          FROM caminho c
          CROSS JOIN LATERAL public.bom_efetiva_produto(c.produto_id) b
         WHERE NOT c.ciclo AND NOT (TG_OP = 'UPDATE' AND b.id = NEW.id)
    )
    SELECT caminho_ids INTO v_cycle FROM caminho WHERE ciclo LIMIT 1;

    IF v_cycle IS NOT NULL THEN
        RAISE EXCEPTION 'BOM_CYCLE: %', array_to_string(v_cycle, ' -> ') USING ERRCODE = '22023';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_ficha_tecnica_sem_ciclo ON public.ficha_tecnica;
CREATE TRIGGER trg_ficha_tecnica_sem_ciclo
BEFORE INSERT OR UPDATE OF produto_pai_id, componente_id, quantidade_necessaria ON public.ficha_tecnica
FOR EACH ROW EXECUTE FUNCTION public.validar_ficha_tecnica_sem_ciclo();

REVOKE ALL ON FUNCTION public.validar_produto_familia_nivel_unico() FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.validar_ficha_tecnica_sem_ciclo() FROM PUBLIC, anon, authenticated;
