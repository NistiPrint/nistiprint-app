> Documento legado.
> Pode descrever enriquecimento anterior a centralizacao por driver de plataforma.
> Fonte atual: [Spec de Pedidos](../specs/02-domains/pedidos/spec.md), [Spec de Integracoes](../specs/02-domains/integracoes/spec.md) e [API Contracts](../specs/03-contracts/api-contracts.md).

# Arquitetura de Filas e Webhooks (Simplificada)

## Contexto e Objetivo EstratÃ©gico
SubstituiÃ§Ã£o do protocolo complexo do Celery/Kombu por uma integraÃ§Ã£o direta via Redis (JSON puro). O objetivo Ã© facilitar a integraÃ§Ã£o entre n8n e o backend Python, garantindo resiliÃªncia e facilidade de depuraÃ§Ã£o.

## Arquitetura e Entidades
- **Produtor (n8n):** Realiza `RPUSH` de strings JSON puras na lista `bling:webhooks:pendentes`.
- **Consumer (Celery Beat + Task):** Task `consumir_fila_bling` atua como bridge, lendo do Redis e despachando tasks Celery nativas.
- **Dead Letter Queue (DLQ):** Mensagens malformadas ou que excedem 5 tentativas sÃ£o movidas para `bling:webhooks:dead-letter`.

## Plano de AÃ§Ã£o (ConsolidaÃ§Ã£o e PrÃ³ximos Passos)

- [x] **Task 1: ImplementaÃ§Ã£o do Consumer Base** - CriaÃ§Ã£o de `services/redis_queue_tasks.py` com lÃ³gica de `blpop` e retry manual.
- [x] **Task 2: ConfiguraÃ§Ã£o do Agendamento** - IntegraÃ§Ã£o no `celery_app.py` com intervalo de 10 segundos.
- [x] **Task 3: AtualizaÃ§Ã£o do Workflow n8n** - SimplificaÃ§Ã£o do nÃ³ Redis para enviar JSON puro sem metadados Kombu.
- [ ] **Task 4: ImplementaÃ§Ã£o de Handlers Reais** - Desenvolver a lÃ³gica interna de `_process_bling_sale_created` e `_process_bling_sale_changed` (vinculaÃ§Ã£o com DB).
- [ ] **Task 5: PadronizaÃ§Ã£o de Erros** - Criar um decorador ou utilitÃ¡rio para logging padronizado de falhas em webhooks.
- [ ] **Task 6: Dashboard de Monitoramento** - Script simples ou endpoint para visualizar o tamanho das filas (`LLEN`).

## ObservaÃ§Ãµes de ManutenÃ§Ã£o
- **AtenÃ§Ã£o:** O campo `id` no JSON enviado pelo n8n Ã© obrigatÃ³rio para o roteamento.
- **SeguranÃ§a:** O worker Redis deve estar em rede interna ou protegido por senha, jÃ¡ que o payload agora Ã© texto puro (sem criptografia de transporte nativa do Kombu).
- **Retry:** O sistema de retry manual (`attempt` counter) deve ser mantido sincronizado entre o n8n e o Python se for expandido.
