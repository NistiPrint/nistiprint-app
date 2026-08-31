CREATE EXTENSION IF NOT EXISTS unaccent;

ALTER TABLE public.categorias
  ADD COLUMN IF NOT EXISTS permite_arte boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN public.categorias.permite_arte IS
  'Permite associar arquivo local de arte para impressão aos produtos da categoria';

UPDATE public.categorias
SET permite_arte = true,
    updated_at = CURRENT_TIMESTAMP
WHERE regexp_replace(lower(unaccent(nome)), '[^a-z0-9]+', '', 'g') LIKE '%capa%'
   OR regexp_replace(lower(unaccent(nome)), '[^a-z0-9]+', '', 'g') LIKE '%miolo%';