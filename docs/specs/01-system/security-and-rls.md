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

## Mercado Livre personalization boundary

- The seven `mercadolivre_*` personalization/chat relations are isolated from
  the Shopee personalization schema and have RLS enabled with no client-role
  policies. Only backend service-role code accesses them.
- Authenticated APIs validate `integration_id` against the installed Mercado
  Livre module on every request and filter orders, items, conversations, batches,
  logs, and results by that same ID. Admin-only settings are also enforced by
  the API decorator.
- The result RPC is `SECURITY DEFINER` with a fixed `search_path=public`; execute
  is revoked from `PUBLIC`, `anon`, and `authenticated`, and granted only to
  `service_role`. It checks canonical order and item ownership before writes.
- Webhook resolution requires both account identity and registered application
  ID. Ambiguous identity remains unmatched and auditable; it never falls back
  to credentials from another account.
- Account-specific AI keys are not read from Shopee environment variables.

