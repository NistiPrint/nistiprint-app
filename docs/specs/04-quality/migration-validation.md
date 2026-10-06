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

## Mercado Livre personalization migration

Target migration: `20261006100000_mercadolivre_personalization_isolated.sql`.

The migration is additive. It creates seven account-scoped relations, enables
RLS without client-role policies, grants service-role access, and adds one
service-role-only transactional RPC. It does not replace Shopee tables, views,
functions, or schedules.

Before activation in the production Supabase project:

1. Confirm the migration is absent/present in `schema_migrations` as expected and
   apply it once through the approved migration pipeline.
2. Check all seven tables, their account foreign keys, unique/index contracts,
   and RLS flags. Verify the RPC has signature
   `persist_mercadolivre_personalization_results(integer,text,text,text,boolean,jsonb,jsonb,uuid)`.
3. Verify `anon` and `authenticated` cannot select or execute the new tables/RPC;
   verify `service_role` can call the RPC and that a cross-account order/item
   input is rejected transactionally.
4. Run the domain integration smoke test with a real connected account, first
   with extraction disabled. Compare Shopee table contents and print results
   before/after to establish the regression baseline.
5. Record the Supabase migration version, SQL advisor results, test run, and
   pilot conversation before enabling daily extraction.

Current validation state: migration and repository checks are prepared locally;
the production database migration has not been applied or verified.

