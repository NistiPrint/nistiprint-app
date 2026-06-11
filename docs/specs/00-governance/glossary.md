# Glossary

Last updated: 2026-05-28

| Term | Meaning |
| --- | --- |
| Pedido | Normalized order in `public.pedidos`; operational order record used by the app. |
| Pedido Bling | Raw or mirrored Bling order in `public.pedidos_bling`. |
| Pedido Shopee | Shopee enrichment/mirror in `public.pedidos_shopee`. |
| Demanda | Production demand/order of work in `public.demandas_producao`. |
| Rascunho | Draft demand that can still receive compatible orders. |
| Canal de venda | Legacy/commercial sales channel in `public.canais_venda`. |
| Integration module | Connector catalog entry in `public.integration_modules`. |
| Installed integration | Active integration instance in `public.installed_integrations`. |
| Channel connection | Explicit channel/integration link in `public.channel_connections`. |
| Bling loja ID | Store identifier from Bling payload, now an important origin pivot. |
| Marketplace integration ID | Installed marketplace integration used as canonical source key. |
| Flex | Fast same-day/urgent shipping classification. |
| Fulfillment | External fulfillment/replenishment classification. |
| BOM | Bill of materials, represented mainly by `public.ficha_tecnica`. |
| RLS | Row Level Security in Supabase/Postgres. |
| Drift | Observable disagreement between code, docs, local migrations, and production database. |
| Gap | Missing detail that must be specified before safe implementation. |

