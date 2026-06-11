# Spec Process

Last updated: 2026-05-28

## Purpose

Nistiprint specs are living contracts. They should make the intent, system
boundary, acceptance criteria, and implementation impact clear before code or
schema changes are made.

## Lifecycle

1. `draft`: initial reverse engineering or proposed behavior.
2. `review`: checked against code, Supabase, and stakeholder intent.
3. `accepted`: approved as source of truth for implementation.
4. `implemented`: code, database, tests, and docs match.
5. `superseded`: replaced by another spec or ADR.

## Required Sections For Domain Specs

Each `02-domains/*/spec.md` must include:

- Objective
- Actors
- Entities
- Main flows
- Business rules
- States
- API and database contracts
- Async events and workers
- Permissions
- Acceptance criteria
- Known gaps

## Change Rules

- Behavior changes require updates to the relevant domain spec and acceptance
  criteria in the same PR.
- API, Supabase, worker, or frontend route changes require updates under
  `03-contracts/`.
- Schema changes require a migration validation note under
  `04-quality/migration-validation.md`.
- Security or RLS changes require `01-system/security-and-rls.md` updates.
- Major tradeoffs should be recorded with the ADR template.

## Review Checklist

- Does the spec identify whether facts are `current`, `target`, `drift`, `gap`,
  or `decision-needed`?
- Are source paths or Supabase objects named when they are important?
- Are acceptance criteria testable?
- Are data ownership and permissions stated?
- Are async retries, idempotency, and failure modes covered when relevant?

