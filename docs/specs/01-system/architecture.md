# System Architecture

Last updated: 2026-05-28

## Current Components

```text
React/Vite frontend
  -> Flask API (/api/v2 and legacy web routes)
  -> Supabase/Postgres via shared service layer
  -> Redis/Celery worker for async ingest, sync, logs, and processing
  -> External platforms: Bling, Shopee, MercadoLivre, and other marketplace drivers
```

## Component Responsibilities

| Component | Responsibility | Canonical paths |
| --- | --- | --- |
| Frontend | User workflows, dashboards, admin screens, filters, printing UI. | `apps/frontend/src/App.jsx`, `apps/frontend/src/pages`, `apps/frontend/src/services` |
| API | HTTP contracts, route orchestration, request validation, response shaping. | `apps/api/main.py`, `apps/api/routes` |
| Shared package | Business services, Supabase access, models, integration drivers, workers. | `packages/shared/nistiprint_shared` |
| Worker | Async execution using Celery/Redis. | `apps/worker`, shared `celery_app.py`, task services |
| Supabase | Persistent data, RPCs, views, RLS, audit logs, storage/auth services. | `supabase/migrations`, remote project `cfknrplrqvyirjxovuvi` |
| Legacy | Historical UI/services and migration reference. | `kb/` |

## Architecture Decisions To Formalize

- `decision-needed`: Whether `pedidos.marketplace_integration_id` fully
  replaces `canal_venda_id` for order source filtering.
- `decision-needed`: Whether API contracts should be generated from Flask
  routes or manually curated.
- `decision-needed`: Whether legacy web routes remain supported product surface.

## Known Drift

- Existing technical docs predate several May 2026 migrations.
- Local migrations include a May 22 order source contract not listed in active
  Supabase migration history.
- API and frontend routes include duplicated/legacy paths that need ownership
  labels.

