# Canonização de status de pedido entre origens de ingest

Contrato normativo para traduzir eventos de Shopee, Mercado Livre e Bling em um
único ciclo de vida interno. Substitui a regra distribuída hoje entre
`marketplace_lifecycle_service.py`, `canonical_order_status_service.py`,
`integration_status_mappings` e o RPC `apply_marketplace_order_event`.

Escopo desta versão: Shopee (direto), Mercado Livre (direto), Bling (3 instâncias).
Fora de escopo: Amazon, TikTok, Shein, Kwai, Loja Integrada — os drivers existem
mas não recebem webhook próprio; entram numa segunda rodada usando o mesmo léxico.

---

## 1. Princípio estruturante

O erro de modelagem que torna a canonização difícil é tratar "status do pedido no
provider" e "situação interna do pedido" como a mesma coisa. Não são.

O provider não descreve um estado; ele descreve **fatos observados em domínios
distintos**, em momentos distintos, por endpoints distintos. O Mercado Livre é o
caso extremo e honesto: pedido, pagamento, envio e devolução são entidades
separadas com timelines próprias. A Shopee é o caso enganoso: ela achata tudo em
um único `order_status`, o que dá a ilusão de máquina de estados única, mas o
achatamento é lossy — `READY_TO_SHIP` mistura fato de pagamento com fato de
logística.

Portanto o pipeline tem três camadas, e nenhuma delas pode ser pulada:

```
webhook  ──►  [A] LÉXICO           ──►  [B] DECISÃO        ──►  [C] PROJEÇÃO
              observação por            estágio canônico        situacao_pedido_id
              domínio, normalizada      (provider-agnóstico)    (guardada)
              tabela, por provider      função única            função única
```

- **[A] Léxico** é o único lugar que conhece vocabulário de provider. É dado
  (tabela), não código. Um status externo desconhecido produz `unmapped` e
  **nunca** um palpite.
- **[B] Decisão** não conhece provider algum. Recebe o conjunto atual de
  observações do pedido e devolve um estágio canônico. É a mesma função para
  Shopee, Meli e Bling.
- **[C] Projeção** aplica o estágio sobre a situação anterior com guardas de
  não-regressão e terminalidade. Já existe no RPC; precisa de ajustes.

Consequência prática: **um driver de marketplace não decide situação de pedido.**
Ele só sabe extrair, do payload que recebeu, quais domínios foram observados e
com quais valores brutos. Tudo depois disso é compartilhado.

---

## 2. Domínios de status

Cada observação pertence a exatamente um domínio. Cada domínio tem sua própria
ordem temporal (`provider_sequence`, `provider_occurred_at`) e sua própria
verificação de staleness.

| Domínio | Significado | Quem observa |
|---|---|---|
| `order` | Estado agregado declarado pelo provider | Shopee, Meli, Bling |
| `payment` | Estado do dinheiro | Meli, (Shopee implícito) |
| `payment_detail` | Qualificador do pagamento (`status:status_detail`) | Meli |
| `shipping` | Estado físico da remessa | Meli, (Shopee implícito) |
| `shipping_substatus` | Qualificador da remessa | Meli |
| `return` | Devolução / reembolso pós-venda | Shopee, Meli |
| `erp` | Fatos fiscais e de identidade no ERP | Bling |

`payment_detail` e `shipping_substatus` são **domínios de refinamento**:
qualificam outro domínio em vez de descrever o pedido sozinhos. Duas
consequências. Primeira, entram como observação independente e disputam por
precedência — é assim que `delivered` + substatus `in_transit` continua entregue
enquanto `delivered` + `returned_to_warehouse` vira devolução, sem nenhuma regra
composta. Segunda, a ausência de mapeamento neles significa "sem informação
adicional", não "status desconhecido": não contam como `unmapped`, porque a
maioria dos substatus do Meli é irrelevante para o ciclo.

O domínio `erp` **nunca** projeta situação em modo `marketplace_direct`. Ele
carrega número do pedido no ERP, NF-e, e vínculo de identidade — não ciclo de vida.

---

## 3. Estágios canônicos

Vocabulário fechado. É o contrato entre camada [A] e camada [C]. `rank` é a
precedência da §7.1: entre observações do mesmo pedido, vence o maior.

| Estágio | Rank | Significado | Situação alvo |
|---|---|---|---|
| `returned` | 100 | Devolução concluída ou reembolso total | 8 |
| `partially_refunded` | 95 | Reembolso parcial; pedido continua vivo | ⇣ subjacente |
| `return_in_progress` | 90 | Devolução iniciada, não concluída | ⇣ subjacente |
| `delivered` | 80 | Entrega confirmada | 6 |
| `shipped` | 70 | Remessa despachada | 5 |
| `shipping_exception` | 65 | Falha de entrega sem conclusão (`not_delivered`) | 5 |
| `cancelled` | 60 | Cancelado antes da expedição | 7 |
| `cancellation_pending` | 55 | Cancelamento solicitado, não efetivado | — |
| `fulfillment_ready` | 45 | Provider emitiu etiqueta/documentação | 4 (ver §5) |
| `paid_preparation` | 40 | Pago; pedido é nosso para produzir e expedir | 2 |
| `chargeback_pending` | 30 | Contestação aberta, não liquidada | — |
| `payment_in_analysis` | 20 | Pagamento em processamento/revisão | 1 |
| `awaiting_payment` | 10 | Pedido existe, dinheiro não confirmado | 1 |
| `ignored` | 1 | Fato que deliberadamente não descreve o pedido | — |
| `unknown` | 0 | Status externo sem mapeamento | — |

Há dois silêncios diferentes, e confundi-los foi o erro da primeira versão desta
spec:

- **⇣ subjacente** — o estágio é um *modificador* sobre o estado real ("há uma
  devolução a caminho deste pedido entregue"). A situação correta continua sendo
  a que as demais observações descrevem, então a decisão cai para o próximo
  estágio que projeta. Sem isso, um pedido visto pela primeira vez já em
  devolução ficaria sem situação nenhuma.
- **—** — o estágio é uma *dúvida* sobre o destino do pedido ("pediram
  cancelamento, ainda não se sabe"). Nada é projetado: registra o fato externo e
  a transição com decisão `external_state_only`, e **não toca** em
  `situacao_pedido_id`.

---

## 4. Situações internas

| ID | Nome | Origem autorizada |
|---|---|---|
| 1 | Em Aberto | Ingest externo |
| 2 | Em Andamento | Ingest externo |
| 3 | Produzido | **Somente interno** (módulo de produção) |
| 4 | Pronto para Envio | Ingest externo (etiqueta emitida pelo provider) |
| 5 | Enviado | Ingest externo |
| 6 | Entregue | Ingest externo |
| 7 | Cancelado | Ingest externo |
| 8 | Devolvido | Ingest externo |

Ingest externo projeta em `{1, 2, 4, 5, 6, 7, 8}`. Apenas 3 é reservado.

3 e 4 **não são etapas sequenciais do mesmo eixo**. São dois eixos concorrentes:
3 é produção interna, 4 é logística do provider. Por isso a projeção nunca
rebaixa 3 para 4 — etiqueta emitida não desfaz produção.

---

## 5. A decisão central: o intervalo pago→enviado

Esta é a pergunta que motivou a spec. A resposta tem duas partes:

> **Entre a confirmação do pagamento e o despacho, a situação é 2 (Em Andamento)
> — exceto quando o provider emite a etiqueta/documentação, que é 4 (Pronto para
> Envio).**

A primeira versão desta spec dizia "sempre 2, sem exceção", tratando 4 como
estado interno de separação. **A inspeção do banco de produção mostrou que isso
é falso**: a situação 3 tem zero pedidos e nenhum escritor no código, enquanto a
4 tem 140 pedidos e 447 transições aplicadas, todas vindas de marketplace. Ou
seja, 4 nunca foi separação interna — é a fila de expedição, alimentada
exclusivamente por ingest externo. Forçá-la a 2 destruiria essa fila para
resolver um problema teórico.

O que permanece verdadeiro: **sub-estado de logística não é avanço do pipeline
interno**. A distinção operacional real é entre "pago, aguardando" e "pago, com
documento emitido para expedir". Só isso justifica sair de 2.

Por isso o léxico distingue caso a caso, e não por analogia de nome:

| Valor | Significa | Estágio | Situação |
|---|---|---|---|
| Shopee `PROCESSED` | documentação de envio emitida | `fulfillment_ready` | 4 |
| Bling `24` (Verificado) | pedido conferido, documentação pronta | `fulfillment_ready` | 4 |
| Meli `ready_to_ship` | **aguardando envio**; etiqueta pode nem estar impressa | `paid_preparation` | 2 |
| Shopee `READY_TO_SHIP` | pago, aguardando processamento | `paid_preparation` | 2 |
| Shopee `INVOICE_PENDING`, `RETRY_SHIP` | pago, pendência de nota/coleta | `paid_preparation` | 2 |
| Meli `handling`, `to_be_shipped`, Bling `15` | pago, em preparo | `paid_preparation` | 2 |

`ready_to_ship` do Meli **não** é o equivalente de `PROCESSED` da Shopee, apesar
do nome sugerir. Confundir os dois foi o que a migration 20260627 tentou fazer
(`SET internal_situacao_pedido_id = 4`) e que a produção acabou revertendo para
2 — o banco estava certo.

**O que sobra do problema original.** 3 e 4 continuam sendo eixos concorrentes:
produção interna vs. logística do provider, espremidos numa coluna só. A guarda
`target 4 AND previous 3 → 3` continua necessária e agora está explícita nos dois
lados (Python e RPC). Se um dia a produção interna passar a usar 3, esta é a
tensão que vai reaparecer.

---

## 6. Léxico — matriz de equivalência

Conteúdo normativo de `integration_status_mappings`. Chave:
`(module_id, integration_id, status_domain, external_status_id)`.
`integration_id NULL` = regra global do provider; linha com `integration_id`
preenchido sobrepõe a global (necessário para as 3 instâncias Bling).

### 6.1 Shopee — domínio `order`

Shopee entrega tudo em `order_status`. A observação é gravada no domínio `order`,
e a coluna `implies` registra o que o valor também afirma sobre outros domínios.

| `external_status_id` | Estágio | Implica | Situação |
|---|---|---|---|
| `UNPAID` | `awaiting_payment` | payment: pendente | 1 |
| `INVOICE_PENDING` | `paid_preparation` | payment: pago | 2 |
| `READY_TO_SHIP` | `paid_preparation` | payment: pago | 2 |
| `RETRY_SHIP` | `paid_preparation` | payment: pago; shipping: falha na coleta | 2 |
| `PROCESSED` | `fulfillment_ready` | payment: pago; shipping: etiqueta emitida | 2 |
| `SHIPPED` | `shipped` | shipping: despachado | 5 |
| `TO_CONFIRM_RECEIVE` | `shipped` | shipping: em trânsito | 5 |
| `COMPLETED` | `delivered` | shipping: entregue | 6 |
| `IN_CANCEL` | `cancellation_pending` | — | — |
| `CANCELLED` | `cancelled` | — | 7 |
| `TO_RETURN` | `returned` | return: aberto | 8 |

`IN_CANCEL` deixa de projetar 7. Cancelamento na Shopee é solicitação sujeita a
recusa; projetar 7 e depois voltar exigiria regredir de estado terminal, o que a
projeção proíbe por construção. Aguarda-se `CANCELLED`.

### 6.2 Shopee — domínio `return`

Domínio próprio, alimentado por `return_status` / `refund_status` e pelos tópicos
de devolução. Precedência sobre `order` (§7.1).

| `external_status_id` | Estágio | Situação |
|---|---|---|
| `REQUESTED`, `PROCESSING`, `JUDGING`, `SELLER_DISPUTE` | `return_in_progress` | — |
| `ACCEPTED`, `REFUND_PAID`, `COMPLETED`, `CLOSED` | `returned` | 8 |
| `CANCELLED`, `SELLER_DISPUTE_SUCCESS` | — (devolução negada) | — |

Reembolso parcial (`partial_refund`, `partially_refunded`) → `partially_refunded`,
situação preservada. Hoje o conjunto `SHOPEE_RETURN_STATES` trata parcial como
devolução total e fecha o pedido em 8 — divergência D-4.

### 6.3 Mercado Livre — domínio `payment`

| `external_status_id` | Estágio | Situação |
|---|---|---|
| `pending`, `in_process` | `payment_in_analysis` | 1 |
| `authorized` | `paid_preparation` | 2 |
| `approved` | `paid_preparation` | 2 |
| `rejected` | `awaiting_payment` | 1 |
| `cancelled` | `awaiting_payment` | 1 |
| `in_mediation` | `chargeback_pending` | — |
| `charged_back` | `chargeback_pending` | — |
| `refunded` | `returned` \| `cancelled` | 8 \| 7 (§7.3) |

Domínio `payment_detail` — o Meli só declara que o dinheiro voltou de fato
quando a contestação está liquidada, e essa informação está em `status_detail`,
não em `status`. O observer compõe os dois campos do provider; quem interpreta
o composto continua sendo o léxico.

| `external_status_id` | Estágio | Situação |
|---|---|---|
| `charged_back:settled` | `returned` | 8 \| 7 (§7.3) |
| `charged_back:reimbursed` | `returned` | 8 \| 7 (§7.3) |

`rejected` e `cancelled` no domínio `payment` referem-se a **uma tentativa de
pagamento**, não ao pedido. Só o domínio `order` cancela pedido.

### 6.4 Mercado Livre — domínio `shipping`

| `external_status_id` | Estágio | Situação |
|---|---|---|
| `pending` | `ignored` | — |
| `handling`, `to_be_shipped` | `paid_preparation` | 2 |
| `ready_to_ship` | `paid_preparation` | 2 |
| `shipped` | `shipped` | 5 |
| `delivered` | `delivered` | 6 |
| `not_delivered` | `shipping_exception` | 5 |
| `cancelled` | `ignored` | — |

`shipping.pending` significa que o registro de envio existe e nada foi decidido.
Não é evidência de pagamento: um pedido aguardando pagamento também tem shipment
pendente. Mapeá-lo para `paid_preparation` faria um pedido não pago aparecer
como em andamento.

`shipping.cancelled` não cancela pedido: o vendedor pode cancelar uma etiqueta e
emitir outra. Só `order.cancelled` cancela. Com o pedido pago, quem vence é
`order.paid` (rank 40) sobre `ignored` (rank 1) — a situação é 2, inclusive para
um pedido visto pela primeira vez neste estado.

Domínio `shipping_substatus` — observação independente, não combinação:

| `external_status_id` | Estágio | Situação |
|---|---|---|
| `authorized_by_carrier`, `dropped_off`, `in_hub`, `in_transit`, `picked_up` | `shipped` | 5 |
| `picked_up_for_return`, `returning_to_sender`, `returning_to_hub`, `returned_to_agency`, `returned_to_hub`, `returning_to_warehouse`, `soon_to_be_returned` | `return_in_progress` | ⇣ subjacente |
| `returned`, `returned_to_warehouse` | `returned` | 8 |
| qualquer outro | (sem entrada) | — |

### 6.5 Mercado Livre — domínio `order`

| `external_status_id` | Estágio | Situação |
|---|---|---|
| `confirmed`, `opened`, `payment_required`, `payment_in_process`, `partially_paid` | `awaiting_payment` | 1 |
| `paid` | `paid_preparation` | 2 |
| `partially_refunded` | `partially_refunded` | — |
| `pending_cancel` | `cancellation_pending` | — |
| `cancelled`, `invalid` | `cancelled` | 7 |

### 6.6 Mercado Livre — domínio `return`

| Condição | Estágio | Situação |
|---|---|---|
| `return.status = delivered` (subtype ≠ `return_partial`) | `returned` | 8 |
| `return.status_money = refunded` (total) | `returned` | 8 |
| `return.status ∈ {label_generated, pending, pending_delivered, pending_expiration, pending_failure, scheduled, shipped}` | `return_in_progress` | — |
| `subtype = return_partial` ou contexto parcial | `partially_refunded` | — |

### 6.7 Bling — domínio `order`

Bling só projeta situação quando o vínculo está em `erp_bling` ou
`erp_only_dummy` (§7.4).

| `external_status_id` | Nome Bling | Estágio | Situação |
|---|---|---|---|
| `6` | Em aberto | `awaiting_payment` | 1 |
| `15` | Em andamento | `paid_preparation` | 2 |
| `24` | Verificado | `fulfillment_ready` | 4 |
| `9` | Atendido | `shipped` | 5 |
| `12` | Cancelado | `cancelled` | 7 |
| `18` | Arquivado | — (arquivamento ≠ ciclo) | — |

Bling `9` (Atendido) significa baixa no ERP, não confirmação de entrega da
transportadora. Projeta 5, nunca 6. Em `marketplace_direct` a entrega vem do
marketplace.

Bling não tem estado de devolução no domínio `order`. Devolução em pedido
Bling-only exige evidência explícita (nota de entrada / devolução registrada);
sem ela, cancelamento pós-envio **não** vira 8.

### 6.8 Bling — domínio `erp`

Sempre aceito, em qualquer modo, sem projetar situação: `numero`, `numeroLoja`,
`id`, NF-e, série, chave de acesso, `loja_id`, `bling_integration_id`.
É o que alimenta `enrich_order_erp_reference`.

**A ausência de identidade ERP é um fato e precisa permanecer visível.** Em
pedido de integração direta o Bling ainda não criou o espelho quando o webhook
do marketplace chega, então `erp_order_id` e `erp_order_number` são nulos por
um intervalo. Preencher esses campos com o id do marketplace "para não ficar
vazio" não resolve nada e quebra a reconciliação, que é justamente quem procura
por nulo. Corrigido na migration `20260801010000` — ver o cabeçalho dela para os
três defeitos encadeados que mantinham 1.398 pedidos sem número Bling e fora da
fila.

---

## 7. Regras de decisão

A camada [B] recebe o estado externo consolidado do pedido (última observação
válida de cada domínio) e devolve o estágio de maior `rank`.

### 7.1 Ordem de avaliação

Não é uma cadeia de `if/elif`: é a ordenação por `rank` da tabela da §3. Cada
observação vira um estágio candidato; vence o maior. Isso é o que permite
acrescentar um provider sem tocar em lógica — só em dado.

```
returned 100 > partially_refunded 95 > return_in_progress 90 > delivered 80
  > shipped 70 > shipping_exception 65 > cancelled 60 > cancellation_pending 55
  > fulfillment_ready 45 > paid_preparation 40 > chargeback_pending 30
  > payment_in_analysis 20 > awaiting_payment 10 > ignored 1 > unknown 0
```

Devolução e logística vencem pagamento porque descrevem o fato mais recente do
mundo físico. Pagamento vence apenas quando nada mais foi observado.

Duas regras não cabem em `rank` porque dependem de contexto, e são aplicadas
depois de eleito o vencedor:

1. **§7.3** — `returned` vindo do domínio `payment`/`payment_detail` vira
   `cancelled` quando não há evidência de despacho.
2. **§3** — vencedor com `⇣ subjacente` cai para o próximo estágio que projeta,
   ignorando tanto seu estágio bruto quanto o reescrito.

Ordenar por `rank` também resolve `delivered` + substatus `in_transit` sem regra
composta: 80 > 70, entregue vence. E `delivered` + `returned_to_warehouse` vira
devolução, porque 100 > 80.

### 7.2 Pagamento efetivo quando há vários

Um pedido pode acumular tentativas. O status efetivo é o de maior precedência
nesta ordem, não o mais recente:

```
approved > authorized > in_process > pending > refunded > charged_back > cancelled > rejected
```

Uma tentativa recusada ao lado de uma aprovada nunca degrada o pedido.

### 7.3 Cancelamento vs. devolução

| Situação anterior | Evento | Resultado |
|---|---|---|
| 1, 2 | cancelamento | 7 |
| 5, 6 | cancelamento **sem** evidência de retorno | preserva 5 / 6 |
| 5, 6 | cancelamento **com** evidência de retorno ou reembolso total | 8 |
| qualquer | devolução concluída | 8 |
| 8 | qualquer | 8 |

Evidência de retorno = observação no domínio `return`, ou `payment.refunded`
total, ou substatus de retorno logístico. Reembolso total antes do despacho é
cancelamento (7); depois do despacho é devolução (8).

### 7.4 Autoridade por origem

`ingest_origin_mode` (em `channel_connections` e `erp_marketplace_links`) decide
quem pode projetar:

| Modo | `order`/`payment`/`shipping`/`return` | `erp` |
|---|---|---|
| `marketplace_direct` | marketplace projeta; Bling → `ignored_non_authoritative` | Bling grava, não projeta |
| `erp_bling` | Bling projeta; marketplace → `external_state_only` | Bling grava e projeta |
| `erp_only_dummy` | só Bling; marketplace → `ignored_non_authoritative` | Bling grava e projeta |

Chat nunca altera estado, em nenhum modo.

Observação não autoritativa **ainda é persistida** como fato externo e transição
auditável. É o que permite reconciliar divergência Bling × marketplace sem
disputa de escrita.

### 7.5 Ordem e staleness

**Correção de desenho.** A primeira versão desta spec exigia comparação de
recência por domínio. Ao implementar ficou claro que isso resolve um problema
que a arquitetura já evita: `fetch_order_snapshot` refaz o estado completo no
provider a cada evento — `/orders` + `/shipments` + `/returns` no Meli,
`get_order_detail` na Shopee. Todas as observações de um evento vêm do mesmo
snapshot coerente.

A consequência é que um webhook entregue fora de ordem não causa regressão: ao
reprocessá-lo, o refetch devolve o estado *atual*, não o estado da época do
evento. Staleness continua sendo comparação de snapshot inteiro contra
`marketplace_status_updated_at`, e isso está correto.

O que permanece verdadeiro de D-2: o `observed_at` do snapshot é o `max` dos
`last_updated` de cada entidade, então um snapshot legítimo pode ser descartado
se uma entidade não tocada carregar timestamp antigo. É um risco menor e
mitigado pelo refetch, não a falha estrutural que a versão anterior descrevia.

Observação stale → decisão `ignored_stale`, sem tocar em nada além da auditoria.

### 7.6 Terminalidade e não-regressão

- 8 absorve tudo e nunca sai.
- 6 e 7 só cedem para 8.
- 5 nunca volta para 1, 2, 3 ou 4.
- 3 e 4 nunca são alvo de ingest externo; `fulfillment_ready` chegando sobre 3
  ou 4 é `external_state_only`.
- `unknown` nunca altera projeção. Registra `unmapped` e alimenta a métrica de
  cobertura do léxico.

---

## 8. Contrato do driver

Um driver de marketplace implementa exatamente isto e nada mais:

```python
def observe(detail: dict, webhook: dict | None) -> tuple[
    list[DomainObservation], DecisionContext
]
```

```python
@dataclass(frozen=True)
class DomainObservation:
    domain: Literal["order", "payment", "payment_detail",
                    "shipping", "shipping_substatus", "return", "erp"]
    external_status_id: str | None      # valor bruto, sem tradução
    provider_occurred_at: str | None    # ISO-8601 UTC
    provider_sequence: int | None
    raw: dict                           # recorte do payload que originou o fato


@dataclass(frozen=True)
class DecisionContext:
    shipped_at: str | None = None       # distingue reembolso pré/pós despacho
    partial_refund: bool = False        # impede que parcial feche o pedido
```

`DecisionContext` carrega os fatos que **não são status** mas condicionam a
decisão. Sem ele o observer precisaria decidir sozinho se um reembolso encerra o
pedido — exatamente o que o contrato proíbe.

O driver **não** importa constantes de situação, **não** conhece estágios
canônicos e **não** decide precedência. Se um driver precisa de um `if` sobre
regra de negócio de status, a regra está no lugar errado.

Consequência para os três casos concretos:

- **Shopee** produz 1 observação `order` (e 1 de `return` quando o tópico for de
  devolução). O achatamento do provider é desfeito pelo léxico via `implies`,
  não pelo driver.
- **Mercado Livre** produz N observações — uma por entidade que o webhook tocou.
  Um `orders_v2` gera `order` + `payment`; um `shipments` gera `shipping`. Não há
  necessidade de buscar as outras entidades para decidir: a camada [B] usa a
  última observação conhecida de cada domínio, persistida.
- **Bling** produz 1 observação `order` + 1 `erp`. Em `marketplace_direct` a
  primeira é registrada e descartada na projeção; a segunda sempre vale.

---

## 9. Divergências entre o código atual e esta spec

| # | Onde | Divergência | Ação |
|---|---|---|---|
| D-1 | `marketplace_lifecycle_service.py` + `integration_status_mappings` | Regra duplicada: `resolve_shopee`/`resolve_mercadolivre` decidem em Python o que a tabela deveria decidir; `canonical_order_status_service.resolve_shopee` delega ao Python e ignora a tabela | Tabela vira autoritativa; resolvers viram a função única de decisão sobre observações |
| D-2 | `apply_marketplace_order_event` | `observed_at` é o `max` dos `last_updated`; entidade não tocada com timestamp antigo pode descartar snapshot legítimo | Rebaixada na implementação — o refetch de snapshot completo já protege (§7.5). Monitorar `ignored_stale` |
| D-3 | Meli `ready_to_ship` vs. Shopee `PROCESSED` | Nomes parecidos, significados diferentes; a migration 20260627 tentou igualar ambos em 4 | **Retirada.** A produção estava certa: `ready_to_ship` → 2, `PROCESSED` → 4. Ver §5 |
| D-4 | `SHOPEE_RETURN_STATES` | `partial_refund` / `partially_refunded` no conjunto de devolução total → fecha pedido em 8 | Reembolso parcial vira `partially_refunded`, preserva situação |
| D-5 | `resolve_shopee` | `IN_CANCEL` → 7 | → `cancellation_pending`, sem projeção |
| D-6 | `resolve_shopee` | Devolução inferida de tokens do evento (`_has_explicit_return_state` sobre `event_type`) | Domínio `return` explícito, alimentado por tópico de devolução |
| D-7 | `DEFAULT_STATUS_MAPPINGS` | Fallback hardcoded do Bling mascara ausência de linha na tabela | Fallback só marca `unmapped`; ausência vira alerta de cobertura |
| D-8 | `canonical_order_status_service.resolve_mercadolivre` | Reconstrói um payload sintético (`{"order": {"payments": [...]}}`) para chamar o resolver | Eliminado pelo contrato de observação |
| D-9 | `_ordered_mercadolivre_statuses` / `MELI_STATUS_PRECEDENCE` | Código morto — verificado: nenhuma chamada em todo o repositório. Declara uma precedência que a decisão real ignora | Remover; §7.1 é a precedência normativa |
| D-10 | Bling `9` (Atendido) | Comentário histórico da migration 20260328 mapeia para 5, mas o texto trata como "Atendido/Enviado" ambíguo | Fixar: 5, nunca 6 |
| D-11 | `situacoes_pedido` | 3 e 4 descritos como sequenciais, mas são eixos concorrentes (produção interna vs. logística do provider) | Só 3 é interno. A guarda `target 4 AND previous 3 → 3` permanece e está explícita nos dois lados |
| D-12 | Escritores diretos de `situacao_pedido_id` (ex.: `/pedido-cancelado`) | Bypassam projeção e auditoria | Roteados pelo RPC |
| D-13 | `resolve_mercadolivre` | `shipping.cancelled` sobre pedido pago devolvia estágio `shipment_cancelled` e alvo `None`; pedido novo nesse estado ficava sem situação | Descoberto na implementação. `order.paid` vence `ignored` e projeta 2 |
| D-14 | `resolve_mercadolivre` | `shipping.pending` mapeado como preparo pago; pedido aguardando pagamento com shipment pendente apareceria em andamento | Descoberto na implementação. `pending` → `ignored` |

---

## 10. Casos de teste normativos

Implementados em `packages/shared/tests/services/test_order_status_canonicalization.py`,
cada teste nomeado com o número do caso. Os casos 16 e 17 são de identidade e
idempotência do ingest e vivem no banco (índice único de
`marketplace_order_transitions`, chave loja + `order_sn`); na camada de decisão
o que se testa é determinismo.

1. Shopee `UNPAID` → `READY_TO_SHIP` → `PROCESSED` → `SHIPPED` → `COMPLETED`
   produz 1 → 2 → 4 → 5 → 6.
2. Mesma sequência com `PROCESSED` chegando **depois** de `SHIPPED`: situação
   permanece 5.
3. Meli: `payment.approved` seguido de `shipping.ready_to_ship` +
   `substatus=in_transit` → 2 → 5.
4. Meli: `shipping.ready_to_ship` sem substatus de despacho → 2, não 4:
   `ready_to_ship` é "aguardando envio", não "etiqueta emitida".
4b. Etiqueta emitida (`PROCESSED`, Bling `24`) sobre pedido em 3 → permanece 3.
5. Meli: `payment.rejected` ao lado de `payment.approved` → 2.
6. Meli: `shipping.cancelled` com `order.paid` → 2 (etiqueta cancelada não
   cancela venda; pedido novo neste estado também recebe 2).
7. Meli: `order.cancelled` com pedido em 5, sem devolução → permanece 5.
8. Meli: `return.status_money = refunded` com pedido em 5 → 8.
9. Meli: `subtype = return_partial` com `shipping.delivered` → permanece 6.
10. Meli: `shipping.not_delivered` → 5, nunca 7.
11. Shopee `IN_CANCEL` seguido de recusa do cancelamento e `SHIPPED` → 2 → 5,
    sem passar por 7.
12. Bling `15` em vínculo `marketplace_direct` com pedido em 5 →
    `ignored_non_authoritative`, situação 5, transição registrada.
13. Bling `9` em vínculo `erp_bling` → 5, nunca 6.
14. Bling emite `erp` (NF-e) em `marketplace_direct` → pedido enriquecido,
    situação intacta.
15. Status externo inexistente no léxico → `unmapped`, situação intacta,
    métrica de cobertura incrementada.
16. Mesmo `provider_event_id` entregue 3× → uma transição, uma projeção, um efeito.
17. Duas lojas Shopee distintas com o mesmo `order_sn` → dois pedidos isolados.

---

## 11. Estado da implementação

Concluído:

| Item | Onde |
|---|---|
| Léxico (§6) como dado, com override do banco e cache de processo | `services/order_status_lexicon.py` |
| Decisão única (§7.1–7.3) e projeção (§7.6), sem `if` de provider | `services/order_status_decision.py` |
| Autoridade por `ingest_origin_mode` (§7.4) | `order_status_decision.is_authoritative` |
| Observers dos três drivers (§8) | `services/order_status_observers.py` |
| Resolvers antigos reduzidos a fachada | `services/marketplace_lifecycle_service.py` |
| Fallback hardcoded removido; ausência vira `unmapped` | `services/canonical_order_status_service.py` |
| Schema + seed + guarda de 3 | `supabase/migrations/20260801000000_canonical_order_status_lexicon.sql` — **aplicada em produção** |
| Casos normativos da §10 | `tests/services/test_order_status_canonicalization.py` |

O seed SQL é gerado a partir de `SEED_LEXICON`, então tabela e código não podem
divergir por edição manual.

A migration corrigiu quatro linhas perigosas que estavam vivas em
`integration_status_mappings` e que o código Python já contornava, mas que
qualquer consumidor da tabela herdaria:

| Linha | Antes | Depois |
|---|---|---|
| `mercadolivre/payment/rejected` | **7 (Cancelado)** | 1 — tentativa recusada não cancela venda |
| `mercadolivre/payment/refunded` | 7 | 8 (ou 7 conforme despacho, §7.3) |
| `mercadolivre/shipping/cancelled` | **7 (Cancelado)** | `ignored` — etiqueta cancelada não cancela venda |
| `mercadolivre/shipping/pending` | ausente | `ignored` — não é evidência de pagamento |

`triggers_demand_consolidation` foi preservado em todas as linhas: a consolidação
de demanda continua disparando exatamente como antes.

Pendente:

1. Ligar `is_authoritative` no ingest: hoje a autoridade existe e é testada, mas
   `marketplace_webhook_ingest_service` ainda não a consulta antes de projetar.
3. Rotear o ingest do Bling (n8n → Redis → worker) por `resolve_bling` e pelo
   RPC, eliminando os escritores diretos (D-12).
4. **Shadow mode**: reaproveitar `MarketplaceRolloutService.normalize`, que já
   compara decisão `active` × `legacy` e sinaliza `diverged` e `regression` por
   integração. A nova decisão entra como `active`; a atual vira `legacy`.
   Divergência esperada concentrada em D-3, D-4 e D-5 — qualquer outra é bug.
6. Ativação por `ingest_origin_mode`, uma integração por vez, via
   `active_integration_ids`.
7. Remoção de `DEFAULT_STATUS_MAPPINGS`, `MELI_STATUS_PRECEDENCE`,
   `_ordered_mercadolivre_statuses` e dos escritores diretos.

Métrica de saída: cobertura do léxico (`unmapped` / total de observações) por
provider e por domínio, com alerta em qualquer valor externo novo.

### Testes que mudaram de expectativa

Estas asserções codificavam o comportamento substituído. Foram reescritas com o
motivo em comentário — não são regressões:

- `IN_CANCEL` esperava 7; agora não projeta (D-5).
- `shipping.cancelled` esperava estágio `shipment_cancelled` e alvo `None`;
  agora `paid_preparation` e 2 (D-13).

`PROCESSED` → 4 e `ready_to_ship` → 2 **permaneceram como estavam**: cheguei a
mudá-los seguindo a primeira versão da §5 e revertí depois de ver a produção.

Tudo o mais na suite do pacote `shared` passa sem alteração. As únicas falhas
remanescentes (`test_ingest_archive_service`, `test_personalized_order_identifier`)
são anteriores a esta mudança: módulo `zstandard` ausente e um mock defasado.
