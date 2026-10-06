# Worker Contracts

Last updated: 2026-05-28

Status: draft

## Current Worker Shape

Workers are Celery/Redis based. The dependency entrypoint is under
`apps/worker`, while much task logic is in `packages/shared/nistiprint_shared`.

## Known Responsibilities

- Bling webhook queue consumption.
- Periodic order sync/fetch.
- Marketplace enrichment.
- Token renewal.
- Stock reconciliation tasks.
- Batch consolidation or reprocessing tasks.
- Task execution logging.
- Isolated private-chat and AI personalization processes for each Mercado Livre
  installation.

## Mercado Livre personalization process contract

- Entrypoint: `nistiprint_shared.services.mercadolivre_personalization_worker`.
- `accounts` discovers active Mercado Livre installations and starts separate
  `messages`, Celery `worker`, and Celery `beat` child processes for each.
- Each child requires one explicit positive `integration_id`; the account is
  validated against `installed_integrations.module_id=mercadolivre` before data access.
- Queue/task names include the account ID. Each account worker runs with
  concurrency one; the Redis supervisor lease prevents duplicate managers.
- Notifications are persisted to the Mercado Livre inbox before reliable-ingest
  events are finalized. Claims use status compare-and-set and expiring leases.
- The worker reconciles unread conversations and stored chats every 120 seconds,
  without marking messages read. Batch recovery runs every 300 seconds and uses
  a renewable lease to resume interrupted work.
- Daily scheduling uses `America/Sao_Paulo`, default 09:00; each account's
  database-configured time is read by its own minute tick and only one run/date
  is recorded.
- Environment credentials for AI are Meli-specific and have no Shopee fallback.
- Operators can enqueue only after the account's independent extraction flags
  are enabled. Account creation starts capture/extraction disabled.

## Contract Rules

- Every queue payload should have a documented schema.
- Every task should declare idempotency key and retry behavior.
- Every task should write enough logs for replay/debug without leaking secrets.
- Long-running or batch jobs should expose progress through
  `task_execution_logs` or equivalent.

## Gaps

- Queue names and payload schemas need extraction.
- Retry/dead-letter behavior needs formal documentation.
- Ownership of reprocess flows between API and worker needs clarification.

