-- Fechamento automatico das janelas de despacho: registro de execucao.
-- Contrato: docs/specs/02-domains/despacho/spec.md
--
-- ## O papel do job, e o que ele NAO e
--
-- Este mecanismo nao e o que mantem a torre correta. `despacho_arvore` calcula
-- corte e coleta na leitura (ver 20260803097000), sempre no futuro. Se o job
-- atrasar, falhar ou nao rodar, os numeros da tela seguem certos.
--
-- O job faz o que calculo nenhum faz: agir no instante em que a janela vira.
-- No corte, o lote fecha e vira demanda RASCUNHO; na coleta, os compromissos
-- sao regravados para os consumidores que leem a coluna direto.
--
-- A distincao importa porque define o modo de falha. Se o job fosse a fonte da
-- verdade, job parado = tela mentindo — que foi exatamente o bug dos horarios
-- de ontem. Do jeito que esta, job parado = automacao perdida naquele ciclo,
-- com os numeros intactos.

CREATE TABLE IF NOT EXISTS public.janelas_despacho_execucoes (
    id              bigserial PRIMARY KEY,
    integration_id  integer     NOT NULL REFERENCES public.installed_integrations(id) ON DELETE CASCADE,
    modalidade_id   integer     NOT NULL REFERENCES public.modalidades_logisticas(id) ON DELETE CASCADE,
    tipo            varchar(10) NOT NULL CHECK (tipo IN ('CORTE', 'COLETA')),
    janela_em       timestamptz NOT NULL,
    executado_em    timestamptz NOT NULL DEFAULT now(),
    demanda_id      integer     REFERENCES public.demandas_producao(id) ON DELETE SET NULL,
    qtd_pedidos     integer     NOT NULL DEFAULT 0,
    observacao      text
);

-- A chave e a identidade da JANELA, nao a da execucao. E ela que torna o
-- fechamento idempotente: o job pode rodar duas vezes, atrasado, ou depois de
-- um restart do beat, e a janela ja fechada nao fecha de novo.
CREATE UNIQUE INDEX IF NOT EXISTS ux_janelas_despacho_execucoes
    ON public.janelas_despacho_execucoes (integration_id, modalidade_id, tipo, janela_em);

COMMENT ON TABLE public.janelas_despacho_execucoes IS
  'Janelas de corte e coleta ja processadas. Existe para idempotencia e para o catch-up de janela perdida: sem ela, um beat reiniciado refaria lotes ou pularia lotes em silencio.';

ALTER TABLE public.janelas_despacho_execucoes ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS janelas_despacho_execucoes_rw ON public.janelas_despacho_execucoes;
CREATE POLICY janelas_despacho_execucoes_rw ON public.janelas_despacho_execucoes
    FOR ALL TO authenticated USING (true) WITH CHECK (true);
