-- Identidade da conta visivel onde se diagnostica.
--
-- `webhook_events` nasceu do Bling e so tem `company_id`, `bling_id` e
-- `numero_loja`. Com um marketplace de conta unica isso nao incomodava: a unica
-- pista da conta era o `dedupe_scope`, que guarda o `user_id` por acidente de
-- projeto e nao como identidade. Com duas contas na mesma origem, qualquer
-- investigacao de backlog ou de falha vira consulta manual.

begin;

alter table public.webhook_events
    add column if not exists marketplace_integration_id integer;

comment on column public.webhook_events.marketplace_integration_id is
    'Conta resolvida para este evento. Nulo enquanto a resolucao nao aconteceu '
    '(ou falhou) — o que por si so ja e um filtro util.';

create index if not exists ix_webhook_events_integration_status
    on public.webhook_events (marketplace_integration_id, last_status, received_at desc)
 where marketplace_integration_id is not null;

-- `pedido_ingest_log.marketplace_integration_id` ja existe; o que faltava era
-- alguem preenche-lo. `_write_ingest_log` passa a faze-lo nesta mesma entrega.
create index if not exists ix_pedido_ingest_log_integration
    on public.pedido_ingest_log (marketplace_integration_id, created_at desc)
 where marketplace_integration_id is not null;

commit;
