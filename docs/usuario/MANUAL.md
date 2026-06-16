# Manual do Usuario - Integracoes e Pedidos

Last updated: 2026-06-16

Status: current-guidance

## 1. Conceitos operacionais

### Origem da venda

E a conta marketplace que vendeu o pedido. Na lista de pedidos, esse filtro
mostra apenas marketplaces instalados.

### Modo de ingest do pedido

E o caminho tecnico pelo qual o pedido entra no sistema:

- `marketplace`: webhook direto da plataforma
- `erp`: webhook/fetch via Bling

Isso nao muda a origem da venda.

### ERP responsavel

E a conta Bling usada para NF e outras funcoes ERP daquela origem de venda.

## 2. Como pensar as integracoes

Cada card de integracao representa uma conta instalada.

Tipos mais comuns:

- Bling: conta ERP
- Shopee e Mercado Livre: conta marketplace com integracao direta
- Dummy, como TikTok Shop ou Shein: origem de venda sem API propria

## 3. Configurando uma conta Bling

A tela da conta Bling serve para leitura operacional dos vinculos.

Para cada marketplace associado, a conta Bling deve mostrar:

- nome da instancia marketplace
- `shop.id`
- modo de ingest, `erp` ou `marketplace`

Interpretacao:

- `shop.id` identifica aquela conta marketplace dentro da conta Bling
- se o ingest estiver em `erp`, o pedido entra pela Bling
- se o ingest estiver em `marketplace`, o pedido entra direto pelo marketplace,
  mas ainda pode usar esse Bling para NF

## 4. Configurando uma conta marketplace

Essa e a tela autoritativa para definir o relacionamento com ERP.

Voce pode:

- vincular a conta marketplace a uma ou mais contas Bling
- informar o `shop.id` correspondente em cada Bling
- definir se o ingest da origem sera por `erp` ou `marketplace`
- definir qual Bling responde por NF

### Quando a mesma conta marketplace estiver ligada a varios Blings

Exemplo:

- Shopee A + `shop.id AA` -> Bling A
- Shopee A + `shop.id AB` -> Bling B

Nesse caso:

- o pedido continua tendo uma unica origem da venda, Shopee A
- a NF precisa ser emitida por um unico ERP por pedido
- quando o pedido vier por webhook direto e houver mais de um Bling possivel, a
  configuracao da conta marketplace define o ERP default

## 5. Modulos dummy

Um modulo dummy existe para criar uma origem de venda quando o marketplace nao
tem integracao direta na plataforma.

Comportamento:

- a instalacao gera uma origem de venda valida
- os pedidos dessa origem entram via Bling
- a conta dummy ainda precisa apontar qual Bling atende NF

## 6. Lista de pedidos

### Filtro "origem da venda"

- mostra somente marketplaces instalados
- nao mostra Bling
- nao mostra rota tecnica de importacao

### O que o usuario deve esperar

- se houver Shopee 01, Mercado Livre 02 e TikTok Shop 01 instalados, os tres
  devem aparecer no filtro, mesmo que algum deles ainda nao tenha pedido no
  periodo

## 7. Credenciais

### Bling

- normalmente nao mostra renovacao local
- as credenciais sao sincronizadas externamente

### Shopee e Mercado Livre

- podem mostrar testar conexao
- podem mostrar renovar token quando o modulo suporta refresh local

O status exibido deve refletir a situacao real da credencial, nao apenas o fato
de a integracao existir.

## 8. Regras praticas

- Se o pedido veio pelo marketplace direto, ele ainda pode depender de Bling
  para NF.
- Se o pedido veio pelo Bling, a origem da venda continua sendo o marketplace
  vinculado, nao a Bling.
- Se houver ambiguidade de ERP para NF, a configuracao da conta marketplace deve
  ser revisada.
