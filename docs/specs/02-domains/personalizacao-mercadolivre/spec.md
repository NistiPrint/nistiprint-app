# Personalização de pedidos Mercado Livre

Last updated: 2026-10-06

Status: implemented in repository; production activation remains gated on
migration validation, account permissions, and a real-message pilot.

## Objective

Capture private post-sale Mercado Livre conversations, identify requested
names and initials with AI, permit operator confirmation, and pass only current,
confirmed results to order printing. Keep provider data and account
configuration scoped to each Mercado Livre integration while using shared
worker infrastructure.

## Actors

- Mercado Livre sends `messages` topic notifications through the existing
  durable N8N/reliable-ingest path.
- The shared chat consumer records Mercado Livre events, and shared Celery
  functions synchronize messages and run AI extraction as separate stages.
- Authenticated operators review conversations and confirm extracted data.
- Administrators configure capture, AI, and the daily run for one account.

## Entities

- `installed_integrations`: account and credential boundary.
- `mercadolivre_chat_inbox`: durable, deduplicated, leased notification inbox.
- `mercadolivre_chat_conversations` and `mercadolivre_chat_messages`: private
  post-sale history and association state.
- `mercadolivre_personalization_config`: AI, capture, enablement, and schedule
  settings keyed by integration ID.
- `mercadolivre_personalization_batches` and
  `mercadolivre_personalization_logs`: account-scoped execution tracking.
- `mercadolivre_personalizations`: account/order/item-scoped results and
  confirmations.

All account, order, item, and provider message identifiers are kept in their
appropriate types. Provider message IDs are opaque text. A second connected
account gets rows in the same schema but cannot read or write another account's
records through the API or workers.

## Main flows

1. The reliable worker routes only Mercado Livre `messages` events into this
   domain. Its inbox row is persisted before the original event is finalized.
2. The shared inbox function resolves `user_id` and `application_id`, fetches
   the message, then pages the `post_sale` package conversation with
   `mark_as_read=false`. An unread-conversation scan recovers missed notices;
   stored active conversations are periodically reconciled.
3. When the order is not imported yet, messages remain stored and appear under
   conversations awaiting order association. No incomplete order is created.
4. Separate shared Celery functions process manual or daily batches with the
   account ID. They read only persisted messages, hash the full conversation,
   and avoid repeated AI calls for unchanged successful context.
5. Operators confirm or correct each name/initial. The print reader selects
   Mercado Livre rows by the canonical integration, order, and item IDs. It
   blocks stale, incomplete, unconfirmed, or review-required personalization.

## Business rules and states

- Capture, extraction, and the master enablement switch default to disabled.
- The account schedule defaults to 09:00 `America/Sao_Paulo`; each account can
  configure its own hour and minute.
- Webhook routing fails closed on missing, divergent, or ambiguous account and
  application identity. Unmatched events remain auditable and can be resolved
  after a matching account is connected.
- A sender is a buyer only when their ID matches a buyer on a related order.
  Seller, known Mercado Livre agent, and unknown senders stay distinct. Agent or
  unknown attribution requires operator review.
- Results must map to an internal personalized item and a message in the current
  conversation. Unit counts must match the quantity ordered before printing.
- Attachments are stored and shown as attachments. OCR/multimodal interpretation
  is outside this version; attachment-dependent instructions need review.
- Manual confirmation records the operator and is logged. A later chat change
  makes the earlier result stale until it is reviewed again.
- AI secrets use `MERCADOLIVRE_PERSONALIZACAO_GEMINI_API_KEY` and
  `MERCADOLIVRE_PERSONALIZACAO_OPENROUTER_API_KEY`; there is no Shopee-key
  fallback.

## API and frontend contracts

Routes are listed in `docs/specs/03-contracts/api-contracts.md` and
`docs/specs/03-contracts/frontend-routes.md`. The account ID is required on all
operations that access configuration, orders, conversations, batches, logs, or
personalizations. Settings writes require an administrator. Every endpoint
checks order or batch ownership in the same account.

## Async workers

The existing shared Celery worker and Beat execute registered Mercado Livre
functions on the default `celery` queue. The shared reliable-ingest `chat`
consumer persists the source-specific webhook notification and schedules the
inbox-processing function. The Beat repeats inbox processing and runs chat
reconciliation as recovery. Both stages resolve the integration using the
webhook seller and application identities; incomplete or ambiguous events stay
in the audit inbox.

AI extraction is an independent set of Celery functions. Manual and daily batch
tasks receive an integration ID and use only that account's settings, API
credentials, and rate-limit bucket. The shared Beat checks per-account daily
settings and dispatches due work; a Redis lock keyed by integration and local
date prevents duplicate daily runs. Batch recovery is dispatched periodically
per account. No account-specific Celery app, queue, worker, beat, supervisor,
or Compose service is required. Shopee's `chat`, `chatsync`, and persistence
paths remain unchanged.

## Permissions and acceptance criteria

- Authenticated users can review personalizations only through the backend;
  administrators alone update settings. The new tables have no direct
  `anon`/`authenticated` access; service-role access is used by server code.
- Shopee event routing, persistence, prompts, configuration, schedules,
  dashboards, and printing remain unchanged by the Mercado Livre additions.
- Two-account tests must prove that orders, messages, tokens, settings, batches,
  logs, and print results never cross `integration_id` boundaries.
- Duplicate and out-of-order notifications, unread recovery, messages arriving
  before order import, opaque IDs, paging, agent senders, moderation, attachments,
  provider failures, and worker restart must be covered.
- Printing must reject stale context, missing confirmations, and mismatched
  quantities; Shopee print results must remain equivalent.

## Operational rollout and rollback

Apply and validate the additive migration, provide account-specific AI secrets
to the shared worker environment, then pilot with capture enabled and extraction
disabled. After real messages and account associations are verified, enable
extraction for the pilot account. A second account appears automatically and
remains disabled until its permissions are checked. Rollback disables the
account settings; persisted data remains available and Shopee continues
independently.

## Known deployment gate

The repository contains the migration, but it has not been applied to production.
Production deployment and the real-message pilot remain outside this change.
