# Revisão de SKUs, equivalências e consumos — 29/10/2026

Esta revisão sucede a importação inicial e usa um novo inventário de produção. Entre as duas etapas houve uma consolidação de miolos: 506 PIs foram removidos e seus vínculos transferidos. O manifesto original não representa mais a base atual e sua reaplicação foi bloqueada pelo executor.

## Resultado aplicado

- 188 cadastros equivalentes consolidados; 221 unidades de anúncios passaram a apontar aos produtos canônicos. A revisão confrontou SKU, imagens, páginas, edição e composição do conjunto. Os registros substituídos permanecem inativos, identificados como consolidados e com referência ao destino, preservando os IDs históricos.
- 69 SKUs comerciais corrigidos para conservar o SKU da origem com sufixo nos conflitos de edição, kit ou oferta. O usuário autorizou os sufixos nesta conversa.
- 50 anúncios sem SKU receberam uma referência interna explícita `SEM-SKU-<anúncio>[-<variação>]`; o SKU comercial ausente continua pendente. Não foram gravados SKUs nos marketplaces.
- 19 miolos existentes tiveram papel/tinta completados ou corrigidos, e 67 novos miolos receberam essas duas MPs. Foram corrigidos 467 vínculos de PAs com miolos para separar tipos, páginas e pautas comprovadamente diferentes.

O papel usa a regra informada pelo usuário: `ceil(páginas / 4)`. A tinta usa a proporção predominante dos miolos manuais: 0,017 por folha, comprovada no miolo 7, cuja receita contém 51 folhas e 0,867 de tinta. As unidades cadastradas das MPs foram preservadas. Exemplo: 210 páginas → 53 folhas → 0,901 de tinta.

A conferência definitiva retornou zero erros. Nenhum produto atualmente vinculado a anúncio mantém SKU iniciado por `IMP-`, e nenhuma unidade de anúncio aponta para um registro consolidado. A repetição final gerou somente os eventos de conferência da referência e conclusão: zero novos produtos, linhas de composição ou vínculos.

Não se aplicou sulfite branco a papel preto, kraft ou gramaturas especiais sem comprovação. Páginas de seções não foram somadas ao total, e a expressão `200 páginas = 100 folhas` não foi interpretada como dois totais de páginas.

## Pendências e preservação

Produtos com mesmo SKU e capas, edições ou especificações divergentes continuam separados e sinalizados. Permanecem 50 referências sem SKU comercial; também há grupos de miolos sem total comprovado, com totais conflitantes ou com papel especial. Arquivos de impressão e outros consumos industriais não comprovados continuam pendentes.

A consolidação anterior havia associado 677 PAs ao DEV365, incluindo tipos e quantidades de páginas diferentes. A revisão separou os casos comprovados dos cadastros importados; não atribuiu uma receita genérica aos casos desconhecidos.

Não houve alteração de saldos, preços, custos, observações comerciais externas ou atribuições históricas de pedidos. Os novos miolos permanecem inativos e sem custo calculado. A repetição do lote de consolidação e de uma amostra com SKU e miolo não criou produtos, vínculos ou linhas adicionais.

## Artefatos privados

Diretório ignorado: `temp/catalog-import-20261029/`.

- `revision-before/verification-snapshot.jsonl`: inventário anterior a esta revisão.
- `revision-plan.json`: plano final autorizado, incluindo política de sufixos e evidências.
- `revision-report/summary.json`: conferência final.
- `revision-report/miolos-consumos.csv`: receitas corrigidas, páginas e quantidades.
- `revision-report/pendencias.json`: conflitos e informações ausentes.
- `duplicate-review-*.jpg` e `extra-duplicate-review-*.jpg`: pranchas da revisão visual.
- `revision-*-audit.jsonl`: alterações e repetições, com estado anterior.

A retomada usa `scripts/apply_catalog_revision.py` com o plano final salvo. A conferência, sem gravações, usa `scripts/verify_catalog_revision.py`. Não regenerar o plano contra inventários antigos para incorporar novas alterações sem nova revisão.

## Código local

Busca e listagem de produtos excluem referências consolidadas das escolhas operacionais. O formulário mostra o destino canônico ao abrir um ID consolidado. Essas mudanças de apresentação estão locais e dependem de publicação; não houve commit, push ou deploy nesta revisão.

Validação: quatro testes das regras de páginas e tinta, suíte de integridade com 285 testes aprovados e build do frontend concluído.
