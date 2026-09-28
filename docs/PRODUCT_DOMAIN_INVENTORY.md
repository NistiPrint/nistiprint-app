# Inventário do domínio Produtos

Data da inspeção: 2026-09-27. Escopo: schema/migrations do checkout e leitura somente de leitura do projeto Supabase via MCP. `list_migrations` do MCP retornou lista vazia, então a reconciliação usa o schema e as funções efetivamente instaladas.

## Estado remoto observado via MCP

- `produtos` remoto tem `tipo_produto`, enum `estagio_produto`, campos fiscais, `personalizado`, confirmação de arte e outros campos ausentes de `schema.sql`.
- `ficha_tecnica.grupo` e `categorias.grupo_bom` existem. `categorias.permite_arte` está aplicada.
- Existem `produto_pai_eixos`, `produto_eixos`, `produto_eixo_opcoes`, `produto_variacao_valores` e `produto_variacao_backfill_revisao`.
- Existem as funções `bom_efetiva_produto`, `produto_prontidao`, `listar_produtos_prontidao` e `clonar_produto_interno`. A clonagem remota ainda é a versão antiga de três parâmetros que gera SKUs dos filhos.

### Resumo remoto do catálogo

| Medida | Resultado |
| --- | ---: |
| Produtos | 358 |
| `status=ativo` e `estagio=PUBLICADO` | 352 |
| `status=inativo` e `estagio=RASCUNHO` | 5 |
| `status=rascunho` e `estagio=RASCUNHO` | 1 |
| Linhas de ficha | 987 |
| Linhas com `grupo` gravado | 0 |
| Revisões de grupo ainda pendentes | 985 |
| Sugestões pendentes: Acabamento / Contra / Miolo / Capa / Embalagem | 767 / 129 / 44 / 40 / 3 |
| Linhas órfãs | 2 |
| Ciclos detectados | 0 |
| Produtos sem categoria | 1 |
| Produtos `formato=simple` com ficha efetiva | 69 |
| Variações sem eixos configurados completos | 0 |
| Manufaturados/kits sem ficha efetiva | 0 |

O único produto sem categoria é `EMPACOTAMENTO` (id 28), ativo e publicado. As linhas órfãs são ids 87 (`MIOLO-LIVRO-BEBE` → `LIVBB`) e 134 (`MIOLO-NP-CADMNAPFL` → `VACMNA`), sem IDs de pai/componente.

As famílias têm um nível: há 6 modelos raiz ativos e 32 variações, todos classificados como matéria-prima. Pela estrutura efetiva, há 296 produtos individuais manufaturados com ficha, 24 individuais sem ficha, 6 modelos sem ficha e 32 variações sem ficha.

### Prontidão e ficha efetiva remotas

O enum `estagio_produto` usa `RASCUNHO`, `ARTE_PENDENTE`, `ARTE_OK`, `FICHA_OK`, `CANAL_OK`, `PUBLICADO` e `DESCONTINUADO`. `produto_prontidao` reflete um processo histórico: suas pendências atuais incluem arte não confirmada (299 produtos), ficha ausente (62), custo ausente (48), ficha incompleta (42) e apelido externo ausente (1). Arte e canal devem ser avisos não bloqueantes no domínio novo, e preço/fiscal ficam para depois; portanto, `proximo_estagio` não é diretamente a prontidão proposta.

O helper `grupo_bom_do_componente` infere grupo pela linha, categoria, configuração de miolo, nome do componente e regras de categoria. As 987 linhas estão sem grupo e 985 revisões seguem sem confirmação, então essa classificação permanece provisória. Não ativar substituição de ficha por grupo até revisar as exceções.

O advisor MCP sinalizou seis tabelas com RLS desabilitada; duas pertencem à evolução de Produtos: `ficha_tecnica_classificacao_pendente` e `produto_variacao_backfill_revisao`. RLS não foi alterada, pois habilitá-la sem políticas pode bloquear acesso. O advisor também lista tabelas com RLS ativa sem políticas e avisos de índices duplicados/não usados fora do escopo deste trabalho.

### Fundações aplicadas nesta entrega

- Foram aplicadas as migrations remotas `produtos_familia_nivel_unico` e `produto_dominio_prontidao` (registradas pelo Supabase como versões `20260927191532` e `20260927192201`). Os gatilhos rejeitam famílias com mais de um nível e linhas de ficha sem componente/quantidade válida ou que introduzam ciclo direto/indireto. Testes transacionais de ciclo e profundidade foram executados com rollback; ambos os gatilhos estão habilitados.
- `produto_dominio_prontidao(id)` é a leitura SQL canônica para papel, estrutura, prontidão e pendências por códigos estáveis. O método Python `evaluate_readiness` agora chama essa RPC e devolve o mesmo objeto à API, evitando manter duas implementações com resultados divergentes. A comparação de paridade fica garantida pelo caminho comum; os testes locais cobrem o contrato e o encaminhamento da RPC.
- A avaliação foi executada para todos os 358 produtos: 357 prontos, um não pronto (`EMPACOTAMENTO`, por `CATEGORY_REQUIRED`); 352 ativos, 5 inativos e 1 rascunho. Há 299 avisos de arte, 295 avisos de revisão de grupo, um aviso de canal e 62 produtos sem ficha efetiva. Os avisos não bloqueiam ativação. O catálogo e suas 987 linhas de ficha permaneceram inalterados.
- Leitura Python de ficha simples e em lote agora usa `bom_efetiva_produto(s)` como fonte canônica, incluindo grupo, origem e linha. A interface mostra esses dados e a explosão recursiva apresenta ciclos e limite de profundidade como erros identificáveis.
- O cadastro agora exibe prontidão e mensagens específicas no cabeçalho persistente; a lista abre a variação diretamente e o cadastro da variação oferece retorno à família. A ação de ativar permanece indisponível até a transição comercial centralizada ser implementada.
- A migration local de clonagem com SKUs explícitos ainda não foi aplicada ao remoto. A função remota `clonar_produto_interno` continua na versão antiga de três argumentos e deve ser atualizada em etapa controlada.

## Schema disponível no repositório

| Relação/campo | Estado observado |
| --- | --- |
| `produtos` | `parent_id`, `formato`, `herdar_dados_pai`, `herdar_bom_pai`, `status`, `tipo_material`, `categoria_id` e `unidade_medida_id`. Não há colunas próprias para papel, estrutura ou prontidão. |
| `ficha_tecnica` | Relação pai/componente por IDs, quantidade e unidade, mais campos SKU denormalizados. No snapshot local falta `grupo`, embora exista no banco remoto. |
| `categorias` | Tem `comercializavel` e `componente`. O banco remoto também tem `permite_arte` e `grupo_bom`, ausentes do snapshot local. |
| `estoque_atual` | Saldo, reservado, disponível derivado e níveis mínimo/máximo. |
| `itens_demanda` | Referencia produto, permitindo ao menos auditar uso operacional; a exclusão também precisa considerar pedidos, movimentações e histórico associados. |

Há drift relevante: `tipo_produto` não aparece na declaração de `produtos` em `schema.sql`, mas existe no banco remoto e é usado pela migration de clonagem. A migration de maio documenta a sincronização de `tipo_produto` com `tipo_material`; os dois campos não devem ser tratados como atributos independentes.

## Migrations e proposta histórica

- A migration de clonagem `20260926130000_clonar_produto_interno.sql` está **não commitada** na árvore local. Ela define `clonar_produto_interno` e copia uma família numa transação. Nesta entrega, a RPC passou a receber um mapa explícito de SKU por variação e valida a lista inteira antes do primeiro `INSERT`.
- As migrations de produto citadas por `PRODUCT_REFACTORING_REVIEW.md` — incluindo `bom_efetiva_produto`, `produto_prontidao` e `despacho_consolidar_pedidos` — não estão presentes em `supabase/migrations` deste checkout. O próprio documento relata drift e defeitos históricos; não é evidência suficiente do estado aplicado hoje.
- `PRODUCT_REFACTORING.md` se declara proposta histórica e descreve outro ponto de partida. Suas decisões de domínio são referência, mas seus números de catálogo e de produção não foram revalidados nesta inspeção.

## Código e alterações locais

Há alterações não commitadas em `apps/api/routes/produtos_api.py`, `apps/frontend/src/pages/produtos/ProdutoFormPage.jsx`, `ProdutoListPage.jsx`, `VariationManager.jsx` e `packages/shared/nistiprint_shared/services/product_service.py`, além de uma migration de clonagem e testes novos. Foram preservadas.

O fluxo atual ainda usa `formato` tanto para topologia quanto para composição. A aba de variações foi liberada para composição e kit; o formulário inicia novos produtos como `rascunho`; e a clonagem local exige SKU do modelo e das variações. `parent_id` e `formato='variacao'` identificam papel implicitamente. No remoto há grupo em linha, mas nenhuma das 987 linhas tem grupo persistido.

## Exceções legadas

`GET /produtos/<id>/readiness` e o campo `readiness` do detalhe usam a RPC nova `produto_dominio_prontidao`; permanecem informativos e não mudam o status comercial. A função histórica `produto_prontidao` segue instalada, mas seus estágios e pendências divergem do contrato novo.

## Próximos passos de fundação

1. Resolver as 2 linhas órfãs e revisar as 985 classificações pendentes antes de persistir grupos; atualmente o BOM efetivo usa inferência provisória.
2. Registrar a exceção de categoria de `EMPACOTAMENTO` e reconciliar os 69 formatos `simples` que têm ficha antes da migração explícita de estrutura.
3. Reconciliar a migration local de clonagem com o schema remoto e substituir a RPC remota antiga; preservar pré-validação de SKU para toda a família.
4. Completar a UI de pendências/ativação e as revisões explícitas da grade, edição ativa, herança por grupo e exclusão com dependências.
5. Depois do saneamento e registro das exceções, migrar os formatos e habilitar transições comerciais; a avaliação atual ainda não aplica bloqueio de ativação.
