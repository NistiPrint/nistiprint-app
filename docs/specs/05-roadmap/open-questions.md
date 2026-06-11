# Open Questions

Last updated: 2026-05-28

## Product And Domain

- Is `marketplace_integration_id` now the canonical order source for all
  marketplace filtering?
- When should `canal_venda_id` remain visible to users?
- What demand states and transitions are officially allowed?
- Which users can reprocess orders or override demand fields?

## Engineering

- Should API contracts be generated from Flask routes or curated manually?
- Which worker queues are canonical and which are legacy?
- What is the retention policy for `pedido_ingest_log`, `webhook_events`, and
  `task_execution_logs`?
- Should `kb/` be treated as frozen legacy reference or still active code?

## Supabase

- Has `20260522000000_canonical_order_source_and_fulfillment_contract.sql`
  been intentionally held back from production?
- Which tables should be reachable through PostgREST by frontend clients?
- What RLS strategy should replace permissive authenticated write policies?
- Should `public.public_merchant_store` remain `SECURITY DEFINER` and public?

