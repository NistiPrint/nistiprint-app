# Organização de famílias — 30/10/2026

## Resultado na base

Foram atualizados os atributos das variações de 97 anúncios com múltiplos
produtos vinculados, usando os adaptadores atuais em memória no servidor.
O procedimento não publicou código da aplicação nem alterou os marketplaces.

- Dez agregadores novos foram criados, incluindo famílias de kits.
- Na conferência final, 55 anúncios estavam organizados e 42 ficaram pendentes.
- Uma repetição final retornou 55 `unchanged` e 42 `pending`: nenhum novo
  agregador ou incorporação adicional.
- Das pendências, 41 envolvem opções incompatíveis ou incompletas entre anúncios;
  uma envolve produtos pertencentes a famílias diferentes. Não foram forçados
  remanejamentos entre famílias.
- A comparação dos 3.969 registros anteriores encontrou zero diferenças em SKU,
  nome, descrição, status, preços, dados de estoque, estrutura, categoria e tipo
  de material. Todas as linhas da ficha técnica foram preservadas.

Evidência privada, ignorada pelo Git: `temp/catalog-families-20261030/` contém
`evidence.jsonl`, `final-snapshot.json` e `preservation.json`.

## Migrações

Foram aplicadas pelo MCP, após conferir o histórico e validar em PostgreSQL
descartável:

- `20261030120000_catalogo_organizacao.sql`: persistência dos atributos na
  sincronização, vínculo entre anúncio e família e RPC de incorporação.
- `20261030121000_catalogo_organizacao_canonical_names.sql`: reutilização dos
  nomes canônicos dos eixos e opções, inclusive quando a capitalização externa
  difere. Corrigiu conflitos de códigos únicos encontrados na execução inicial.

Não reaplicar os arquivos em produção: conferir os nomes no ledger remoto.

## Aplicação

As alterações de API, frontend e worker estão no checkout, sem commit, push ou
deploy nesta execução. Após publicação, a sincronização completa encadeia a
reconciliação e a organização. A tela de anúncios permite repetir a organização
por conta e mostra o agregador ou o motivo da pendência. A Central de Operações
recebe os totais por resultado.

A listagem usa `view=hierarquia`, pagina famílias, inclui o pai quando a busca
encontra um filho e apresenta variações expansíveis com miniaturas. A consulta
atual lê o catálogo em páginas de 500 registros antes de paginar as famílias;
essa implementação deve ser movida para consulta SQL dedicada se o crescimento
do catálogo tornar esse custo relevante.

## Validação

- 285 testes de integridade operacional aprovados.
- Quatro testes da API de catálogo e quatro da listagem aprovados.
- Três testes frontend de imagens e hierarquia aprovados; build aprovado.
- PostgreSQL descartável: criação, preservação de kits, repetição e atributos
  incompletos aprovados; duas transações concorrentes criaram um único pai.
- ESLint dos módulos frontend alterados: zero erros; um aviso de dependência
  do hook de carregamento na lista.
- Verificação de rotas acusa `/produtos/composicao-lote` fora do menu e das
  exceções. Essa rota não foi alterada nesta entrega.

O script `scripts/organize_catalog_families.py` recupera atributos e organiza os
anúncios existentes; não equivale a uma varredura completa de todos os anúncios
das contas. O ciclo automático completo deve ser observado após publicar os
workers atualizados.
