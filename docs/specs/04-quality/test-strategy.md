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

## Gaps

- Frontend automated coverage is not inventoried.
- API endpoint tests need route-by-route mapping.
- Supabase local vs remote validation needs a documented workflow.

