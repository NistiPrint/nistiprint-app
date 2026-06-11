# Frontend Routes

Last updated: 2026-05-28

Status: draft

Primary route source: `apps/frontend/src/App.jsx`.

## Route Areas

| Area | Routes |
| --- | --- |
| Auth | `/login` |
| Home | `/` |
| Products | `/produtos`, `/produtos/novo`, `/produtos/:id/editar` |
| Production | `/producao`, `/producao/foco`, `/producao/resumo`, `/producao/demanda`, `/producao/demanda/rascunhos`, `/producao/demanda/nova`, `/producao/demanda/:id/editar`, `/producao/demanda/prioridade`, `/producao/demanda/calendario`, `/producao/demanda/:id/dashboard`, `/producao/miolos`, `/producao/capas`, `/producao/expedicao`, `/producao/impressao` |
| Sales/orders | `/vendas/personalizadas`, `/vendas/pedidos`, `/vendas/pedidos/:id`, `/pedidos`, `/pedidos/:id` |
| Consolidation | `/consolidar`, `/consolidar/revisao`, `/consolidar/rascunhos` |
| Stock | `/estoque/dashboard`, `/estoque/historico`, `/estoque/movimentar`, `/estoque/posicao`, `/estoque/reservas`, `/estoque/ajuste`, `/estoque/relatorios`, `/estoque/movimentacao-lote` |
| Admin catalog | `/cadastros/*` |
| System admin | `/sistema/*` |
| Config | `/configuracoes/*` |
| Reports | `/relatorios/*` |
| Tools | `/ferramentas`, `/ferramentas/ia`, `/admin/utilitarios/tasks` |
| AI logs | `/ai/logs` |

## Protection Rules Observed

- Most application routes sit behind `ProtectedRoute`.
- Admin areas use `ProtectedRoute requireAdmin={true}`.
- `decision-needed`: API and RLS authorization must be verified because
  frontend route guards are not sufficient security controls.

## Gaps

- Route-to-service mapping is not yet complete.
- Duplicate order routes require ownership labels.
- Sidebar/navigation visibility rules should be documented.

