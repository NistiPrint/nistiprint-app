# Domain Spec: Producao / Demandas

Last updated: 2026-05-28

Status: draft

## Objective

Turn orders and manual input into production demands that operators can plan,
prioritize, execute, monitor, and close with traceability.

## Actors

- Production operator
- Expedition operator
- Admin user
- Worker process
- Operations manager

## Entities

- `demandas_producao`
- `itens_demanda`
- `demandas_pedidos`
- `contextos_producao`
- `regras_priorizacao`
- `sinalizacoes_demanda`
- `templates_obs_canal`
- `entrega_producao`

## Main Flows

- Consolidate compatible orders into draft demands.
- Create manual demands.
- Publish draft demands.
- Prioritize production by logistics, deadlines, and manual priority.
- Track item progress for covers, inserts, finalization, and expedition.
- Show focus, dashboard, calendar, and expedition views.

## Business Rules

- The factory works on demands, not only individual orders.
- Demand traceability to orders is many-to-many through `demandas_pedidos`.
- Draft demands can receive additional compatible orders until published or
  expired.
- Priority combines urgency, logistics, deadline, manual boost, and customer
  classification.

## States

Expected demand states include `RASCUNHO`, `AGUARDANDO`, `EM_PRODUCAO`,
`COLETA_PARCIAL`, and `CONCLUIDO`. Exact allowed transitions need validation
against code and data.

## API And Database Contracts

- Frontend routes: `/producao`, `/producao/foco`, `/producao/resumo`,
  `/producao/demanda`, `/producao/demanda/rascunhos`,
  `/producao/demanda/nova`, `/producao/demanda/:id/editar`,
  `/producao/demanda/prioridade`, `/producao/demanda/calendario`,
  `/producao/demanda/:id/dashboard`, `/producao/miolos`, `/producao/capas`,
  `/producao/expedicao`, `/producao/impressao`.
- API routes: `/api/v2/demandas`, `/api/v2/demanda_producao`,
  `/api/v2/producao`, `/api/v2/producao-contexto`.

## Async Events And Workers

- Order consolidation can be triggered by order ingest.
- Production context and signaling may be generated or refreshed by services.
- Notifications may emit demand updates.

## Permissions

`gap`: Admin-only vs sector/operator permissions need a domain authorization
matrix. Existing docs mention sector-scoped behavior for inventory; demand
permissions need verification.

## Acceptance Criteria

- Orders linked to a demand remain traceable from both order and demand views.
- Draft publication closes the draft for normal grouping.
- Production priority order is explainable.
- Production progress cannot exceed planned quantities without explicit rule.
- Demand views agree on status and item progress.

## Known Gaps

- Exact demand transition table.
- Consolidation behavior after user edits.
- Which priority rules are configurable vs hardcoded.
- RLS/policy design for production operators.

