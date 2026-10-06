# Personalização de pedidos Mercado Livre

Last updated: 2026-10-06

Status: implemented in repository; production activation remains gated on
migration validation, account permissions, and a real-message pilot.

## Objective

Capture private post-sale Mercado Livre conversations, identify requested
names and initials with AI, permit operator confirmation, and pass only current,
confirmed results to order printing. Keep this flow isolated from Shopee and
scoped to each installed Mercado Livre integration.

## Actors

- Mercado Livre sends `messages` topic notifications through the existing
  durable N8N/reliable-ingest path.
- A dedicated process group synchronizes each connected Mercado Livre account.
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
2. Per-account consumers resolve `user_id` and `application_id`, fetch the
   message, then page the `post_sale` package conversation with
   `mark_as_read=false`. An unread-conversation scan recovers missed notices;
   stored active conversations are periodically reconciled.
3. When the order is not imported yet, messages remain stored and appear under
   conversations awaiting order association. No incomplete order is created.
4. A dedicated account worker processes manual or daily batches. It synchronizes
   the chat first, hashes the full conversation, and avoids repeated AI calls
   for unchanged successful context.
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

Run the separate account manager with
`python -m nistiprint_shared.services.mercadolivre_personalization_worker accounts`.
It discovers active Mercado Livre installations and maintains an isolated
message consumer, Celery worker, queue, and beat scheduler for each. The
existing Shopee Celery app, task names, queues, and schedules are not imported
or changed. Each Meli queue is named `meli_personalization_<integration_id>`;
per-account worker concurrency is one. The daily due task reads its own account
schedule from Supabase, and batch recovery runs every five minutes.

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

Apply and validate the additive migration, provision account-specific AI
secrets, then pilot with capture enabled and extraction disabled. After real
messages and account associations are verified, enable extraction for the pilot
account. A second account appears automatically and remains disabled until its
permissions are checked. Rollback disables only these account processes and
settings; persisted data remains available and Shopee continues independently.

## Known deployment gate

The repository contains the migration and account supervisor, but they have not
been applied to production and the new account process has not been started in
the deployed environment. Do not enable the feature until both steps and the
real-message pilot are recorded.
