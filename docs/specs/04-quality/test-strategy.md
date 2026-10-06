# Test Strategy

Last updated: 2026-05-28

Status: draft

## Goals

- Protect high-risk order ingest, production, stock, and integration flows.
- Make specs executable through acceptance criteria and targeted tests.
- Catch migration drift before runtime failures.

## Test Layers

| Layer | Purpose |
| --- | --- |
| Unit tests | Business service rules, mappers, classifiers, pure helpers. |
| Integration tests | Supabase RPCs, service/database interactions, API endpoints. |
| Worker tests | Queue payload handling, idempotency, retry behavior. |
| Frontend tests | Critical route/page workflows and display contracts. |
| Migration validation | Schema existence, RPC signatures, backfill checks, advisors. |
| Manual acceptance | End-to-end operational scenarios with real-like data. |

## Priority Scenarios

1. Order ingest idempotency across Bling and marketplace payloads.
2. `list_pedidos_filtrados` filters and pagination.
3. Demand consolidation and order traceability.
4. Stock reconciliation idempotency and no double consumption.
5. Integration routing and token renewal failure visibility.
6. Admin permission enforcement.
7. Mercado Livre private-chat isolation from Shopee and between connected
   accounts; provider-message deduplication, unread recovery, and context-bound
   print confirmation.

## Mercado Livre personalization checks

- Unit: route classification for nested/direct Mercado Livre `messages` events;
  opaque message IDs; sender role resolution using the order buyer ID; context
  digest changes; exact account/order/item print filtering.
- Integration: notification persistence precedes event finalization; duplicate
  and out-of-order events; multi-page `post_sale` fetch with
  `mark_as_read=false`; order-not-imported pending state; RPC rollback on
  cross-account or invalid item writes.
- Two accounts: same buyer and external order identifiers in A/B; verify that
  messages, access tokens, prompt/schedule settings, task queues, batches, logs,
  and print rows remain account-scoped.
- Resilience: expired tokens, rate limit and retry, process termination with
  expired inbox/batch lease, and concurrent manual/scheduled batches.
- Regression: run reliable-ingest and Shopee chat tests, existing AI
  personalization tests, and printing tests; compare Shopee output snapshots.
- Manual pilot: validate read/unread conversations, agent-intermediated sender,
  moderation, attachments, and delayed order import before enabling daily AI.

## Gaps

- Frontend automated coverage is not inventoried.
- API endpoint tests need route-by-route mapping.
- Supabase local vs remote validation needs a documented workflow.

