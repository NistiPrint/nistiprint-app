# Arquitetura de Filas e Webhooks (Simplificada)

## Contexto e Objetivo Estratégico
Substituição do protocolo complexo do Celery/Kombu por uma integração direta via Redis (JSON puro). O objetivo é facilitar a integração entre n8n e o backend Python, garantindo resiliência e facilidade de depuração.

## Arquitetura e Entidades
- **Produtor (n8n):** Realiza `RPUSH` de strings JSON puras na lista `bling:webhooks:pendentes`.
- **Consumer (Celery Beat + Task):** Task `consumir_fila_bling` atua como bridge, lendo do Redis e despachando tasks Celery nativas.
- **Dead Letter Queue (DLQ):** Mensagens malformadas ou que excedem 5 tentativas são movidas para `bling:webhooks:dead-letter`.

## Plano de Ação (Consolidação e Próximos Passos)

- [x] **Task 1: Implementação do Consumer Base** - Criação de `services/redis_queue_tasks.py` com lógica de `blpop` e retry manual.
- [x] **Task 2: Configuração do Agendamento** - Integração no `celery_app.py` com intervalo de 10 segundos.
- [x] **Task 3: Atualização do Workflow n8n** - Simplificação do nó Redis para enviar JSON puro sem metadados Kombu.
- [ ] **Task 4: Implementação de Handlers Reais** - Desenvolver a lógica interna de `_process_bling_sale_created` e `_process_bling_sale_changed` (vinculação com DB).
- [ ] **Task 5: Padronização de Erros** - Criar um decorador ou utilitário para logging padronizado de falhas em webhooks.
- [ ] **Task 6: Dashboard de Monitoramento** - Script simples ou endpoint para visualizar o tamanho das filas (`LLEN`).

## Observações de Manutenção
- **Atenção:** O campo `id` no JSON enviado pelo n8n é obrigatório para o roteamento.
- **Segurança:** O worker Redis deve estar em rede interna ou protegido por senha, já que o payload agora é texto puro (sem criptografia de transporte nativa do Kombu).
- **Retry:** O sistema de retry manual (`attempt` counter) deve ser mantido sincronizado entre o n8n e o Python se for expandido.
