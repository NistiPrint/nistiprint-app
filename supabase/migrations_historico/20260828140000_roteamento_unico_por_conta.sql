-- Roteamento de conta em uma tabela so, e modo de ingest gravado no pedido.
--
-- Antes desta migracao o modo de ingestao vivia em duas tabelas que podiam
-- discordar: `erp_marketplace_links` e `channel_connections`. Cada leitura
-- consultava uma delas —
--
--   _find_direct_ingest_link          erp_marketplace_links (filtrando por
--                                     'marketplace_direct') e so entao
--                                     channel_connections
--   resolve_ingest_origin_mode_...    erp_marketplace_links, sempre
--
-- — com duas consequencias. A primeira: uma conta em `erp_bling` registrada
-- apenas em `erp_marketplace_links` era invisivel para a primeira consulta e,
-- sem linha em `channel_connections`, o webhook virava
-- `skipped_inactive_source` em vez do `pending_erp_order` pretendido. A
-- segunda: a linha que vencia a busca do Mercado Livre nao tinha `channel_id`,
-- e por isso 1.804 pedidos nasceram com `canal_venda_id` nulo enquanto
-- `channel_connections` dizia canal 9.
--
-- `pedidos.ingest_origin_mode` existe para que trocar o modo de um vinculo
-- (migrar uma conta do ERP para o marketplace direto) valha para pedidos novos
-- sem mudar retroativamente quem manda nos que ja estao em transito.

begin;

alter table public.erp_marketplace_links
    add column if not exists channel_id integer references public.canais_venda(id);

comment on column public.erp_marketplace_links.channel_id is
    'Canal de venda deste vinculo. Fonte unica: substitui channel_connections.channel_id.';

-- Backfill pelo vinculo de marketplace, que e o casamento forte.
update public.erp_marketplace_links as l
   set channel_id = c.channel_id
  from public.channel_connections as c
 where l.channel_id is null
   and c.channel_id is not null
   and l.marketplace_integration_id is not null
   and c.marketplace_integration_id = l.marketplace_integration_id;

-- Vinculos ainda sem integracao de marketplace (linhas orfas, esperando a conta
-- ser instalada) casam pela loja do ERP.
update public.erp_marketplace_links as l
   set channel_id = c.channel_id
  from public.channel_connections as c
 where l.channel_id is null
   and c.channel_id is not null
   and c.marketplace_integration_id is null
   and c.bling_integration_id = l.erp_integration_id
   and c.aggregator_store_id = l.erp_store_id;

create index if not exists idx_erp_links_channel
    on public.erp_marketplace_links (channel_id)
 where channel_id is not null;

alter table public.pedidos
    add column if not exists ingest_origin_mode text;

comment on column public.pedidos.ingest_origin_mode is
    'Modo de ingest que governa ESTE pedido, congelado na ingestao. Trocar o modo '
    'do vinculo passa a valer para pedidos novos; os em transito terminam sob a '
    'fonte que os acompanhou desde o inicio.';

-- Backfill: o modo em vigor no vinculo de cada pedido, hoje.
update public.pedidos as p
   set ingest_origin_mode = l.ingest_origin_mode
  from public.erp_marketplace_links as l
 where p.ingest_origin_mode is null
   and p.erp_integration_id = l.erp_integration_id
   and p.erp_store_id = l.erp_store_id;

update public.pedidos as p
   set ingest_origin_mode = l.ingest_origin_mode
  from public.erp_marketplace_links as l
 where p.ingest_origin_mode is null
   and p.marketplace_integration_id is not null
   and l.marketplace_integration_id = p.marketplace_integration_id;

create index if not exists idx_pedidos_ingest_origin_mode
    on public.pedidos (marketplace_integration_id, ingest_origin_mode)
 where marketplace_integration_id is not null;

commit;
