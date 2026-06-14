# WEBHOOKS

## Como consultar as notificações

Quando você receber uma notificação sobre um tópico, será necessário realizar uma solicitação GET ao recurso indicado para obter os detalhes completos. Se você tiver salvo uma versão anterior do JSON, é importante compará-la com a nova resposta para identificar mudanças.

### Estrutura de Notificação tópico geral:

As notificações têm uma estrutura uniforme, o que facilita o acesso e a análise dos dados:

```javascript

{
   "_id": "id_unico",
   "resource": "/caminho_do_recurso",
   "user_id": "id_do_usuario",
   "topic": "topico",
   "application_id": "id_da_aplicacao",
   "attempts": numero_tentativas,
   "sent": "timestamp_envio",
   "received": "timestamp_recebimento"
}

```

### Como Acessar o Recurso:

1. Identifique o  **resource** : O campo **resource** na notificação indica a URL para a qual você deve fazer a solicitação GET.
2. Determine o  **topic** : O campo **topic** indica o tipo de recurso (por exemplo, items, orders, claims).
3. Faça a Solicitação GET: Com base no  **resource** , envie uma solicitação GET para acessar os detalhes completos do recurso.

### Exemplo de atualização de pedido

```
{
  "_id": "b8ea6057-8cda-4b5a-b77f-a353209b96db",
  "topic": "orders_v2",
  "resource": "/orders/2000016928497960",
  "user_id": 207584268,
  "application_id": 2056757525653794,
  "sent": "2026-06-14T01:41:15.551Z",
  "attempts": 1,
  "received": "2026-06-14T01:41:15.428Z",
  "actions": [
    "flows:catalog",
    "site_id:mlb",
    "channel:marketplace",
    "expiration_date",
    "is_test:false",
    "pack_order:true"
  ]
}
```
