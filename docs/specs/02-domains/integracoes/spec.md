# Domain Spec: Integracoes / Marketplace / Bling

Last updated: 2026-05-28

Status: draft

## Objective

Manage integrations with ERP and marketplaces, resolve order origins, maintain
tokens, and provide a clear connector model for new platforms.

## Actors

- Admin user
- Worker process
- External APIs: Bling, Shopee, MercadoLivre, Amazon, Shein, TikTok, others
- Operations user consuming integration status

## Entities

- `integration_modules`
- `installed_integrations`
- `channel_connections`
- `erp_marketplace_links`
- `integracao_canais_config`
- `integration_refresh_logs`
- `integration_status_mappings`
- `flex_classification_rules`
- `fulfillment_classification_rules`
- `regras_logisticas_integracao`

## Main Flows

- Browse available integration modules.
- Install/configure integration instances.
- Link ERP instance to marketplace instance.
- Link channels to integrations and Bling stores.
- Refresh tokens and log status.
- Resolve platform-specific statuses into internal statuses.
- Classify Flex and fulfillment.

## Business Rules

- Bling is currently a primary source for many orders.
- Marketplace enrichments provide source/platform-specific data.
- `channel_connections` is replacing older integration/channel config as the
  explicit routing model.
- Multi-Bling and multi-marketplace identity must be scoped by integration
  instance, not only display identifiers.

## States

- Installed integrations have sync status and activity flags.
- Token status is derived from token fields, expiration, refresh logs, and
  worker outcomes.

## API And Database Contracts

- Frontend routes: `/configuracoes/integracoes`,
  `/configuracoes/integracoes/install/:moduleId`, `/configuracoes/roteamento`,
  `/configuracoes/bling`.
- API routes: `/api/v2/marketplace`, `/api/v2/integracoes`,
  `/api/v2/integracao-canais`, `/api/v2/erp-links`.

## Async Events And Workers

- Token renewal.
- Periodic sync.
- Marketplace enrichment.
- Status synchronization.
- Webhook event reprocessing.

## Permissions

Integration setup is admin-only in frontend routing. RLS/API enforcement needs
formal verification.

## Acceptance Criteria

- Each order source can be traced to ERP and marketplace integration instances.
- Token refresh failure is visible in operational logs.
- Installing a module captures required config and auth flow.
- Routing changes are auditable and do not break existing order lookup.

## Known Gaps

- Final deprecation plan for `integracao_canais_config`.
- Per-provider auth schemas.
- Canonical source key contract after May 22 local migration.

