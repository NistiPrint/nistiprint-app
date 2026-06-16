# Arquitetura Tecnica - Integracoes e Pedidos

Last updated: 2026-06-16

Status: target-state

## 1. Visao geral

O sistema atua como um orquestrador entre marketplaces, ERP e processos locais.
Ele nao assume que toda venda entra pelo mesmo caminho tecnico, nem que todo
marketplace tenha integracao direta.

Arquitetura logica:

```text
Marketplace direto webhook ----\
                                \
                                 -> worker/servicos -> pedido canonico -> producao/NF/UI
                                /
Bling webhook/fetch ----------/

Marketplace driver <-------- enrich/test/refresh when supported

Installed integrations ------ routing/configuration identity
ERP-marketplace links ------- NF and ingest routing context
```

## 2. Unidade central: integracao instalada

- `integration_modules` define o tipo do conector.
- `installed_integrations` define a conta instalada que o usuario realmente usa.
- Uma instancia instalada pode ser:
  - ERP, hoje Bling
  - marketplace direto, como Shopee e Mercado Livre
  - marketplace dummy, como origem de venda sem API propria

Consequencia arquitetural:

- Toda resolucao operacional relevante deve partir de uma instancia instalada,
  nao apenas de um nome de plataforma ou de um canal legado.

## 3. Relacionamentos chave

### 3.1 Entrada da venda, ERP para Marketplace

Quando o pedido chega via Bling, o sistema resolve:

- qual conta ERP recebeu o evento, usando `companyId`
- qual conta marketplace dentro daquele ERP recebeu a venda, usando `shop.id`

Esse relacionamento descreve o caminho tecnico de entrada do pedido.

### 3.2 Atendimento da venda, Marketplace para ERP

Quando a plataforma precisa emitir NF ou executar funcao ERP, o marketplace
aponta qual conta Bling atende aquela venda.

Esse relacionamento descreve quem atende a venda depois que ela existe.

### 3.3 Cardinalidade

- Um marketplace pode apontar para varios Blings.
- Um Bling pode atender varios marketplaces.
- A unidade operacional do vinculo e:
  `erp_integration_id + marketplace_integration_id + erp_store_id`

## 4. Ingest e precedencia

### 4.1 Regras alvo

- Shopee: webhook direto quando configurado.
- Mercado Livre: webhook direto quando configurado.
- Dummies e demais marketplaces: Bling webhook/fetch.
- Bling permanece essencial para NF e para marketplaces sem driver direto.

### 4.2 Enriquecimento

- Quando um pedido chega pelo Bling e a origem comercial e uma conta direta
  Shopee ou Mercado Livre, o sistema pode enriquecer o pedido usando o driver
  da plataforma.
- Teste de conexao, renovacao e enriquecimento devem viver no driver da
  plataforma, e nao dispersos em rotas ou servicos ad hoc.

## 5. Pedido canonico

O pedido operacional e formado por:

- `pedidos`: registro principal da venda
- `pedido_snapshots`: payload normalizado e particularidades em `platform_fields`

Tabelas espelho:

- `pedidos_bling`
- `pedidos_shopee`
- `pedidos_mercadolivre`

Essas tabelas servem para auditoria, rastreabilidade e reprocessamento. Elas
nao sao a fonte primaria do dominio.

## 6. Dedupe e identidade

- Origem canonica da venda: `marketplace_integration_id`
- Contexto ERP: `bling_integration_id`
- ID externo estavel: `codigo_pedido_externo`
- Quando o pedido veio pelo Bling, `numeroLoja` e o identificador externo da
  venda na origem, salvo regra mais especifica do marketplace

Regra:

- Deduplicacao deve usar origem canonica + ID externo do pedido.

## 7. Resolucao de NF

Ordem de resolucao:

1. `pedido.bling_integration_id`, quando ja materializado
2. vinculo explicito por `marketplace_integration_id + erp_store_id`
3. fallback configurado na conta marketplace para webhook direto

Regra obrigatoria:

- Se ainda houver mais de um ERP possivel, a NF deve falhar por ambiguidade.

## 8. Contrato de UI

### Tela do ERP

- Exibe os marketplaces vinculados a essa conta Bling
- Mostra `shop.id`
- Mostra se o ingest daquela origem esta em `erp` ou `marketplace`
- E uma visao operacional, nao o local autoritativo de cadastro do vinculo

### Tela do marketplace

- E o ponto autoritativo para configurar qual ERP atende a venda
- Define o Bling responsavel por NF
- Pode manter varios vinculos Bling quando necessario
- Dummy segue a mesma semantica de origem da venda

### Lista de pedidos

- O filtro `origem da venda` mostra apenas marketplaces instalados
- Ele nao representa rota de importacao nem mecanismo tecnico de webhook

## 9. Credenciais

- Bling: sincronizacao externa; sem refresh local
- Shopee e Mercado Livre: refresh e teste local quando suportados
- O status exibido deve considerar estrategia real da credencial, expiracao e
  suporte do modulo

## 10. Notas de transicao

- `channel_connections` e `canal_venda` ainda existem por compatibilidade, mas
  nao definem a origem comercial canonica.
- Documentos ou trechos legados que tratem Bling como fonte primaria absoluta
  de todos os pedidos devem ser considerados superados por este documento.
