# Contexto do Projeto: Consolidação de Demandas por Evento

**Data:** 2026-04-02  
**Status:** Fase 1 Implementada (Infraestrutura de Classificação)

---

## Objetivo Central

Implementar consolidação **automática** de pedidos em demandas de produção à medida que webhooks chegam, com fluxo de **mediação do usuário** (revisar e publicar, não criar do zero).

### Princípio de Design

> O usuário nunca consolida do zero. Ele **media** o que o sistema já pré-montou.

---

## Lacunas Arquiteturais Identificadas

### 1. Derivação de Modalidade (CRÍTICO)
**Problema:** Quando o Bling envia `servico_logistico: "Entrega Rápida Shopee"`, não havia como mapear para `modalidade: EXPRESS`.

**Solução:** Tabela `canal_modalidade_mapeamento` com padrões ILIKE configuráveis por canal.

### 2. Horário de Coleta com Dois Donos
**Problema:** `canais_venda.horario_coleta` e `regras_logisticas_canal.horario_limite` conflitam sem precedência.

**Solução:** Regra declarada:
```
1. regras_logisticas_canal (canal, modalidade) — FONTE CANÔNICA
2. canais_venda.horario_coleta — FALLBACK LEGADO
3. NULL — Default
```

### 3. Consolidação Não Era Data-Driven
**Problema:** Critérios de agrupamento (janela de 4h, agrupar por produto/miolo) estavam hardcoded.

**Solução:** Tabela `regras_consolidacao_canal` configurável por canal/modalidade.

### 4. Resolução de Canal no Webhook
**Problema:** Fluxo `bling_loja_id → canal_venda_id` não era explícito.

**Solução:** Service `resolve_canal_from_bling_store()` em `canal_venda_service.py`.

### 5. Inconsistência de Documentação
**Problema:** `demandas_item_origem` (legado) vs `demandas_pedidos` (novo).

**Solução:** Documentação atualizada para usar `demandas_pedidos`.

---

## Arquitetura Implementada

### Fluxo de Consolidação

```
Webhook Bling/Shopee
    ↓
Worker (upsert_order)
    ↓
consolidation_service.consolidar_pedido(pedido_id)
    │
    ├─→ resolver_modalidade() → canal_modalidade_mapeamento
    ├─→ resolver_horario() → regras_logisticas_canal
    ├─→ get_regra_consolidacao() → regras_consolidacao_canal
    ├─→ calcular_chave(produto, miolo, data_entrega)
    │
    ├─→ buscar_rascunho_compativel()
    │   ├─→ ENCONTROU: adicionar_ao_rascunho()
    │   └─→ NÃO ENCONTROU: criar_rascunho()
    │
    └─→ Demanda em status RASCUNHO
```

### Ciclo de Vida da Demanda

```
RASCUNHO (automático)
  │  ← novos pedidos entram enquanto janela aberta
  │  ← usuário pode editar
  │
  │ [usuário publica]
  │
  ↓
AGUARDANDO (publicado, fechado para novos pedidos)
  │
  ↓
EM_PRODUCAO
  │
  ↓
COLETA_PARCIAL
  │
  ↓
CONCLUIDO
```

### Estados do Rascunho

| Estado | Descrição | UI |
|--------|-----------|-----|
| Limpo | Sem edição humana | [Editar] [Publicar] |
| Editado | `editado_pelo_usuario = true` | ✏️ [Editar] [Publicar] |
| Modificado | Pedidos chegaram após edição | ⚠️ +N [Ver novos] [Publicar] |

---

## Schema do Banco de Dados

### Tabelas Criadas

#### `canal_modalidade_mapeamento`
Traduz `servico_logistico` → `modalidade`.

```sql
CREATE TABLE canal_modalidade_mapeamento (
    id BIGSERIAL PRIMARY KEY,
    canal_venda_id BIGINT NOT NULL,
    padrao_servico VARCHAR(255) NOT NULL,  -- Ex: '%flex%', '%rápida%'
    modalidade VARCHAR(50) NOT NULL,        -- STANDARD, EXPRESS, FULFILLMENT, RETIRADA
    prioridade INTEGER DEFAULT 0,           -- Maior = mais específico
    ativo BOOLEAN DEFAULT true
);
```

#### `regras_consolidacao_canal`
Configura agrupamento por canal/modalidade.

```sql
CREATE TABLE regras_consolidacao_canal (
    id BIGSERIAL PRIMARY KEY,
    canal_venda_id BIGINT,                  -- NULL = regra global
    modalidade VARCHAR(50),                 -- NULL = todas
    agrupar_por_produto BOOLEAN DEFAULT true,
    agrupar_por_miolo BOOLEAN DEFAULT true,
    agrupar_por_data_entrega BOOLEAN DEFAULT true,
    janela_agrupamento_horas INTEGER DEFAULT 4,
    comportamento_pos_edicao VARCHAR(30) DEFAULT 'ADICIONAR_COM_SINALIZACAO',
    comportamento_pos_publicacao VARCHAR(30) DEFAULT 'CRIAR_NOVO_RASCUNHO'
);
```

#### `pedidos_nao_classificados`
Fila de atenção para pedidos sem padrão mapeado.

```sql
CREATE TABLE pedidos_nao_classificados (
    id BIGSERIAL PRIMARY KEY,
    pedido_id BIGINT NOT NULL,
    canal_venda_id BIGINT NOT NULL,
    servico_logistico_recebido VARCHAR(500),
    resolvido BOOLEAN DEFAULT false,
    modalidade_atribuida VARCHAR(50)
);
```

### Colunas Adicionadas

#### `demandas_producao`
```sql
rascunho_expira_em TIMESTAMPTZ          -- Janela deslizante
editado_pelo_usuario BOOLEAN DEFAULT false
editado_em TIMESTAMPTZ
editado_por INTEGER REFERENCES usuarios(id)
pedidos_apos_edicao_qtd INTEGER DEFAULT 0
requer_revisao BOOLEAN DEFAULT false
publicado_em TIMESTAMPTZ
publicado_por INTEGER REFERENCES usuarios(id)
```

#### `demandas_pedidos`
```sql
adicionado_apos_edicao BOOLEAN DEFAULT false
adicionado_em TIMESTAMPTZ DEFAULT NOW()
```

---

## Arquivos Criados

### Migrations
| Arquivo | Descrição |
|---------|-----------|
| `20260402000014_consolidacao_simples.sql` | Migration final (funciona) |
| `20260402000005_consolidacao_fase1_classificacao.sql` | Obsoleta (não usar) |
| `20260402000006_consolidacao_fase2_rascunho_lifecycle.sql` | Obsoleta (não usar) |

### Models Python
| Arquivo | Descrição |
|---------|-----------|
| `models/canal_modalidade_mapeamento.py` | Model da tabela de mapeamento |
| `models/regras_consolidacao_canal.py` | Model das regras de consolidação |

### Services Python
| Arquivo | Descrição |
|---------|-----------|
| `services/canal_modalidade_service.py` | CRUD de mapeamentos |
| `services/regras_consolidacao_service.py` | CRUD de regras |
| `services/consolidation_service.py` | **Serviço principal** de consolidação |

### Seeds
| Arquivo | Descrição |
|---------|-----------|
| `seeds/01_canal_modalidade_mapeamento.sql` | Dados iniciais de exemplo |

### Documentação
| Arquivo | Descrição |
|---------|-----------|
| `docs/ARQUITETURA-SISTEMA.md` | Atualizado com `demandas_pedidos` e resolução de canal |

---

## Integração no Worker

Para ativar a consolidação automática, adicionar no `bling_order_processing_service.py` ou `pedidos_fetch_tasks.py`:

```python
from nistiprint_shared.services.consolidation_service import consolidation_service

# Após upsert_order():
consolidation_service.consolidar_pedido(pedido_id)
```

---

## Dados Iniciais Sugeridos

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

-- Mapeamentos Shopee
INSERT INTO canal_modalidade_mapeamento (canal_venda_id, padrao_servico, modalidade, prioridade) VALUES
  (1, '%flex%', 'EXPRESS', 10),
  (1, '%rápida%', 'EXPRESS', 10),
  (1, '%normal%', 'STANDARD', 5),
  (1, '%padrão%', 'STANDARD', 5);
```

---

## Próximos Passos (Fases Futuras)

### Fase 2: Endpoints de Rascunho
- `GET /demandas/rascunhos` — Lista rascunhos ordenados
- `GET /demandas/rascunhos/{id}/pedidos?apenas_novos=true` — Filtra pedidos pós-edição
- `PATCH /demandas/rascunhos/{id}` — Edição pelo usuário
- `PATCH /demandas/{id}/publicar` — Publica com confirmação se `requer_revisao=true`

### Fase 3: Interface (Dashboard)
- Seção "Rascunhos" separada de "Demandas Ativas"
- Cards com estados visuais (limpo, editado, modificado)
- Badge `⚠️ +N` para pedidos pós-edição
- Modal "Ver novos pedidos"
- Seção "Pedidos aguardando classificação"

---

## Lições Aprendidas

1. **Supabase SQL Editor valida todo o script antes de executar** — `EXCEPTION WHEN others` não protege se a tabela não existir no parse.

2. **Solução:** Dividir migration em partes ou só dropar tabelas que existem.

3. **Migration final que funcionou:** `20260402000014_consolidacao_simples.sql` — só dropa `regras_consolidacao_canal` (que existe) e cria as 3 tabelas do zero.

---

## Contato e Referências

- **Service Principal:** `packages/shared/nistiprint_shared/services/consolidation_service.py`
- **Migration:** `supabase/migrations/20260402000014_consolidacao_simples.sql`
- **Documentação:** `docs/ARQUITETURA-SISTEMA.md` (seções 3.4, 5)
