# Regras de Negócio e Dependências - Nistiprint

**Última atualização:** 2026-04-02  
**Status:** Consolidado

Este documento consolida as regras de negócio, dependências entre entidades e fluxos operacionais do sistema Nistiprint.

---

## 1. Visão Geral do Negócio

### 1.1 Princípios Centrais

| Princípio | Descrição |
|-----------|-----------|
| **Demanda é o centro** | A fábrica trabalha com demandas, não com pedidos individuais |
| **Consolidação inteligente** | Múltiplos pedidos → Uma demanda (quando possível) |
| **Ordenação por coleta** | O que sai primeiro, produz primeiro |
| **Plataforma + Modalidade** | Regra de coleta define prioridade |
| **Snapshot no tempo** | Características do canal são capturadas na criação |

### 1.2 Fluxo Operacional da Fábrica

```
┌──────────────┐     ┌─────────────────┐     ┌────────────────────────────┐
│   PEDIDOS    │     │  CONSOLIDAÇÃO   │     │    DEMANDA DE PRODUÇÃO     │
│   (entrada)  │ ──▶ │  (agrupamento)  │ ──▶ │    (o que a fábrica vê)    │
│              │     │                 │     │                            │
│ • Shopee     │     │ Critérios:      │     │ • Ordenada por coleta     │
│ • ML         │     │ • Produto       │     │ • Plataforma + Modalidade │
│ • Amazon     │     │ • Miolo         │     │ • Quantidade total        │
│ • Shein      │     │ • Data entrega  │     │ • Status de produção      │
│ • Bling      │     │ • Canal         │     │ • Coletas parciais        │
│              │     │ • Modalidade    │     │                            │
└──────────────┘     └─────────────────┘     └────────────────────────────┘
```

---

## 2. Regras de Consolidação de Demandas

### 2.1 Derivação de Modalidade Logística

**Problema:** Quando o Bling envia `servico_logistico: "Entrega Rápida Shopee"`, o sistema precisa mapear para `modalidade: EXPRESS`.

**Solução:** Tabela `canal_modalidade_mapeamento` com padrões ILIKE configuráveis por canal.

**Regra:**
```
Para cada pedido recebido:
  1. Buscar mapeamentos do canal_venda_id
  2. Ordenar por prioridade (maior = mais específico)
  3. Verificar matching com ILIKE
  4. Retornar primeira modalidade que casar
  5. Se nenhum casar → pedidos_nao_classificados
```

**Exemplo de Mapeamento:**
```sql
INSERT INTO canal_modalidade_mapeamento (canal_venda_id, padrao_servico, modalidade, prioridade) VALUES
  (1, '%flex%', 'EXPRESS', 10),
  (1, '%rápida%', 'EXPRESS', 10),
  (1, '%normal%', 'STANDARD', 5),
  (1, '%padrão%', 'STANDARD', 5);
```

**Modalidades Válidas:**
| Modalidade | Descrição | Exemplos de Padrões |
|------------|-----------|---------------------|
| `STANDARD` | Envio padrão | '%normal%', '%padrão%', '%standard%' |
| `EXPRESS` | Entrega expressa | '%flex%', '%rápida%', '%express%' |
| `FULFILLMENT` | Armazém externo | '%full%', '%fulfillment%' |
| `RETIRADA` | Retirada no local | '%retirada%', '%pickup%' |

### 2.2 Resolução de Horário de Coleta

**Problema:** `canais_venda.horario_coleta` e `regras_logisticas_canal.horario_limite` conflitam sem precedência.

**Solução:** Regra de precedência declarada:

```
1. regras_logisticas_canal (canal, modalidade) — FONTE CANÔNICA
2. canais_venda.horario_coleta — FALLBACK LEGADO
3. NULL — Default
```

**Implementação:**
```python
def resolver_horario(canal_venda_id: int, modalidade: str) -> Optional[str]:
    # 1. Buscar em regras_logisticas_canal
    regra = get_regra_logistica(canal_venda_id, modalidade)
    if regra and regra.horario_limite:
        return regra.horario_limite
    
    # 2. Fallback: canais_venda.horario_coleta
    canal = get_canal(canal_venda_id)
    if canal and canal.horario_coleta:
        log_warning("Usando horario_coleta legado")
        return canal.horario_coleta
    
    # 3. Default
    return None
```

### 2.3 Critérios de Agrupamento

**Problema:** Critérios de agrupamento (janela de 4h, agrupar por produto/miolo) estavam hardcoded.

**Solução:** Tabela `regras_consolidacao_canal` configurável por canal/modalidade.

**Critérios para AGRUPAR:**
```
✅ AGRUPAR quando:
  • Mesmo produto (se agrupar_por_produto = true)
  • Mesmo miolo (se agrupar_por_miolo = true)
  • Mesma data de entrega (se agrupar_por_data_entrega = true)
  • Dentro da janela de tempo (janela_agrupamento_horas)
  • Mesmo canal e modalidade
```

**Critérios para NÃO AGRUPAR:**
```
❌ NÃO AGRUPAR quando:
  • Modalidades diferentes (Flex ≠ Normal)
  • Janelas de coleta muito distantes (>janela_agrupamento_horas)
  • Produtos incompatíveis (linhas de produção diferentes)
  • Configuração específica do canal proíbe agrupamento
```

**Exemplo de Configuração:**
```sql
-- Regra global (fallback)
INSERT INTO regras_consolidacao_canal (canal_venda_id, modalidade, janela_agrupamento_horas)
VALUES (NULL, NULL, 4);

-- Shopee Flex (janela menor por urgência)
INSERT INTO regras_consolidacao_canal (canal_venda_id, modalidade, janela_agrupamento_horas)
VALUES (1, 'EXPRESS', 2);

-- Shopee Fulfillment (demanda direta, sem rascunho)
INSERT INTO regras_consolidacao_canal (canal_venda_id, modalidade, janela_agrupamento_horas)
VALUES (1, 'FULFILLMENT', 0);
```

### 2.4 Ciclo de Vida da Consolidação

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    CICLO DE VIDA DA DEMANDA                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  RASCUNHO (automático)                                                  │
│    │  ← novos pedidos entram enquanto janela aberta                    │
│    │  ← usuário pode editar                                            │
│    │  ← janela deslizante: rascunho_expira_em                          │
│    │                                                                    │
│    │ [usuário publica]                                                  │
│    ▼                                                                    │
│  AGUARDANDO (publicado, fechado para novos pedidos)                     │
│    │                                                                    │
│    ▼                                                                    │
│  EM_PRODUCAO                                                            │
│    │                                                                    │
│    ▼                                                                    │
│  COLETA_PARCIAL                                                         │
│    │                                                                    │
│    ▼                                                                    │
│  CONCLUIDO                                                              │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.5 Estados do Rascunho

| Estado | Descrição | Indicador UI | Ações |
|--------|-----------|--------------|-------|
| **Limpo** | Sem edição humana | — | [Editar] [Publicar] |
| **Editado** | `editado_pelo_usuario = true` | ✏️ | [Editar] [Publicar] |
| **Modificado** | Pedidos chegaram após edição | ⚠️ +N | [Ver novos] [Publicar] |

**Regra de Sinalização:**
```python
# Trigger SQL
CREATE FUNCTION fn_atualizar_requer_revisao() RETURNS TRIGGER AS $$
BEGIN
    NEW.requer_revisao = (NEW.pedidos_apos_edicao_qtd > 0);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_atualizar_requer_revisao
BEFORE INSERT OR UPDATE OF pedidos_apos_edicao_qtd
ON demandas_producao
FOR EACH ROW EXECUTE FUNCTION fn_atualizar_requer_revisao();
```

---

## 3. Regras de Priorização de Produção

### 3.1 Cálculo de Score de Prioridade

**Fatores de Prioridade:**

| Fator | Peso | Descrição |
|-------|------|-----------|
| **Categoria Temporal** | 100-1000 | `flex` (1000), `urgente` (800), `curto_prazo` (600), `medio_prazo` (400), `longo_prazo` (200), `normal` (100) |
| **Modalidade Logística** | 50-1000 | `EXPRESS` (1000), `STANDARD` (100), `FULFILLMENT` (50), `RETIRADA` (75) |
| **Deadline Crítico** | Variável | `(24 - hora_deadline) × 100` |
| **Urgência de Entrega** | 0-1000 | Atrasado (1000), Amanhã (800), ≤3 dias (600), ≤7 dias (400), ≤14 dias (200) |
| **Prioridade Manual** | 0+ | Boost manual configurado |
| **Classificação do Cliente** | 0-50 | `B2B` (50), `INTERNO` (25), `B2C` (0) |

**Fórmula:**
```
priority_score = categoria_temporal + modalidade_logistica + deadline_critico + urgencia_entrega + prioridade_manual + classificacao_cliente
```

### 3.2 Ordenação no Dashboard

**Critérios de ordenação (em ordem de prioridade):**
```
1. is_flex = TRUE (entrega no mesmo dia)
2. modalidade_logistica = EXPRESS
3. horario_coleta (mais próximo primeiro)
4. prioridade_calculada (score)
5. data_entrega (mais próxima primeiro)
6. modalidade_logistica = STANDARD
7. modalidade_logistica = RETIRADA
```

### 3.3 Matriz de Agrupamento por Plataforma + Modalidade

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    MATRIZ DE AGRUPAMENTO                                │
├──────────────────┬───────────────┬────────────┬────────────┬───────────┤
│  PLATAFORMA      │ MODALIDADE    │ HORÁRIO    │ PRIORIDADE │ AGRUPA    │
├──────────────────┼───────────────┼────────────┼────────────┼───────────┤
│  Shopee          │ Flex          │ 14:00      │ MÁXIMA     │ Urgentes  │
│                  │ (EXPRESS)     │            │            │           │
├──────────────────┼───────────────┼────────────┼────────────┼───────────┤
│  Shopee          │ Normal        │ 18:00      │ ALTA       │ Demais    │
│                  │ (STANDARD)    │            │            │           │
├──────────────────┼───────────────┼────────────┼────────────┼───────────┤
│  Mercado Livre   │ Flex          │ 15:00      │ MÁXIMA     │ Urgentes  │
│                  │ (EXPRESS)     │            │            │           │
├──────────────────┼───────────────┼────────────┼────────────┼───────────┤
│  Mercado Livre   │ Normal        │ 19:00      │ ALTA       │ Demais    │
│                  │ (STANDARD)    │            │            │           │
├──────────────────┼───────────────┼────────────┼────────────┼───────────┤
│  Amazon          │ Prime         │ 16:00      │ MÁXIMA     │ Prime     │
│                  │ (EXPRESS)     │            │            │           │
├──────────────────┼───────────────┼────────────┼────────────┼───────────┤
│  Amazon          │ Standard      │ 20:00      │ NORMAL     │ Demais    │
│                  │ (STANDARD)    │            │            │           │
├──────────────────┼───────────────┼────────────┼────────────┼───────────┤
│  Qualquer        │ Fulfillment   │ Agendado   │ VARIÁVEL   │ Reposição │
│                  │ (FULFILLMENT) │            │            │           │
├──────────────────┼───────────────┼────────────┼────────────┼───────────┤
│  Qualquer        │ Retirada      │ Balcão     │ BAIXA      │ Retirada  │
│                  │ (RETIRADA)    │            │            │           │
└──────────────────┴───────────────┴────────────┴────────────┴───────────┘
```

---

## 4. Regras de Produtos e Estoque

### 4.1 Formatos de Produto

| Formato | Descrição | Pode ter Estoque? | Requer BOM? |
|---------|-----------|-------------------|-------------|
| **Simples** | Produto padrão autônomo | ✅ Sim | ❌ Não |
| **Com Variação (Parent)** | Template para variações | ❌ **Não** | ❌ Não |
| **Variação** | Variação específica (ex: Cor/Tamanho) | ✅ Sim | ❌ Não (pode herdar) |
| **Composição** | Produto fabricado a partir de componentes | ✅ Sim | ✅ **Obrigatório** |
| **Kit** | Bundle de produtos acabados | ⚠️ Virtual (calculado) | ✅ **Obrigatório** |

### 4.2 Regras de Herança

**Herança de Dados:**
```
Variação pode herdar do produto pai se herdar_dados_pai = true
```

**Herança de BOM:**
```
Variação pode herdar Ficha Técnica do pai se herdar_bom_pai = true
```

### 4.3 Validações de Estoque

**Tipos de Movimentação:**

| Tipo | Efeito no Saldo | Permite Negativo? |
|------|----------------|-------------------|
| `ENTRADA` | ➕ Aumenta | ❌ Não |
| `SAIDA` | ➖ Diminui | ⚠️ Sim (com alerta) |
| `BALANCO` | ⚖️ Ajuste absoluto | ✅ Sim (ajuste) |
| `TRANSFERENCIA_SAIDA` | ➖ Diminui (origem) | ❌ Não |
| `TRANSFERENCIA_ENTRADA` | ➕ Aumenta (destino) | ❌ Não |

**Fórmula de Disponibilidade:**
```
Quantidade Disponível = Saldo Atual - Quantidade Reservada
disponivel = saldo_atual - reservado
```

### 4.4 Reservas de Estoque

**Finalidade:** Reservar componentes para Ordens de Produção

**Efeito:**
- Deduz de `disponivel`, mas mantém `saldo_atual`
- Liberação: Reservas são liberadas quando OP é cancelada ou consumidas na entrega

**Validação de Suficiência:**
```
Reserva falha se: Quantidade Requerida > Quantidade Disponível
```

---

## 5. Regras de Ordens de Produção

### 5.1 Ciclo de Vida da OP

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

### 5.2 Ações Permitidas por Status

| Status | Ações Permitidas |
|--------|-----------------|
| `DRAFT` | Editar, Iniciar, Cancelar |
| `PENDING` | Entregar, Pausar, Cancelar |
| `IN_PROGRESS` | Entregar, Pausar, Cancelar |
| `PARTIALLY_DELIVERED` | Entregar, Pausar, Cancelar |
| `PAUSED` | Retomar, Cancelar |
| `COMPLETED` | ❌ Imutável |
| `CANCELED` | ❌ Imutável |

### 5.3 Validações de Entrega

**Tolerância para float:**
```python
if total_produced > total_to_produce + 0.001:
    raise ValueError(f"Quantidade ultrapassou o planejado: {total_produced} > {total_to_produce}")
```

**Snapshot de Estoque:**
Cada entrega gera snapshot do estoque dos componentes para auditoria:
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

## 6. Regras de Integração com Plataformas

### 6.1 Unicidade de Pedidos

**Estratégia de Identificação:**
```
Chave Externa = order_sn (Shopee)
             or order_id (Mercado Livre)
             or numeroLoja (Bling)
```

**Upsert:**
```
Pedidos recebidos são confrontados pelo ID externo:
  • Se existir → atualiza
  • Se não existir → cria novo
```

### 6.2 Mapeamento de Status

#### Shopee
| Status Original | Status Unificado |
|----------------|------------------|
| `UNPAID` | `AGUARDANDO_PAGAMENTO` |
| `READY_TO_SHIP` | `PAGO` |
| `PROCESSED` | `EM_SEPARACAO` |
| `SHIPPED` | `ENVIADO` |
| `COMPLETED` | `ENTREGUE` |
| `CANCELLED` | `CANCELADO` |

#### Bling
| ID Situação | Status Unificado |
|-------------|------------------|
| `6` | `AGUARDANDO_PAGAMENTO` |
| `15` | `PAGO` (gatilho de produção) |
| `9` | `ENVIADO` |
| `12` | `CANCELADO` |

### 6.3 Deduplicação de Pedidos

**Problema:** O mesmo pedido pode chegar via webhook múltiplas vezes.

**Solução:** Tabela `demandas_item_origem` (legado) ou `demandas_pedidos` (novo) para rastreabilidade.

**Regra:**
```python
# order_tracker_service.filter_processed_items()
processed_map = {(order_id, sku, item_id): total_processed_qty}

if qty_already_processed < qty_requested:
    remaining_qty = qty_requested - qty_already_processed
    # Processa apenas o remanescente
```

---

## 7. Regras de Autorização (RBAC)

### 7.1 Papéis e Permissões

| Papel | Permissões |
|-------|------------|
| **Admin** | Acesso total a todas as operações |
| **Usuário** | Restrito ao seu `setor_id` |

### 7.2 Acesso a Movimentações de Estoque

| Operação | Admin | Usuário (mesmo setor) | Usuário (setor diferente) |
|----------|-------|----------------------|--------------------------|
| `registrar_entrada` | ✅ | ✅ | ❌ |
| `registrar_saida` | ✅ | ✅ | ❌ |
| `registrar_balanco` | ✅ | ✅ | ❌ |
| `registrar_transferencia` | ✅ | ✅ | ❌ |
| `reservar_estoque` | ✅ | ✅ | ❌ |

**Regra de Validação:**
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

---

## 8. Regras de Cálculo

### 8.1 Custo de BOM (Ficha Técnica)

```
Custo do Produto = Σ(Quantidade do Componente × Custo Unitário do Componente)
```

**Atualização Automática:**
- Quando um componente da BOM é alterado, o `preco_custo` do produto pai é recalculado automaticamente

### 8.2 Estoque Virtual de Kits

```
Estoque do Kit = MIN(Disponível do Componente / Quantidade na BOM) para todos os componentes
```

### 8.3 Progresso de Demanda

**Progresso Percentual:**
```
Progresso % = (Itens Concluídos / Total Itens) × 100
```

**Readiness Score (Prontidão):**
```
Readiness Score = ((Capas Impressas + Miolos Prontos) / (2 × Total Itens)) × 100
```

**Propósito:** Medir o quão próxima a demanda está de estar pronta para montagem final

### 8.4 Detecção de Demandas "Travadas"

**Heurística:**
```python
if status == 'EM_PRODUCAO' and total_itens > 0:
    gap_capas = capas_impressas_qtd - capas_produzidas_qtd
    if gap_capas > (total_itens * 0.5) and itens_concluidos < (total_itens * 0.2):
        is_stuck = True  # Demanda travada
```

---

## 9. Dependências entre Entidades

### 9.1 Dependências de Criação

```
1. plataformas                     → Independente
2. integration_modules             → Independente
3. installed_integrations          → Depende de: integration_modules
4. canais_venda                    → Depende de: plataformas
5. channel_connections             → Depende de: canais_venda, installed_integrations
6. regras_logisticas_canal         → Depende de: canais_venda, pontos_coleta
7. canal_modalidade_mapeamento     → Depende de: canais_venda
8. regras_consolidacao_canal       → Depende de: canais_venda
9. pedidos                         → Depende de: canais_venda
10. demandas_producao              → Depende de: canais_venda, produtos
11. demandas_pedidos               → Depende de: demandas_producao, pedidos
```

### 9.2 Dependências de Exclusão

**Cascata:**
```
canais_venda (EXCLUIR)
    ↓ CASCADE
    • canal_modalidade_mapeamento
    • regras_logisticas_canal
    • regras_consolidacao_canal
    • pedidos
    • demandas_producao

pedidos (EXCLUIR)
    ↓ CASCADE
    • itens_pedido
    • vinculos_integracao_pedido
    • demandas_pedidos

demandas_producao (EXCLUIR)
    ↓ CASCADE
    • itens_demanda
    • demandas_pedidos
    • entregas_producao
```

---

## 10. Referências de Implementação

### Services Python
| Arquivo | Responsabilidade |
|---------|------------------|
| `services/consolidation_service.py` | Consolidação de pedidos |
| `services/canal_modalidade_service.py` | Mapeamento de modalidade |
| `services/regras_consolidacao_service.py` | Regras de consolidação |
| `services/order_service.py` | Gestão de pedidos |
| `services/demanda_producao_service.py` | Gestão de demandas |
| `services/ordem_producao_service.py` | Ordens de produção |
| `services/estoque_service.py` | Gestão de estoque |
| `services/bom_service.py` | Ficha técnica |

### Migrations
| Arquivo | Descrição |
|---------|-----------|
| `20260402000014_consolidacao_simples.sql` | Consolidação |
| `20260329000004_contexto_producao_ux.sql` | Contexto e UX |
| `20260324000002_demandas_pedidos_pivot.sql` | Tabela pivot |

---

*Documento consolidado em 2026-04-02*
