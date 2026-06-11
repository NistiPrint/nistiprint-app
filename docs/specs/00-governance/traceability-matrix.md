# Traceability Matrix

Last updated: 2026-05-28

This matrix links domains to code, database objects, contracts, and tests. It is
seeded from reverse engineering and must be refined as specs mature.

| Domain | Frontend | API / Worker | Supabase | Tests / Validation | Status |
| --- | --- | --- | --- | --- | --- |
| Pedidos/Vendas | `apps/frontend/src/pages/vendas`, `apps/frontend/src/pages/pedidos` | `apps/api/routes/pedidos.py`, `pedidos_gestao.py`, `pedidos_sync.py`, shared order services | `pedidos`, `pedidos_bling`, `pedidos_shopee`, `itens_pedido`, `pedido_ingest_log`, `webhook_events` | order service tests, RPC validation, spot checks | current + drift |
| Producao/Demandas | `apps/frontend/src/pages/producao`, `components/demandas` | `demandas.py`, `demanda_producao_*`, `producao_contexto.py` | `demandas_producao`, `itens_demanda`, `demandas_pedidos`, `contextos_producao`, `regras_priorizacao` | production service tests, UI acceptance | current + gap |
| Estoque | `apps/frontend/src/pages/estoque` | `estoque_*`, shared `motor_estoque_v2.py` | `estoque_atual`, `movimentacoes_estoque`, `estoque_consolidado`, `eventos_producao_v2` | `test_motor_estoque_v2.py`, reconciliation RPC checks | current |
| Integracoes | `apps/frontend/src/components/marketplace`, admin config pages | `marketplace*`, `integracao_canais.py`, `erp_links.py`, Bling/Shopee services | `integration_modules`, `installed_integrations`, `channel_connections`, `erp_marketplace_links` | integration resolution tests | current + drift |
| Administracao | `apps/frontend/src/pages/admin`, `cadastros` | `cadastros_*`, `configuracoes.py`, `usuarios_setores.py` | `usuarios`, `setores`, `permissoes_setor`, reference tables | CRUD and permission checks | gap |
| Relatorios/Monitoramento | `apps/frontend/src/pages/admin/relatorios`, `ai` | `relatorios.py`, `tasks_api.py`, `notifications.py` | `task_execution_logs`, `notificacoes`, logs and views | report route checks | gap |

