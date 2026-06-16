# Modelo de Dados - Integracoes e Pedidos Canonicos

Last updated: 2026-06-16

Status: target-state

## 1. Diagrama textual

```text
integration_modules
    1:N
installed_integrations
    |-- ERP instances, ex: Bling 01
    |-- Direct marketplace instances, ex: Shopee 01
    |-- Dummy marketplace instances, ex: TikTok Shop 01

installed_integrations (marketplace)
    N:N with installed_integrations (ERP)
    via erp_marketplace_links

pedidos
    N:1 marketplace installed integration
    N:1 ERP installed integration, when resolved
    1:1 or 1:N normalized snapshots/audit context

pedido_snapshots
    canonical normalized structure

pedidos_bling / pedidos_shopee / pedidos_mercadolivre
    mirror and audit support
```

## 2. Tabelas centrais

### 2.1 `integration_modules`

Catalogo de conectores disponiveis.

Campos principais:

- `id`
- `slug`
- `name`
- `tipo`
- `auth_flow`
- `config_schema`
- `is_active`

### 2.2 `installed_integrations`

Representa uma conta instalada ou uma origem dummy instalada.

Campos principais:

- `id`
- `module_id`
- `platform_slug`
- `instance_name`
- `config`
- `credentials`
- `is_active`
- `sync_status`
- `expires_at`
- `functional_scopes`

Regras:

- Esta tabela representa identidade operacional, nao apenas token.
- Uma linha pode representar um marketplace dummy sem credencial propria.

### 2.3 `erp_marketplace_links`

Representa um vinculo explicito entre uma conta marketplace e uma conta ERP.

Campos esperados:

- `id`
- `marketplace_integration_id`
- `erp_integration_id`
- `erp_store_id`
- `ingest_via`
- `supports_invoicing`
- `is_active`

Cardinalidade:

- N:N entre marketplace e ERP

Chave operacional:

- `erp_integration_id + marketplace_integration_id + erp_store_id`

Regra:

- O mesmo marketplace pode aparecer varias vezes, desde que em ERP diferente ou
  com `erp_store_id` diferente.

### 2.4 `channel_connections`

Tabela de compatibilidade para roteamentos e auxiliares legados.

Uso esperado:

- apoio a resolucao de canais antigos
- compatibilidade com telas e regras em transicao

Regra:

- nao substitui o contrato marketplace-first baseado em `installed_integrations`
  e `erp_marketplace_links`

## 3. Pedido canonico

### 3.1 `pedidos`

Fonte operacional principal.

Campos de identidade e roteamento:

- `id`
- `marketplace_integration_id`
- `bling_integration_id`
- `bling_loja_id`
- `codigo_pedido_externo`

Campos genericos esperados:

- comprador
- datas principais
- totais
- situacao
- indicadores logisticos

### 3.2 `pedido_snapshots`

Estrutura normalizada do payload do pedido.

Blocos esperados:

- `identity`
- `customer`
- `logistics`
- `items`
- `financial`
- `platform_fields`

Regra:

- `platform_fields` armazena particularidades do marketplace sem poluir o
  contrato generico do pedido.

Exemplos:

- Shopee:
  - `buyer_username`
  - `buyer_user_id`
  - detalhes de logistics e Flex
- Mercado Livre:
  - dados especificos de comprador e envio
- Bling:
  - referencias ERP, numero interno e contexto de NF

## 4. Tabelas espelho e auditoria

### 4.1 `pedidos_bling`

- espelho do payload e da leitura ERP
- apoio a reprocessamento
- nao e a fonte principal do dominio

### 4.2 `pedidos_shopee`

- espelho/enriquecimento Shopee
- nao e a fonte principal do dominio

### 4.3 `pedidos_mercadolivre`

- espelho/enriquecimento Mercado Livre
- nao e a fonte principal do dominio

### 4.4 `pedido_ingest_log`

- trilha do processamento
- origem tecnica do evento
- correlacao de erros, retries e enriquecimento

## 5. Regras de identidade e deduplicacao

- Origem comercial: `marketplace_integration_id`
- Contexto ERP: `bling_integration_id`
- ID externo: `codigo_pedido_externo`
- Quando o pedido entra via Bling, `numeroLoja` deve ser materializado como ID
  externo da venda na origem sempre que aplicavel

Dedupe:

- usar origem comercial canonica + ID externo

## 6. Regras de consulta e UI

- O filtro `origem da venda` deve consultar marketplaces instalados ativos
- `source:<marketplace_integration_id>` e a chave canonica de filtro
- ERP nao deve aparecer como origem da venda

## 7. Regras de NF

- NF nunca deve ser resolvida por `marketplace_integration_id` isolado
- deve usar:
  - `bling_integration_id`, ou
  - `marketplace_integration_id + erp_store_id`

Quando um pedido direto de marketplace tem varios Blings possiveis:

- a configuracao default da conta marketplace define o ERP emissor

## 8. Notas de transicao

- `canais_venda` e estruturas ligadas a canal permanecem por compatibilidade
  operacional
- o modelo alvo do dominio, no entanto, e centrado em integracoes instaladas e
  pedido canonico
