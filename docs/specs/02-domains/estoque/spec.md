# Domain Spec: Estoque

Last updated: 2026-05-28

Status: draft

## Objective

Maintain accurate inventory availability, reservations, movements, and
production reconciliation with auditability.

## Actors

- Stock operator
- Production operator
- Admin user
- Worker/process service

## Entities

- `produtos`
- `ficha_tecnica`
- `estoque_atual`
- `movimentacoes_estoque`
- `estoque_consolidado`
- `eventos_producao_v2`
- `snapshots_reconciliacao`
- `demanda_alocacoes_estoque`

## Main Flows

- View current stock position.
- Register stock movement.
- Reserve stock for production.
- Reconcile production events with inventory consumption.
- Audit stock history and consolidated movements.
- Run batch movement actions.

## Business Rules

- Product variations must follow parent/type invariants.
- BOM drives component requirements.
- Available quantity is current balance minus reserved quantity.
- Production signals and final reconciliation must be distinguishable.
- Stock reconciliation must be idempotent for a production event/correlation.

## States

- Movement stages and event stages are defined by stock engine v2 migrations.
- Demand/item production states interact with reconciliation.

## API And Database Contracts

- Frontend routes: `/estoque/dashboard`, `/estoque/historico`,
  `/estoque/movimentar`, `/estoque/posicao`, `/estoque/reservas`,
  `/estoque/ajuste`, `/estoque/relatorios`, `/estoque/movimentacao-lote`.
- API routes: `/api/v2/estoque`, `/api/v2/auditoria`.
- RPCs include stock reconciliation functions such as
  `reconciliar_item_estoque` and `reconciliar_estoque_v2`.

## Async Events And Workers

- Reconciliation may be synchronous from production actions or worker-backed
  depending on caller.
- Audit and snapshots are required for debug.

## Permissions

Existing business docs describe admin access and sector-scoped user access.
`gap`: verify code/RLS implementation and encode it as a formal matrix.

## Acceptance Criteria

- Movement history is append-only enough for audit.
- Reconciliation is idempotent by correlation/event.
- Stock cannot silently double-consume for the same production item.
- Batch movement validates every item before committing changes.
- Inventory dashboards match underlying movement/consolidated records.

## Known Gaps

- Formal source of truth between `estoque_atual` and `estoque_consolidado`.
- Complete transition model for `eventos_producao_v2`.
- RLS policies for stock operators.

