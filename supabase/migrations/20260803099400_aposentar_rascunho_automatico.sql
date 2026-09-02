-- Aposentadoria do rascunho automatico (27/08/2026).
--
-- Os 39 rascunhos que a consolidacao automatica criou entre 27/06 e 16/07 ja
-- estao CANCELADO desde 26/08: nao ha dado a migrar. O que sobrou foi a regra
-- de EXPIRACAO, e ela e o que esta sendo removida aqui.
--
-- rascunho_expirado() so fazia sentido para um rascunho que o sistema criava
-- sozinho e que ninguem talvez fosse olhar — dai o prazo de validade. Uma
-- consolidacao da Torre de Despacho e o oposto: alguem a montou ha minutos,
-- conferiu o total contra o painel do marketplace e provavelmente ja emitiu
-- nota fiscal sobre ela. Uma funcao que responde "expirou" sobre esse objeto
-- e uma resposta errada esperando por um chamador.
--
-- A coluna rascunho_expira_em fica: e vestigio barato, e apagar coluna de
-- tabela viva por limpeza cosmetica custa mais do que rende. O COMMENT abaixo
-- existe para que ninguem a leia como regra ativa.

DROP FUNCTION IF EXISTS public.rascunho_expirado(bigint);

COMMENT ON COLUMN public.demandas_producao.rascunho_expira_em IS
'Vestigial. Prazo de validade do rascunho automatico, aposentado em 27/08/2026. Uma consolidacao da Torre de Despacho nao expira: ela e publicada ou desfeita pelo operador. Sempre NULL em registros novos.';

COMMENT ON COLUMN public.demandas_producao.status IS
'RASCUNHO = consolidacao aberta na Torre de Despacho (lote fechado, ainda nao entregue ao galpao). A interface nunca usa a palavra "rascunho" para isso: ela sugere esboco descartavel, quando e o lote sobre o qual a nota fiscal ja foi emitida.';
