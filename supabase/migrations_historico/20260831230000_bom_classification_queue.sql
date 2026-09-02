-- F5: fila de classificação da BOM. Não altera linhas existentes.
CREATE TABLE IF NOT EXISTS public.ficha_tecnica_classificacao_pendente (
  ficha_tecnica_id integer PRIMARY KEY REFERENCES public.ficha_tecnica(id) ON DELETE CASCADE,
  produto_pai_id integer NOT NULL REFERENCES public.produtos(id) ON DELETE CASCADE,
  componente_id integer REFERENCES public.produtos(id) ON DELETE SET NULL,
  categoria_componente_id integer,
  sugestao_grupo text,
  motivo text NOT NULL,
  criado_em timestamptz NOT NULL DEFAULT now(),
  resolvido_em timestamptz
);

INSERT INTO public.ficha_tecnica_classificacao_pendente
  (ficha_tecnica_id, produto_pai_id, componente_id, categoria_componente_id, sugestao_grupo, motivo)
SELECT f.id, f.produto_pai_id, f.componente_id, c.categoria_id,
       CASE WHEN c.categoria_id=6 THEN 'Miolo'
            WHEN c.categoria_id=10 THEN 'Contra'
            WHEN c.categoria_id=3 AND lower(c.nome) LIKE '%contra%' THEN 'Contra'
            WHEN c.categoria_id=3 THEN 'Capa'
            WHEN c.categoria_id=4 THEN 'Acabamento'
            WHEN c.categoria_id=5 THEN 'Embalagem' END,
       'linha legada sem grupo; classificação requer confirmação'
  FROM public.ficha_tecnica f
  LEFT JOIN public.produtos c ON c.id=f.componente_id
 WHERE f.grupo IS NULL
ON CONFLICT (ficha_tecnica_id) DO NOTHING;

CREATE INDEX IF NOT EXISTS ix_ficha_classificacao_pendente
  ON public.ficha_tecnica_classificacao_pendente (resolvido_em)
  WHERE resolvido_em IS NULL;