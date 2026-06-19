create or replace function public.repair_personalized_classification(
    p_pedido_ids bigint[] default null,
    p_source text default 'shopee'
)
returns table (
    matched_items integer,
    updated_items integer,
    updated_orders integer,
    updated_bling_orders integer
)
language plpgsql
as $$
declare
    v_matched_items integer := 0;
    v_updated_items integer := 0;
    v_updated_orders integer := 0;
    v_updated_bling_orders integer := 0;
begin
    with candidate_items as (
        select
            ip.id as item_id,
            p.id as pedido_id,
            p.pedido_bling_id,
            position('personaliz' in lower(coalesce(ip.descricao, ''))) > 0 as should_be_personalized
        from public.itens_pedido ip
        join public.pedidos p on p.id = ip.pedido_id
        left join public.canais_venda cv on cv.id = p.canal_venda_id
        where (p_pedido_ids is null or p.id = any(p_pedido_ids))
          and (
              p_source is null
              or lower(coalesce(cv.slug, p.origem, '')) = lower(p_source)
          )
    ),
    updated_item_rows as (
        update public.itens_pedido ip
           set personalizado = ci.should_be_personalized,
               updated_at = now()
          from candidate_items ci
         where ip.id = ci.item_id
           and coalesce(ip.personalizado, false) is distinct from ci.should_be_personalized
        returning ip.id
    ),
    order_flags as (
        select
            ci.pedido_id,
            ci.pedido_bling_id,
            bool_or(ci.should_be_personalized) as should_be_personalized
        from candidate_items ci
        group by ci.pedido_id, ci.pedido_bling_id
    ),
    updated_order_rows as (
        update public.pedidos p
           set personalizado = of.should_be_personalized,
               updated_at = now()
          from order_flags of
         where p.id = of.pedido_id
           and coalesce(p.personalizado, false) is distinct from of.should_be_personalized
        returning p.id
    ),
    updated_bling_rows as (
        update public.pedidos_bling pb
           set personalizado = of.should_be_personalized,
               updated_at = now()
          from order_flags of
         where pb.id = of.pedido_bling_id
           and coalesce(pb.personalizado, false) is distinct from of.should_be_personalized
        returning pb.id
    )
    select
        count(*) filter (where should_be_personalized)::integer,
        (select count(*)::integer from updated_item_rows),
        (select count(*)::integer from updated_order_rows),
        (select count(*)::integer from updated_bling_rows)
    into
        v_matched_items,
        v_updated_items,
        v_updated_orders,
        v_updated_bling_orders
    from candidate_items;

    return query
    select
        coalesce(v_matched_items, 0),
        coalesce(v_updated_items, 0),
        coalesce(v_updated_orders, 0),
        coalesce(v_updated_bling_orders, 0);
end;
$$;
