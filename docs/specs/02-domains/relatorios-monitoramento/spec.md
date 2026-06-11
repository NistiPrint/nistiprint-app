# Domain Spec: Relatorios / Monitoramento

Last updated: 2026-05-28

Status: draft

## Objective

Give operators and managers reliable visibility into production history,
collections, inventory monitoring, task execution, alerts, notifications, and
AI/order processing logs.

## Actors

- Admin user
- Operations manager
- Support/debug user
- Worker process

## Entities

- `task_execution_logs`
- `pedido_ingest_log`
- `webhook_events`
- `notificacoes`
- `system_events_log`
- `logs_execucao_ia`
- `feedbacks_execucao_ia`
- reporting views/RPCs

## Main Flows

- View production history.
- View collection history.
- Monitor inventory and stock queue.
- Inspect worker/task logs.
- Receive or trigger notifications.
- Review AI/personalization logs.

## Business Rules

- Monitoring data should be queryable without exposing secrets or raw tokens.
- Logs should support correlation IDs when available.
- High-volume logs need pagination and retention policy.

## States

- Task status, ingest stage/status, webhook processed/reprocess state, and
  notification read/unread states require formal dictionaries.

## API And Database Contracts

- Frontend routes: `/relatorios/*`, `/ai/logs`,
  `/admin/utilitarios/tasks`.
- API routes: `/api/v2/relatorios`, `/api/v2/tasks`,
  `/api/v2/admin/task-schedules`, `/api/v2/notifications`,
  `/api/v2/alertas`.

## Async Events And Workers

- Worker task logging.
- Notification streaming and send events.
- Webhook reprocessing and ingest logging.

## Permissions

Reporting and monitoring routes are mostly admin-protected in frontend. API and
RLS authorization need verification.

## Acceptance Criteria

- Logs can be filtered by useful operational dimensions.
- High-volume endpoints paginate.
- Error states include enough context to reprocess or debug.
- Notifications do not leak cross-user data.

## Known Gaps

- Retention policy for operational logs.
- Correlation ID standard.
- Public/support-safe log redaction rules.

