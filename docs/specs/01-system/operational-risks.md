# Operational Risks

Last updated: 2026-05-28

| Risk | Type | Impact | Current mitigation | Next spec action |
| --- | --- | --- | --- | --- |
| Local migration newer than active Supabase | drift | Code may expect columns/RPC behavior not deployed. | Documented in migration validation. | Add migration drift check to release process. |
| RLS enabled with no policy | security/ops | Client calls may fail or rely on service role. | Advisors recorded. | Write authorization spec per domain. |
| Permissive write policies | security | Authenticated users may mutate too broadly. | Advisors recorded. | Define RBAC and update policies deliberately. |
| Duplicate/unused indexes | performance | Extra write cost and schema noise. | Advisors recorded. | Review workload before index cleanup. |
| Hardcoded publishable Supabase config | config hygiene | Environment rotation/deployment friction. | Identified in report. | Move to env-driven frontend config. |
| Legacy code still present | maintainability | Behavior ownership ambiguity. | Keep `kb/` as reference. | Label active vs legacy route surfaces. |
| Docs mix current and historical plans | delivery | Engineers may implement against stale intent. | New `docs/specs` layer. | Convert highest-risk domains first. |

