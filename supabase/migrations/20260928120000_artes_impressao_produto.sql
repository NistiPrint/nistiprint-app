CREATE TABLE IF NOT EXISTS public.impressao_artes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    produto_final_id integer NOT NULL REFERENCES public.produtos(id) ON DELETE CASCADE,
    nome text NOT NULL CHECK (length(trim(nome)) > 0),
    ativo boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_impressao_artes_produto ON public.impressao_artes(produto_final_id);

CREATE TABLE IF NOT EXISTS public.impressao_arte_componentes (
    arte_id uuid NOT NULL REFERENCES public.impressao_artes(id) ON DELETE CASCADE,
    produto_final_id integer NOT NULL REFERENCES public.produtos(id) ON DELETE CASCADE,
    componente_id integer NOT NULL REFERENCES public.produtos(id) ON DELETE CASCADE,
    papel text NOT NULL CHECK (papel IN ('capa', 'contra', 'miolo')),
    PRIMARY KEY (arte_id, componente_id),
    UNIQUE (produto_final_id, componente_id)
);

CREATE OR REPLACE FUNCTION public.validar_arte_produto_final()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.impressao_artes a
        WHERE a.id = NEW.arte_id AND a.produto_final_id = NEW.produto_final_id
    ) THEN
        RAISE EXCEPTION 'Arte e componente devem pertencer ao mesmo produto final';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_validar_arte_produto_final
BEFORE INSERT OR UPDATE ON public.impressao_arte_componentes
FOR EACH ROW EXECUTE FUNCTION public.validar_arte_produto_final();

ALTER TABLE public.impressao_capas_itens
    ADD COLUMN IF NOT EXISTS arte_id uuid REFERENCES public.impressao_artes(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS produto_final_id integer,
    ADD COLUMN IF NOT EXISTS componentes_ids integer[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS papeis text[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS quantidade_por_unidade numeric(15,6),
    ADD COLUMN IF NOT EXISTS pedido_id integer,
    ADD COLUMN IF NOT EXISTS pedido_codigo text,
    ADD COLUMN IF NOT EXISTS revisao_pendente boolean NOT NULL DEFAULT false;

ALTER TABLE public.impressao_capas_envios
    ADD COLUMN IF NOT EXISTS arte_id uuid REFERENCES public.impressao_artes(id) ON DELETE SET NULL;

ALTER TABLE public.impressao_capas_grupos
    ADD COLUMN IF NOT EXISTS quantidade_legada numeric(15,4) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS revisao_pendente boolean NOT NULL DEFAULT false;

ALTER TABLE public.impressao_artes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.impressao_arte_componentes ENABLE ROW LEVEL SECURITY;
GRANT ALL ON public.impressao_artes TO service_role;
GRANT ALL ON public.impressao_arte_componentes TO service_role;

CREATE OR REPLACE FUNCTION public.salvar_arte_impressao(
    p_produto_final_id integer, p_arte_id uuid, p_nome text, p_componentes jsonb
) RETURNS uuid LANGUAGE plpgsql SET search_path = public AS $$
DECLARE v_arte_id uuid;
BEGIN
    IF p_arte_id IS NULL THEN
        INSERT INTO public.impressao_artes(produto_final_id, nome)
        VALUES (p_produto_final_id, p_nome) RETURNING id INTO v_arte_id;
    ELSE
        UPDATE public.impressao_artes SET nome = p_nome, ativo = true, updated_at = now()
        WHERE id = p_arte_id AND produto_final_id = p_produto_final_id
        RETURNING id INTO v_arte_id;
        IF v_arte_id IS NULL THEN
            RAISE EXCEPTION 'Arte não encontrada para o produto';
        END IF;
        DELETE FROM public.impressao_arte_componentes WHERE arte_id = v_arte_id;
    END IF;
    INSERT INTO public.impressao_arte_componentes(arte_id, produto_final_id, componente_id, papel)
    SELECT v_arte_id, p_produto_final_id,
           (item->>'componente_id')::integer, item->>'papel'
    FROM jsonb_array_elements(p_componentes) AS item;
    RETURN v_arte_id;
END;
$$;

REVOKE ALL ON FUNCTION public.salvar_arte_impressao(integer, uuid, text, jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.salvar_arte_impressao(integer, uuid, text, jsonb) TO service_role;

CREATE OR REPLACE FUNCTION public.arquivar_arte_impressao(p_produto_final_id integer, p_arte_id uuid)
RETURNS void LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
    UPDATE public.impressao_artes SET ativo = false, updated_at = now()
    WHERE id = p_arte_id AND produto_final_id = p_produto_final_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Arte não encontrada para o produto';
    END IF;
    DELETE FROM public.impressao_arte_componentes WHERE arte_id = p_arte_id;
END;
$$;

REVOKE ALL ON FUNCTION public.arquivar_arte_impressao(integer, uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.arquivar_arte_impressao(integer, uuid) TO service_role;
