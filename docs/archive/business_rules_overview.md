# Documentação da Camada de Negócios - Nistiprint

> **Escopo:** Esta documentação cobre exclusivamente os módulos de produção e operações:
> - `nistiprint-shared/` - Modelos e serviços compartilhados
> - `nistiprint-api/` - API e regras de negócio
> - `nistiprint-worker/` - Tarefas assíncronas e processamento em background
> - `nistiprint-frontend/` - Validações e schemas do cliente

---

## 1. Regras de Negócio Principais (Core Business Rules)

### 1.1 Definições de Produtos

#### Formatos de Produto (`formato`)

| Formato | Descrição | Pode ter Estoque Físico? | Requer BOM? |
|---------|-----------|-------------------------|-------------|
| **Simples** | Produto padrão autônomo | ✅ Sim | ❌ Não |
| **Com Variação (Parent)** | Produto-template que atua como container para variações | ❌ **Não** | ❌ Não |
| **Variação** | Variação específica (ex: Cor/Tamanho) de um produto pai. Herda dados do pai se `herdar_dados_pai = true` | ✅ Sim | ❌ Não (pode herdar via `herdar_bom_pai`) |
| **Composição** | Produto fabricado a partir de componentes. Gerencia estoque de componentes via BOM | ✅ Sim (produto acabado) | ✅ **Obrigatório** |
| **Kit** | Produto virtual representando um bundle de produtos acabados existentes | ⚠️ Virtual (calculado) | ✅ **Obrigatório** |

**Implementação:**
- **Arquivo:** `nistiprint-shared/nistiprint_shared/models/product.py`
- **Campos:** `formato`, `herdar_dados_pai`, `herdar_bom_pai`, `parent_id`

```python
# Regra de elegibilidade para estoque
allow_stock_movement = (parent_id is not None) or (not (len(variants) > 0 if variants else False))
```

#### Regras de Herança
- **Herança de Dados:** Variações podem herdar dados do produto pai se `herdar_dados_pai = true`
- **Herança de BOM:** Variações podem herdar a Ficha Técnica do produto pai se `herdar_bom_pai = true`

**Implementação:** `nistiprint-shared/nistiprint_shared/services/bom_service.py`

```python
# Se produto é variação com herdar_bom_pai habilitado, busca BOM do pai
if product and product.get('parent_id') and product.get('herdar_bom_pai', False):
    parent_id = product.get('parent_id')
    response = self.bom_table.select("*").eq('produto_pai_id', parent_id).execute()
```

---

### 1.2 Gestão de Estoque

#### Estrutura de Armazenagem
- **Múltiplos Depósitos:** O sistema suporta múltiplos depósitos (`depositos`)
- **Depósito Padrão:** Operações usam o "Default Production Deposit" configurado em `app_config_service`

#### Disponibilidade de Estoque
```
Quantidade Disponível = Saldo Atual - Quantidade Reservada
disponivel = saldo_atual - reservado
```

**Implementação:** `nistiprint-shared/nistiprint_shared/models/estoque_atual.py`

#### Tipos de Movimentação (`tipo_movimentacao`)

| Tipo | Efeito no Saldo | Descrição |
|------|----------------|-----------|
| `ENTRADA` | ➕ Aumenta | Entrada de mercadoria (compra, produção, devolução) |
| `SAIDA` | ➖ Diminui | Saída de mercadoria (venda, consumo, perda) |
| `BALANCO` | ⚖️ Ajuste absoluto | Ajuste de inventário (pode resultar em saldo negativo) |
| `TRANSFERENCIA_SAIDA` | ➖ Diminui (origem) | Transferência entre depósitos |
| `TRANSFERENCIA_ENTRADA` | ➕ Aumenta (destino) | Transferência entre depósitos |
| `SAIDA_INSUMO_PRODUCAO` | ➖ Diminui | Consumo automático de insumos na produção |

**Implementação:** `nistiprint-shared/nistiprint_shared/services/estoque_service.py`

#### Reservas de Estoque
- **Finalidade:** Reservar componentes para Ordens de Produção
- **Efeito:** Deduz de `disponivel`, mas mantém `saldo_atual`
- **Liberação:** Reservas são liberadas quando OP é cancelada ou consumidas na entrega

---

### 1.3 Unicidade de Pedidos

#### Estratégia de Identificação
- **Chave Externa:** Pedidos são identificados unicamente por `codigo_pedido_externo` (order_sn, order_id, numeroLoja)
- **Upsert:** Pedidos recebidos são confrontados pelo ID externo. Se existir, atualiza; se não, cria novo

**Implementação:** `nistiprint-shared/nistiprint_shared/services/order_sync_service.py`

```python
# Prioridade de identificação
external_id = order_sn (Shopee) 
           or order_id (Mercado Livre) 
           or numeroLoja (Bling)
```

---

## 2. Lógica de Validação

### 2.1 Validações de Estoque e Produção

#### Estoque Negativo
| Tipo de Movimentação | Permite Negativo? |
|---------------------|-------------------|
| `ENTRADA` | ❌ Não |
| `SAIDA` | ⚠️ Sim (com alerta) |
| `BALANCO` | ✅ Sim (ajuste) |
| `TRANSFERENCIA` | ❌ Não (valida origem) |

**Implementação:** `nistiprint-shared/nistiprint_shared/services/estoque_service.py`

```python
# Log de alerta para saldo negativo (Resiliência: Não trava, apenas permite e segue)
if saldo_posterior < 0:
    print(f"AVISO: Saldo negativo gerado para o produto {produto_id}. Saldo atual: {saldo_posterior}")
```

#### Validação de Suficiência para Reservas
```
Reserva falha se: Quantidade Requerida > Quantidade Disponível
```

**Implementação:** `nistiprint-shared/nistiprint_shared/services/ordem_producao_service.py`

```python
if required > available:
    insufficient.append(f"{comp['name']}: necessita {required}, disponível {available}")
    raise ValueError(f"Estoque insuficiente para: {', '.join(insufficient)}")
```

#### Consistência de Produtos

| Regra | Validação |
|-------|-----------|
| Produto Pai (Com Variação) | ❌ Não pode ter movimentação direta de estoque |
| Composição/Kit | ✅ **Obrigatório** ter BOM definida |
| Variação | ✅ **Obrigatório** ter `parent_id` |
| BOM de Produto Pai | Valida regras de categoria via `category_bom_rule_service` |

**Implementação:** `nistiprint-shared/nistiprint_shared/services/product_service.py`

```python
def validate_product_consistency(self, product_data):
    errors = []
    formato = product_data.get('formato')
    
    # Produto Pai não pode ter BOM direta
    if formato == 'com_variacao' and has_bom:
        errors.append("Produto Pai (Template) não pode ter Ficha Técnica direta. Use as Variações.")
    
    # Composição/Kit requer BOM
    if formato in ['composicao', 'kit'] and not has_bom:
        errors.append(f"Produto {formato} deve ter Ficha Técnica (BOM) definida.")
    
    return errors
```

### 2.2 Validações de Status de Produção

#### Ciclo de Vida da Ordem de Produção (OP)

```
DRAFT → PENDING → IN_PROGRESS → COMPLETED
              ↓         ↓
           PAUSED  CANCELED
```

| Status | Ações Permitidas |
|--------|-----------------|
| `DRAFT` | Editar, Iniciar, Cancelar |
| `PENDING` | Entregar, Pausar, Cancelar |
| `IN_PROGRESS` | Entregar, Pausar, Cancelar |
| `PARTIALLY_DELIVERED` | Entregar, Pausar, Cancelar |
| `PAUSED` | Retomar, Cancelar |
| `COMPLETED` | ❌ Imutável |
| `CANCELED` | ❌ Imutável |

**Implementação:** `nistiprint-shared/nistiprint_shared/services/ordem_producao_service.py`

```python
# Validações por status
if op_data['status'] != 'DRAFT':
    raise ValueError("Apenas OPs em DRAFT podem ser editadas.")

if op_data['status'] not in ['PENDING', 'IN_PROGRESS', 'PARTIALLY_DELIVERED']:
    raise ValueError("Apenas OPs ativas podem receber entregas.")
```

#### Validação de Entrega
```python
# Tolerância para float (0.001)
if total_produced > total_to_produce + 0.001:
    raise ValueError(f"Quantidade total produzida ultrapassaria o planejado: {total_produced} > {total_to_produce}")
```

### 2.3 Validações de Integridade de Dados

#### Permissões por Setor
- **Admin:** Acesso total a todas as operações
- **Usuário Comum:** Apenas movimenta produtos do seu `setor_responsavel_id`
- **Produtos sem Setor:** Liberados para todos (estratégia de migração)

**Implementação:** `nistiprint-shared/nistiprint_shared/services/estoque_service.py`

```python
def _validate_sector_permission(self, produto_id, user_context):
    if user_context.get('is_admin'):
        return
    
    product = product_service.get_by_id(str(produto_id))
    setor_produto = product.get('setor_responsavel_id')
    
    if setor_produto is None:
        return  # Produtos sem setor são liberados
    
    if str(setor_produto) != str(user_context.get('setor_id')):
        raise PermissionError(
            f"Acesso Negado: Este produto pertence ao setor '{product.get('setor_responsavel_nome')}'"
        )
```

#### Campos Únicos
- `sku` - Código de identificação do produto (único)
- `numero_pedido` - Número do pedido (único)
- `demanda_id` - ID da demanda de produção (único)

---

## 3. Lógica de Fluxo de Trabalho (Workflow)

### 3.1 Fluxo de Ordem de Produção (Make-to-Stock)

```
┌─────────┐     ┌─────────┐     ┌─────────────┐     ┌───────────────────┐     ┌───────────┐
│  DRAFT  │────▶│ PENDING │────▶│ IN_PROGRESS │────▶│ PARTIALLY_DELIVERED│────▶│ COMPLETED │
└─────────┘     └────┬────┘     └──────┬──────┘     └─────────┬─────────┘     └───────────┘
     │               │                 │                       │
     │               │                 ▼                       │
     │               │              PAUSED ◀───────────────────┘
     │               │                 │
     │               ▼                 │
     │          CANCELED ◀─────────────┘
     ▼
 CANCELED
```

#### Etapas Detalhadas

| Etapa | Ação | Validações | Efeitos no Estoque |
|-------|------|------------|-------------------|
| **1. Draft** | `create_draft()` | Produto existe, quantidade > 0 | Nenhum |
| **2. Start** | `start_production()` | Estoque de componentes suficiente | 🔒 **Reserva** componentes |
| **3. Deliver** | `deliver_production(qty)` | qty ≤ total_to_produce | 🔓 **Consome** reserva componentes<br>➕ **Entrada** produto acabado |
| **4. Complete** | Auto quando `qty_produced >= total` | — | — |
| **5. Cancel** | `cancel_production()` | — | 🔓 **Libera** reservas pendentes |

**Implementação:** `nistiprint-shared/nistiprint_shared/services/ordem_producao_service.py`

#### Snapshot de Estoque na Entrega
Cada entrega gera um snapshot do estoque dos componentes para auditoria:

```python
snapshot_item = {
    "component_id": comp_data['componente_id'],
    "component_name": comp_data.get('descricao', ''),
    "quantity_used": qty_to_consume,
    "stock_before_production": stock_before,
    "stock_after_production": stock_after
}
```

---

### 3.2 Fluxo de Demanda de Produção (Make-to-Order)

#### Origens de Demanda
| Tipo | Descrição | Gatilho |
|------|-----------|---------|
| `PLATAFORMA` | Pedidos de marketplaces (Shopee, ML, Amazon) | Webhook/Poling |
| `B2B` | Vendas corporativas | Manual/API |
| `FULFILLMENT` | Reposição de fulfillment externo | Manual/API |
| `ESTOQUE_INTERNO` | Reposição de estoque interno | Manual |

**Implementação:** `nistiprint-shared/nistiprint_shared/models/demanda_producao.py`

#### Deduplicação de Pedidos
```python
# order_tracker_service.filter_processed_items()
# Verifica se items já foram processados via tabela demandas_item_origem
processed_map = {(order_id, sku, item_id): total_processed_qty}

if qty_already_processed < qty_requested:
    remaining_qty = qty_requested - qty_already_processed
    # Processa apenas o remanescente
```

**Implementação:** `nistiprint-shared/nistiprint_shared/services/order_tracker_service.py`

#### Estágios de Produção por Item

| Estágio | Campo | Descrição |
|---------|-------|-----------|
| **Capas Impressas** | `capas_impressas_qtd` | Primeira etapa de produção de capas |
| **Capas Produzidas** | `capas_produzidas_qtd` | Capas finalizadas |
| **Capas Prontas Retirada** | `capas_prontas_retirada_qtd` | Capas disponíveis para montagem |
| **Miolos Prontos Retirada** | `miolos_prontos_retirada_qtd` | Miolos disponíveis para montagem |
| **Expedição Capas Retiradas** | `expedicao_capas_retiradas_qtd` | Capas retiradas para expedição |
| **Expedição Miolos Retirados** | `expedicao_miolos_retirados_qtd` | Miolos retirados para expedição |
| **Status do Item** | `status_item` | `Pendente` → `Em Produção` → `Concluído` |

**Implementação:** `nistiprint-shared/nistiprint_shared/models/demanda_producao.py`

#### Finalização Automática
```python
# Quando todos os itens estão Concluído
if itens_totalmente_concluidos == total_itens:
    status = 'CONCLUIDO'
```

#### Detecção de Demandas "Travadas"
```python
# Heurística: está em produção, mas há gap entre etapas
if status == 'EM_PRODUCAO' and total_itens > 0:
    gap_capas = capas_impressas_qtd - capas_produzidas_qtd
    if gap_capas > (total_itens * 0.5) and itens_concluidos < (total_itens * 0.2):
        is_stuck = True
```

**Implementação:** `nistiprint-shared/nistiprint_shared/services/demanda_producao_service.py`

---

### 3.3 Sincronização de Pedidos

#### Fluxo de Recepção
```
1. Recepção do payload (Webhook/API)
   ↓
2. Normalização do status (platform-specific → unificado)
   ↓
3. Upsert na tabela `pedidos` (via order_service.upsert_order)
   ↓
4. Insert/Update itens do pedido
   ↓
5. Registro em demandas_item_origem (deduplicação)
   ↓
6. Criação de Demanda de Produção (se elegível)
```

**Implementação:** `nistiprint-shared/nistiprint_shared/services/order_sync_service.py`

#### Mapeamento de Status

**Shopee:**
| Status Original | Status Unificado |
|----------------|------------------|
| `UNPAID` | `AGUARDANDO_PAGAMENTO` |
| `READY_TO_SHIP` | `PAGO` |
| `PROCESSED` | `EM_SEPARACAO` |
| `SHIPPED` | `ENVIADO` |
| `COMPLETED` | `ENTREGUE` |
| `CANCELLED` | `CANCELADO` |

**Bling:**
| ID Situação | Status Unificado |
|-------------|------------------|
| `6` | `AGUARDANDO_PAGAMENTO` |
| `15` | `PAGO` (gatilho de produção) |
| `9` | `ENVIADO` |
| `12` | `CANCELADO` |

---

## 4. Lógica de Cálculo

### 4.1 Custos e Precificação

#### Custo de BOM (Ficha Técnica)
```
Custo do Produto = Σ(Quantidade do Componente × Custo Unitário do Componente)
```

**Implementação:** `nistiprint-shared/nistiprint_shared/services/product_service.py`

```python
def update_composite_product_cost(self, product_id):
    """Atualiza o custo de produtos Composição/Kit quando BOM muda."""
    bom_components = bom_service.get_bom_for_produto(int(product_id))
    total_cost = sum(comp.quantity * comp.component.cost_price for comp in bom_components)
    # Atualiza produto
```

#### Atualização Automática de Custo
- Quando um componente da BOM é alterado, o `preco_custo` do produto pai é recalculado automaticamente
- **Gatilho:** `bom_service.sync_bom_for_product()` → `product_service.update_composite_product_cost()`

### 4.2 Avaliação de Estoque
```
Valor Total do Estoque = Σ(Quantidade em Estoque × Preço de Custo)
```

### 4.3 Análise ABC
- **Critério:** Classifica produtos A/B/C baseado no valor de consumo (Quantidade Saída × Custo) nos últimos 30 dias
- **Campo:** `curva_abc` no modelo `Product`

**Implementação:** `nistiprint-shared/nistiprint_shared/services/consumption_service.py`

```python
def get_daily_consumption(self, days=30):
    # Calcula consumo médio diário de cada insumo
    # Retorna: {component_id: {media_diaria, total_periodo}}
```

### 4.4 Estoque Virtual de Kits
```
Estoque do Kit = MIN(Disponível do Componente / Quantidade na BOM) para todos os componentes
```

### 4.5 Progresso e Prontidão de Demanda

#### Progresso Percentual
```
Progresso % = (Itens Concluídos / Total Itens) × 100
```

#### Readiness Score (Prontidão)
```
Readiness Score = ((Capas Impressas + Miolos Prontos) / (2 × Total Itens)) × 100
```
- **Propósito:** Medir o quão próxima a demanda está de estar pronta para montagem final
- **Peso:** Média ponderada das duas etapas iniciais

**Implementação:** `nistiprint-shared/nistiprint_shared/services/demanda_producao_service.py`

```python
if total_itens > 0:
    readiness_score = round(((capas_impressas_qtd + miolos_produzidos_qtd) / (2 * total_itens)) * 100)
```

### 4.6 Cálculo de Prioridade de Demandas

#### Fatores de Prioridade
| Fator | Peso | Descrição |
|-------|------|-----------|
| **Categoria Temporal** | 100-1000 | `flex` (1000), `urgente` (800), `curto_prazo` (600), `medio_prazo` (400), `longo_prazo` (200), `normal` (100) |
| **Modalidade Logística** | 50-1000 | `EXPRESS` (1000), `STANDARD` (100), `FULFILLMENT` (50), `RETIRADA` (75) |
| **Deadline Crítico** | Variável | Baseado no maior horário limite do canal: `(24 - hora_deadline) × 100` |
| **Urgência de Entrega** | 0-1000 | Atrasado (1000), Amanhã (800), ≤3 dias (600), ≤7 dias (400), ≤14 dias (200) |
| **Prioridade Manual** | 0+ | Boost manual configurado |
| **Classificação do Cliente** | 0-50 | `B2B` (50), `INTERNO` (25), `B2C` (0) |

**Implementação:** `nistiprint-shared/nistiprint_shared/services/priority_calculation_service.py`

```python
def calculate_priority_score(self, demanda_data, item_data=None, canal_info=None):
    score = tipo_prioridade.get(categoria_temporal, 100)
    
    # Deadline crítico baseado nas regras logísticas do canal
    if canal_info and regras_logisticas:
        deadline_final = max(horarios_limite)
        deadline_score = int((24 - hora_ref) * 100)
        score += deadline_score
    
    # Urgência de entrega
    dias_para_entrega = (data_entrega - hoje).days
    if dias_para_entrega <= 0: score += 1000  # Atrasado
    elif dias_para_entrega <= 1: score += 800  # Amanhã
    # ...
    
    return score
```

---

## 5. Regras de Autorização

### 5.1 Controle de Acesso Baseado em Papel (RBAC)

| Papel | Permissões |
|-------|------------|
| **Admin** | Acesso total a todas as operações |
| **Usuário** | Restrito ao seu `setor_id` |

### 5.2 Acesso a Movimentações de Estoque

```python
# Regra de validação
if not user_context.get('is_admin'):
    setor_produto = product.get('setor_responsavel_id')
    
    if setor_produto is not None and str(setor_produto) != str(user_setor_id):
        raise PermissionError("Acesso Negado: Produto pertence a outro setor")
```

**Tabela de Permissões:**

| Operação | Admin | Usuário (mesmo setor) | Usuário (setor diferente) |
|----------|-------|----------------------|--------------------------|
| `registrar_entrada` | ✅ | ✅ | ❌ |
| `registrar_saida` | ✅ | ✅ | ❌ |
| `registrar_balanco` | ✅ | ✅ | ❌ |
| `registrar_transferencia` | ✅ | ✅ | ❌ |
| `reservar_estoque` | ✅ | ✅ | ❌ |

**Implementação:** `nistiprint-shared/nistiprint_shared/services/estoque_service.py`

---

## 6. Lógica de Integração

### 6.1 Produtos Externos

#### Mapeamento
Tabela `produtos_externos` linka:
- `produto_id` (interno)
- `codigo_externo` (SKU externo)
- `plataforma` (Bling, Shopee, ML, Amazon)

#### Estratégias de Resolução
1. **Match Exato por SKU:** `get_by_sku(external_sku)`
2. **Match Exato por Nome:** `select().eq('nome', external_name)`
3. **Fuzzy Search (Fallback):** `fuzz.partial_ratio()` com limite de similaridade

**Implementação:** `nistiprint-shared/nistiprint_shared/services/product_service.py`

```python
def find_internal_product(self, platform, external_sku, external_name):
    # 1. Exact SKU Match
    product = self.get_by_sku(external_sku)
    if product:
        return [product]
    
    # 2. Exact Name Match
    response = self.table.select("*").eq('nome', external_name).execute()
    if response.data:
        return [dict(row) for row in response.data]
    
    # 3. Fuzzy Search
    return self.search_produtos(query, limit=5)
```

### 6.2 Regras Logísticas por Canal

#### Estrutura
Tabela `regras_logisticas_canal`:
- `canal_venda_id`: Canal de venda
- `modalidade`: `STANDARD`, `EXPRESS`, `FULFILLMENT`, `RETIRADA`
- `tipo_envio`: Tipo de envio
- `horario_limite`: Horário limite para coleta/entrega
- `ponto_coleta_id`: Ponto de coleta associado
- `prioridade_uso`: Prioridade de aplicação

#### Critérios de Roteamento
```python
# Busca regras por canal e modalidade
regras = [r for r in regras_log if r.modalidade == modalidade_logistica]
deadline_final = max([r.horario_limite for r in regras])
```

**Implementação:** `nistiprint-shared/nistiprint_shared/services/regra_logistica_service.py`

### 6.3 Especificidades por Plataforma

#### Bling
| Tipo Bling | Formato Interno |
|------------|-----------------|
| `P` | Simples |
| `V` | Variação |
| `K` | Kit |

#### Shopee
- **Chave Externa:** `order_sn`
- **Itens:** `item_list` com `item_sku`, `model_quantity_purchased`

#### Mercado Livre
- **Chave Externa:** `order_id`

#### Amazon
- **Chave Externa:** `AmazonOrderId`

---

## 7. Validações do Frontend

### 7.1 Schema de Produto (Zod)

**Arquivo:** `nistiprint-frontend/src/schemas/productSchema.js`

```javascript
export const productSchema = z.object({
  sku: z.string().min(1, { message: "SKU é obrigatório." }),
  name: z.string().min(1, { message: "Nome do produto é obrigatório." }),
  category_id: z.string().min(1, { message: "Categoria é obrigatória." }),
  unit_of_measure_id: z.string().min(1, { message: "Unidade de medida é obrigatória." }),
  setor_responsavel_id: z.string().optional(),
  
  cost_price: z.preprocess(
    (a) => parseFloat(a),
    z.number().min(0, { message: "Preço de custo não pode ser negativo." })
  ),
  
  stock_min: z.preprocess(
    (a) => parseInt(a, 10),
    z.number().int().min(0, { message: "Estoque mínimo não pode ser negativo." }).optional()
  ),
  
  material_type: z.enum(["materia_prima", "intermediario", "produto_acabado", "servico"]),
  status: z.enum(["ativo", "rascunho", "inativo"]),
  formato: z.enum(["simples", "com_variacao", "variacao", "composicao", "kit"]),
  herdar_dados_pai: z.boolean().default(true),
  herdar_bom_pai: z.boolean().default(true),
});
```

---

## 8. Referências de Implementação

### Módulos Principais

| Módulo | Arquivos Chave | Responsabilidade |
|--------|---------------|------------------|
| **Modelos** | `nistiprint-shared/models/*.py` | Definições de entidades e relacionamentos |
| **Serviços** | `nistiprint-shared/services/*.py` | Regras de negócio e operações CRUD |
| **API** | `nistiprint-api/routes/*.py` | Endpoints HTTP e controllers |
| **Worker** | `nistiprint-worker/tasks/*.py` | Tarefas assíncronas (Celery) |
| **Frontend** | `nistiprint-frontend/src/**` | Validações, schemas e UI |

### Serviços Especializados

| Serviço | Arquivo | Função |
|---------|---------|--------|
| `ProductService` | `product_service.py` | Gestão de produtos, variações, BOM |
| `BomService` | `bom_service.py` | Ficha técnica e cálculo de custos |
| `EstoqueService` | `estoque_service.py` | Movimentações, reservas, saldos |
| `DemandaProducaoService` | `demanda_producao_service.py` | Demandas de produção e acompanhamento |
| `OrdemProducaoService` | `ordem_producao_service.py` | Ordens de produção (OP) |
| `OrderTrackerService` | `order_tracker_service.py` | Deduplicação de pedidos externos |
| `PriorityCalculationService` | `priority_calculation_service.py` | Cálculo de prioridade de demandas |
| `RegraLogisticaService` | `regra_logistica_service.py` | Regras de logística por canal |
| `CategoryBOMRuleService` | `category_bom_rule_service.py` | Regras de BOM por categoria |

---

*Documento gerado em: 2026-02-27*  
*Última atualização: Análise do código V3*
