# Glossary

Last updated: 2026-06-16

| Term | Meaning |
| --- | --- |
| Integration module | Connector catalog entry in `integration_modules`. |
| Installed integration | Installed ERP or marketplace instance in `installed_integrations`. |
| Direct marketplace integration | Installed marketplace with its own driver and webhook/auth strategy. |
| Dummy marketplace integration | Installed marketplace origin without a direct API driver; it still exists as a sales origin and routing identity. |
| ERP integration | Installed ERP account, currently Bling. |
| Sales origin | Marketplace instance that owns the commercial sale. |
| Ingest origin | Technical source that delivered the event or import, such as Bling webhook or direct marketplace webhook. |
| ERP store ID | `shop.id` or `erp_store_id` that identifies a marketplace account inside a specific ERP/Bling account. |
| Company ID | Bling `companyId`, used to identify which ERP account sent or owns a webhook context. |
| Canonical order | Operational order represented by `pedidos` plus its normalized snapshot. |
| Mirror table | Provider-specific audit/raw table such as `pedidos_bling`, `pedidos_shopee` or `pedidos_mercadolivre`. |
| Platform fields | Provider-specific attributes stored in `pedido_snapshots.platform_fields`. |
| Marketplace integration ID | Installed marketplace identity used as the canonical sales-origin key. |
| Bling integration ID | Installed ERP identity used to resolve NF and ERP-side actions. |
| Bling loja ID | Store identifier used by Bling to identify the marketplace account within a Bling account. |
| Dummy origin | Sales origin created by installing a dummy marketplace module. |
| NF routing | Logic that chooses which ERP account can emit the invoice for a given order. |
| Ambiguous ERP resolution | Situation where the system cannot choose a unique ERP account from the available order and routing context. |
| Drift | Disagreement between docs, code, local migrations and production behavior. |
