## Autenticação

### Técnica

A autenticação das mensagens enviadas pelo Bling deve ser realizada por meio do cabeçalho HTTP `X-Bling-Signature-256`. Esse cabeçalho contém um *hash* de autenticação HMAC (Hash-Based Message Authentication Code) composto pelo *payload* JSON da resposta e o *client secret* do aplicativo. Esse processo garante a integridade e a autenticidade dos dados enviados pelo Bling.

### Validação do hash

Para garantir que a mensagem recebida é legítima e não foi manipulada, considere os seguintes passos:

1. Gerar um *hash* HMAC utilizando o *payload* e o *client secret* do aplicativo.
2. Comparar se o *hash* informado no *header* `X-Bling-Signature-256` é igual ao *hash* gerado.

Exemplo de  *hashes* :

* *Hash* gerado: `a012da891d0cebcb375c8e12b881e81df40256dfffc25e08ba9db4ab35515516`
* *Header* informado na requisição: `sha256=a012da891d0cebcb375c8e12b881e81df40256dfffc25e08ba9db4ab35515516`

Observações:

* O Bling usa um código *hash* hexadecimal HMAC para calcular o  *hash* .
* A assinatura do *hash* sempre começa com `sha256=`.
* O padrão de codificação utilizado é o UTF-8.

## Idempotência

Idempotência é a capacidade de uma operação retornar o mesmo resultado, independentemente de quantas vezes seja executada, desde que os parâmetros sejam os mesmos.

No contexto de  *webhooks* , caso o Bling envie o mesmo *webhook* duas vezes, sua aplicação deve responder a ambas as requisições com um código HTTP `2xx`.

## Entrega não ordenada

Não há garantia da entrega dos eventos na ordem em que foram gerados. Por exemplo, um *webhook* de atualização de produto pode ser recebido antes que o *webhook* de criação deste mesmo produto.

Uma prática recomendada para lidar com esse cenário é gerenciar os *webhooks* recebidos de maneira assíncrona, usando filas, por exemplo.

## Retentativas

O processo de retentativas foi projetado para garantir a entrega confiável de *webhooks* aos integradores, mesmo diante de falhas temporárias no sistema de destino. Serão feitas tentativas no período máximo de 3 dias onde, a cada retentativa, o tempo da próxima retentativa poderá ser maior. Ao final do processo de retentativas, caso o processamento do evento continue com problemas, a configuração do *webhook* para o recurso em questão será desabilitada e o Bling não enviará novos eventos até que a configuração seja habilitada manualmente através das configurações de *webhooks* do aplicativo.

Uma requisição é considerada entregue com sucesso quando o integrador responde com um código HTTP `2xx` em até **5** segundos. Caso exceda o tempo de resposta ou o código for diferente de `2xx` serão feitas as retentativas no envio da mensagem.

## Ações

Abaixo estão detalhadas as ações disponíveis:

* `created`: Ocorre quando um recurso é criado.
* `updated`: Ocorre quando um recurso é atualizado.
* `deleted`: Ocorre quando um recurso é deletado definitivamente.
  * Alterar a situação de um recurso para excluído gera um evento de `updated`.

## Recursos

### Recursos disponíveis

Antes de configurar um recurso de  *webhook* , é necessário adicionar o escopo referente ao recurso aos dados básicos do aplicativo.

* Pedido de Venda: `order`
* Produto: `product`
* Estoque: `stock`
* Estoque virtual: `virtual_stock`
* Produto fornecedor: `product_supplier`
* Nota fiscal: `invoice`
* Nota fiscal de consumidor: `consumer_invoice`

### Estrutura de retorno

JSON

```json
{
	"eventId": "01945027-150e-72b4-e7cf-4943a042cd9c",
	"date": "2025-01-10T12:18:46Z",
	"version": "v1",
	"event": "$resource.$action",
	"companyId": "d4475854366a36c86a37e792f9634a51",
	"data": $payload
}
```

Detalhamento dos campos:

* `eventId`: Identificador único do evento.
* `date`: Data no formato ISO 8601.
* `version`: Versão do webhook.
* `event`: Recurso junto a ação separados por "`.`".
* `companyId`: ID da empresa.
  * Para obtê-lo, consulte os [dados básicos](https://developer.bling.com.br/referencia#/Empresas/get_empresas_me_dados_basicos) da empresa por API.
* `data`: *Payload* do evento.

Considere:

* `$resource`: O [recurso](https://developer.bling.com.br/webhooks#recursos) do  *webhook* .
* `$action`: A [ação](https://developer.bling.com.br/webhooks#a%C3%A7%C3%B5es) do  *webhook* .
* `$payload`: Uma das estruturas abaixo, conforme o recurso e a ação do  *webhook* 


### Pedido de venda

Estrutura dos *payloads* dos *webhooks* de pedido de venda:

#### Versão 1

##### Created

JavaScript

```javascript
{
  "id": 12345678,
  "data": "2024-09-25",
  "numero": 123,
  "numeroLoja": "Loja_123",
  "total": 123.45,
  "contato": {
    "id": 12345678
  },
  "vendedor": {
    "id": 12345678
  },
  "loja": {
    "id": 12345678
  },
  "situacao": {
    "id": 12345678,
    "valor": 12345678
  }
}
```

##### Updated

JavaScript

```javascript
{
  "id": 12345678,
  "data": "2024-09-25",
  "numero": 123,
  "numeroLoja": "Loja_123",
  "total": 123.45,
  "contato": {
    "id": 12345678
  },
  "vendedor": {
    "id": 12345678
  },
  "loja": {
    "id": 12345678
  },
  "situacao": {
    "id": 12345678,
    "valor": 12345678
  }
}
```

##### Deleted

JavaScript

```javascript
{
  "id": 12345678
}
```

### Exemplo de retorno

Para exemplicicar, conforme a [estrutura de retorno](https://developer.bling.com.br/webhooks#estrutura-de-retorno), em uma [ação](https://developer.bling.com.br/webhooks#a%C3%A7%C3%B5es) de atualização no [recurso](https://developer.bling.com.br/webhooks#recursos) de produtos, teríamos o seguinte  *payload* :

JSON

```json
{
	"eventId": "01945027-150e-72b4-e7cf-4943a042cd9c",
	"date": "2025-01-10T12:18:46Z",
	"version": "v1",
	"event": "product.updated",
	"companyId": "d4475854366a36c86a37e792f9634a51",
	"data": {
		"id": 12345678,
		"nome": "Copo do Bling",
		"codigo": "COD-4587",
		"tipo": "P",
		"situacao": "A",
		"preco": 4.99,
		"unidade": "UN",
		"formato": "S",
		"idProdutoPai": 12345678,
		"categoria": {
			"id": 12345679
		},
		"descricaoCurta": "Descrição curta",
		"descricaoComplementar": "Descrição complementar"
	}
}
```
