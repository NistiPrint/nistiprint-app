CREATE TABLE IF NOT EXISTS public.priority_score_snapshots (
    snapshot_key text PRIMARY KEY,
    demand_id integer NOT NULL REFERENCES public.demandas_producao(id) ON DELETE RESTRICT,
    item_id integer REFERENCES public.itens_demanda(id) ON DELETE RESTRICT,
    score integer NOT NULL,
    rules_revision text NOT NULL,
    reference_date date NOT NULL,
    captured_at timestamptz NOT NULL,
    inputs jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_priority_score_snapshots_demand_captured
    ON public.priority_score_snapshots (demand_id, captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_priority_score_snapshots_item_captured
    ON public.priority_score_snapshots (item_id, captured_at DESC)
    WHERE item_id IS NOT NULL;

ALTER TABLE public.priority_score_snapshots ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.priority_score_snapshots FROM anon, authenticated;
GRANT ALL ON public.priority_score_snapshots TO service_role;
