# Relatorio de Limpeza de Base - Integracoes, Pedidos e Marketplaces

Este relatorio lista pontos de limpeza e consolidacao de banco identificados durante a refatoracao do dominio de integracoes e pedidos. Ele nao deve ser executado como plano destrutivo direto. A recomendacao e validar cada item em staging, com contagem de linhas, dependencias de codigo e plano de rollback.

## Objetivo

Transformar a base em um modelo mais coerente para um ERP/integrador:

- `installed_integrations` representa contas/instancias instaladas.
- Modulos definem capacidades e contratos.
- Webhooks e imports geram um pedido canonico.
- Dados especificos de marketplace ficam em estruturas especificas e controladas.
- Tabelas antigas de espelho continuam temporariamente como compatibilidade/auditoria.
- Emissao de notas fiscais passa a ser roteada por configuracao entre marketplace e ERP.

## Principios de Limpeza

- Nao apagar tabelas antes de criar views/compatibilidade e backfill.
- Nao remover colunas lidas por telas ou workers ativos.
- Antes de dropar coluna: verificar `rg`, views SQL, RPCs, triggers, jobs e dashboards.
- Antes de migrar dado JSON: gerar amostras por integracao e validar chaves obrigatorias.
- Separar identidade da conta externa de credencial sensivel.
- Separar pedido canonico de payload bruto da plataforma.

## Areas Principais

### 1. `installed_integrations`

Situacao observada:

- A tabela concentra instancia instalada, tokens, status, config, credentials, vinculos e metadados.
- Ha dados legados em lugares diferentes: top-level, `config` e `credentials`.
- `user_id` e ambiguo no dominio: usuario do sistema versus usuario/seller externo em alguns fluxos.
- Bling tem credenciais sincronizadas externamente via Firebase.
- Shopee e Mercado Livre precisam renovar/testar localmente.

Limpeza recomendada:

- Manter:
  - `id`
  - `module_id`
  - `instance_name`
  - `user_id` como dono interno da instalacao
  - `config`
  - `credentials`
  - `access_token`
  - `refresh_token`
  - `expires_at`
  - `sync_status`
  - `last_sync`
  - `last_refresh_attempt`
  - `refresh_error`
  - `parent_integration_id`
  - `functional_scopes`
  - `is_default`
  - `platform_slug`

- Normalizar/backfill:
  - `config.account_identifiers.primary`
  - `config.account_identifiers.kind`
  - `config.shop_id` para Shopee
  - `config.user_id` para Mercado Livre
  - `credentials.access_token`
  - `credentials.refresh_token`
  - `credentials.expires_in`

- Evitar:
  - usar `user_id` para seller/user externo do marketplace
  - gravar `partner_key` ou `client_secret` em payloads publicos
  - update parcial que regrave `config={}` ou `credentials={}`

Backfill sugerido:

```sql
-- Exemplo conceitual. Validar nomes reais e amostras antes de executar.
update installed_integrations
set config = jsonb_set(
    coalesce(config, '{}'::jsonb),
    '{shop_id}',
    to_jsonb(coalesce(config->>'shop_id', credentials->>'shop_id'))
)
where module_id ilike '%shopee%'
  and coalesce(config->>'shop_id', credentials->>'shop_id') is not null;
```

Risco:

- Alto, porque credenciais afetam ingest, renovacao, teste e webhooks.
- Executar em lotes e validar por integracao instalada.

### 2. Capacidades de Integracao

Situacao observada:

- Parte das capacidades esta implicita no codigo.
- `functional_scopes` existe, mas ainda nao cobre todo o contrato desejado.
- Necessario distinguir importacao, atualizacao, emissao NF, refresh e teste.

Tabela/contrato recomendado:

```text
integration_capabilities
- id
- installed_integration_id
- capability
- mode
- target_integration_id
- is_enabled
- config
- created_at
- updated_at
```

Capabilities iniciais:

- `ORDER_IMPORT`
- `ORDER_UPDATE`
- `WEBHOOK_INGEST`
- `INVOICING`
- `TOKEN_REFRESH`
- `CONNECTION_TEST`

Limpeza posterior:

- Reduzir regras hardcoded que procuram `module_id == 'bling'`, `shopee`, `mercadolivre`.
- Substituir por consulta ao roteador/capability resolver.

### 3. Vinculo Marketplace -> ERP

Situacao observada:

- O vinculo e essencial para emissao de NF via Bling.
- Existe historico de tabelas/vinculos como `channel_connections`, `erp_marketplace_links`, `integracao_canais`.
- A aplicacao precisa exibir todos os Blings vinculados a uma conta marketplace especifica.
- Uma mesma conta marketplace pode estar vinculada a multiplas contas Bling, com `shop.id` diferente em cada ERP.

Modelo recomendado:

```text
marketplace_erp_links
- id
- marketplace_integration_id
- erp_integration_id
- erp_store_id            -- shop.id/loja Bling neste ERP
- channel_id
- status
- config
- created_at
- updated_at
```

Limpeza recomendada:

- Usar como chave operacional `marketplace_integration_id + erp_integration_id + erp_store_id`.
- Remover constraints legadas que tornem `erp_integration_id + marketplace_integration_id` unico.
- Nunca resolver NF apenas por `marketplace_integration_id`; usar contexto do pedido (`bling_integration_id` ou `shop.id`).
- Escolher uma tabela canonica de vinculo no futuro.
- Criar view de compatibilidade para nomes antigos.
- Backfill a partir das tabelas atuais.
- Remover duplicidade so depois de validar telas, workers e filtros.

### 4. Notas Fiscais

Situacao observada:

- O dominio ainda nao esta explicito.
- A emissao de NF precisa ser configuravel por marketplace instalado.
- Mesmo quando pedido vem direto da Shopee/ML, a NF pode ser emitida via Bling vinculado.

Tabelas recomendadas:

```text
invoice_routing_configs
- id
- marketplace_integration_id
- mode                 -- local, erp, disabled
- erp_integration_id
- is_default
- config
- created_at
- updated_at

invoice_events
- id
- pedido_id
- marketplace_integration_id
- erp_integration_id
- status
- external_invoice_id
- request_payload
- response_payload
- error_message
- created_at
- updated_at
```

Limpeza futura:

- Remover configuracoes de NF escondidas em JSON generico quando o dominio estiver estavel.
- Garantir FK/indice por `pedido_id`, `marketplace_integration_id` e `erp_integration_id`.

### 5. Pedidos Canonicos

Situacao observada:

- A base ainda usa `pedidos` como tabela principal operacional.
- Existem tabelas espelho como `pedidos_bling`, `pedidos_shopee` e estruturas Mercado Livre.
- Ja existe `pedido_snapshots`, que guarda:
  - `identity`
  - `customer`
  - `items`
  - `logistics`
  - `financial`
  - `platform_fields`
  - `raw_refs`
  - `source_history`
- Fluxos diretos Shopee/ML e Bling ja caminham para gravar snapshot.

Recomendacao:

- Promover `pedido_snapshots` a fonte canonica de leitura.
- Manter `pedidos` como indice operacional/compatibilidade.
- Manter espelhos de plataforma como auditoria temporaria.
- Migrar telas para ler:
  - campos principais de `pedidos`
  - detalhes ricos de `pedido_snapshots`

Contrato recomendado para `pedido_snapshots`:

```text
identity:
  ingest_source
  marketplace
  marketplace_order_id
  marketplace_integration_id
  bling_integration_id
  bling_order_id
  bling_order_number

customer:
  name
  username/nickname
  document
  phone
  email
  address

items:
  sku
  name
  quantity
  unit_price
  subtotal
  raw

logistics:
  service
  shipping_carrier
  is_flex
  is_fulfillment
  deadline
  purchase_at
  payment_at
  collection_at
  marketplace_shipped_at
  rule_id

financial:
  total
  currency

platform_fields:
  shopee
  mercadolivre
  bling
  buyer_username
  buyer_user_id
  message_to_seller
```

### 6. Tabelas Espelho de Pedido

#### `pedidos_bling`

Uso atual:

- Espelho do payload do Bling.
- Fonte de compatibilidade para importacao, personalizacao, demanda e filtros.
- Referencia em `pedidos.pedido_bling_id`.

Limpeza recomendada:

- Nao dropar agora.
- Classificar como `source mirror`.
- Garantir unique por `bling_integration_id + bling_id` ou equivalente.
- Migrar leituras ricas para `pedido_snapshots.raw_refs.bling`.
- Manter apenas campos necessarios para compatibilidade e auditoria.

#### `pedidos_shopee`

Uso atual:

- Espelho do payload Shopee.
- Usado para dados especificos como username, shipping carrier e datas.
- Referencia em `pedidos.pedido_shopee_id`.

Limpeza recomendada:

- Nao dropar agora.
- Migrar leitura de dados especificos para `pedido_snapshots.platform_fields.shopee`.
- Garantir que `buyer_username`, `shipping_carrier`, `ship_by_date`, `package_list` existam no snapshot.
- Depois de migrar telas e workers, transformar em tabela de auditoria ou view.

#### Mercado Livre

Uso atual:

- Ha upsert de espelho Mercado Livre via `_upsert_pedido_meli`.
- Dados de order/shipment/payment/SLA precisam ficar vinculados ao pedido.

Limpeza recomendada:

- Padronizar nome e contrato do espelho se ainda nao estiver formalizado.
- Priorizar `pedido_snapshots.platform_fields.mercadolivre`.
- Guardar `order`, `shipment`, `payment`, `sla` em `raw_refs` ou `platform_fields`.

### 7. Colunas Candidatas a Revisao em `pedidos`

Observacao: nao remover sem verificar views/telas/workers.

Colunas que provavelmente devem permanecer como cache operacional:

- `id`
- `numero_pedido`
- `codigo_pedido_externo`
- `origem`
- `marketplace_integration_id`
- `bling_integration_id`
- `canal_venda_id`
- `situacao_pedido_id`
- `status_original`
- `marketplace_order_id`
- `bling_order_id`
- `bling_order_number`
- `ingest_source`
- timestamps principais
- campos de busca/filtro frequente

Colunas candidatas a migrar para snapshot ou manter apenas como cache:

- `informacoes_cliente`
- `buyer_username`
- `shipping_carrier`
- `message_to_seller`
- `servico_logistico`
- `is_flex`
- `is_fulfillment`
- dados financeiros detalhados
- qualquer payload especifico de marketplace

Regra recomendada:

- Campo usado para filtro/listagem rapida pode ficar em `pedidos`.
- Campo rico/especifico/inspecionavel deve viver em `pedido_snapshots`.
- Payload bruto deve ficar em `raw_refs` ou espelho de auditoria.

### 8. Views de Compatibilidade

Antes de remover tabelas/colunas, criar views como:

```text
vw_pedidos_operacionais
vw_pedidos_marketplace
vw_pedidos_com_snapshot
vw_integracoes_credenciais_status
vw_marketplace_invoice_routing
```

Objetivo:

- Reduzir acoplamento das telas ao modelo antigo.
- Permitir migracao gradual.
- Facilitar auditoria de divergencia entre `pedidos`, snapshots e espelhos.

### 9. Ordem Recomendada de Execucao

1. Inventario de dependencias por tabela/coluna com `rg` e queries em `information_schema`.
2. Backfill de credenciais canonicas em `installed_integrations`.
3. Criar/validar contrato de capabilities.
4. Criar/validar contrato de NF.
5. Garantir snapshot para todos os caminhos de ingest.
6. Migrar leitura das telas para snapshot/views.
7. Criar jobs de validacao de divergencia.
8. Marcar tabelas espelho como deprecated na documentacao.
9. Remover colunas/tabelas somente apos 2 ciclos sem leitura/escrita ativa.

### 10. Queries de Auditoria Sugeridas

```sql
-- Integracoes Shopee sem shop_id canonico.
select id, instance_name, config, credentials
from installed_integrations
where module_id ilike '%shopee%'
  and coalesce(config->>'shop_id', credentials->>'shop_id') is null;

-- Integracoes Mercado Livre sem user_id/seller_id canonico.
select id, instance_name, config, credentials
from installed_integrations
where module_id = 'mercadolivre'
  and coalesce(config->>'user_id', credentials->>'user_id', config->>'seller_id', credentials->>'seller_id') is null;

-- Pedidos sem snapshot.
select p.id, p.codigo_pedido_externo, p.marketplace_integration_id, p.ingest_source
from pedidos p
left join pedido_snapshots ps on ps.pedido_id = p.id
where ps.id is null;

-- Snapshots sem marketplace_order_id.
select id, pedido_id, identity
from pedido_snapshots
where coalesce(identity->>'marketplace_order_id', '') = '';

-- Pedidos com marketplace direto sem vinculo Bling.
select id, codigo_pedido_externo, marketplace_integration_id, bling_integration_id
from pedidos
where ingest_source in ('shopee', 'mercadolivre')
  and bling_integration_id is null;
```

## Conclusao

A limpeza nao deve comecar por `drop column` ou `drop table`. O caminho mais seguro e:

1. estabilizar contratos (`installed_integrations`, capabilities, NF, snapshots);
2. fazer backfill;
3. migrar leituras;
4. auditar divergencias;
5. so entao remover legado.

O maior ganho imediato vem de consolidar `pedido_snapshots` como fonte canonica e tratar `pedidos_bling`/`pedidos_shopee`/espelhos Mercado Livre como origem bruta ou compatibilidade, nao como modelo principal do dominio.
