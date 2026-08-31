# Domain Spec: Despacho e Consolidacao

Last updated: 2026-08-31

Status: target-state

## Objective

Definir como pedidos sao agrupados para virar demanda de producao, usando a
regra logistica do marketplace como eixo de navegacao, e como o sistema
reconhece e absorve novas modalidades logisticas sem alteracao de codigo.

O escopo cobre a decisao operacional "o que eu lanco agora", nao a execucao da
producao (ver [Producao](../producao/spec.md)) nem a ingestao do pedido (ver
[Pedidos](../pedidos/spec.md)).

Uma planilha de marketplace e uma terceira origem de selecao. O operador envia
o arquivo em `/despacho/arquivo`, escolhe o filtro e o sistema persiste uma
`conferencias_arquivo`. O conjunto apos o filtro, e nao o arquivo inteiro nem
o no inteiro da torre, e o lote congelado da conferencia.

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
Nao existe selecao pedido a pedido no fluxo normal. Para arquivo, a chave e
`conferencia_id`; as linhas normalizadas e o filtro aplicado ficam persistidos.

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

A classificacao roda no **banco**, por trigger em `pedido_snapshots` e
`pedidos`, nao no worker de ingest. O extrator Python continua existindo e
continua correto, mas deixou de ser a unica garantia: pedido entra por webhook
de marketplace, por ingest de ERP e por reprocessamento manual, e uma regra que
vale para todo pedido pertence ao lugar por onde todo pedido passa.

O que motivou a mudanca: apos o backfill inicial, todo pedido novo voltou a
entrar sem modalidade — inclusive um Flex obvio, com o dado correto ja gravado
no snapshot. A regra estava certa, o dado estava certo, e a correcao do
extrator estava no repositorio e nao no processo em execucao.

O ingest classifica o pedido aplicando `regras_classificacao_modalidade` em
ordem de prioridade. Cada regra casa um caminho de `pedido_snapshots.platform_fields`
(ex.: metodo de envio, servico logistico) contra um valor, e aponta para uma
modalidade.

Tres alvos, do mais confiavel para o menos:

| Alvo | Fonte | Prioridade |
| --- | --- | --- |
| `CHAVE` | `pedidos.metodo_envio_chave` — `logistics_channel_id` (Shopee, dentro de `package_list[]`), `logistic_type` (ML) | 10..99 |
| `ROTULO` | `pedidos.metodo_envio_rotulo` — `shipping_carrier` | 900 |
| `CANONICA` | `pedidos.modalidade_logistica`, derivado por `logistics_canonicalization` | 950 |

O alvo `CANONICA` e desvio consciente da regra "nunca classificar como Comum
por omissao" logo abaixo: `logistics_canonicalization` grava `STANDARD` tambem
quando nao reconhece sinal nenhum. Decisao de 02/08/2026: o custo de o volume
inteiro aparecer como nao classificado e maior que o de um canal exotico cair
em Comum. Existe so como ultimo recurso, para o pedido ingerido via Bling, que
nao carrega `package_list`. Onde a chave estavel discorda da canonica, a chave
ganha — e ela ja provou estar certa: a canonicalizacao rotulou como STANDARD 38
pedidos de Retirada e 2 de Turbo que o `logistics_channel_id` acertou.

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

## Canais de envio: observar, nao cadastrar

A lista de canais de um marketplace nao vem de catalogo cadastrado nem de um
endpoint da plataforma. Catalogo desatualiza em silencio; nem toda plataforma
expoe a lista. `metodos_envio_observados` guarda o distinct do trafego ja
ingerido, com contagem e primeira ocorrencia — canal novo aparece sozinho, sem
deploy.

A tela vive em Integracoes > Logistica e tem duas partes:

| Secao | O que resolve | Escopo |
| --- | --- | --- |
| Canais de envio | canal observado -> modalidade | por marketplace (o canal e da plataforma) |
| Janela de coleta | modalidade -> corte, coleta, ponto | por conta (varia entre lojas) |

A separacao nao e cosmetica: "Shopee Xpress" significa a mesma coisa em toda
conta Shopee, mas o horario de corte nao. Associar canal por conta obrigaria a
repetir a mesma decisao N vezes e permitiria N respostas diferentes para a
mesma pergunta.

Associar reclassifica retroativamente os pedidos **pendentes** que usam o
canal. Pedido ja despachado nao muda: a demanda que o levou para producao ja
existe, e reescrever a modalidade dele reescreveria a historia do lote.

Desassociar desativa a regra, nunca apaga. Quem associou o que e historico de
cadastro — um DELETE apagaria a explicacao de por que 4 mil pedidos foram para
Comum na semana passada.

Consequencia de design: a tela nunca fica "completa". Ela fica **zerada**,
quando nenhum canal esta sem modalidade. E fila de trabalho, nao cadastro.

## Criterio de pendencia

A torre conta apenas pedido que ainda e trabalho do galpao:

- `despachado_em IS NULL`, e
- `situacao_pedido_id IN (2, 3, 4)` — Em Andamento, Produzido, Pronto para
  Envio, e
- modalidade com `entra_na_torre = true` (fallback `NOT is_fulfillment` para o
  pedido ainda nao classificado), e
- nao pertence a demanda publicada (status diferente de `RASCUNHO` e nao
  cancelada).

Rascunho continua aparecendo na torre para permitir conferencia, mas o
lancamento recusa pedidos que ja estejam em outro rascunho aberto e devolve a
demanda existente para o operador abrir.

## Corte e coleta

Sao dois momentos com papeis distintos, e confundi-los custa lote:

| | O que e | Papel |
| --- | --- | --- |
| Corte | horario que fecha o lote | regra de **pertencimento** |
| Coleta | quando a transportadora passa | **prazo de producao** e processo fisico |

O corte **nao e prazo de producao**. Ele responde "quais pedidos entram nesta
coleta":

> Mercado Livre Comum, corte 13h, coleta 17h. Todos os pedidos feitos ate as
> 13h precisam ser produzidos e enviados ate as 17h. Os feitos depois das 13h
> saem na proxima coleta.

Quem chega 13h05 nao esta atrasado — esta no proximo lote. Por isso o card diz
"lote fecha as 13h", nunca "pronto ate as 13h".

O pertencimento e resolvido por `coleta_do_pedido`, a partir de
`data_pagamento_marketplace`. Pedido cujo lote ja saiu inteiro (ultima janela
vencida) cai no proximo — continua atrasado perante o marketplace, o que os
buckets de prazo mostram, mas o caminhao dele agora e outro.

### Duas saidas para o mesmo lote

Um corte pode ter mais de uma janela de despacho:

> Shopee Comum, corte 13h, coleta local 17h **e** entrega em ponto de coleta 19h.

Sao duas chances para o MESMO lote, nao dois lotes. Cadastro: duas linhas em
`regras_logisticas_integracao` com o mesmo `horario_corte` e `tipo_envio`
diferente.

O **prazo final e a ultima saida**. Uma demanda com coleta 17h e envio 19h que
teve coleta parcial as 17h continua no prazo ate as 19h: ainda ha caminhao.
Marca-la como atrasada as 17h01 diria ao operador que ele falhou quando ele
ainda tem duas horas para levar o resto.

A demanda congela as proprias janelas em `escopo_despacho.janelas` no
fechamento. Um lote fechado hoje nao pode ser julgado atrasado por um horario
que alguem editou na aba Logistica amanha.

### Janela calculada na leitura

`corte_em` e `coleta_em` sao calculados por `proxima_janela_logistica` a cada
consulta, e **sempre no futuro**. Uma janela diaria recorrente — "corte 13:00"
— nao e um instante, e uma regra que se repete; guardar a proxima ocorrencia
como timestamp cria um valor que envelhece sozinho toda meia-noite.

`dias_semana` e respeitado: consultada num sabado, uma modalidade Seg-Sex
devolve a segunda.

`pedidos.compromisso_logistico_em` permanece armazenado e correto **apenas para
`RELATIVO`**, que ancora em `data_venda` e pode legitimamente estar no passado —
atraso de Turbo e informacao real. Para `FIXO` a coluna e mantida por rotina,
so para consumidores legados (ver abaixo).

### Fechamento automatico da janela

Uma task roda em cada horario de corte e de coleta cadastrado na aba Logistica.
Ela **nao** e o que mantem a torre correta — o calculo na leitura ja garante
isso. Ela faz o que calculo nenhum faz: agir no instante em que a janela vira.

| Janela | Efeito |
| --- | --- |
| Corte | fecha o lote e cria a demanda `RASCUNHO` com os pedidos daquele momento |
| Coleta | regrava `compromisso_logistico_em` dos pedidos `FIXO` pendentes |

A distincao define o modo de falha, e e o ponto principal deste desenho: job
parado significa automacao perdida naquele ciclo, nunca numero errado na tela.

O fechamento cria `RASCUNHO` e nunca publica. A conferencia contra o painel do
marketplace e o proposito da torre, e um job nao pode faze-la. Tambem nao
carimba `despachado_em`: rascunho nao e despacho, e o pedido continua na torre
ate alguem publicar.

**Idempotencia.** `janelas_despacho_execucoes` tem unique em
(integracao, modalidade, tipo, janela). `despacho_fechar_corte` reserva a
janela antes de trabalhar, entao chamada repetida ou concorrente nao cria
segundo lote — a guarda esta na propria funcao, nao na disciplina de quem
chama.

**Catch-up.** O job pergunta `janelas_despacho_vencidas` em vez de assumir que
rodou na hora. Beat reiniciado, worker fora do ar ou horario editado na tela
nao fazem o lote ser pulado em silencio: a janela e recuperada na proxima
execucao, dentro de 26h.

Lista positiva, nunca negativa por `flag_cancelado`: a negativa deixaria
Enviado e Entregue dentro do escopo, e quebra de novo assim que alguem criar
uma situacao nova.

`despacho_arvore` e `despacho_escopo_pedidos` compartilham esse predicado
palavra por palavra. Se divergirem, a tela promete um total que o lancamento
nao entrega — e o lancamento carimba `despachado_em` em pedido que nao devia
estar la.

Full / fulfillment nao entra: quem despacha e o marketplace. O pedido continua
classificado e visivel no detalhe, apenas fora do contador de conferencia.

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

A janela de coleta de uma modalidade `RELATIVO` e cadastrada na mesma tela das
demais (Integracoes > Logistica), mas com outra forma: minutos apos a venda em
vez de hora de parede.

| | `FIXO` | `RELATIVO` |
| --- | --- | --- |
| Campos | `horario_corte`, `horario_coleta` | `offset_etiqueta_min`, `offset_coleta_min` |
| Ancora | hora do dia | `pedidos.data_venda` |
| Dias de atendimento | configuraveis | sempre todos |
| Compartilhamento | um corte serve o lote inteiro | um relogio por pedido |

`tg_regra_logistica_sync_modalidade` zera os campos da forma oposta em vez de
deixa-los conviver: uma linha Turbo com `horario_corte` esquecido de uma edicao
anterior mentiria para quem le a tabela.

O offset por conta vence o do catalogo, do mesmo jeito que o horario de corte.
O compromisso e ancorado em `data_venda`, nunca em `now()` — reprocessar o
pedido amanha nao pode empurrar o prazo dele para amanha.

Modalidades `RELATIVO` nao possuem janela diaria e nao aparecem como no
acumulavel para conferencia. Elas formam uma esteira separada.

### Quando o pedido sai da esteira

A esteira usa criterio proprio: o pedido sai quando pertence a uma demanda
**publicada** (status diferente de `RASCUNHO` e nao cancelada), nao quando
recebe `despachado_em`.

A torre continua usando `despachado_em`, e a diferenca e deliberada. Sao duas
perguntas distintas:

| | Pergunta | Criterio |
| --- | --- | --- |
| Torre | o que ainda precisa ser lancado? | `despachado_em IS NULL` |
| Esteira | alguem ja assumiu este prazo? | nao esta em demanda publicada |

Um Turbo dentro de um rascunho — alguem comecou a montar o lote e parou no
meio — continua sendo responsabilidade de ninguem, com o relogio correndo. A
faixa de alerta muda de texto nesse caso ("em rascunho, ainda nao publicado"),
mas nao some.

### Faixa de alerta

Ocupa a largura da tela acima do cabecalho, em qualquer rota. Reflete estado,
nao evento: aparece enquanto existir pedido na esteira e some sozinha quando o
ultimo sai. Nao tem botao de dispensar — nao se dispensa um prazo que continua
correndo, e um alerta que da para fechar e um alerta que sera fechado.

O relogio e recalculado no cliente a partir de `compromisso_em`, nao do
`minutos_restantes` da RPC: a contagem precisa continuar correndo entre um
refetch e outro.

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
- `POST /api/v2/despacho/arquivo/conferir` le, filtra, casa refs e grava a
  conferencia; o upload e removido em qualquer caminho.
- `POST /api/v2/despacho/arquivo/<id>/ingerir` cria ausentes pelo pipeline
  canonico e popula `itens_pedido`.
- `POST /api/v2/despacho/arquivo/<id>/resolver-erp` resolve `numeroLoja` em
  blocos de 50 e pode ser repetido.
- `GET /api/v2/despacho/previsao?conferencia_id=` mostra a consolidacao antes
  do lancamento.

Contratos de banco: ver [Supabase contracts](../../03-contracts/supabase-contracts.md)
apos a migration.

## Migration and transition

- `pedidos.is_flex` e `pedidos.modalidade_logistica` (texto) sao derivados de
  `modalidade_logistica_id` por trigger, para nao quebrar de uma vez os
  consumidores atuais em API, worker, impressao e alertas. Removidos em fase
  posterior. Nao escrever nessas colunas: a fonte de verdade e a FK.
- `demandas_producao.modalidade_logistica` (varchar) migra para FK.
- **Correcao de rumo (03/08/2026).** A versao anterior desta spec previa que
  `regras_logisticas_canal` fosse absorvida por `modalidades_logisticas`. A
  absorcao correta e a inversa: `regras_logisticas_integracao` e quem tem tela,
  historico e seis consumidores, entao ela sobrevive e ganha
  `modalidade_id` (FK). `modalidade_config_conta` foi removida — era a mesma
  tabela com menos campos e sem tela.
- `pontos_coleta` e referenciado pela **regra por conta**, nunca pelo catalogo:
  a mesma modalidade tem pontos diferentes em contas diferentes.
- Backfill de `modalidade_logistica_id` a partir do metodo de envio observado
  em `pedido_snapshots.platform_fields`.

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
