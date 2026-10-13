# Mensagens e personalização do Mercado Livre

O Mercado Livre usa o worker e o Beat Celery já existentes. Não existe serviço,
supervisor, worker ou Beat exclusivo do marketplace ou de cada integração.

## Etapas

1. O N8N recebe e enfileira o webhook. O consumidor compartilhado de chat chama
   o adaptador do Mercado Livre, que resolve a conta por `user_id` e
   `application_id` e grava a notificação em `mercadolivre_chat_inbox`.
2. O consumidor agenda a função Celery `mercadolivre.chat.process_inbox` na
   fila padrão `celery`. O Beat compartilhado também a agenda periodicamente
   para recuperar notificações retidas. A função usa as credenciais e o
   limitador de chamadas da integração identificada e persiste conversas e
   mensagens. Identidades incompletas ou ambíguas permanecem em `unmatched`.
3. A reconciliação de conversas roda pela função Celery
   `mercadolivre.chat.reconcile`; ela recupera lacunas do histórico sem chamar
   IA.
4. A extração é uma etapa independente. As funções Celery de lotes manuais,
   diários e recuperação recebem o `integration_id`, usam a configuração da
   conta e processam somente mensagens já persistidas. O agendamento diário
   continua configurável na integração e é despachado pelo Beat compartilhado.

O ramo Shopee do consumidor de chat, seus workers `chat` e `chatsync`, e sua
persistência não mudam. Apenas o adaptador e os dados de origem do Mercado Livre
são específicos.

## Operação e recuperação

### IA: primeira passagem e retentativas

Cada conta mantém até dez pacotes simultâneos, repondo a vaga assim que um
pacote termina. A primeira passagem chama apenas o principal. Depois que todos
os pacotes terminam essa passagem, somente as falhas elegíveis recebem uma
nova chamada, com fallback configurado ou principal. O limite é duas chamadas
por pacote; os retries internos do SDK estão desativados nesse executor.

`Retry-After` determina a próxima execução; sem prazo, falhas temporárias
aguardam 30 segundos. A espera libera o worker e o lease da conta. O Beat
verifica trabalhos vencidos a cada 30 segundos e apenas despacha tarefas.
Tokens e transições no PostgreSQL protegem contra entregas duplicadas. Uma
resposta validada é salva antes da gravação final: falhas de persistência
retomam essa resposta, sem chamar a IA novamente.

O painel dos pedidos e a Central de Atividade mostram a primeira passagem,
sucessos, erros definitivos, pacotes ativos e retentativas. A primeira passagem
pode chegar a 100% enquanto o lote continua ativo. Eventos atualizam o painel;
sem stream, a consulta ocorre a cada dois segundos. Os detalhes incluem
provedor, tentativas, próxima execução e tempos de preparação, IA e gravação.

Para ativar, drene as tarefas antigas de personalização, aplique a migração
`20261013150000_mercadolivre_deferred_ai_retry.sql` e então publique API,
frontend e worker, reiniciando também o Beat. Mantenha a fila compartilhada
`celery`. Confira seus consumidores e a concorrência instalada; cada processo
coordenador permite uma conta ativa. Lotes terminais antigos são preservados.

Compare lotes equivalentes usando `created_at`, `started_at`, `finished_at`
e as métricas `preparation_ms`, `ai_ms`, `persistence_ms` e `duration_ms` dos
itens. Separe espera na fila, duração total, pacotes por minuto, erros e
retentativas. O ganho com chamadas reais ao provedor precisa ser medido após
a implantação. Os testes PostgreSQL usam apenas um banco isolado local
`nistiprint_test`, configurado por `NISTIPRINT_TEST_DATABASE_URL`.

- Todas as funções do Mercado Livre usam a fila padrão `celery`; tarefas
  manuais e periódicas são executadas pelo worker compartilhado.
- O intervalo de segurança da inbox e da reconciliação usa
  `MERCADOLIVRE_CHAT_RECONCILE_SECONDS` (padrão: 120 segundos). Notificações
  novas também disparam a ingestão imediatamente.
- O Beat verifica agendamentos diários por integração a cada minuto. Uma trava
  Redis por integração/data evita execução duplicada; lotes não confirmados são
  recuperados periodicamente.
- As credenciais de IA são compartilhadas pela empresa no ambiente do worker:
  `NISTIPRINT_AI_KEY` para Gemini e `OPENROUTER_API_KEY` para OpenRouter.
  Provedor, modelo e fallback continuam configuráveis por integração; chaves
  exclusivas do Mercado Livre não são utilizadas.
- A Central de Tarefas mostra a saúde da ingestão, das contas e dos lotes a
  partir das execuções e pendências registradas, sem exigir heartbeat de
  processos do Mercado Livre.
