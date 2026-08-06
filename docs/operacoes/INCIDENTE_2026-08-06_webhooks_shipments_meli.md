# Incidente — Pedidos do Mercado Livre travados em "Em Andamento"

**Data do diagnóstico:** 06/08/2026
**Início do impacto:** 31/07/2026, ~10:50 (BRT)
**Pedido de referência:** `numeroLoja = 2000017648389902` (pedido interno `55107`)

## Sintoma

Pedidos do Mercado Livre permaneciam em **"Em Andamento"** mesmo depois de despachados.
Nenhum pedido do ML chegou à situação **"Enviado"** desde 31/07.

Estado do pedido de referência no momento do diagnóstico:

| Campo | Valor |
|---|---|
| `situacao_pedido_id` | 2 (Em Andamento) |
| `marketplace_shipping_status` | `ready_to_ship` |
| `marketplace_shipping_substatus` | `ready_to_print` |
| `marketplace_status_updated_at` | 03/08/2026 10:29 |
| `data_venda` | 29/07/2026 |

## Causa raiz

O commit **`b870300`** ("feat: adicionar suporte a claims...", 30/07/2026) passou a enviar o
header `x-format-new: true` em `get_shipment`:

```python
headers = {**_auth_headers(integration), "x-format-new": "true"}
```

No formato novo, `GET /shipments/{id}` **deixa de expor `order_id` e `pack_id` no root** —
os dados passam a viver em `origin` / `destination` / `logistic` / `external_reference`.
O `MercadoLivreAdapter.resolve_order_ids` procurava exatamente esses dois campos e, ao não
encontrá-los, encerrava o evento como terminal:

```
error_type = "shipment_without_order_reference"
```

Como o Mercado Livre só notifica mudanças de envio pelo tópico `shipments`
(o `orders_v2` não dispara em transições de logística), **todo o avanço de status parou**.

### Evidência

Chaves do `raw_shipment` gravado em `pedidos_mercadolivre` (resposta real da API):

```
id, tags, origin, source, status, sibling, logistic, lead_time, quotation,
substatus, dimensions, destination, items_types, date_created, external_key,
last_updated, declared_value, priority_class, tracking_method, tracking_number,
snapshot_packing, external_reference, threshold_cancellation
```

Sem `order_id`. Sem `pack_id`.

Corte exato coincidindo com o deploy do commit:

| `raw_shipment` tem `order_id`? | Primeiro registro | Último registro | Qtd |
|---|---|---|---|
| Sim | 29/07 21:08 | **31/07 10:48** | 150 |
| Não | **31/07 10:58** | 06/08 17:06 | 479 |

Webhooks de `shipments` — **314 de 314 falharam**, 100% com o mesmo erro:

| source | topic | last_status | last_error_type | qtd |
|---|---|---|---|---|
| mercadolivre | shipments | `failed_terminal` | `shipment_without_order_reference` | 314 |

Impacto em pedidos (ML, venda a partir de 31/07):

| Situação | Qtd |
|---|---|
| Em Andamento | 260 |
| Entregue | 50 |
| **Enviado** | **0** |

## Correção aplicada

### 1. Fallback de resolução via `/shipments/{id}/items`

`GET /shipments/{id}/items` continua retornando `order_id` por item, inclusive em packs.
O adapter agora tenta, em ordem: `order_id` → `pack_id` → **items**.

- `platform_drivers/mercadolivre.py`: novo `get_shipment_items()`.
- `marketplace_adapters.py`: fallback antes de declarar `shipment_without_order_reference`.
- `marketplace_http.py`: `request_json(..., list_key=...)` para respostas com array no root
  (o helper rejeitava qualquer resposta não-dict).

Erros de provider no novo endpoint são propagados como `shipment_items_resolution_failed`,
preservando o `retryable` original (ex.: 429 continua retentável).

### 2. Replay de eventos terminais

- `webhook_monitoring_service`: `failed_terminal` entrou em `REPROCESSABLE_STATUSES`.
  "Terminal" descreve a decisão de não retentar *automaticamente*, não a impossibilidade
  de replay — quando a causa foi um bug nosso, o operador precisa poder reenfileirar.
- `marketplace_payment_reprocess_service`: generalizado para
  `MarketplaceEventReprocessService(topic, resource_types, label)`, reaproveitando a
  reserva atômica e o envelope de ingestão confiável já existentes.
  Novas instâncias: `marketplace_shipment_reprocess_service` + task Celery
  `reprocess_unresolved_shipments`. O alias `MarketplacePaymentReprocessService` foi
  mantido para não quebrar imports.

### 3. Script de backfill

```bash
# 1. Deploy da correção PRIMEIRO (senão os eventos falham de novo)
# 2. Conferir o que será reprocessado
python scripts/backfill_reprocessar_shipments_meli.py --dry-run

# 3. Reprocessar em lotes, respeitando o rate limit do ML
python scripts/backfill_reprocessar_shipments_meli.py --limite 100 --lotes 4
```

## Verificação pós-deploy

```sql
-- Nao deve haver mais failed_terminal novo neste topico
select last_status, last_error_type, count(*)
from webhook_events
where source='mercadolivre' and provider_topic='shipments'
  and received_at > now() - interval '1 day'
group by 1,2;

-- Pedidos devem voltar a alcançar "Enviado" (id=5)
select sp.nome, count(*)
from pedidos p join situacoes_pedido sp on sp.id=p.situacao_pedido_id
where p.origem='MERCADOLIVRE' and p.data_venda > '2026-07-31'
group by 1;
```

## Pendência relacionada (não corrigida aqui)

`get_claim_returns` chama `/post-purchase/v2/claims/{id}/returns`, que também responde com
array no root. O `marketplace_adapters` já tem tratamento para `isinstance(result, list)`,
mas esse ramo é inalcançável: `request_json` rejeita a resposta antes, com
`provider_invalid_response`. A correção é passar `list_key="returns"` — mesmo padrão
aplicado em `get_shipment_items`.
