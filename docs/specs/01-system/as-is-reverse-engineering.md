# As-Is Reverse Engineering Report

Last updated: 2026-05-28

## Executive Summary

Nistiprint is a production operations system for ecommerce orders, production
demands, inventory, marketplace integrations, and operational monitoring. The
repository already has substantial documentation under `docs/`, but the code
and Supabase migrations moved faster than the docs after April 2026. The new
spec-driven layer should preserve useful historic docs while making
`docs/specs/` the canonical place for current contracts and implementation
intent.

## Architecture Map

| Component | Current observation |
| --- | --- |
| Frontend | React 19, Vite/Rolldown, React Router, Supabase JS, Axios, Radix, Bootstrap, Tailwind utilities. Main route map is in `apps/frontend/src/App.jsx`. |
| API | Flask application factory in `apps/api/main.py`; blueprints register legacy web routes and `/api/v2/*` APIs. |
| Worker | Celery/Redis worker dependencies in `apps/worker`; shared task logic lives mostly in `packages/shared/nistiprint_shared/services`. |
| Shared package | Python business logic, models, Supabase database compatibility layer, integration drivers, inventory engine, and order services. |
| Database | Supabase/Postgres 17, exposed `public` schema, RLS enabled broadly. Local SQL under `supabase/`. |
| Legacy | `kb/` contains Flask/PHP/template legacy material that still documents old behavior and may still be useful for migration context. |

## Domains And Inferred Functionalities

| Domain | Inferred functionality |
| --- | --- |
| Pedidos/Vendas | Ingest Bling/Shopee/MercadoLivre orders, normalize into `pedidos`, filter/list/detail/reprocess, print, link to demands, identify personalized orders. |
| Producao/Demandas | Create and manage production demands, draft consolidation, prioritization, production dashboards, timeline, expedition, printing queue. |
| Estoque | Inventory positions, movements, reservations, batch movement, reconciliation, event sourcing v2, audit views. |
| Integracoes | Integration marketplace, installed connectors, Bling account routing, channel connections, ERP/marketplace links, token renewal, status sync. |
| Administracao | Product/catalog CRUD, users, sectors, permissions, categories, tags, units, suppliers, deposits, logistics points, configuration. |
| IA/Personalizados | Personalized order detection, execution logs, configuration, feedback tables, AI dashboards/logs. |
| Relatorios/Monitoramento | Production history, collection history, inventory monitoring, worker/task logs, alerts, notifications. |
| Impressao | Print jobs, product artwork, order printing endpoints, production print queue. |

## Existing Documentation Review

| Area | Current value | Trust status |
| --- | --- | --- |
| `docs/README.md` | Useful map for current docs. | current as index, stale as source of truth. |
| `docs/tecnico/ARQUITETURA.md` | Good architecture narrative for April 2026. | partial drift; does not include all May changes. |
| `docs/tecnico/MODELO-DADOS.md` | Strong data model explanation. | partial drift; must be compared with Supabase active database. |
| `docs/negocio/REGRAS.md` | Useful business rules for consolidation, priority, inventory, RBAC. | current for concepts, not fully proven against code. |
| `docs/REFATORACAO_PEDIDOS_2904.md` | Important plan for order ingest unification. | target/history; several later migrations changed contracts. |
| `docs/estoque/*` | Detailed stock engine v2 knowledge. | relatively current, should be converted into formal spec. |
| `docs/executivo/*` | Useful stakeholder narrative. | reference only. |
| `docs/archive/*` | Historical context. | non-canonical. |

## Supabase Baseline

Project: `nistiprint-supabase` (`cfknrplrqvyirjxovuvi`)

- Status: `ACTIVE_HEALTHY`
- Region: `sa-east-1`
- Database: Postgres `17.6.1.063`
- Created at: `2026-01-17T00:05:03.64244Z`

Key operational tables observed:

| Table | Rows observed | Meaning |
| --- | ---: | --- |
| `public.pedidos` | 7457 | Normalized order core. |
| `public.pedidos_bling` | 7804 | Bling order mirror/audit. |
| `public.pedidos_shopee` | 5634 | Shopee order mirror/enrichment. |
| `public.itens_pedido` | 7390 | Normalized order items. |
| `public.pedido_ingest_log` | 256625 | High-volume ingest audit log. |
| `public.webhook_events` | 33119 | Webhook processing/reprocess source. |
| `public.task_execution_logs` | 36400 | Worker/task execution records. |
| `public.integration_modules` | 11 | Integration catalog. |
| `public.installed_integrations` | 10 | Active integration instances. |
| `public.channel_connections` | 10 | Explicit channel/integration links. |
| `public.erp_marketplace_links` | 10 | ERP to marketplace links. |
| `public.produtos` | 357 | Product catalog. |
| `public.ficha_tecnica` | 985 | BOM/component relationships. |

## Migration Drift

`drift`: The active Supabase project reports latest migration
`20260521101740 optimize_order_filters_rpc`, while the repository contains at
least one newer local migration:

- `supabase/migrations/20260522000000_canonical_order_source_and_fulfillment_contract.sql`

The May 22 local migration changes canonical order source behavior,
`pedidos.bling_loja_id`, fulfillment classification, and
`list_pedidos_filtrados`. It must be treated as not proven deployed until
verified by migration history or direct schema inspection in the target
environment.

## Security And RLS Findings

`gap`: Advisors show broad RLS coverage, but the policy model is not yet a
well-specified authorization contract.

Observed risk categories:

- Many public tables have RLS enabled but no policies.
- Some write policies use `USING (true)` or `WITH CHECK (true)` for
  authenticated users.
- `public.public_merchant_store(_merchant_id uuid)` is a `SECURITY DEFINER`
  function executable by `anon` and `authenticated`.
- Auth leaked password protection is disabled.
- Frontend has a hardcoded Supabase publishable key in
  `apps/frontend/src/lib/supabase.js`; this is not a secret key, but it should
  still be moved into environment configuration for environment hygiene and
  rotation.

## Performance Findings

Advisors report:

- Many unindexed foreign keys.
- Duplicate indexes, including on `pedidos`, `demandas_producao`,
  `pedido_ingest_log`, `mensagem_chat_shopee`, and `preferencias_ux_usuario`.
- Multiple unused indexes. These should not be dropped blindly; usage windows
  and query workloads must be reviewed first.

## API And Route Surface

Frontend routes are centralized in `apps/frontend/src/App.jsx` and cover:

- `/login`
- `/produtos`
- `/producao/*`
- `/vendas/*`
- `/pedidos/*`
- `/consolidar/*`
- `/estoque/*`
- `/cadastros/*`
- `/sistema/*`
- `/configuracoes/*`
- `/relatorios/*`
- `/ferramentas/*`
- `/admin/utilitarios/tasks`

API blueprints are registered in `apps/api/main.py` and include:

- `/api/v2/pedidos`, `/api/v2/demandas`, `/api/v2/producao`,
  `/api/v2/producao-contexto`
- `/api/v2/estoque`, `/api/v2/auditoria`
- `/api/v2/marketplace`, `/api/v2/integracoes`,
  `/api/v2/integracao-canais`, `/api/v2/erp-links`
- `/api/v2/cadastros`, `/api/v2/configuracoes`,
  `/api/v2/usuarios-setores`
- `/api/v2/tasks`, `/api/v2/admin/task-schedules`, worker logs
- `/api/v2/webhooks`, `/api/v2/personalizados`, `/api/v2/notifications`

`drift`: Some routes are legacy web routes and some are APIs. The specs should
make frontend-used contracts explicit instead of assuming every registered
blueprint is public product surface.

## Recommendations

1. Make Pedidos/Vendas the first full domain spec, because it has the most
   active drift across Bling, marketplace source, filters, fulfillment, and
   local migrations.
2. Turn Estoque v2 docs into a formal domain spec with acceptance tests tied to
   `test_motor_estoque_v2.py`.
3. Create a Supabase authorization spec before changing RLS policies, because
   current advisors show high ambiguity.
4. Add migration drift checks to PR review: local migration list must be
   reconciled with active Supabase migration history before deployment.
5. Move environment-specific frontend Supabase values to env-driven config.
6. Keep archived docs as references only; new work should cite `docs/specs`.

