# Domain Spec: Pedidos

Last updated: 2026-06-16

Status: target-state

## Objective

Definir o pedido canonico da plataforma, sua deduplicacao, a relacao entre
ingest tecnico e origem da venda, e o uso de tabelas espelho para auditoria e
reprocessamento.

## Entities

- `pedidos`
- `itens_pedido`
- `pedido_snapshots`
- `pedido_ingest_log`
- `webhook_events`
- `pedidos_bling`
- `pedidos_shopee`
- `pedidos_mercadolivre`

## Canonical model

- `pedidos` is the operational order record used by list, detail, NF routing,
  production and most business decisions.
- `pedido_snapshots` is the canonical normalized payload snapshot associated
  with the order.
- `pedidos_bling`, `pedidos_shopee` and `pedidos_mercadolivre` are mirror and
  audit tables. They are not the primary business model.

## Canonical fields and ownership

| Concern | Canonical owner |
| --- | --- |
| Internal order identity | `pedidos.id` |
| Sales origin | `pedidos.marketplace_integration_id` |
| ERP context | `pedidos.bling_integration_id` |
| ERP store / Bling store | `pedidos.bling_loja_id` or snapshot identity/logistics mirror |
| Stable external order key | `pedidos.codigo_pedido_externo` |
| Marketplace-specific data | `pedido_snapshots.platform_fields` |
| Audit of source events | `pedido_ingest_log` and mirror tables |

## Deduplication rules

- Deduplication must use canonical sales origin plus the external order ID.
- When the order came through Bling, `numeroLoja` is the external order ID
  unless a more explicit marketplace order ID is already known.
- When the order came through direct Shopee or Mercado Livre webhook, the
  marketplace native order ID is the preferred external key.
- Reprocessing must update the canonical order instead of creating a duplicate
  mirror row and a second operational order.

## Sales origin versus ingest origin

- Sales origin answers `who sold the order`.
- Ingest origin answers `who delivered the event to the platform`.
- The orders filter `origem da venda` must use sales origin only and list
  installed marketplace instances.
- Technical flows such as Bling webhook, Shopee webhook, Mercado Livre webhook
  or spreadsheet import do not change the commercial origin of the order.

## Precedence and enrichment

- Shopee and Mercado Livre direct webhook ingest take precedence when enabled
  for that installed marketplace instance.
- Bling remains fallback ingest for marketplaces without direct integration and
  for dummy modules.
- Bling webhook ingest may still enrich the canonical order through the
  marketplace driver when the source account is direct-capable.
- Field-level conflict resolution remains transitional, but the documentation
  target is:
  - identity and ERP routing fields stay stable once resolved
  - marketplace-specific fields prefer direct marketplace data when available
  - Bling retains importance for ERP-specific fields such as NF context

## Platform fields

`pedido_snapshots.platform_fields` is the standard place for provider-specific
attributes that do not belong in the generic order contract.

Examples:

- Shopee:
  - `buyer_username`
  - `buyer_user_id`
  - platform logistics metadata
  - Flex-related data used by the existing classification rule
- Mercado Livre:
  - buyer and shipping details specific to ML
  - platform status details that do not map directly to generic fields
- Bling:
  - ERP-specific identifiers and NF references

## Acceptance criteria

- No canonical doc treats `pedidos_shopee` or `pedidos_mercadolivre` as the
  main source of truth.
- A direct marketplace order can still resolve one valid Bling account for NF.
- Order list filtering by origin uses installed marketplace instances only.
- The role of `numeroLoja`, `marketplace_integration_id`,
  `bling_integration_id` and `bling_loja_id` is explicit and non-conflicting.

## Open transition notes

- Some legacy RPCs and routes still bridge `canal_venda_id` and
  `marketplace_integration_id`.
- The target contract is marketplace-first; legacy channel semantics remain only
  for compatibility where not yet removed.
