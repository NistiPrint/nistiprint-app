# Domain Spec: Administracao

Last updated: 2026-05-28

Status: draft

## Objective

Provide secure administration for users, sectors, permissions, catalog
reference data, products, suppliers, deposits, logistics points, and system
configuration.

## Actors

- Admin user
- Operations manager
- System service

## Entities

- `usuarios`
- `setores`
- `permissoes_setor`
- `recursos`
- `categorias`
- `tags`
- `unidades_medida`
- `conversoes_uom_produto`
- `fornecedores`
- `depositos`
- `pontos_coleta`
- `configuracoes_aplicacao`
- `produtos`

## Main Flows

- Manage users and sectors.
- Assign sector permissions.
- Manage product/catalog metadata.
- Manage suppliers, deposits, and units.
- Configure production and integration settings.

## Business Rules

- Admin routes are protected in frontend with `ProtectedRoute requireAdmin`.
- Sector permission behavior must be enforced server-side, not only in UI.
- Catalog data can affect production, stock, and order mapping.

## States

- Active/inactive flags appear across multiple reference entities.
- Product status includes active/draft/inactive concepts in existing docs.

## API And Database Contracts

- Frontend routes: `/cadastros/*`, `/sistema/*`, `/configuracoes/*`,
  `/ferramentas/*`.
- API routes: `/api/v2/cadastros`, `/api/v2/configuracoes`,
  `/api/v2/usuarios-setores`, `/api/v2/produtos`,
  `/api/v2/cadastros/uom-conversions`.

## Async Events And Workers

- Mostly synchronous admin CRUD. Some config changes affect workers,
  integrations, and order classification.

## Permissions

`gap`: Formalize server-side admin checks and RLS policy alignment for every
admin table.

## Acceptance Criteria

- Admin-only screens are not sufficient without API authorization.
- Catalog edits preserve referential integrity with orders, BOM, and stock.
- Permission updates are auditable or at least traceable.
- Config changes that affect workers are documented with rollout steps.

## Known Gaps

- Complete RBAC matrix.
- Audit policy for admin mutations.
- Data retention and delete constraints for reference data.

