# Data Architecture

Last updated: 2026-05-28

## Baseline

The active operational database is Supabase project `nistiprint-supabase`
(`cfknrplrqvyirjxovuvi`), Postgres 17. Local schema and migrations are under
`supabase/`.

## Data Domains

| Domain | Primary objects |
| --- | --- |
| Orders | `pedidos`, `pedidos_bling`, `pedidos_shopee`, `pedidos_mercadolivre`, `itens_pedido`, `vinculos_integracao_pedido` |
| Production | `demandas_producao`, `itens_demanda`, `demandas_pedidos`, `contextos_producao`, `regras_priorizacao`, `sinalizacoes_demanda` |
| Inventory | `produtos`, `ficha_tecnica`, `estoque_atual`, `movimentacoes_estoque`, `estoque_consolidado`, `eventos_producao_v2` |
| Integrations | `integration_modules`, `installed_integrations`, `channel_connections`, `erp_marketplace_links`, `integration_refresh_logs` |
| Admin/RBAC | `usuarios`, `setores`, `permissoes_setor`, `recursos` |
| Observability | `pedido_ingest_log`, `webhook_events`, `task_execution_logs`, `system_events_log`, `debug_rpc_logs` |

## Current Data Patterns

- Order ingest keeps raw/mirror records and normalized operational records.
- Production demands are the work center, with many-to-many traceability to
  orders through `demandas_pedidos`.
- Integration identity is transitioning from legacy channels toward installed
  integration IDs and explicit links.
- Inventory v2 uses movement/events, reconciliation RPCs, and consolidated
  views/tables.

## Required Spec Work

- Document canonical IDs for Bling, marketplace, internal orders, and demands.
- Reconcile local migrations against active Supabase before using local schema
  as implementation truth.
- Define ownership for duplicated source columns such as `canal_venda_id`,
  `marketplace_integration_id`, `bling_integration_id`, and `bling_loja_id`.

