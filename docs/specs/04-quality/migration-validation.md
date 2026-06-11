# Migration Validation

Last updated: 2026-05-28

Status: draft

## Current Drift Record

`drift`: Active Supabase migration history currently ends at
`20260521101740 optimize_order_filters_rpc`, while local repository contains
newer migration `20260522000000_canonical_order_source_and_fulfillment_contract.sql`.

This means code/specs must not assume the May 22 contract is deployed until it
is confirmed in the target Supabase project.

## Required Validation For Every Migration

- Confirm migration is present locally and in intended environment.
- Confirm schema objects exist with expected columns/indexes/functions.
- Run domain-specific smoke query or API call.
- Run Supabase security/performance advisors when the migration touches schema,
  functions, views, RLS, or indexes.
- Record any advisor finding as fixed, accepted risk, or follow-up.

## Suggested Checks

```sql
-- Migration drift: compare Supabase migration history with local files.
select version, name
from supabase_migrations.schema_migrations
order by version desc
limit 20;

-- RPC signature check example.
select oid::regprocedure
from pg_proc
where proname = 'list_pedidos_filtrados';
```

## Release Gate

No production deployment should depend on a local-only migration unless the PR
explicitly includes migration application steps and validation evidence.

