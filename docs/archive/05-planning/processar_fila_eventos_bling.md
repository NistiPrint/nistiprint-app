# Processamento de Fila de Eventos Bling - Webhooks Shopee

## Visão Geral

Este documento descreve o fluxo de processamento de webhooks da Bling para pedidos da Shopee, com foco em acumular registros de pedidos no sistema para consolidar demandas de produção.

---

## Arquitetura Atual

```
┌─────────────┐      ┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│   Bling     │ ───► │   n8n       │ ───► │   Redis     │ ───► │   Worker    │
│  (webhook)  │      │  (externo)  │      │  (fila)     │      │  (Celery)   │
└─────────────┘      └─────────────┘      └─────────────┘      └─────────────┘
                                              │                      │
                                              │                      ▼
                                              │            ┌─────────────────┐
                                              │            │ bling_order_    │
                                              │            │ processing_     │
                                              │            │ service.py      │
                                              │            └─────────────────┘
                                              │                      │
                                              │                      ▼
                                              │            ┌─────────────────┐
                                              │            │ order_service   │
                                              │            │ (pedidos)       │
                                              │            └─────────────────┘
                                              │
                                              │ (opcional: log)
                                              ▼
                                     ┌─────────────────┐
                                     │ webhook_logs    │
                                     │ (Supabase)      │
                                     └─────────────────┘
```

### Componentes

| Componente | Responsabilidade |
|------------|------------------|
| **Bling** | Envia webhook quando pedido muda de situação |
| **n8n (externo)** | Recebe webhook, valida e enqueue no Redis |
| **Redis** | Fila `bling:webhooks:pendentes` |
| **Worker Celery** | Consome fila a cada 30s (`consumir_fila_bling`) |
| **BlingOrderProcessingService** | Processa webhook, enriquece dados, persiste |

---

## Requisitos de Negócio

### 1. Filtro por Situação do Pedido

Apenas pedidos com **situação ID 15 (Em Andamento)** devem ser processados:

| ID | Situação | Ação |
|----|----------|------|
| 15 | Em Andamento | ✅ Processar completo (buscar detalhes, produtos, Shopee) |
| 6 | Em Aberto | ℹ️ Apenas atualizar status |
| 9 | Atendido | ℹ️ Apenas atualizar status |
| 12 | Cancelado | ⏭️ Ignorar |
| Outros | - | ⏭️ Ignorar |

### 2. Filtro por Loja Shopee

Apenas pedidos das lojas Shopee devem ser processados:

| ID Loja | Plataforma | CNPJ |
|---------|------------|------|
| 204047801 | Shopee (antiga) | 13597 |
| 205218967 | Shopee (nova) | 13597 |
| 205533791 | Shein (cnpj03) | 30301 |

**Constante:** `BLING_ID_LOJA_SHOPEE = [204047801, 205218967, 205533791]`

### 3. Dados a Serem Coletados

#### Da Bling (API V3)
- ✅ ID do pedido
- ✅ Número do pedido (numeroLoja)
- ✅ Situação
- ✅ Contato (cliente)
- ✅ **Itens do pedido** (produtos, quantidades, SKUs)
- ✅ Totais

#### Da Shopee (API V2)
- ✅ `buyer_username` (nome de usuário do comprador)
- ✅ `pay_time` (data limite para postagem)
- ✅ `order_status` (status original Shopee)
- ✅ `item_list` (detalhes dos itens)

### 4. Associação de Produtos

Para cada item do pedido, tentar associar com cadastro interno:

```python
match = product_service.resolve_variation(
    sku_externo=item['codigo'],
    plataforma='Shopee',
    nome_externo=item['descricao']
)
```

**Resultado:**
- ✅ **Mapeado:** `produto_id` interno vinculado
- ⚠️ **Não Mapeado:** Registro como órfão para revisão posterior

---

## Fluxo de Processamento

### Diagrama de Sequência

```
Worker (Celery)
    │
    ├─► 1. Recebe payload do Redis
    │    {data: {id: 123, situacao: {id: 15}, loja: {id: 204047801}}}
    │
    ├─► 2. Filtra por situação (id == 15?)
    │    └─► NÃO: Retorna skipped
    │    └─► SIM: Continua
    │
    ├─► 3. Filtra por loja Shopee (loja.id ∈ BLING_ID_LOJA_SHOPEE?)
    │    └─► NÃO: Retorna skipped
    │    └─► SIM: Continua
    │
    ├─► 4. Busca detalhes na Bling API V3
    │    GET /pedidos/vendas/{order_id}
    │    └─► Retorna: itens, contato, totais
    │
    ├─► 5. Para cada item, associa produto interno
    │    product_service.resolve_variation(sku, plataforma, nome)
    │    └─► Adiciona produto_id se encontrado
    │
    ├─► 6. Busca dados adicionais na Shopee API V2
    │    GET /api/v2/order/get_order_detail
    │    └─► Retorna: buyer_username, pay_time, order_status
    │
    ├─► 7. Persiste no banco unificado
    │    order_service.upsert_order(...)
    │    ├─► tabela: pedidos (core)
    │    ├─► tabela: vinculos_integracao_pedido (link)
    │    └─► tabela: itens_pedido (itens)
    │
    └─► 8. Gera demanda de produção
         demanda_producao_service.create_from_order()
```

---

## Estrutura de Dados

### Payload do Webhook (Entrada)

```json
{
  "data": {
    "id": 987654321,
    "numero": 12345,
    "numeroLoja": "204047801-SP240313ABC123",
    "data": "2026-03-13T10:30:00",
    "situacao": {
      "id": 15,
      "valor": 3
    },
    "loja": {
      "id": 204047801
    },
    "contato": {
      "nome": "João Silva",
      "numeroDocumento": "123.456.789-00"
    },
    "itens": [
      {
        "codigo": "MIOLO-AGENDA-2026",
        "descricao": "Miolo Agenda 2026 - Floral",
        "quantidade": 2,
        "valor": 25.90
      }
    ]
  }
}
```

### Pedido Core (tabela: `pedidos`)

```python
{
    'id': <core_id>,
    'numero_pedido': '12345',
    'codigo_pedido_externo': '204047801-SP240313ABC123',
    'origem': 'SHOPEE',
    'cliente_nome': 'João Silva',
    'cliente_documento': '123.456.789-00',
    'data_venda': '2026-03-13T10:30:00',
    'status_unificado': 'PAGO',  # mapeado de situacao.id=15
    'status_original': '15',
    'total_pedido': 51.80,
    'informacoes_cliente': {
        'buyer_username': 'joao.silva',
        'data_limite_postagem': '2026-03-15T23:59:59',
        'shopee_order_status': 'READY_TO_SHIP'
    },
    'canal_venda_id': <channel_id>,
    'created_at': '2026-03-13T10:35:00',
    'updated_at': '2026-03-13T10:35:00'
}
```

### Vínculo de Integração (tabela: `vinculos_integracao_pedido`)

```python
{
    'id': <vinculo_id>,
    'pedido_id': <core_id>,
    'plataforma': 'BLING',
    'id_na_plataforma': '987654321',  # ID interno Bling
    'status_na_plataforma': '15',
    'integration_id': <account_id>,
    'dados_brutos': {...payload completo Bling...},
    'last_synced_at': '2026-03-13T10:35:00'
}
```

### Itens do Pedido (tabela: `itens_pedido`)

```python
[
    {
        'id': <item_id>,
        'pedido_id': <core_id>,
        'produto_id': <id_produto_interno>,  # null se não mapeado
        'sku_externo': 'MIOLO-AGENDA-2026',
        'descricao': 'Miolo Agenda 2026 - Floral',
        'quantidade': 2,
        'preco_unitario': 25.90,
        'subtotal': 51.80,
        'created_at': '2026-03-13T10:35:00'
    }
]
```

---

## Implementação

### Arquivos Envolvidos

| Arquivo | Responsabilidade |
|---------|------------------|
| `packages/shared/nistiprint_shared/services/bling_order_processing_service.py` | Processamento principal |
| `packages/shared/nistiprint_shared/services/order_sync_service.py` | Sincronização com modelo unificado |
| `packages/shared/nistiprint_shared/services/order_service.py` | Persistência no banco |
| `packages/shared/nistiprint_shared/services/product_service.py` | Associação de produtos |
| `packages/shared/nistiprint_shared/services/platform_drivers/shopee.py` | API Shopee V2 |
| `apps/worker/worker_entrypoint.py` | Configuração Celery |
| `packages/shared/nistiprint_shared/services/redis_queue_tasks.py` | Consumer da fila |

### Constantes

```python
# Em constants.py
BLING_ID_LOJA = {
    204047801: 'Shopee',
    205218967: 'Shopee',
    205533791: 'Shein'
}

BLING_ID_LOJA_SHOPEE = [204047801, 205218967, 205533791]

SITUACOES_PEDIDOS_BLING = {
    'Em Andamento': 15,
    'Em Aberto': 6,
    'Atendido': 9,
    'Cancelado': 12,
}
```

### Pseudocódigo do Processamento

```python
class BlingOrderProcessingService:
    
    def process_webhook(self, webhook_payload: dict):
        data = webhook_payload.get('data', webhook_payload)
        order_id = data.get('id')
        loja = data.get('loja', {})
        loja_id = loja.get('id')
        situacao = data.get('situacao', {})
        situacao_id = situacao.get('id')
        
        # 1. Filtrar por situação
        if situacao_id != 15:
            return {"status": "skipped", "message": f"Situação {situacao_id} ignorada"}
        
        # 2. Filtrar por loja Shopee
        if loja_id not in BLING_ID_LOJA_SHOPEE:
            return {"status": "skipped", "message": f"Loja {loja_id} não é Shopee"}
        
        # 3. Buscar detalhes na Bling
        client = self._get_bling_client_for_details()
        full_order_data = client.get_order(order_id)
        
        if not full_order_data:
            return {"status": "failed", "message": "Falha ao buscar detalhes"}
        
        # 4. Associar produtos internos
        enriched_items = self._associate_products(full_order_data.get('itens', []))
        full_order_data['itens'] = enriched_items
        
        # 5. Buscar dados Shopee
        numero_loja = full_order_data.get('numeroLoja')
        shopee_data = self._fetch_shopee_additional_data(numero_loja)
        
        # 6. Sincronizar com modelo unificado
        sync_result = order_sync_service.sync_bling_order(
            full_order_data, 
            shopee_data
        )
        
        # 7. Salvar no banco legado (compatibilidade)
        self._save_order_to_db(full_order_data, shopee_data)
        
        return {
            "status": "success", 
            "message": f"Pedido {order_id} processado",
            "core_id": sync_result.get('id')
        }
    
    def _associate_products(self, items: list) -> list:
        """Associa produtos internos a cada item do pedido."""
        enriched = []
        for item in items:
            match = product_service.resolve_variation(
                sku_externo=item.get('codigo'),
                plataforma='Shopee',
                nome_externo=item.get('descricao')
            )
            
            enriched_item = {
                **item,
                'produto_id': match['id'] if match else None,
                'mapping_status': 'mapeado' if match else 'nao_mapeado'
            }
            enriched.append(enriched_item)
        
        return enriched
    
    def _fetch_shopee_additional_data(self, numero_loja: str) -> dict:
        """Busca dados adicionais na API Shopee."""
        # Extrair order_sn do numeroLoja (formato: "204047801-SP240313ABC123")
        order_sn = numero_loja.split('-')[-1] if '-' in numero_loja else numero_loja
        
        try:
            shopee_data = platform_api_service.get_order_detail(
                order_sn_list=[order_sn],
                instance_id=None,
                platform="shopee"
            )
            
            return {
                'buyer_username': shopee_data.get('customer', {}).get('name'),
                'pay_time': shopee_data.get('date_created'),
                'order_status': shopee_data.get('status_original'),
                'raw': shopee_data.get('raw', {})
            }
        except Exception as e:
            logging.error(f"Erro ao buscar dados Shopee: {e}")
            return {}
```

---

## Critérios de Aceite

- [ ] Pedidos de outras lojas (Amazon, Mercado Livre) são ignorados
- [ ] Pedidos com situação diferente de 15 são ignorados
- [ ] Detalhes completos do pedido são buscados da Bling
- [ ] Produtos são associados ao cadastro interno quando possível
- [ ] Dados da Shopee (username, pay_time) são coletados
- [ ] Pedido é persistido na tabela `pedidos` (core)
- [ ] Vínculo é criado em `vinculos_integracao_pedido`
- [ ] Itens são salvos em `itens_pedido`
- [ ] Demanda de produção é gerada automaticamente
- [ ] Logs adequados são gerados para monitoramento

---

## Monitoramento e Debug

### Logs Esperados

```
📄 Processando Evento Bling - Pedido: 987654321, Situação: 15
🏪 Loja: 204047801 (Shopee)
🚀 Pedido 987654321 em ANDAMENTO. Buscando detalhes na Conta 01...
📦 Itens encontrados: 3
🔗 Associando produtos internos...
  ✅ SKU 'MIOLO-AGENDA-2026' → Produto ID: 456
  ⚠️ SKU 'CUSTOM-XYZ' → Não mapeado
🦐 Buscando dados Shopee para: SP240313ABC123
  ✅ buyer_username: joao.silva
  ✅ pay_time: 2026-03-15T23:59:59
💾 Persistindo pedido no banco unificado...
  ✅ Core ID: 789
  ✅ Vínculo criado
  ✅ 3 itens salvos
🏭 Gerando demanda de produção...
  ✅ Demanda criada: DEM-2026-00123
```

### Queries de Verificação

```sql
-- Verificar pedidos processados hoje
SELECT 
    p.id,
    p.numero_pedido,
    p.codigo_pedido_externo,
    p.origem,
    p.status_unificado,
    p.created_at,
    COUNT(i.id) as total_itens
FROM pedidos p
LEFT JOIN itens_pedido i ON i.pedido_id = p.id
WHERE p.origem = 'SHOPEE'
  AND p.created_at >= CURRENT_DATE
GROUP BY p.id;

-- Verificar itens não mapeados
SELECT 
    ip.sku_externo,
    ip.descricao,
    COUNT(*) as ocorrencias
FROM itens_pedido ip
WHERE ip.produto_id IS NULL
  AND ip.created_at >= CURRENT_DATE - INTERVAL '7 days'
GROUP BY ip.sku_externo, ip.descricao
ORDER BY ocorrencias DESC;

-- Verificar vínculos de integração
SELECT 
    p.numero_pedido,
    vip.plataforma,
    vip.id_na_plataforma,
    vip.last_synced_at
FROM pedidos p
JOIN vinculos_integracao_pedido vip ON vip.pedido_id = p.id
WHERE p.origem = 'SHOPEE'
ORDER BY vip.last_synced_at DESC
LIMIT 10;
```

---

## Próximos Passos da Evolução

1. ✅ **Acumular registros de pedidos** (este documento)
2. ⏳ **Consolidar demandas de produção** (próxima fase)
3. ⏳ **Dashboard de acompanhamento** (pedidos, produção, estoque)
4. ⏳ **Alertas de atraso** (data limite postagem vs. status)
5. ⏳ **Relatórios de conversão** (pedidos por período, produto, plataforma)

---

## Referências

- [API Bling V3 - Pedidos](https://developer.bling.com.br/referencia#/Pedidos%20Vendas)
- [Shopee Partner API V2](https://open.shopee.com/documents?version=2)
- [Documentação order_service](./order_service.md)
- [Documentação product_service](./product_service.md)

---

**Última atualização:** 2026-03-13  
**Autor:** Equipe NistiPrint  
**Status:** Em implementação
