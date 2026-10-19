# Diagnóstico das telas Torre de Despacho e Vendas Personalizadas

Leitura de produção em 19/10/2026, aproximadamente 15h em Brasília, sem alterar
dados. O agendamento real em `configuracoes_aplicacao` confirma o lote de IA às
12h na fila `ai_personalization`.

| Sinal | Observação |
| --- | --- |
| Projeção de personalizados | 0 linhas; `backfill_complete=false` |
| Outbox dos modelos de leitura | 5.956 eventos, o mais antigo de 15/10; 5.915 com mais de uma hora |
| Snapshot da Torre | Última geração às 14h25, cerca de 33 minutos antes da leitura |
| Worker | `nistiprint-worker` e beat ativos; unit de IA inativa; worker principal sem restrição de filas |
| Erro repetido | `refresh_operational_read_models`: `DELETE requires a WHERE clause` |

As tabelas e funções dos modelos de leitura existem no banco, mas a versão
`20261015120000` não apareceu no ledger consultado. Conferir esse descompasso
antes de registrar a nova migration; não usar `supabase db push`.

O erro vem dos `DELETE` sem filtro em `rebuild_despacho_janelas_read_model`.
Como toda atualização ocorre na mesma transação, a falha impede tanto o avanço
da projeção quanto a atualização do snapshot. A API então usa consultas diretas
e mais caras. `pg_stat_statements` registrava 1.204 leituras da view-resumo de
Personalizadas com média de 704 ms e 326 chamadas do contexto da Torre com
média de 437 ms e máximo de 1.616 ms. Esses valores são acumulados desde o
reset das estatísticas e não representam p95 nem uma medição isolada da tarde.

A migration `20261019124500_operational_read_model_latency.sql` corrige a falha
de atualização, completa os status 2/3/4 e elimina a recomputação simultânea
do snapshot. Depois da implantação, conferir a drenagem da outbox, o fim do
backfill e a idade do snapshot. Os logs de duração adicionados às duas APIs e
ao worker permitirão calcular p95 antes/depois das 12h e validar as metas do
plano em tráfego real.
