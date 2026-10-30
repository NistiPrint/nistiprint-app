-- Finaliza a normalização dos miolos por código e remove somente registros
-- sem referências em nenhuma tabela com FK para produtos.

create table if not exists public.miolo_codigo_limpeza_final_log (
  id bigserial primary key,
  produto_id bigint,
  sku text,
  nome text,
  acao text not null,
  referencias bigint not null default 0,
  observacao text,
  created_at timestamptz not null default now()
);

-- Os registros de separação são a fonte auditável dos canônicos definidos por
-- código. Não se deriva código de nomes descritivos de miolos antigos.
create temp table _miolos_canonicos on commit drop as
select distinct on (canonical_id)
  canonical_id as produto_id,
  codigo
from public.miolo_codigo_separacao_log
where canonical_id is not null
order by canonical_id, id desc;

-- Garante o padrão operacional dos canônicos.
update produtos p
set nome = 'Miolo ' || c.codigo,
    sku = 'MIOLO-' || c.codigo,
    categoria_id = 6,
    tipo_material = 'intermediario'
from _miolos_canonicos c
where p.id = c.produto_id;

insert into public.miolo_codigo_limpeza_final_log
  (produto_id, sku, nome, acao, observacao)
select p.id, p.sku, p.nome, 'canonico_normalizado', c.codigo
from produtos p
join _miolos_canonicos c on c.produto_id = p.id;

-- Conta referências de todas as FKs que apontam para produtos. Isso cobre BOM,
-- demandas, estoque, pedidos, OPs, artes, anúncios, históricos e tabelas
-- auxiliares, evitando exclusão baseada em uma lista parcial.
create temp table _miolos_referencias (
  produto_id bigint primary key,
  referencias bigint not null default 0
) on commit drop;

insert into _miolos_referencias (produto_id)
select p.id
from produtos p
where p.categoria_id = 6
  and not exists (select 1 from _miolos_canonicos c where c.produto_id = p.id)
  and p.sku not like 'PI-IMP-%';

do $$
declare
  r record;
begin
  for r in
    select distinct
      tc.table_schema,
      tc.table_name,
      kcu.column_name
    from information_schema.table_constraints tc
    join information_schema.key_column_usage kcu
      on kcu.constraint_name = tc.constraint_name
     and kcu.constraint_schema = tc.constraint_schema
    join information_schema.constraint_column_usage ccu
      on ccu.constraint_name = tc.constraint_name
     and ccu.constraint_schema = tc.constraint_schema
    where tc.constraint_type = 'FOREIGN KEY'
      and tc.table_schema = 'public'
      and ccu.table_schema = 'public'
      and ccu.table_name = 'produtos'
      and not (tc.table_name = 'produtos' and kcu.column_name = 'id')
  loop
    execute format(
      'update _miolos_referencias r
          set referencias = r.referencias + x.total
         from (
           select p.produto_id, count(*)::bigint as total
           from _miolos_referencias p
           join %I.%I t on t.%I = p.produto_id
           group by p.produto_id
         ) x
        where r.produto_id = x.produto_id',
      r.table_schema, r.table_name, r.column_name
    );
  end loop;
end $$;

insert into public.miolo_codigo_limpeza_final_log
  (produto_id, sku, nome, acao, referencias, observacao)
select p.id, p.sku, p.nome,
       case when r.referencias = 0 then 'candidato_remocao_sem_referencia'
            else 'preservado_com_referencia' end,
       r.referencias,
       'não é canônico por código; pendência preservada quando há referência'
from produtos p
join _miolos_referencias r on r.produto_id = p.id;

-- Remove apenas miolos sem referências. Os PI-IMP permanecem para revisão
-- porque representam importações sem classificação segura.
delete from produtos p
using _miolos_referencias r
where p.id = r.produto_id
  and r.referencias = 0;

insert into public.miolo_codigo_limpeza_final_log
  (produto_id, sku, nome, acao, referencias, observacao)
select r.produto_id, p.sku, p.nome, 'miolo_removido_sem_referencia', 0,
       'registro excluído após validação de todas as FKs'
from _miolos_referencias r
left join produtos p on p.id = r.produto_id
where p.id is null;

-- Mantém a trilha de pendências de produtos elegíveis sem BOM.
insert into public.miolo_codigo_limpeza_log
  (run_id, action, codigo, produto_id, details)
select gen_random_uuid(), 'sem_bom', split_part(p.sku, '_', 1), p.id,
       jsonb_build_object('sku', p.sku, 'nome', p.nome, 'categoria_id', p.categoria_id)
from produtos p
where p.categoria_id in (7, 11)
  and p.formato <> 'kit'
  and not exists (select 1 from ficha_tecnica ft where ft.produto_pai_id = p.id)
  and not exists (
    select 1 from public.miolo_codigo_limpeza_log l
    where l.produto_id = p.id and l.action = 'sem_bom'
  );

-- Reforça a regra de demanda após a consolidação.
update itens_demanda d
set miolo_nome = d.miolo_chave
where d.miolo_chave is not null
  and d.miolo_nome is distinct from d.miolo_chave;

