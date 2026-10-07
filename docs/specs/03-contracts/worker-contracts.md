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
- Mercado Livre private-chat ingestion, reconciliation, and AI personalization
  as independent functions on the shared Celery worker.

## Mercado Livre personalization task contract

- Entrypoint: `nistiprint_shared.services.mercadolivre_personalization_worker`.
- The shared reliable-ingest `chat` consumer writes provider notifications to
  `mercadolivre_chat_inbox` and dispatches `mercadolivre.chat.process_inbox`.
  Scheduled processing recovers inbox rows if immediate dispatch is delayed.
- `mercadolivre.chat.process_inbox`, `mercadolivre.chat.reconcile`, and
  `mercadolivre.chat.replay_retained_events` are ingestion functions. They run
  on the shared `celery` queue and never invoke AI.
- `mercadolivre.personalization.process_batch`, `run_due`, and recovery tasks
  are a separate AI stage. They receive a positive `integration_id`; the account
  is validated against `installed_integrations.module_id=mercadolivre` before
  data access. Credentials and provider rate limits remain account-scoped.
- The Beat dispatches account schedules every minute using
  `America/Sao_Paulo`, default 09:00. A Redis lock keyed by integration/date
  prevents duplicate daily runs. Batch recovery runs every 300 seconds.
- Inbox claims use status compare-and-set and expiring leases. Batch claims and
  leases remain account-scoped so retries resume without crossing accounts.
- No account-specific Celery app, queue, worker, Beat, supervisor, or Compose
  service is required.
- Environment credentials for AI are Meli-specific and have no Shopee fallback.
- The existing Shopee `chat` and `chatsync` consumers and message persistence
  are unchanged.

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

