# Decision Record: Integracoes instaladas e pedidos canonicos

Date: 2026-06-16

Status: accepted

## Decision

The platform adopts these architectural decisions as the source of truth:

1. `installed_integrations` is the central business unit for ERP and
   marketplace accounts.
2. The operational order model is canonical-first:
   `pedidos` plus normalized snapshots are primary; provider-specific tables are
   mirrors and audit support.
3. ERP to marketplace routing is explicit and scoped by
   `erp_integration_id + marketplace_integration_id + erp_store_id`.
4. When a direct marketplace webhook arrives and the marketplace is linked to
   multiple Bling accounts, the default ERP for NF comes from the marketplace
   instance configuration chosen by the user.

## Rationale

- The platform is an orchestrator, not only a Bling mirror.
- Marketplace direct ingest and ERP-backed NF must coexist without ambiguity.
- A single marketplace account may legitimately operate across multiple Bling
  accounts.
- Provider-specific order tables do not scale as the primary model.

## Consequences

- Sales origin must be represented by installed marketplace instances.
- `origem da venda` filters must list marketplaces only.
- NF cannot resolve from `marketplace_integration_id` alone.
- Direct drivers must centralize provider-specific enrichment and test logic.
