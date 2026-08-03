# Domain Spec: Despacho e Consolidacao

Last updated: 2026-08-02

Status: target-state

## Objective

Definir como pedidos sao agrupados para virar demanda de producao, usando a
regra logistica do marketplace como eixo de navegacao, e como o sistema
reconhece e absorve novas modalidades logisticas sem alteracao de codigo.

O escopo cobre a decisao operacional "o que eu lanco agora", nao a execucao da
producao (ver [Producao](../producao/spec.md)) nem a ingestao do pedido (ver
[Pedidos](../pedidos/spec.md)).

## Principio geral: degradar, nao bloquear

Nenhuma condicao de dado ausente ou inconsistente pode impedir o agrupamento,
o lancamento de demanda ou a producao.

- Produto do pedido sem vinculo com produto interno: prossegue com os dados do
  pedido. A reconciliacao de estoque nao ocorre para esse item. Nao bloqueia.
- Estoque insuficiente: prossegue. Nao bloqueia.
- Erro ou pendencia de NF: prossegue. Nao bloqueia.
- Modalidade logistica nao reconhecida: prossegue em no proprio, com prioridade
  maxima. Nao bloqueia.
- Origem da venda nao resolvida: prossegue em no proprio. Nao bloqueia.

A resposta do sistema a dado faltante e **visibilidade**, nunca retencao. Todo
pedido pertence a exatamente um no da arvore de despacho e sempre pode ser
lancado.

Consequencia direta nos contadores: nao existe categoria "retido" e nenhum
pedido e subtraido de um totalizador. Ver "Arvore de totalizadores".

## Actors

- Operador de despacho: decide o escopo e lanca a demanda.
- Operador de producao: consome a fila resultante, nao decide agrupamento.
- Admin: cadastra modalidades logisticas e regras de classificacao.
- Worker de ingest: classifica e carimba o pedido.

## Entities

Novas:

- `modalidades_logisticas`
- `regras_classificacao_modalidade`
- `metodos_envio_observados`

Existentes afetadas:

- `pedidos` (ganha `modalidade_logistica_id`)
- `demandas_producao` (ganha `escopo_despacho`)
- `regras_logisticas_canal` (absorvida por `modalidades_logisticas`)
- `installed_integrations`
- `pedido_snapshots`

## Core concepts

### Origem da venda

A origem da venda e sempre uma instancia de marketplace instalada, incluindo
modulos dummy. Um dummy existe justamente para carregar o `shop_id` que amarra
o ingest via Bling e e uma origem de venda de primeira classe, sem tratamento
visual diferenciado.

Bling nunca e origem da venda. Bling e origem de ingest, exposta apenas no
detalhe do pedido e na auditoria de ingest.

### Modalidade logistica

Modalidade e a regra de despacho publicada pelo marketplace (Comum, Flex,
Turbo, Full, Envios, Retirada). E um registro de cadastro, nao um enum de
codigo, e pertence a um marketplace.

### Data limite de envio

Terceiro nivel de agrupamento. Usa `pedidos.data_limite_envio`, o prazo
canonico informado pela origem. Nunca derivar de `created_at`, porque a
derivacao quebra exatamente nos casos de excecao que importam.

Buckets: `atrasado`, `hoje`, `amanha`, `depois`.

### Escopo de despacho

Par (no da arvore, horizonte) que define o conjunto de pedidos de uma demanda.
Nao existe selecao pedido a pedido no fluxo normal.

## Regras de origem da venda

- O seletor de origem lista somente `installed_integrations` de tipo
  marketplace, incluindo dummies.
- Contas Bling nao aparecem em nenhum filtro de origem da venda.
- Todo pedido deve resolver `marketplace_integration_id` no ingest, via
  `shop_id` / `loja.id`.
- Se nao resolver, o pedido vai para o no raiz `Origem nao resolvida`, com o
  identificador cru de loja visivel para cadastro. O pedido continua listavel e
  lancavel.
- Um pedido nunca recebe origem por default ou por heuristica silenciosa.

## Regras de modalidade logistica

`modalidades_logisticas` e cadastro editavel por admin. Adicionar uma
modalidade nova nao pode exigir deploy.

Campos obrigatorios:

| Campo | Papel |
| --- | --- |
| `marketplace_integration_id` | Marketplace dono da modalidade |
| `codigo`, `nome` | Identidade e rotulo de tela |
| `tipo_prazo` | `FIXO` ou `RELATIVO` |
| `politica_lote` | `LOTE` ou `INDIVIDUAL` |
| `nivel_interrupcao` | Se pode furar a fila de producao corrente |
| `ativo` | Desativacao sem perda de historico |

Campos condicionais:

- `tipo_prazo = FIXO`: `corte_horario`, `coleta_horario`, `ponto_coleta_id`.
- `tipo_prazo = RELATIVO`: `offset_etiqueta_min`, `offset_coleta_min`,
  contados a partir de `pedidos.data_pedido`.

Exemplos alvo:

- Shopee Comum: `FIXO`, corte 18:00, coleta dia seguinte 08:00, `LOTE`.
- Shopee Flex: `FIXO`, corte 12:00, coleta 13:00, `LOTE`.
- Shopee Turbo: `RELATIVO`, etiqueta +40min, coleta +60min, `INDIVIDUAL`,
  interrupcao habilitada.

## Classificacao e deteccao de modalidade nova

O ingest classifica o pedido aplicando `regras_classificacao_modalidade` em
ordem de prioridade. Cada regra casa um caminho de `pedido_snapshots.platform_fields`
(ex.: metodo de envio, servico logistico) contra um valor, e aponta para uma
modalidade.

Regras de deteccao:

1. O ingest registra em `metodos_envio_observados` todo valor distinto de
   metodo de envio por marketplace, com contagem e primeira ocorrencia.
2. Valor nunca visto gera alerta de administracao nomeando o valor cru, o
   marketplace e a contagem de pedidos afetados.
3. Pedidos com valor nao classificado vao para o no `Modalidade nao classificada`
   do marketplace, dentro da arvore, e sao exibidos com prioridade maxima.
   Prazo desconhecido e tratado como a hipotese mais urgente.
4. Ao cadastrar a modalidade e a regra, o backlog reclassifica retroativamente
   os pedidos ainda nao despachados.

Um metodo de envio desconhecido nunca e classificado como Comum ou STANDARD por
omissao. Essa e a diferenca entre replicar o dado do marketplace e antecipar a
mudanca dele.

## Arvore de totalizadores

Tres niveis fixos: marketplace, modalidade, data limite de envio.

```
Shopee (200)
  Comum (165)
    atrasado (2)
    hoje (120)
    amanha (43)
    depois (0)
  Flex (35)
  Turbo (0)
```

Invariantes:

- A soma dos filhos e sempre igual ao pai. Nenhum pedido e omitido.
- Todo pedido nao despachado pertence a exatamente um caminho da arvore.
- `atrasado` nunca colapsa e sempre aparece primeiro no seu nivel.
- O contador de conferencia e **quantidade de pedidos**, que e a unidade que o
  painel do marketplace exibe. Todo numero comparavel com a origem usa essa
  unidade.
- Quantidade de itens pode ser exibida como carga de producao, sempre em
  posicao secundaria e nunca como numero de conferencia, para nao competir com
  o contador de pedidos.
- Sinalizacoes informativas (item sem vinculo de produto, estoque insuficiente,
  NF pendente) sao exibidas como marcadores no no, sem alterar contagem.

## Escopo composto e lancamento

O operador define o escopo com duas acoes, ambas de um clique:

1. Selecionar o no: `Shopee > Comum`.
2. Selecionar o horizonte: `atrasado + hoje` (default) ou estender para
   `+ amanha`.

Ao estender o horizonte, o total recalcula na hora (`122 -> 165`), para
conferencia contra a tela do marketplace antes de lancar.

Regras:

- Nao existe checkbox por pedido no fluxo normal.
- Remover um pedido do escopo e acao de excecao, exige motivo e fica registrada
  no historico da demanda.
- `demandas_producao.escopo_despacho` guarda o escopo que originou a demanda
  (marketplace, modalidade, horizonte, data operacional), tornando o lote
  reproduzivel e auditavel.

## Modalidades de prazo relativo

Modalidades `RELATIVO` nao possuem janela diaria e nao aparecem como no
acumulavel para conferencia. Elas formam uma esteira separada.

- Fila FIFO ordenada por prazo de etiqueta.
- Cada pedido carrega o proprio relogio regressivo.
- Entrada de pedido nesta esteira notifica com destaque, independentemente da
  tela em que o operador esteja.
- Demanda de 1 pedido e o caso normal quando `politica_lote = INDIVIDUAL`.
- Quando `nivel_interrupcao` permite, o item entra a frente da fila de producao
  corrente sem exigir decisao do operador.

## Retardatarios

Pedido que chega depois que o operador ja lancou o escopo:

- Antes do lancamento: entra no rascunho, o contador do no incrementa e sinaliza.
- Depois do lancamento e antes do corte: gera lote complementar vinculado ao
  mesmo escopo. A demanda em producao nao e alterada.
- Depois do corte: cai automaticamente no proximo escopo equivalente.

A regra decide o destino. O sistema nunca pergunta ao operador onde colocar.

## Ordenacao canonica

Existe uma unica ordenacao global de demandas, compartilhada por torre de
despacho, lista de demandas e painel de producao: tempo restante ate o
compromisso logistico (corte para `FIXO`, prazo de etiqueta para `RELATIVO`).

O painel de producao e projecao somente leitura dessa mesma ordenacao. Nao ha
ordenacao alternativa por tela.

## Navegacao

| Nivel | Rota | Conteudo |
| --- | --- | --- |
| N0 | `/despacho` | Arvore de totalizadores do dia, ordenada por compromisso |
| N1 | `/despacho/:marketplaceId/:modalidadeId` | Escopo, horizonte, conferencia e lancamento |
| N1b | `/despacho/esteira` | Modalidades `RELATIVO`, FIFO por prazo |
| N2 | `/pedidos/:id` | Detalhe e excecao |
| TV | `/painel` | Projecao somente leitura da ordenacao canonica |

`/pedidos` deixa de ser tela operacional e passa a ser busca e consulta, sem
selecao em massa e sem geracao de demanda. `PedidosListPageLotAware` e
`GerarDemandaModal` sao aposentados.

## API and database contracts

Rotas alvo:

- `GET /api/v2/despacho/arvore?data=` retorna a arvore completa com contagens
  em uma unica chamada.
- `GET /api/v2/despacho/escopo?marketplace=&modalidade=&horizonte=` retorna os
  pedidos do escopo.
- `POST /api/v2/despacho/lancar` cria ou publica a demanda a partir do escopo.
- `GET /api/v2/despacho/esteira` retorna a fila de prazo relativo.
- `GET /api/v2/admin/metodos-envio?status=nao_classificado`.

Contratos de banco: ver [Supabase contracts](../../03-contracts/supabase-contracts.md)
apos a migration.

## Migration and transition

- `pedidos.is_flex` passa a ser derivado de `modalidade_logistica_id` durante a
  transicao, para nao quebrar de uma vez os consumidores atuais em API, worker,
  impressao e alertas. Removido em fase posterior.
- `demandas_producao.modalidade_logistica` (varchar) migra para FK.
- `regras_logisticas_canal` e migrada para `modalidades_logisticas`, com o
  vinculo `canal_venda_id` traduzido para `marketplace_integration_id`.
- `pontos_coleta` permanece e passa a ser referenciado pela modalidade.
- Backfill de `modalidade_logistica_id` a partir de `is_flex` e do metodo de
  envio observado em `pedido_snapshots.platform_fields`.

## Acceptance criteria

- Nenhum filtro ou seletor de origem da venda exibe conta Bling.
- Um marketplace dummy aparece na arvore em igualdade com um marketplace com
  API propria.
- A soma dos nos filhos e igual ao no pai em todos os niveis, e o total do
  marketplace e igual a contagem de pedidos nao despachados daquele
  marketplace.
- Pedido sem vinculo de produto interno, sem estoque ou com NF pendente aparece
  no contador normalmente e pode ser lancado.
- Cadastrar uma modalidade nova e criar sua regra de classificacao nao exige
  alteracao de codigo nem deploy.
- Metodo de envio nunca visto gera alerta e no `Modalidade nao classificada`,
  e nunca e classificado como Comum.
- Apos cadastro da modalidade, pedidos nao despachados sao reclassificados.
- Um pedido de modalidade `RELATIVO` aparece na esteira com relogio proprio em
  menos de um minuto apos o ingest.
- Estender o horizonte de `hoje` para `hoje + amanha` altera o total exibido
  antes do lancamento.
- A demanda gerada registra o escopo que a originou.
- Torre de despacho e painel de producao exibem a mesma ordem.

## Known gaps

- Regra de fuso e virada de dia operacional para marketplaces com corte apos
  meia-noite.
- Comportamento quando o mesmo marketplace tem duas contas Bling e cortes
  distintos por conta.
- Politica de permissao: quem pode remover pedido de um escopo.
- Se a esteira `RELATIVO` deve ter capacidade maxima configuravel antes de
  alertar sobrecarga de producao.
