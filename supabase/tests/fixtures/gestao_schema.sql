-- Minimal disposable PostgreSQL fixture. Never run against an application database.
CREATE ROLE anon;
CREATE ROLE authenticated;
CREATE ROLE service_role;
CREATE TABLE public.recursos(id serial PRIMARY KEY,nome text UNIQUE,descricao text);
CREATE TABLE public.installed_integrations(id integer PRIMARY KEY,instance_name text);
CREATE TABLE public.produtos(id integer PRIMARY KEY,preco_custo numeric);
CREATE TABLE public.produto_anuncios(id integer PRIMARY KEY,integration_id integer,item_externo_id text,variacao_externa_id text,produto_id integer);
CREATE TABLE public.pedidos_bling(id integer PRIMARY KEY,raw_payload jsonb);
CREATE TABLE public.pedidos_shopee(id integer PRIMARY KEY,raw_payload jsonb);
CREATE TABLE public.pedidos_mercadolivre(id integer PRIMARY KEY,raw_order jsonb,raw_shipment jsonb);
CREATE TABLE public.pedidos(id integer PRIMARY KEY,marketplace_integration_id integer,
 pedido_bling_id integer,pedido_shopee_id integer,pedido_mercadolivre_id integer,
 marketplace_module_id text,data_compra_marketplace timestamptz,marketplace_lifecycle_stage text,total_pedido numeric);
CREATE TABLE public.itens_pedido(id integer PRIMARY KEY,pedido_id integer REFERENCES public.pedidos(id) ON DELETE CASCADE,
 produto_id integer,sku_externo text,quantidade numeric,preco_unitario numeric,subtotal numeric);
CREATE TABLE public.pedido_snapshots(id integer PRIMARY KEY,pedido_id integer UNIQUE REFERENCES public.pedidos(id) ON DELETE CASCADE,customer jsonb);
CREATE TABLE public.personalizacoes_pedido(id integer PRIMARY KEY,item_pedido_id integer REFERENCES public.itens_pedido(id),customization_name text,status text);
CREATE TABLE public.mercadolivre_personalizations(id integer PRIMARY KEY,pedido_id integer REFERENCES public.pedidos(id),item_pedido_id integer,customization_name text,status text);
