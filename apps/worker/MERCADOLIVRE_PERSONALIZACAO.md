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

- Todas as funções do Mercado Livre usam a fila padrão `celery`; tarefas
  manuais e periódicas são executadas pelo worker compartilhado.
- O intervalo de segurança da inbox e da reconciliação usa
  `MERCADOLIVRE_CHAT_RECONCILE_SECONDS` (padrão: 120 segundos). Notificações
  novas também disparam a ingestão imediatamente.
- O Beat verifica agendamentos diários por integração a cada minuto. Uma trava
  Redis por integração/data evita execução duplicada; lotes não confirmados são
  recuperados periodicamente.
- As chaves de provedor de IA por conta continuam no ambiente do worker
  compartilhado: `MERCADOLIVRE_PERSONALIZACAO_GEMINI_API_KEY_<integration_id>`
  e `MERCADOLIVRE_PERSONALIZACAO_OPENROUTER_API_KEY_<integration_id>`.
- A Central de Tarefas mostra a saúde da ingestão, das contas e dos lotes a
  partir das execuções e pendências registradas, sem exigir heartbeat de
  processos do Mercado Livre.
