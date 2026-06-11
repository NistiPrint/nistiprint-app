# Supabase Contracts

Last updated: 2026-05-28

Status: draft

## Baseline

Operational project: `nistiprint-supabase` (`cfknrplrqvyirjxovuvi`)

- Region: `sa-east-1`
- Database: Postgres `17.6.1.063`
- Local config: `supabase/config.toml`, Postgres major version `17`

## Contract Categories

| Category | Objects |
| --- | --- |
| Operational tables | `pedidos`, `demandas_producao`, `produtos`, `estoque_atual`, `installed_integrations` |
| Mirror/audit tables | `pedidos_bling`, `pedidos_shopee`, `pedidos_mercadolivre`, `pedido_ingest_log`, `webhook_events` |
| Contract RPCs | `list_pedidos_filtrados`, stock reconciliation RPCs, integration lookup RPCs |
| Views | personalized sales views, movement views, routing/audit views |
| Security | RLS policies, function grants, exposed schemas |

## Current Drift

`drift`: Active Supabase latest listed migration is
`20260521101740 optimize_order_filters_rpc`; repository has
`20260522000000_canonical_order_source_and_fulfillment_contract.sql`.

## Required Rules

- Every DB-facing spec must name canonical table/RPC/view ownership.
- Every migration must document:
  - why it exists;
  - target environment;
  - rollback or mitigation;
  - validation query;
  - advisor review outcome when relevant.
- RLS changes must be reviewed against `01-system/security-and-rls.md`.

## Gaps

- Full table-column contract is not yet generated.
- Function grant inventory is not complete.
- Data API exposure settings are not documented in repo.

