CREATE TABLE IF NOT EXISTS public.bom_efetiva_versoes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    produto_id integer NOT NULL REFERENCES public.produtos(id) ON DELETE RESTRICT,
    content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    contract_version integer NOT NULL DEFAULT 1 CHECK (contract_version > 0),
    graph jsonb NOT NULL CHECK (jsonb_typeof(graph) = 'object'),
    created_by integer,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (produto_id, content_hash)
);
ALTER TABLE public.bom_efetiva_versoes ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.bom_efetiva_versoes FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT ON public.bom_efetiva_versoes TO service_role;

CREATE OR REPLACE FUNCTION public.bom_versao_immutable()
RETURNS trigger LANGUAGE plpgsql SET search_path = public, pg_temp
AS $function$
BEGIN
    RAISE EXCEPTION 'Versões publicadas da BOM são imutáveis' USING ERRCODE = '55000';
END;
$function$;
DROP TRIGGER IF EXISTS trg_bom_versao_immutable ON public.bom_efetiva_versoes;
CREATE TRIGGER trg_bom_versao_immutable BEFORE UPDATE OR DELETE
    ON public.bom_efetiva_versoes FOR EACH ROW EXECUTE FUNCTION public.bom_versao_immutable();
REVOKE ALL ON FUNCTION public.bom_versao_immutable() FROM PUBLIC, anon, authenticated;

ALTER TABLE public.snapshots_reconciliacao
    ADD COLUMN IF NOT EXISTS bom_version_id uuid
        REFERENCES public.bom_efetiva_versoes(id) ON DELETE RESTRICT;
ALTER TABLE public.itens_demanda
    ADD COLUMN IF NOT EXISTS bom_version_id uuid
        REFERENCES public.bom_efetiva_versoes(id) ON DELETE RESTRICT;
ALTER TABLE public.ordens_producao
    ADD COLUMN IF NOT EXISTS bom_version_id uuid
        REFERENCES public.bom_efetiva_versoes(id) ON DELETE RESTRICT;

CREATE OR REPLACE FUNCTION public.vincular_versao_bom_snapshot()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp
AS $function$
BEGIN
    IF NEW.payload ? 'bom_version_id' THEN
        NEW.bom_version_id := nullif(NEW.payload->>'bom_version_id', '')::uuid;
    END IF;
    RETURN NEW;
END;
$function$;
DROP TRIGGER IF EXISTS trg_vincular_versao_bom_snapshot ON public.snapshots_reconciliacao;
CREATE TRIGGER trg_vincular_versao_bom_snapshot BEFORE INSERT
    ON public.snapshots_reconciliacao FOR EACH ROW EXECUTE FUNCTION public.vincular_versao_bom_snapshot();

CREATE OR REPLACE FUNCTION public.atualizar_versao_bom_item_snapshot()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp
AS $function$
BEGIN
    IF NEW.bom_version_id IS NOT NULL THEN
        UPDATE public.itens_demanda SET bom_version_id = NEW.bom_version_id
         WHERE id = NEW.item_id;
    END IF;
    RETURN NEW;
END;
$function$;
DROP TRIGGER IF EXISTS trg_atualizar_versao_bom_item_snapshot ON public.snapshots_reconciliacao;
CREATE TRIGGER trg_atualizar_versao_bom_item_snapshot AFTER INSERT
    ON public.snapshots_reconciliacao FOR EACH ROW EXECUTE FUNCTION public.atualizar_versao_bom_item_snapshot();
REVOKE ALL ON FUNCTION public.vincular_versao_bom_snapshot() FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.atualizar_versao_bom_item_snapshot() FROM PUBLIC, anon, authenticated;
