-- Estado de reconciliacao do prazo de postagem, no proprio pedido.
--
-- ## O problema
--
-- `data_limite_envio` so chega quando o provider resolve informa-lo: a Shopee
-- devolve `ship_by_date = 0` enquanto o pedido esta em LOGISTICS_NOT_START, e
-- o ML nem sempre tem SLA no primeiro evento. Ate hoje o unico jeito de
-- descobrir o valor era um evento NOVO daquele pedido — pedido parado no mesmo
-- status ficava sem prazo indefinidamente. A varredura existente
-- (`ressincronizar_pendentes`) percorre a base por cursor a 100 pedidos/hora,
-- contra ~300 pedidos novos/hora: nao alcanca o problema nem em teoria.
--
-- ## Por que o estado mora aqui, e nao numa fila
--
-- Uma fila e uma copia da verdade e pode discordar dela. Foi exatamente assim
-- que a reconciliacao de ERP travou em 09/09/2026: 53 linhas 'pending' de
-- pedidos que ja tinham referencia ocupavam o lote de 50 para sempre, e a task
-- reportava "applied: 50" enquanto nada acontecia.
--
-- Aqui a fila e um indice parcial sobre `data_limite_envio IS NULL`. O conjunto
-- de trabalho e derivado da verdade, nao paralelo a ela: no instante em que o
-- prazo e gravado o pedido sai do indice. Nao existe linha para virar zumbi,
-- nem estado para divergir.
--
-- As tres colunas guardam apenas o que a verdade nao sabe dizer: quantas vezes
-- ja perguntamos, quando vale perguntar de novo, e o que o provider respondeu
-- da ultima vez.

ALTER TABLE public.pedidos
  ADD COLUMN IF NOT EXISTS prazo_postagem_tentativas INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS prazo_postagem_proxima_tentativa TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS prazo_postagem_motivo TEXT;

COMMENT ON COLUMN public.pedidos.prazo_postagem_tentativas IS
  'Consultas ja feitas ao provider em busca de data_limite_envio. Zera quando o prazo chega.';
COMMENT ON COLUMN public.pedidos.prazo_postagem_proxima_tentativa IS
  'Momento a partir do qual vale reconsultar o provider. NULL = consultar na proxima rodada.';
COMMENT ON COLUMN public.pedidos.prazo_postagem_motivo IS
  'Resposta da ultima tentativa. Existe para que "sem prazo" seja legivel sem abrir log.';

-- O predicado parcial usa so `data_limite_envio IS NULL` de proposito: e a
-- unica condicao que nao muda quando mudam as regras de elegibilidade (canais
-- com driver, situacoes, horizonte). Indice que embute politica precisa ser
-- recriado toda vez que a politica anda.
CREATE INDEX IF NOT EXISTS ix_pedidos_prazo_postagem_pendente
  ON public.pedidos (prazo_postagem_proxima_tentativa NULLS FIRST, created_at)
  WHERE data_limite_envio IS NULL;
