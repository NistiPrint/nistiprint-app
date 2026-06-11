# Security And RLS

Last updated: 2026-05-28

## Current State

Supabase advisors show that RLS is broadly enabled in `public`, but the policy
model is not yet a precise authorization contract. This document records the
current risk categories. It does not approve changing policies without a domain
authorization spec.

## Advisor Findings

| Finding | Status | Notes |
| --- | --- | --- |
| RLS enabled with no policy | gap | Many tables are protected from client access but may be inaccessible or dependent on service-role access. |
| Permissive write policies | risk | Some authenticated policies allow unrestricted insert/update/delete. |
| Public `SECURITY DEFINER` function | risk | `public.public_merchant_store(_merchant_id uuid)` is executable by `anon` and `authenticated`. |
| Auth leaked password protection disabled | risk | Auth hardening decision needed. |
| Frontend publishable key hardcoded | hygiene gap | Publishable keys can be public, but should be env-configured and rotatable. |

## Required Authorization Specs

For each domain, specify:

- Which roles can read, create, update, delete.
- Whether access is global, admin-only, sector-scoped, user-owned, or
  service-role-only.
- Which tables are exposed through PostgREST.
- Which functions are callable by `anon`, `authenticated`, or service role.
- Whether views need `security_invoker = true`.

## Immediate Guardrails

- Do not add new public tables without explicit RLS and policy intent.
- Do not add `SECURITY DEFINER` functions in exposed schemas unless reviewed.
- Do not use user-editable metadata for authorization decisions.
- Do not expose service-role keys to frontend code.

