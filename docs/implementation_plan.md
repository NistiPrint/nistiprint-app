# Consolidação e Gerenciamento de Fila de Webhooks (Bling)

## Contexto e Objetivo Estratégico
Limpar a base de código de arquivos redundantes e consolidar a recepção/monitoramento de webhooks do Bling. O objetivo é utilizar o Redis como fila principal e o worker para consumo simplificado, expondo uma interface de gerenciamento para o admin.

## Arquitetura e Entidades
- **Redis (Fila):** Chaves `bling:webhooks:pendentes`, `bling:webhooks:processados` e `bling:webhooks:falhas`.
- **API (Consolidação):** Centralizar tudo em `apps/api/routes/webhooks_v2.py`.
- **Frontend (Reuso):** Atualizar `apps/frontend/src/components/admin/QueueMonitor.jsx`.
- **Worker:** Utilizar `packages/shared/nistiprint_shared/services/redis_queue_tasks.py`.

## Plano de Ação

### Fase 1: Limpeza Técnica (Cleanup)
- [ ] **Task 1: Remover Arquivos Obsoletos** - Deletar:
    - `apps/api/routes/webhooks.py` (Substituído por v2)
    - `packages/shared/nistiprint_shared/services/webhook_tasks.py`
    - `packages/shared/nistiprint_shared/services/webhook_worker.py`
    - `apps/frontend/src/components/marketplace/WebhookMonitor.jsx` (Redundante)

### Fase 2: Backend (API & Redis)
- [ ] **Task 2: Consolidar Webhooks V2** - Mover endpoints de fila de `webhooks.py` para `webhooks_v2.py`:
    - `GET /api/v2/webhooks/queue/stats`
    - `GET /api/v2/webhooks/queue/items` (Novo: usa `LRANGE` para ver o conteúdo)
    - `POST /api/v2/webhooks/queue/reprocess`
    - `DELETE /api/v2/webhooks/queue/clear` (Novo: limpa as listas)
- [ ] **Task 3: Update Redis Tasks** - Adicionar métodos auxiliares em `redis_queue_tasks.py` para as operações acima.

### Fase 3: Frontend (Monitor)
- [ ] **Task 4: Atualizar QueueMonitor.jsx** - Adaptar o componente existente para:
    - Exibir a tabela com o conteúdo das mensagens (JSON formatado).
    - Adicionar botão para limpar filas.
    - Integrar com os novos endpoints da V2.
- [ ] **Task 5: Roteamento** - Garantir que a tela esteja acessível em "Ferramentas > Monitor de Fila".

### Fase 4: Worker (Consumo)
- [ ] **Task 6: Worker Simulado** - Garantir que o worker em `redis_queue_tasks.py` apenas registre o log e mova para `bling:webhooks:processados` (ou apenas dê LPOP se for apenas teste).

## Observações de Manutenção
- Manter o `rawBody: true` no n8n para validação de assinatura futura.
- Certificar-se que a API v2 use a rede `nistiprint-shared` para acessar o host `redis`.
