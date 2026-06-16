# API Contracts

Last updated: 2026-06-16

Status: target-state

## Scope

This document captures the public contracts that matter for integrations,
orders origin resolution and ERP routing. Route names may still evolve, but the
behavior documented here is the expected contract for frontend and worker code.

## Main API areas

| Area | Prefixes |
| --- | --- |
| Orders | `/api/v2/pedidos`, `/api/v2/orders`, `/api/v2/order` |
| Integrations | `/api/v2/marketplace`, `/api/v2/integracoes`, `/api/v2/erp-links`, `/api/v2/integracao-canais` |
| Webhooks | `/api/v2/webhooks` |

## Integration contracts

### Installed integrations

- List installed integrations returns installed instances, not bare modules.
- Response items should expose enough information for UI status:
  - `id`
  - `module_id`
  - `platform_slug`
  - `instance_name`
  - `is_active`
  - `sync_status`
  - `credential_status`
  - `functional_scopes`
  - `config`
  - `credentials` when the caller is allowed to inspect them

### Install/test/refresh

- Marketplace install routes must support:
  - direct marketplace modules with auth flow
  - dummy marketplace modules with no auth flow
- Test endpoints must execute the platform driver strategy first when the module
  has a driver.
- Refresh endpoints must only be shown and enabled when the credential strategy
  supports local refresh.
- Bling must be documented as externally synchronized for credentials.

### ERP to marketplace links

The link payload contract must use these fields:

| Field | Meaning |
| --- | --- |
| `marketplace_integration_id` | Installed marketplace instance that owns the sale |
| `erp_integration_id` | Installed ERP instance, currently Bling |
| `erp_store_id` | `shop.id` / store identifier inside the ERP account |
| `ingest_via` | `erp` or `marketplace` |
| `supports_invoicing` | Whether this ERP can emit NF for that marketplace link |

Rules:

- `marketplace_integration_id + erp_integration_id + erp_store_id` identifies a
  routing line.
- Multiple routing lines may exist for the same marketplace.
- A marketplace configuration is the authority for creating/editing the link.
- The ERP screen may expose the links as read-only operational visibility.

## Orders contracts

### `GET /api/v2/pedidos/origens`

This endpoint exists to populate the `origem da venda` filter.

Behavior:

- Returns only installed marketplace instances that are active sales origins.
- Does not return ERP instances.
- Does not return technical import routes.
- Does not return legacy channel labels as canonical origin keys.

Response contract per item:

| Field | Meaning |
| --- | --- |
| `key` | Canonical key in the form `source:<marketplace_integration_id>` |
| `nome` | Installed marketplace instance name |
| `tipo` | Always `marketplace` for this endpoint |
| `marketplace_integration_id` | Installed marketplace ID |
| `slug` | Module slug |
| `color` | Optional UI color |
| `total` | Optional order count |

### Order list and detail

- Order list and detail responses must preserve:
  - `marketplace_integration_id`
  - `bling_integration_id`
  - `bling_loja_id`
  - `codigo_pedido_externo`
  - marketplace presentation metadata when available
- `origem_pedido_key` should resolve from `marketplace_integration_id` in the
  form `source:<id>` whenever the sales origin is known.

## Error semantics

- NF routing ambiguity must be explicit and actionable.
- Test/refresh endpoints must expose whether failure was caused by:
  - missing credentials
  - expired credentials
  - unsupported strategy
  - ambiguous routing
  - upstream API failure

## Open transition notes

- Some duplicate order prefixes still exist for legacy compatibility.
- No generated OpenAPI contract is currently maintained in the repository.
