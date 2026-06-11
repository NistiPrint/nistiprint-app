# Domain Spec: Pedidos / Vendas

Last updated: 2026-05-28

Status: draft

## Objective

Provide a reliable order lifecycle from external ingest to normalized order
records, list/detail screens, reprocessing, printing, and production demand
linkage.

## Actors

- Operations user
- Admin user
- Worker process
- External platforms: Bling, Shopee, MercadoLivre
- Supabase service-role backend

## Entities

- `pedidos`
- `pedidos_bling`
- `pedidos_shopee`
- `pedidos_mercadolivre`
- `itens_pedido`
- `demandas_pedidos`
- `pedido_ingest_log`
- `webhook_events`
- `fulfillment_classification_rules`
- `flex_classification_rules`

## Main Flows

- Receive webhook or scheduled fetch.
- Resolve Bling integration and marketplace origin.
- Store raw/mirror platform payloads.
- Upsert normalized `pedidos` and `itens_pedido`.
- Classify Flex, fulfillment, personalized, and status.
- List and filter orders in frontend.
- Show order detail and related production demands.
- Reprocess failed or stale orders.
- Send order or product artifacts to print.

## Business Rules

- `pedidos.id` is the internal operational order ID.
- Bling `numero` is display-only and must not be treated as globally unique.
- Bling `numeroLoja` is marketplace order ID when present.
- Bling `loja.id`/`bling_loja_id` is an origin resolution pivot.
- `codigo_pedido_externo` should be the stable external order key.
- Marketplace source filtering is moving toward `source:<marketplace_integration_id>`.

## States

- Payment/status states come from `situacoes_pedido` and platform mappings.
- Processing states are reflected in `pedido_ingest_log`, `webhook_events`,
  task logs, and reprocess endpoints.

## API And Database Contracts

- Frontend routes: `/vendas/pedidos`, `/vendas/pedidos/:id`, `/pedidos`,
  `/pedidos/:id`.
- API routes: `/api/v2/pedidos`, `/api/v2/pedidos/<id>`,
  `/api/v2/pedidos/<id>/logs`, `/api/v2/pedidos/<id>/reprocessar`,
  `/api/v2/pedidos/<id>/status`, `/api/v2/pedidos/<id>/imprimir`.
- RPC: `list_pedidos_filtrados` is a core listing/filtering contract.
- `drift`: local migration `20260522000000_canonical_order_source_and_fulfillment_contract.sql`
  changes the RPC and origin contract but is not listed in active Supabase
  migration history.

## Async Events And Workers

- Bling webhooks and Redis queue processing.
- Periodic sync/fetch jobs.
- Marketplace enrichment and token renewal.
- Reprocessing uses stored events and ingest logs.

## Permissions

`gap`: Current RLS and API authorization must be specified. Until then, assume
API/service-role access is authoritative and frontend direct table access must
be reviewed.

## Acceptance Criteria

- New webhook creates or updates one normalized `pedidos` row idempotently.
- Platform mirror rows are preserved for audit/reprocess.
- Order list filters by status, origin, Flex, personalized, fulfillment,
  delivery date, order date, search, and demand presence.
- Detail view shows customer, totals, dates, logistics, marketplace, items,
  logs, and demand links.
- Reprocessing does not duplicate orders or items.

## Known Gaps

- Canonical source ownership between `canal_venda_id` and
  `marketplace_integration_id`.
- Complete status mapping spec per integration.
- Exact retry/dead-letter behavior.
- Authorization for reprocess and status update actions.

