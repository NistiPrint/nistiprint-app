# Migrations históricas (arquivadas em 2026-09-01)

Estes 236 arquivos **já estão aplicados** no banco e foram tirados de
`supabase/migrations/` quando o histórico foi reiniciado com um baseline.

## Por que o corte

O livro-razão (`supabase_migrations.schema_migrations`) e o repositório estavam
descolados há meses, e não por um detalhe de nomenclatura:

| | Qtd |
| --- | --- |
| Linhas do banco que casavam com um arquivo | 78 |
| Linhas do banco **sem arquivo nenhum** | 147 |
| Arquivos **sem linha correspondente** | 126 |

As 147 sem arquivo foram aplicadas pelo editor SQL do Supabase desde janeiro —
não existe arquivo para elas em lugar nenhum. Nesse estado, um
`supabase db push` tentaria reaplicar o repositório inteiro sobre um banco que
já tem tudo.

## O que foi feito

1. `supabase db dump --schema public` gerou `migrations/00000000000000_baseline.sql`
   (124 tabelas, 146 funções, 25 views, 83 triggers, 46 policies, 118 tabelas
   com RLS, 1115 grants).
2. Estes arquivos vieram para cá. **Nada foi apagado.**
3. O livro-razão foi zerado e passou a ter uma linha só: `00000000000000 baseline`.
   Cópia do estado anterior em `supabase_migrations.schema_migrations_backup_20260901`
   (253 linhas, com o SQL de cada uma).

O schema do banco não foi tocado em nenhum momento — só o registro de quais
migrations foram aplicadas.

## Daqui em diante

Migration nova entra em `supabase/migrations/` com timestamp normal e é aplicada
por `supabase db push`. O baseline nunca é reaplicado num banco existente: ele
serve para recriar o schema do zero (ambiente novo, projeto de teste, CI).

Os arquivos aqui continuam valendo como **história**: as decisões de 2026-08-31
e 2026-09-01 (consolidação, kit, herança de ficha, higiene de SKU) estão
comentadas dentro deles, e são a referência de por que cada regra é como é.
