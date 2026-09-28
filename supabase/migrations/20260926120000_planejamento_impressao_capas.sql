CREATE TABLE IF NOT EXISTS public.impressao_capas_planos (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    chave_escopo text NOT NULL UNIQUE,
    demanda_id integer REFERENCES public.demandas_producao(id) ON DELETE SET NULL,
    pedido_ids integer[] NOT NULL DEFAULT '{}',
    previsao_versao text,
    criado_por text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_impressao_capas_planos_demanda
    ON public.impressao_capas_planos(demanda_id);

CREATE TABLE IF NOT EXISTS public.impressao_capas_itens (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    plano_id uuid NOT NULL REFERENCES public.impressao_capas_planos(id) ON DELETE CASCADE,
    chave_origem text NOT NULL,
    chave_grupo text NOT NULL,
    item_pedido_id integer,
    personalizacao_id integer,
    produto_capa_id integer,
    sku_capa text,
    capa_nome text,
    variacao text,
    tipo text NOT NULL CHECK (tipo IN ('estatica', 'personalizada', 'pendente')),
    nome_personalizado text,
    quantidade_planejada numeric(15,4) NOT NULL DEFAULT 0,
    quantidade_confirmada numeric(15,4) NOT NULL DEFAULT 0,
    pendencia text,
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (plano_id, chave_origem)
);

CREATE INDEX IF NOT EXISTS idx_impressao_capas_itens_plano
    ON public.impressao_capas_itens(plano_id, chave_grupo, tipo);

CREATE TABLE IF NOT EXISTS public.impressao_capas_grupos (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    plano_id uuid NOT NULL REFERENCES public.impressao_capas_planos(id) ON DELETE CASCADE,
    chave_grupo text NOT NULL,
    quantidade_confirmada numeric(15,4) NOT NULL DEFAULT 0,
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (plano_id, chave_grupo)
);

CREATE TABLE IF NOT EXISTS public.impressao_capas_envios (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    plano_id uuid NOT NULL REFERENCES public.impressao_capas_planos(id) ON DELETE CASCADE,
    request_id uuid NOT NULL UNIQUE,
    chave_grupo text,
    sku_capa text NOT NULL,
    tipo text NOT NULL CHECK (tipo IN ('estatica', 'abrir_editor')),
    quantidade integer NOT NULL DEFAULT 0,
    printer_name text,
    agent_job_id integer,
    status text NOT NULL,
    mensagem text,
    enviado_por text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_impressao_capas_envios_plano
    ON public.impressao_capas_envios(plano_id, created_at DESC);

ALTER TABLE public.impressao_capas_planos ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.impressao_capas_itens ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.impressao_capas_envios ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.impressao_capas_grupos ENABLE ROW LEVEL SECURITY;

GRANT ALL ON public.impressao_capas_planos TO service_role;
GRANT ALL ON public.impressao_capas_itens TO service_role;
GRANT ALL ON public.impressao_capas_envios TO service_role;
GRANT ALL ON public.impressao_capas_grupos TO service_role;
