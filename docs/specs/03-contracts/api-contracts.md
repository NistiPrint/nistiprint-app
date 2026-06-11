# API Contracts

Last updated: 2026-05-28

Status: draft

## Current API Surface

The Flask app registers blueprints in `apps/api/main.py`. The product API
surface is a mix of current `/api/v2/*` endpoints, admin/debug endpoints, and
legacy web routes.

## Primary `/api/v2` Areas

| Area | Prefixes |
| --- | --- |
| Orders | `/api/v2/pedidos`, `/api/v2/order`, `/api/v2/orders`, `/api/admin/orders` |
| Production | `/api/v2/demandas`, `/api/v2/demanda_producao`, `/api/v2/producao`, `/api/v2/producao-contexto` |
| Stock | `/api/v2/estoque`, `/api/v2/auditoria` |
| Integrations | `/api/v2/marketplace`, `/api/v2/integracoes`, `/api/v2/integracao-canais`, `/api/v2/erp-links`, `/api/v2/webhooks` |
| Admin/config | `/api/v2/cadastros`, `/api/v2/configuracoes`, `/api/v2/usuarios-setores`, `/api/v2/produtos` |
| Monitoring | `/api/v2/tasks`, `/api/v2/admin/task-schedules`, `/api/v2/notifications`, `/api/v2/alertas`, `/api/v2/relatorios` |
| Printing/personalized | `/api/v2/printing`, `/api/v2/pedidos/impressao`, `/api/v2/personalizados` |

## Contract Rules

- Each endpoint used by frontend services should have request, response, auth,
  error, and pagination semantics documented.
- Legacy web routes should be labeled `legacy-web` or `active-web`.
- Endpoint names should not be considered stable until they are referenced from
  a domain spec and test plan.

## Gaps

- No generated OpenAPI contract is currently identified.
- Duplicate order prefixes need consolidation or ownership labels.
- Error envelope consistency needs audit.

