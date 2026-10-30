# Importação inicial de catálogo — 29/10/2026

Importação executada em produção pelos serviços existentes, com alterações locais de código ainda sem commit, push ou publicação. Relatório final verificado contra o inventário anterior; nenhuma divergência encontrada.

## Cobertura e resultados

| Indicador | Total |
| --- | ---: |
| Anúncios consultados | 1.041 |
| Unidades externas, incluindo variações | 1.419 |
| Produtos existentes reutilizados | 37 |
| Unidades externas consolidadas em produtos equivalentes | 264 |
| Novos PAs, excluindo modelos | 1.346 |
| Novos PIs | 2.698 |
| Nova MP | 1 |
| Modelos de família | 72 |
| Total de novos registros, incluindo modelos e componentes | 4.117 |
| PAs componentes de kits, incluídos acima | 228 |
| Linhas de composição adicionadas | 3.848 |
| Cadastros com URLs de imagens | 1.227 |
| Registros do manifesto com pendências | 4.054 |
| Novos produtos ativos | 0 |
| Custos preenchidos nos novos registros | 0 |
| Erros na verificação final | 0 |

Shopee, conta 6: 299 NORMAL, 29 UNLIST e 5 SELLER_DELETE. Mercado Livre, conta 7091: 237 ativos, 451 pausados, 12 em revisão e 8 encerrados. A Shopee informa sete excluídos, mas retorna apenas cinco: os dois omitidos permanecem como lacuna de cobertura, sem cadastro inventado.

## Composições e evidências

Foram confrontadas descrições, atributos, variações e imagens. A estrutura segue o padrão confirmado pelo usuário: PA com PIs de miolo/capas e MPs de acabamento diretamente no PA quando aplicável; kits contêm PAs. O insumo CANGURU foi identificado pelo usuário como o bolso plástico interno. Materiais e consumos industriais sem comprovação permanecem pendentes, sem estimativas. Os PIs criados não devem ser considerados fichas industriais completas.

As 1.004 linhas de composição anteriores foram preservadas. A conferência também verificou preços, situação, configurações de estoque anteriores, vínculos, quantidades/unidades esperadas, duplicidades e ausência de ciclos. A repetição de seis anúncios da amostra reutilizou 58 registros e preservou os 16 vínculos, sem criar produtos, componentes ou vínculos adicionais.

As imagens estão em URLs nos atributos dos produtos. A galeria e a apresentação de pendências estão implementadas no código local; sua exibição na aplicação depende de publicação futura. Não houve alteração de anúncios nos marketplaces, saldos ou atribuições históricas de pedidos.

## Evidências privadas e retomada

Os arquivos comerciais ficam no diretório ignorado `temp/catalog-import-20261029/`:

- `report/summary.json`: totais e resultado da conferência final.
- `report/produtos-composicoes-pendencias.csv`: produtos, origens, composições e pendências por registro.
- `report/verification-snapshot.jsonl`: leitura final da base.
- `evidence.jsonl` e `mercadolivre.jsonl`: inventário anterior e anúncios coletados.
- `products-review/`: imagens e pranchas usadas na revisão visual.
- `manifest-complete.json`: manifesto final para retomada.
- Arquivos `*-audit.jsonl`: alterações e repetições dos lotes.

Usar somente o manifesto final na retomada. O executor impede a reaplicação de manifestos antigos após a criação dos PIs. `scripts/verify_catalog_import.py` compara a produção com o manifesto final e o inventário anterior, sem gravar na base.

## Validação de código

Suíte de integridade: 285 testes aprovados. Frontend: 56 testes aprovados e build concluído. Hierarquia: cinco testes aprovados. Testes específicos de famílias, kits e metadados da importação aprovados. Sem commit, push ou deploy.
