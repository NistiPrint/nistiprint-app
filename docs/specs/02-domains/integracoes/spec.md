# Domain Spec: Integracoes

Last updated: 2026-06-16

Status: target-state

## Objective

Definir como a plataforma instala conectores, representa contas externas,
resolve origem da venda, escolhe o ERP responsavel por NF e expõe capacidades
operacionais por instancia instalada.

## Core concepts

| Term | Meaning |
| --- | --- |
| Integration module | Catalog entry in `integration_modules`; describes a connector type such as Bling, Shopee, Mercado Livre, Shein or TikTok Shop. |
| Installed integration | Runtime instance in `installed_integrations`; represents one external account or one dummy sales origin installed by the user. |
| Direct marketplace integration | Installed marketplace instance with its own driver, webhook and credential strategy. |
| Dummy marketplace integration | Installed marketplace instance without direct API driver; it exists to represent a sales origin and can still be linked to an ERP. |
| ERP integration | Installed ERP instance, currently Bling, used for ERP functions such as invoicing and legacy/fallback ingest. |
| Sales origin | Marketplace instance that owns the commercial sale. It is what the orders list must show in the `origem da venda` filter. |
| Ingest origin | Technical channel that delivered the order event, such as direct marketplace webhook or Bling webhook/fetch. |
| ERP store ID | `shop.id` / `erp_store_id` that identifies a marketplace account inside a specific Bling account. |
| Company ID | Bling `companyId` used to identify which ERP account emitted a webhook or owns a store mapping. |

## Entities

- `integration_modules`
- `installed_integrations`
- `erp_marketplace_links`
- `channel_connections`
- `integration_refresh_logs`
- `pedido_ingest_log`

Legacy helpers such as `integracao_canais_config` remain transitional and do not
replace the contracts above.

## Canonical rules

### Installed integration is the central unit

- Every ERP or marketplace account is represented by one row in
  `installed_integrations`.
- A dummy marketplace is also an installed integration, even without its own
  credentials.
- `installed_integrations` stores identity, runtime config, credential strategy,
  sync state and functional scopes for that installed account.

### ERP and marketplace links have two different meanings

- Entry of the sale, `ERP -> Marketplace`:
  Bling identifies the marketplace account through `companyId` plus `shop.id`
  received in webhook/fetch flows.
- Fulfillment of the sale, `Marketplace -> ERP`:
  the marketplace instance points to the Bling account used for NF and other ERP
  actions.
- These relationships are related but not interchangeable.

### Marketplace to ERP is N:N

- One marketplace account may be linked to multiple Bling accounts.
- One Bling account may be linked to multiple marketplace accounts.
- The operational key is
  `erp_integration_id + marketplace_integration_id + erp_store_id`.
- No resolver may choose ERP only from `marketplace_integration_id`.

### Resolution for invoicing

- First choice: `pedido.bling_integration_id`, when already materialized.
- Second choice: explicit link using
  `marketplace_integration_id + erp_store_id/shop.id`.
- For direct marketplace webhook with multiple linked Blings, the default NF ERP
  comes from the marketplace instance configuration selected by the user.
- If the system still cannot resolve a unique ERP, NF must fail with an
  ambiguity error.

### Resolution for order ingest

- Shopee and Mercado Livre direct instances may ingest through direct webhook.
- Other marketplaces, including dummies, ingest through Bling webhook/fetch.
- Even when the order is ingested directly from Shopee or Mercado Livre, the
  order still needs a resolvable Bling context for NF.
- Platform-specific enrichment must run through the marketplace driver, not by
  scattering HTTP logic across routes or workers.

## UI/UX contracts

### ERP account configuration

- Shows linked marketplace instances in read-only operational form.
- Each row documents:
  - marketplace instance
  - `shop.id`
  - ingest mode: `erp` or `marketplace`
- The ERP screen does not create the relationship by itself; it reflects the
  marketplace-driven configuration.

### Marketplace account configuration

- This is the authoritative place to define the ERP relationship.
- For each linked Bling account the user may configure:
  - ERP instance
  - `shop.id`
  - ingest mode for that sales origin
  - whether that ERP supports invoicing for the marketplace
- A dummy module follows the same rule: it is configured like a marketplace
  origin even though it has no direct API.

### Orders list

- `origem da venda` means installed marketplace instance only.
- It never means import route, webhook source or technical sales channel.

## Credential rules

- Bling credentials are synchronized externally and are not locally refreshed by
  this app.
- Shopee and Mercado Livre may expose local test and refresh actions.
- Credential status in UI must reflect:
  - credential source
  - expiration
  - refresh support
  - latest refresh/test outcome
  - whether the module can actually perform the requested action

## Acceptance criteria

- A user can explain every installed account as either ERP, direct marketplace
  or dummy marketplace.
- A marketplace linked to multiple Blings remains unambiguous once the order
  context is known.
- Documentation never describes Bling as the unique source of all orders.
- Documentation never describes `marketplace_integration_id` as sufficient to
  choose NF.

## Open transition notes

- `channel_connections` still exists for operational compatibility and routing
  helpers, but the business source of truth is the installed marketplace
  instance.
- Some legacy routes and tables may still mention `canal_venda`; when that
  conflicts with this document, this spec wins.
