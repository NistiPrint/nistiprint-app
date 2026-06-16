# Regras de Negocio - Integracoes, Pedidos e NF

Last updated: 2026-06-16

Status: target-state

## 1. Principios

- A plataforma roteia funcoes entre modulos locais e integracoes externas.
- A origem da venda pertence ao marketplace, nao ao mecanismo tecnico de ingest.
- O ERP pode continuar sendo obrigatorio para NF mesmo quando o pedido entra
  direto do marketplace.
- Tabelas especificas por provedor existem para auditoria e apoio operacional,
  nao como modelo principal do pedido.

## 2. Regras de integracoes

### 2.1 Instalacao

- Cada conta externa instalada vira uma `installed_integration`.
- Um modulo dummy tambem pode ser instalado para criar uma origem de venda.
- Uma instalacao dummy nao precisa de API propria para existir como origem.

### 2.2 Viculos ERP e marketplace

- Uma conta marketplace pode estar ligada a multiplas contas Bling.
- Cada vinculo e contextualizado por `erp_store_id`/`shop.id`.
- Uma conta Bling pode atender varios marketplaces.
- O ERP nao deve ser escolhido somente pelo marketplace.

### 2.3 Configuracao operacional

Na conta Bling:

- a tela mostra quais marketplaces usam aquela conta
- cada linha mostra `shop.id`
- cada linha mostra se o ingest ocorre por `erp` ou `marketplace`

Na conta marketplace:

- a tela define qual Bling atende NF
- a tela pode manter varios vinculos Bling
- a tela pode definir o comportamento default quando o pedido entra por webhook
  direto e ha mais de um ERP possivel

## 3. Regras de ingest de pedidos

- Shopee: ingest e atualizacao via webhook direto quando configurado
- Mercado Livre: ingest e atualizacao via webhook direto quando configurado
- Demais marketplaces e dummies: ingest e atualizacao via Bling
- Bling continua podendo enriquecer e contextualizar pedidos mesmo quando nao e
  a origem tecnica principal do evento

Precedencia alvo:

1. webhook direto do marketplace quando a conta suporta esse fluxo
2. Bling webhook/fetch como fallback
3. enriquecimento sempre centralizado no driver da plataforma

## 4. Regras do pedido canonico

- `pedidos` e `pedido_snapshots` sao a fonte principal do dominio
- `pedidos_bling`, `pedidos_shopee` e `pedidos_mercadolivre` sao espelhos
- o pedido deve conter os campos comuns de qualquer venda:
  - comprador
  - itens
  - datas principais
  - contexto logistico
  - totais
- detalhes especificos do marketplace vao para `platform_fields`

Exemplos:

- Shopee precisa armazenar `buyer_username`
- Mercado Livre pode armazenar campos proprios de envio e comprador
- Bling precisa armazenar contexto ERP e NF

## 5. Dedupe e identidade

- `pedidos.id` e a identidade interna
- `codigo_pedido_externo` e a identidade estavel na origem
- quando o pedido chega pelo Bling, `numeroLoja` e o ID externo da venda na
  origem
- a deduplicacao deve usar origem comercial canonica + ID externo do pedido

## 6. Regras de NF

- Todo pedido especifico deve resolver uma unica conta ERP para NF
- A ordem de resolucao e:
  1. `bling_integration_id` do pedido
  2. vinculo por `marketplace_integration_id + erp_store_id`
  3. default configurado na conta marketplace para webhook direto

Regra de erro:

- se mais de um ERP permanecer valido e nao houver contexto suficiente, a NF
  deve ser bloqueada por ambiguidade

## 7. Regras de credenciais

- Bling: credenciais sincronizadas externamente
- Shopee e Mercado Livre: refresh/teste local quando o modulo suportar
- UI deve mostrar:
  - origem da credencial
  - expiracao
  - suporte a refresh
  - ultimo status de teste/renovacao

## 8. Regras da lista de pedidos

- `origem da venda` mostra somente marketplaces instalados
- o filtro nao representa rota de importacao
- ERP/Bling nao deve aparecer como origem da venda no filtro

## 9. Regras de producao que permanecem validas

- classificacao de Flex continua sendo uma regra de negocio relevante
- modalidade logistica continua sendo derivada de regras configuradas
- consolidacao e producao seguem usando o pedido canonico como insumo
