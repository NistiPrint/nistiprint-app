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

