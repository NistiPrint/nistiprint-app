# Worker de personalização Mercado Livre

Este é um serviço independente do container/entrypoint padrão do worker, que
continua executando as tarefas atuais e o processamento Shopee.

## Subir a implantação

1. Aplicar a migração `20261006100000_mercadolivre_personalization_isolated.sql`.
2. Configurar `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` e copiar
   `.env.mercadolivre.accounts.example` para `.env.mercadolivre.accounts`, com
   chaves de IA próprias por instalação. Não reutilizar variáveis da Shopee.
3. Iniciar apenas o serviço adicional pelo arquivo
   `apps/worker/docker-compose.mercadolivre.yml`.
4. Acompanhar os logs do container. O supervisor detecta cada instalação ativa
   de Mercado Livre e inicia, para cada ID, os subprocessos `messages`,
   `worker` e `beat`, cada qual com sua própria fila.
5. No painel da conta piloto, validar identidade e mensagens com captura ativa
   e extração desligada. Ativar extração depois da conferência operacional.

Uma segunda conta ativa aparece automaticamente no supervisor, mas sua
configuração nasce com captura e extração desabilitadas. Habilite-a apenas após
validar usuário, application profile, permissões de mensagens, token e segredo
de assinatura para a nova instalação.

## Rollback

Desabilitar `enabled`, `capture_enabled` e `extraction_enabled` na conta ou
parar somente `mercadolivre-personalization-accounts`. Isso não reinicia nem
altera o container da Shopee. Inbox, conversas, personalizações e logs ficam
preservados para auditoria e retomada.

## Operação

- Chaves de IA por instalação (recomendado para cotas independentes):
  `MERCADOLIVRE_PERSONALIZACAO_GEMINI_API_KEY_<integration_id>` e
  `MERCADOLIVRE_PERSONALIZACAO_OPENROUTER_API_KEY_<integration_id>`. As chaves
  gerais sem sufixo, quando injetadas pelo ambiente, são fallback apenas dentro
  do ambiente Mercado Livre; nunca são lidas as chaves usadas pela Shopee.
- A leitura das mensagens usa `tag=post_sale` e `mark_as_read=false`.
- O limitador Redis coordena consumidor e worker pela conta (padrão: 2 chamadas/s
  por conta e 12 chamadas/s no total); respeita `Retry-After` e retoma lotes com
  falhas parciais até três tentativas.
- Agendamento diário padrão: 09:00 `America/Sao_Paulo`; a tela administra hora e
  minuto separadamente por conta.
- Reconciliação padrão: a cada 120 segundos; lote interrompido recuperado a cada
  300 segundos.
