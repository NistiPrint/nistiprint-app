-- E7: identifica a origem dos dados fiscais sem alterar valores existentes.
ALTER TABLE public.produtos
  ADD COLUMN IF NOT EXISTS origem_fiscal text NOT NULL DEFAULT 'interno';

ALTER TABLE public.produtos
  DROP CONSTRAINT IF EXISTS produtos_origem_fiscal_ck;

ALTER TABLE public.produtos
  ADD CONSTRAINT produtos_origem_fiscal_ck
  CHECK (origem_fiscal IN ('interno', 'espelho_bling'));

COMMENT ON COLUMN public.produtos.origem_fiscal IS
  'Fonte dos dados fiscais: interno ou espelho_bling';