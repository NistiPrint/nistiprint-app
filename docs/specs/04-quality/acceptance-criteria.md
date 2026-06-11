# Acceptance Criteria Catalog

Last updated: 2026-05-28

Status: draft

## Global Criteria

- Specs updated in the same change as behavior.
- Existing behavior labeled `current`, desired behavior labeled `target`.
- Known drift captured before implementation.
- Tests or validation steps named for every changed contract.

## Domain Criteria

| Domain | Initial acceptance criteria |
| --- | --- |
| Pedidos | Order ingest is idempotent; list/detail screens show normalized data; reprocess does not duplicate. |
| Producao | Demand/order traceability is visible; draft lifecycle is consistent; priority is explainable. |
| Estoque | Stock movement and reconciliation are auditable and idempotent. |
| Integracoes | Source resolution is traceable; token and sync failures are visible. |
| Administracao | Admin-only behavior is enforced by API, not only frontend. |
| Relatorios | High-volume logs paginate and expose enough debug context. |

## Definition Of Done For Spec-Driven Work

- Domain spec updated.
- Contract docs updated if API/DB/worker/frontend route changes.
- Acceptance criteria added or updated.
- Migration validation updated for schema changes.
- Tests or manual validation executed and recorded.

