# Supabase Contracts

Last updated: 2026-06-16

Status: target-state

## Baseline

Operational project: `nistiprint-supabase` (`cfknrplrqvyirjxovuvi`)

## Contract groups

| Category | Objects |
| --- | --- |
| Integration identity | `integration_modules`, `installed_integrations` |
| ERP-marketplace routing | `erp_marketplace_links`, `channel_connections` |
| Canonical order model | `pedidos`, `itens_pedido`, `pedido_snapshots` |
| Mirror/audit | `pedidos_bling`, `pedidos_shopee`, `pedidos_mercadolivre`, `pedido_ingest_log`, `webhook_events` |
| Mercado Livre private-chat personalization | `mercadolivre_chat_inbox`, `mercadolivre_chat_conversations`, `mercadolivre_chat_messages`, `mercadolivre_personalization_config`, `mercadolivre_personalization_batches`, `mercadolivre_personalization_logs`, `mercadolivre_personalizations` |
| RPCs/views | `list_pedidos_filtrados` and supporting views/RPCs |

## Canonical ownership

### Integrations

- `integration_modules` defines connector type, auth flow, schemas and catalog
  metadata.
- `installed_integrations` defines one installed account or dummy origin.
- `installed_integrations` is the business identity of ERP and marketplace
  accounts.

### Routing

- `erp_marketplace_links` defines the explicit ERP to marketplace relationship.
- One row represents one routing line scoped by:
  - `erp_integration_id`
  - `marketplace_integration_id`
  - `erp_store_id`
- `channel_connections` may still exist for backward compatibility and helper
  resolution, but it does not replace the marketplace-first business contract.

### Orders

- `pedidos` is the operational order table.
- `pedido_snapshots` stores the canonical normalized order payload, including
  generic identity/logistics/customer/item data and provider-specific
  `platform_fields`.
- `pedidos_bling`, `pedidos_shopee` and `pedidos_mercadolivre` are mirrors for
  audit, raw source traceability and reprocessing support.

## Field-level expectations

### `installed_integrations`

Expected responsibilities:

- module identity: `module_id`, `platform_slug`
- runtime identity: `id`, `instance_name`
- lifecycle: `is_active`, `sync_status`, `last_sync`
- credentials: token fields, expiration, credential source/strategy
- config: provider config, ERP defaults, routing-related defaults

Rule:

- The table represents an installed instance, not only a bag of tokens.

### `erp_marketplace_links`

Expected fields or their semantic equivalents:

- `marketplace_integration_id`
- `erp_integration_id`
- `erp_store_id`
- `ingest_via`
- `supports_invoicing`
- `is_active`

Rules:

- Unique business scope is
  `erp_integration_id + marketplace_integration_id + erp_store_id`.
- It must be valid to have the same marketplace linked to different ERP
  accounts with different `erp_store_id` values.

### `pedidos`

Expected fields or semantic equivalents:

- `marketplace_integration_id`
- `bling_integration_id`
- `bling_loja_id`
- `codigo_pedido_externo`
- generic order/customer/logistics/financial fields

Rules:

- `codigo_pedido_externo` is the stable external order key used in deduplication
  together with canonical origin.
- `marketplace_integration_id` expresses the sales origin.
- `bling_integration_id` expresses the ERP context used or resolved for that
  order.

### `pedido_snapshots`

Expected structure:

- `identity`
  - marketplace order ID
  - marketplace integration ID
  - ERP integration ID when known
- `customer`
- `logistics`
- `items`
- `platform_fields`

Rule:

- `platform_fields` is the canonical place for marketplace-specific data that
  does not belong in the generic order contract.

## Mercado Livre personalization tables

- All operational rows are scoped to `marketplace_integration_id`; inbox
  notification identity additionally includes `application_id` and account
  `user_id`.
- `mercadolivre_chat_messages` uses opaque text `provider_message_id` as part
  of its account-scoped primary key. Attachments, moderation state, participants,
  timestamps, and provider JSON are retained.
- `mercadolivre_personalizations` links to canonical integer `pedidos.id` and
  `itens_pedido.id`. The context hash identifies the exact conversation version
  used by AI. Manual results carry `confirmed_by`/`confirmed_at`.
- The atomic RPC
  `persist_mercadolivre_personalization_results(integer,text,text,text,boolean,jsonb,jsonb,uuid)`
  verifies that each order/item belongs to the same Mercado Livre installation,
  then stores result rows, conversation state, and log in one transaction.
- New tables enable RLS and revoke direct access from `PUBLIC`, `anon`, and
  `authenticated`; backend service-role operations are the only data path.
- Shopee messages, batches, logs, configuration, and customizations stay in
  their existing tables and are not copied into these relations.

## Drift and transition

- Legacy local migration drift still needs reconciliation against the active
  Supabase migration history.
- Until the migration trail is fully reconciled, this document defines the
  intended database contract and should be used to evaluate future migrations.

## Validation rules

- No new migration may reintroduce provider-specific order tables as the primary
  operational source.
- No new routing logic may rely on `marketplace_integration_id` alone to choose
  NF ERP.
- Order origin filter support must remain compatible with
  `source:<marketplace_integration_id>`.
