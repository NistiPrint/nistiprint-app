# Migration Validation

Last updated: 2026-10-10

Status: active; the historical May 2026 drift note below is superseded by the current record.

## Current Migration Tracking (2026-10-10)

The Supabase project has 49 tracked remote migrations and the repository has
289 local SQL files. Name matching found 47 local files with a remote
counterpart; 24 of those have a different version prefix because the MCP
`apply_migration` endpoint assigned its own timestamp. Two remote migration
names have no same-named local file, and 242 local filenames have no same-named
remote record. This reflects historical baseline drift; absence from the remote
ledger does **not** establish that a migration's effects are absent from the
schema.

Until the historical baseline is reconciled against the live catalog, do not
run `supabase db push` or apply old files based only on their local prefix. For
the active project, apply reviewed DDL through the Supabase MCP HTTP
`apply_migration` tool, then record the server-assigned remote version, inspect
the catalog, exercise the RPC in a rollback transaction where appropriate,
and run advisors. The cross-reference and evidence for the current plan are in
[the integrity execution report](../../operacoes/integridade-estoque-diagnostico-20261009.md).

## Historical Drift Note (May 2026)

At the time this note was written, active Supabase migration history ended at
`20260521101740 optimize_order_filters_rpc`, while local repository contains
newer migration `20260522000000_canonical_order_source_and_fulfillment_contract.sql`.

This note is historical and does not describe the current project. See
**Current Migration Tracking (2026-10-10)** above and the integrity execution
report for the live ledger and schema verification.

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

## Legacy Mercado Livre personalization migration checklist

This checklist refers to a 2026-10-06 proposal and is retained as historical
context. It is not a statement that this migration is pending or ready to
activate. Use the current ledger and the integrity execution report before
changing the live project.

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

