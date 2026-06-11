# Nistiprint Spec-Driven Docs

Last updated: 2026-05-28

This folder is the spec-driven layer for Nistiprint. It does not replace the
existing documentation under `docs/`; it turns the current knowledge into
versioned, reviewable contracts that can guide implementation, tests, and
operational decisions.

## Baseline

- Operational database: Supabase project `nistiprint-supabase`
  (`cfknrplrqvyirjxovuvi`), region `sa-east-1`, Postgres `17.6.1`.
- Repository baseline: monorepo with React/Vite frontend, Flask API, Celery
  worker, shared Python package, Supabase migrations, and legacy code under
  `kb/`.
- Documentation stance: existing docs are reference material; specs here are
  the canonical place for current requirements, contracts, gaps, and decisions.

## How To Use

1. Start with [as-is reverse engineering](01-system/as-is-reverse-engineering.md)
   to understand the current system.
2. Read the relevant domain spec under `02-domains/` before changing behavior.
3. Update contracts under `03-contracts/` whenever API, database, worker, or
   frontend routes change.
4. Add acceptance criteria and tests under `04-quality/` before implementation.
5. Record open decisions in [open questions](05-roadmap/open-questions.md) and
   accepted decisions with the ADR template.

## Document Map

| Area | Purpose |
| --- | --- |
| `00-governance/` | Process, glossary, ADR template, traceability matrix. |
| `01-system/` | Reverse engineering, architecture, data, RLS, operational risks. |
| `02-domains/` | Domain-level specs for product and engineering behavior. |
| `03-contracts/` | API, Supabase, worker, and frontend route contracts. |
| `04-quality/` | Test strategy, acceptance criteria, migration validation. |
| `05-roadmap/` | Backlog and open questions for future spec work. |

## Canonical First Reads

- [System as-is report](01-system/as-is-reverse-engineering.md)
- [Spec process](00-governance/spec-process.md)
- [Pedidos spec](02-domains/pedidos/spec.md)
- [Supabase contracts](03-contracts/supabase-contracts.md)
- [Migration validation](04-quality/migration-validation.md)

## Status Labels

- `current`: observed in code, docs, or Supabase.
- `target`: desired behavior not fully proven current.
- `drift`: repo, database, code, or docs disagree.
- `gap`: required spec detail is missing.
- `decision-needed`: product or engineering choice is needed before work.

