

Endpoint para obter múltiplos pedidos de venda

GET /pedidos/vendas/

Query parameters:

```
Name	Description
pagina
integer
(query)
N° da página da listagem
Default value : 1

limite
integer
(query)
Quantidade de registros que devem ser exibidos por página
Default value : 100

idContato
integer
(query)
ID do contato

idsSituacoes[]
array<integer>
(query)
Conjunto de situações

dataInicial
string($date)
(query)
Data incial
2022-01-01

dataFinal
string($date)
(query)
Data final
2022-01-15

dataAlteracaoInicial
string($datetime)
(query)
Data inicial da alteração
2022-01-01 10:00:00

dataAlteracaoFinal
string($datetime)
(query)
Data final da alteração
2022-01-15 11:00:00

dataPrevistaInicial
string($date)
(query)
Data inicial prevista
2022-01-01

dataPrevistaFinal
string($date)
(query)
Data final prevista
2022-01-15

numero
integer
(query)
Número do pedido de venda

idLoja
integer
(query)
ID da loja

idVendedor
integer
(query)
ID do vendedor

idControleCaixa
integer
(query)
ID do controle de caixa

numerosLojas[]
array<string>
(query)
Conjunto de números de pedidos nas lojas

idUnidadeNegocio
integer
(query)
ID da unidade de negócio (filial)


```

Response:

```
{
  "data": [
    {
      "id": 12345678,
      "numero": 123,
      "numeroLoja": "Loja_123",
      "data": "2023-01-12",
      "dataSaida": "2023-01-12",
      "dataPrevista": "2023-01-12",
      "totalProdutos": 10,
      "total": 12,
      "contato": {
        "id": 12345678,
        "nome": "Contato do Bling",
        "tipoPessoa": "J",
        "numeroDocumento": "30188025000121"
      },
      "situacao": {
        "id": 12345678,
        "valor": 1
      },
      "loja": {
        "id": 12345678,
        "unidadeNegocio": {
          "id": 12345678
        }
      }
    }
  ]
}
```


Endpoint para obter pedido de venda

**GET** [/pedidos/vendas/{idPedidoVenda}](https://developer.bling.com.br/referencia#/Pedidos%20-%20Vendas/get_pedidos_vendas__idPedidoVenda_) Obtém um pedido de venda

```
{
  "data": {
    "id": 12345678,
    "numero": 123,
    "numeroLoja": "Loja_123",
    "data": "2023-01-12",
    "dataSaida": "2023-01-12",
    "dataPrevista": "2023-01-12",
    "totalProdutos": 10,
    "total": 12,
    "contato": {
      "id": 12345678,
      "nome": "Contato do Bling",
      "tipoPessoa": "J",
      "numeroDocumento": "30188025000121"
    },
    "situacao": {
      "id": 12345678,
      "valor": 1
    },
    "loja": {
      "id": 12345678,
      "unidadeNegocio": {
        "id": 12345678
      }
    },
    "numeroPedidoCompra": "123",
    "outrasDespesas": 2,
    "observacoes": "Observações do pedido.",
    "observacoesInternas": "Observações internas do pedido.",
    "desconto": {
      "valor": 15.45,
      "unidade": "REAL"
    },
    "categoria": {
      "id": 12345678
    },
    "notaFiscal": {
      "id": 12345678
    },
    "tributacao": {
      "totalICMS": 5.55,
      "totalIPI": 5.55
    },
    "itens": [
      {
        "id": 12345678,
        "codigo": "BLG-5",
        "unidade": "UN",
        "quantidade": 1,
        "desconto": 2,
        "valor": 4.9,
        "aliquotaIPI": 0,
        "descricao": "Produto do Bling",
        "descricaoDetalhada": "Brinde",
        "produto": {
          "id": 12345678
        },
        "comissao": {
          "base": 10,
          "aliquota": 2,
          "valor": 0.2
        },
        "naturezaOperacao": {
          "id": 12345678
        }
      }
    ],
    "parcelas": [
      {
        "id": 12345678,
        "dataVencimento": "2023-01-12",
        "valor": 123.45,
        "observacoes": "Observação da parcela",
        "caut": "123456789",
        "formaPagamento": {
          "id": 12345678
        }
      }
    ],
    "transporte": {
      "fretePorConta": 0,
      "frete": 20,
      "quantidadeVolumes": 1,
      "pesoBruto": 0.5,
      "prazoEntrega": 10,
      "contato": {
        "id": 12345678,
        "nome": "Transportador"
      },
      "etiqueta": {
        "nome": "Transportador",
        "endereco": "Olavo Bilac",
        "numero": "914",
        "complemento": "Sala 101",
        "municipio": "Bento Gonçalves",
        "uf": "RS",
        "cep": "95702-000",
        "bairro": "Imigrante",
        "nomePais": "BRASIL"
      },
      "volumes": [
        {
          "id": 12345678,
          "servico": "ALIAS_123",
          "codigoRastreamento": "COD123BR"
        }
      ]
    },
    "vendedor": {
      "id": 12345678
    },
    "intermediador": {
      "cnpj": "13921649000197",
      "nomeUsuario": "usuario"
    },
    "taxas": {
      "taxaComissao": 1,
      "custoFrete": 9.99,
      "valorBase": 129.9
    }
  }
}
```
