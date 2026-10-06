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
| Mercado Livre personalization | `/api/v2/mercadolivre/integracoes` |

### Mercado Livre private post-sale personalization

Every account-scoped route carries `integration_id`; all database reads and
mutations filter by it. Order, personalization, and batch IDs are revalidated
against that account. Reads require login; configuration updates require admin.

| Method | Route | Behavior |
| --- | --- | --- |
| `GET` | `/api/v2/mercadolivre/integracoes/personalizacoes` | List connected accounts and per-account enablement. |
| `GET` | `/api/v2/mercadolivre/integracoes/{integration_id}/personalizados/pedidos` | List personalized in-progress/ready orders and current-context results. |
| `GET` | `.../pedidos/{pedido_id}/chat` | Read that account's conversation and messages. |
| `GET` | `.../conversas-pendentes` | List stored conversations awaiting order import. |
| `GET` | `.../webhooks-pendentes` | Audit message notifications whose account/application identity did not match. |
| `GET` | `/api/v2/mercadolivre/personalizacoes/webhooks-sem-vinculo` | Admin-only audit list for unmatched notifications without a unique account. |
| `GET` | `.../pedidos/{pedido_id}/logs` | Read account/order execution and manual-review history. |
| `GET`, `PUT` | `.../config` | Read or admin-update account-specific capture, provider, model, prompt, and schedule. |
| `POST` | `.../extrair` | Create an account-scoped extraction/reprocessing batch and enqueue it. |
| `GET` | `.../lotes/{batch_id}` | Read progress after verifying batch ownership. |
| `POST` | `.../pedidos/{pedido_id}/personalizacoes` | Add and confirm an operator-entered name/initial for an internal item. |
| `POST` | `.../personalizacoes/{id}/confirmar` | Correct/confirm a result and record operator history. |

The print API adds a Mercado Livre branch keyed by canonical order integration
and internal item ID. It never reads Mercado Livre results from Shopee's
`personalizacoes_pedido` table. Shopee keeps its existing print reader.

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
- Bling credentials are app-managed and may be republished to Firebase only for
  compatibility consumers.

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
