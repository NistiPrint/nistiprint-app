# Levantamento ER - Demandas de Produção

## Visão Geral: Fluxo Operacional da Fábrica

> **Princípio Central:** O que importa para o dia a dia da fábrica e operação é a **demanda de produção consolidada**, ordenada pelo que deve ser **coletado/enviado primeiro**.

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    FLUXO OPERACIONAL - VISÃO DA FÁBRICA                         │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ENTENDA: A fábrica não produz "pedidos", produz "demandas consolidadas"        │
│                                                                                 │
│  ┌──────────────┐     ┌─────────────────┐     ┌────────────────────────────┐   │
│  │   PEDIDOS    │     │  CONSOLIDAÇÃO   │     │    DEMANDA DE PRODUÇÃO     │   │
│  │   (entrada)  │ ──▶ │  (agrupamento)  │ ──▶ │    (o que a fábrica vê)    │   │
│  │              │     │                 │     │                            │   │
│  │ • Shopee     │     │ Critérios:      │     │ • Ordenada por coleta     │   │
│  │ • ML         │     │ • Produto       │     │ • Plataforma + Modalidade │   │
│  │ • Amazon     │     │ • Miolo         │     │ • Quantidade total        │   │
│  │ • Shein      │     │ • Data entrega  │     │ • Status de produção      │   │
│  │ • Bling      │     │ • Canal         │     │ • Coletas parciais        │   │
│  └──────────────┘     │ • Modalidade    │     └────────────────────────────┘   │
│                       └─────────────────┘                                      │
│                                                                                 │
│  REGRA DE COLETA: Plataforma + Modalidade Logística                             │
│  ─────────────────────────────────────────────                                  │
│  • Shopee + Flex         → Coleta 14h (prioridade máxima)                       │
│  • Shopee + Normal       → Coleta 18h                                           │
│  • Mercado Livre + Flex  → Coleta 15h                                           │
│  • Mercado Livre + Normal→ Coleta 19h                                           │
│  • Fulfillment           → Coleta conforme agendamento externo                  │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Princípios de Design

| Princípio | Descrição |
|-----------|-----------|
| **Demanda é o centro** | A fábrica trabalha com demandas, não com pedidos individuais |
| **Consolidação inteligente** | Múltiplos pedidos → Uma demanda (quando possível) |
| **Ordenação por coleta** | O que sai primeiro, produz primeiro |
| **Plataforma + Modalidade** | Regra de coleta define prioridade |
| **Snapshot no tempo** | Características do canal são capturadas na criação |

---

## Diagrama Entidade-Relacionamento

### Visão Geral: Entidades Centrais

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                            NÚCLEO OPERACIONAL                                   │
│                         (o que a fábrica usa)                                   │
└─────────────────────────────────────────────────────────────────────────────────┘

                              ┌─────────────────────────┐
                              │  INTEGRATION_MODULES    │
                              │  (catálogo)             │
                              │  • Shopee, ML, Amazon   │
                              │  • Bling (ERP)          │
                              └───────────┬─────────────┘
                                          │ 1:N
                                          ▼
                              ┌─────────────────────────┐
                              │ INSTALLED_INTEGRATIONS  │
                              │  (instâncias ativas)    │
                              │  • tokens, config       │
                              └───────────┬─────────────┘
                                          │
                                          │
                    ┌─────────────────────┴─────────────────────┐
                    │                                           │
                    ▼                                           ▼
        ┌─────────────────────┐                   ┌─────────────────────┐
        │ CHANNEL_CONNECTIONS │                   │    PLATAFORMAS      │
        │  (vínculo canal ↔   │                   │  (sistema externo)  │
        │   integração)       │                   │  Shopee, ML, etc.   │
        └──────────┬──────────┘                   └──────────┬──────────┘
                   │                                          │ 1:N
                   │ 1:1                                      │
                   ▼                                          ▼
        ┌─────────────────────────────────────────────────────────────────┐
        │                         CANAIS_VENDA                            │
        │  (instância específica de venda)                                │
        │                                                                 │
        │  • flex: boolean           → Entrega rápida/urgente             │
        │  • fulfillment: boolean    → Fulfillment externo                │
        │  • horario_coleta: time    → Horário de coleta padrão           │
        │  • color: string           → Cor para UI                        │
        └─────────────────────────────────────────────────────────────────┘
                   │ 1:N
                   │ define
                   ▼
        ┌─────────────────────────────────────────────────────────────────┐
        │                   REGRAS_LOGISTICAS_CANAL                       │
        │                                                                 │
        │  • modalidade: STANDARD, EXPRESS, FULFILLMENT, RETIRADA         │
        │  • tipo_envio: COLETA_LOCAL, PONTO_COLETA                       │
        │  • horario_limite: time    → Horário de corte                   │
        │  • ponto_coleta_id: FK                                          │
        └─────────────────────────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────────────────────┐
│                    FLUXO: PEDIDOS → DEMANDAS (N:N)                              │
└─────────────────────────────────────────────────────────────────────────────────┘

                              ┌─────────────────────────┐
                              │       PEDIDOS           │
                              │  (vendas individuais)   │
                              │                         │
                              │  • is_flex (herdado)    │
                              │  • data_limite_envio    │
                              │  • servico_logistico    │
                              │  • channel_snapshot     │
                              └───────────┬─────────────┘
                                          │
                                          │ N:M
                                          │ consolidado em
                                          ▼
                              ┌─────────────────────────┐
                              │  DEMANDAS_PEDIDOS       │
                              │  (tabela PIVOT N:N)     │
                              │                         │
                              │  • demanda_id (FK)      │
                              │  • pedido_id (FK)       │
                              │  • created_at           │
                              └───────────┬─────────────┘
                                          │
                                          │ N:1
                                          │ composto por
                                          ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         DEMANDAS_PRODUCAO (CENTRO)                              │
│  (ordem de fabricação para a fábrica)                                           │
│                                                                                 │
│  ┌───────────────────────────────────────────────────────────────────────────┐ │
│  │ ATRIBUTOS PRINCIPAIS                                                      │ │
│  ├───────────────────────────────────────────────────────────────────────────┤ │
│  │ • demanda_id: UUID            → Identificador único                       │ │
│  │ • descricao: text             → Descrição da demanda                      │ │
│  │ • status: varchar(50)         → AGUARDANDO, EM_PRODUCAO, CONCLUIDO        │ │
│  │ • prioridade: integer         → Score calculado                           │ │
│  │                                                                         │ │
│  │ • canal_venda_id: FK          → Canal de origem                           │ │
│  │ • horario_coleta: time        → Quando deve ser coletado                  │ │
│  │ • modalidade_logistica:       → STANDARD, EXPRESS, FULFILLMENT            │ │
│  │ • is_flex: boolean            → Entrega urgente (mesmo dia)               │ │
│  │ • fulfillment: boolean        → Reposição externa                         │ │
│  │                                                                         │ │
│  │ • data_entrega: date          → Deadline de entrega                       │ │
│  │ • data_limite_execucao: date  → Deadline de produção                      │ │
│  │ • categoria_temporal:         → URGENTE, HOJE, AMANHA, FUTURO             │ │
│  │                                                                         │ │
│  │ • channel_snapshot: jsonb     → Snapshot do canal na criação              │ │
│  │ • setores_envolvidos: jsonb   → Setores necessários (BOM)                 │ │
│  └───────────────────────────────────────────────────────────────────────────┘ │
│                                                                                 │
│  ┌───────────────────────────────────────────────────────────────────────────┐ │
│  │ ITENS_DEMANDA (1:N)                                                       │ │
│  ├───────────────────────────────────────────────────────────────────────────┤ │
│  │ • produto_id, sku, descricao, quantidade                                  │ │
│  │ • id_produto_miolo, miolo_nome, variacao                                  │ │
│  │                                                                         │ │
│  │ CONTROLE DE PRODUÇÃO:                                                     │ │
│  │ • capas_impressas_qtd, capas_produzidas_qtd                               │ │
│  │ • miolos_prontos_retirada_qtd                                             │ │
│  │ • finalizados_qtd                                                         │ │
│  │ • status_item: PENDENTE, PROCESSANDO, CONCLUIDO                           │ │
│  └───────────────────────────────────────────────────────────────────────────┘ │
│                                                                                 │
│  ┌───────────────────────────────────────────────────────────────────────────┐ │
│  │ ENTREGA_PRODUCAO (1:N) - Coletas parciais                                 │ │
│  ├───────────────────────────────────────────────────────────────────────────┤ │
│  │ • demanda_id, item_demanda_id, quantidade                                 │ │
│  │ • data_entrega, user_id                                                   │ │
│  └───────────────────────────────────────────────────────────────────────────┘ │
│                                                                                 │
│  ┌───────────────────────────────────────────────────────────────────────────┐ │
│  │ ALERTAS_DEMANDA, SINALIZACOES_DEMANDA - Monitoramento                     │ │
│  └───────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Agrupamento por Plataforma + Modalidade Logística

> **Regra de Coleta:** A plataforma interpreta os pedidos recebidos via webhook e agrupa as demandas de produção com base na combinação **Plataforma + Modalidade Logística**.

### Matriz de Agrupamento

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    COMO OS PEDIDOS SÃO AGRUPADOS EM DEMANDAS                    │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  PLATAFORMA         │ MODALIDADE    │ HORÁRIO    │ PRIORIDADE │ AGRUPAMENTO    │
│  ───────────────────┼───────────────┼────────────┼────────────┼────────────────│
│  Shopee             │ Flex          │ 14:00      │ MÁXIMA     │ Urgentes do    │
│                     │ (EXPRESS)     │            │            │ mesmo dia      │
│  ───────────────────┼───────────────┼────────────┼────────────┼────────────────│
│  Shopee             │ Normal        │ 18:00      │ ALTA       │ Demais pedidos │
│                     │ (STANDARD)    │            │            │ do dia         │
│  ───────────────────┼───────────────┼────────────┼────────────┼────────────────│
│  Mercado Livre      │ Flex          │ 15:00      │ MÁXIMA     │ Urgentes do    │
│                     │ (EXPRESS)     │            │            │ mesmo dia      │
│  ───────────────────┼───────────────┼────────────┼────────────┼────────────────│
│  Mercado Livre      │ Normal        │ 19:00      │ ALTA       │ Demais pedidos │
│                     │ (STANDARD)    │            │            │ do dia         │
│  ───────────────────┼───────────────┼────────────┼────────────┼────────────────│
│  Amazon             │ Prime         │ 16:00      │ MÁXIMA     │ Prime mesmo dia│
│                     │ (EXPRESS)     │            │            │                │
│  ───────────────────┼───────────────┼────────────┼────────────┼────────────────│
│  Amazon             │ Standard      │ 20:00      │ NORMAL     │ Demais pedidos │
│                     │ (STANDARD)    │            │            │                │
│  ───────────────────┼───────────────┼────────────┼────────────┼────────────────│
│  Shein              │ Express       │ 17:00      │ ALTA       │ Express        │
│                     │ (EXPRESS)     │            │            │                │
│  ───────────────────┼───────────────┼────────────┼────────────┼────────────────│
│  Shein              │ Standard      │ 21:00      │ NORMAL     │ Standard       │
│                     │ (STANDARD)    │            │            │                │
│  ───────────────────┼───────────────┼────────────┼────────────┼────────────────│
│  Qualquer           │ Fulfillment   │ Agendado   │ VARIÁVEL   │ Reposição      │
│                     │ (FULFILLMENT) │            │            │ externa        │
│  ───────────────────┼───────────────┼────────────┼────────────┼────────────────│
│  Qualquer           │ Retirada      │ Balcão     │ BAIXA      │ Retirada local │
│                     │ (RETIRADA)    │            │            │                │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Critérios de Consolidação

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    CRITÉRIOS PARA AGRUPAR PEDIDOS EM UMA DEMANDA                │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ✅ AGRUPAR (mesma demanda) quando:                                             │
│  ─────────────────────────────────────────────                                  │
│  • Mesmo produto (ou produto equivalente)                                       │
│  • Mesmo miolo (componente principal)                                           │
│  • Mesma data de entrega (ou janela de 24h)                                     │
│  • Mesma plataforma + modalidade (ex: Shopee+Flex)                              │
│  • Mesmo canal de venda (configurável)                                          │
│                                                                                 │
│  ❌ NÃO AGRUPAR (demandas separadas) quando:                                    │
│  ─────────────────────────────────────────────────────                          │
│  • Modalidades diferentes (Flex ≠ Normal)                                       │
│  • Janelas de coleta muito distantes (>4h)                                      │
│  • Produtos incompatíveis (linhas de produção diferentes)                       │
│  • Pedido urgente isolado (não compensa agrupar)                                │
│  • Configuração específica do canal proíbe agrupamento                          │
│                                                                                 │
│  EXEMPLO PRÁTICO:                                                               │
│  ─────────────────                                                              │
│  Pedidos recebidos:                                                             │
│  • Pedido 1001: Shopee, Flex, Capa iPhone 14, entrega 14h                       │
│  • Pedido 1002: Shopee, Flex, Capa iPhone 14, entrega 14h                       │
│  • Pedido 1003: Shopee, Flex, Capa iPhone 14, entrega 14h                       │
│  • Pedido 1004: Shopee, Normal, Capa iPhone 14, entrega 18h                     │
│  • Pedido 1005: ML, Flex, Capa iPhone 14, entrega 15h                           │
│                                                                                 │
│  Demandas geradas:                                                              │
│  • Demanda A: Pedidos 1001+1002+1003 (Shopee+Flex, 14h, qty=3)                  │
│  • Demanda B: Pedido 1004 (Shopee+Normal, 18h, qty=1)                           │
│  • Demanda C: Pedido 1005 (ML+Flex, 15h, qty=1)                                 │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Ordem de Produção (Dashboard)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    ORDENAÇÃO NO DASHBOARD DE PRODUÇÃO                           │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  CRITÉRIOS DE ORDENAÇÃO (em ordem de prioridade):                               │
│  ───────────────────────────────────────────────                                │
│                                                                                 │
│  1. is_flex = TRUE (entrega no mesmo dia)                                       │
│  2. modalidade_logistica = EXPRESS                                                │
│  3. horario_coleta (mais próximo primeiro)                                      │
│  4. prioridade_calculada (score)                                                │
│  5. data_entrega (mais próxima primeiro)                                        │
│  6. modalidade_logistica = STANDARD                                               │
│  7. modalidade_logistica = RETIRADA                                               │
│                                                                                 │
│  EXEMPLO DE ORDENAÇÃO:                                                          │
│  ──────────────────────                                                         │
│  ┌────┬──────────────┬─────────────┬────────────┬─────────────────────────┐    │
│  │ #  │ Plataforma   │ Modalidade  │ Coleta     │ Demanda                 │    │
│  ├────┼──────────────┼─────────────┼────────────┼─────────────────────────┤    │
│  │ 1  │ Shopee       │ Flex        │ 14:00      │ Capa iPhone 14 (qty=5)  │    │
│  │ 2  │ Mercado Livre│ Flex        │ 15:00      │ Capa Samsung S23 (qty=3)│    │
│  │ 3  │ Amazon       │ Prime       │ 16:00      │ Miolo Agenda 2026 (qty=10)   │
│  │ 4  │ Shopee       │ Normal      │ 18:00      │ Capa iPhone 13 (qty=8)  │    │
│  │ 5  │ Shein        │ Standard    │ 21:00      │ Miolo Planner (qty=15)  │    │
│  │ 6  │ Fulfillment  │ Agendado    │ 10:00+1    │ Reposição Estoque (qty=50)     │
│  └────┴──────────────┴─────────────┴────────────┴─────────────────────────┘    │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Detalhamento das Entidades

### 1. Integrações e Canais de Venda

#### `integration_modules` (Catálogo de Conectores)

Catálogo de todos os conectores disponíveis no sistema.

| Coluna | Tipo | Nullable | Descrição |
|--------|------|----------|-----------|
| `id` | text | NO | PK (ex: 'shopee', 'mercadolivre', 'amazon', 'bling') |
| `name` | text | NO | Nome amigável |
| `tipo` | varchar(50) | YES | `MARKETPLACE`, `ERP`, `ECOMMERCE` |
| `slug` | varchar(100) | YES | Identificador URL-friendly |
| `is_aggregator` | boolean | YES | True se é agregador (ex: Bling) |
| `config_schema` | jsonb | YES | Schema de configuração (JSON Schema) |
| `auth_flow` | text | YES | OAuth2, API_KEY, etc. |
| `is_active` | boolean | YES | Status do módulo |

**Tipos de Integração:**

| Tipo | Descrição | Exemplos |
|------|-----------|----------|
| `MARKETPLACE` | Plataformas de venda | Shopee, Mercado Livre, Amazon, Shein |
| `ERP` | Sistema de gestão | Bling (agregador de pedidos) |
| `ECOMMERCE` | Loja virtual | Loja Integrada |

---

#### `installed_integrations` (Instâncias Ativas)

Instâncias ativas de integrações, com tokens e configuração.

| Coluna | Tipo | Nullable | Descrição |
|--------|------|----------|-----------|
| `id` | integer | NO | PK |
| `module_id` | varchar(100) | NO | FK → integration_modules.id |
| `platform_slug` | varchar(100) | YES | Slug da plataforma |
| `instance_name` | varchar(255) | NO | Nome da instância (ex: "Shopee - CNPJ 01") |
| `access_token` | text | YES | Token de acesso |
| `refresh_token` | text | YES | Token de refresh |
| `expires_at` | timestamptz | YES | Expiração do token |
| `config` | jsonb | YES | Configurações específicas |
| `is_active` | boolean | YES | Status |
| `last_sync` | timestamptz | YES | Última sincronização |
| `sync_status` | varchar(50) | YES | pending, success, error |

---

#### `channel_connections` (Vínculo Canal ↔ Integração)

**Nova arquitetura.** Vínculo explícito entre canal de venda e integração.

| Coluna | Tipo | Nullable | Descrição |
|--------|------|----------|-----------|
| `id` | uuid | NO | PK |
| `channel_id` | integer | NO | FK → canais_venda.id |
| `integration_id` | integer | YES | FK → installed_integrations.id |
| `aggregator_store_id` | varchar(255) | YES | Loja no agregador (ex: bling_loja_id) |
| `aggregator_store_name` | varchar(255) | YES | Nome da loja (ex: "Shopee Antiga") |
| `bling_integration_id` | integer | YES | FK → installed_integrations (Bling) |
| `marketplace_integration_id` | integer | YES | FK → installed_integrations (Marketplace) |
| `config` | jsonb | YES | Configurações específicas |
| `is_active` | boolean | YES | Status |
| `last_sync` | timestamptz | YES | Última sincronização |
| `sync_status` | varchar(50) | YES | Status do sync |

**Fluxo de Vínculo:**

```
┌─────────────────────────────────────────────────────────────────┐
│                    VÍNCULO CANAL → INTEGRAÇÃO                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  CANAL_VENDA (Shopee - CNPJ 01)                                 │
│       │                                                         │
│       │ 1:1                                                     │
│       ▼                                                         │
│  CHANNEL_CONNECTIONS                                            │
│       │                                                         │
│       │ N:1                                                     │
│       ▼                                                         │
│  INSTALLED_INTEGRATIONS                                         │
│       │                                                         │
│       ├─────────────────┬─────────────────────────────────┐    │
│       │                 │                                 │    │
│       ▼                 ▼                                 │    │
│  Bling (ERP)      Shopee (Marketplace)                    │    │
│  • Busca pedidos  • Webhook direto                        │    │
│  • Agrega todas   • Atualiza status                       │    │
│    as lojas       • OAuth específico                      │    │
│                                                             │    │
└─────────────────────────────────────────────────────────────┘
```

---

#### `integracao_canais_config` (Legado)

Tabela legada, em processo de substituição por `channel_connections`.

| Coluna | Tipo | Nullable | Descrição |
|--------|------|----------|-----------|
| `id` | uuid | NO | PK |
| `canal_venda_id` | integer | YES | FK → canais_venda.id |
| `integration_id` | integer | YES | FK → installed_integrations.id |
| `bling_loja_id` | bigint | YES | ID da loja no Bling |
| `plataforma_nome` | varchar(100) | YES | Nome da plataforma |
| `is_active` | boolean | YES | Status |

---

#### `canais_venda`

Representa um canal específico de venda (ex: "Shopee - CNPJ 01", "Amazon - Prime").

| Coluna | Tipo | Nullable | Descrição |
|--------|------|----------|-----------|
| `id` | integer | NO | PK |
| `nome` | varchar(100) | NO | Nome do canal |
| `plataforma_id` | integer | YES | FK → plataformas.id (legado) |
| `slug` | varchar(100) | YES | Identificador URL-friendly |
| `flex` | boolean | YES | **Entrega rápida/urgente** |
| `fulfillment` | boolean | YES | **Fulfillment externo** |
| `horario_coleta` | time | YES | Horário de coleta padrão |
| `color` | varchar(7) | YES | Cor para UI |
| `ativo` | boolean | YES | Status do canal |

**Atributos Especiais:**

| Atributo | Impacto no Fluxo |
|----------|------------------|
| `flex = true` | Pedidos herdam `is_flex = true` → Prioridade máxima, coleta no mesmo dia |
| `fulfillment = true` | Pedidos geram demanda tipo `FULFILLMENT` → Reposição externa |
| `horario_coleta` | Define horário padrão para demandas do canal |

---

#### `regras_logisticas_canal`

Regras de janelas de despacho por canal e modalidade. **Define como os pedidos do canal serão processados.**

| Coluna | Tipo | Nullable | Descrição |
|--------|------|----------|-----------|
| `id` | integer | NO | PK |
| `canal_venda_id` | integer | NO | FK → canais_venda.id |
| `modalidade` | varchar(50) | NO | `STANDARD`, `EXPRESS`, `FULFILLMENT`, `RETIRADA` |
| `tipo_envio` | varchar(50) | NO | `COLETA_LOCAL`, `PONTO_COLETA` |
| `horario_limite` | time | NO | **Horário de corte para despacho** |
| `ponto_coleta_id` | integer | YES | FK → pontos_coleta.id |
| `prioridade_uso` | integer | YES | Prioridade da regra |

**Modalidades Logísticas:**

| Modalidade | Descrição | Impacto na Demanda |
|------------|-----------|-------------------|
| `STANDARD` | Envio padrão | Demanda com prioridade normal, coleta no horário padrão |
| `EXPRESS` | Entrega expressa (Flex) | Demanda `is_flex = true`, prioridade máxima |
| `FULFILLMENT` | Armazém externo | Demanda tipo `FULFILLMENT`, agendamento externo |
| `RETIRADA` | Retirada no balcão | Demanda com retirada local, prioridade baixa |

---

#### `pontos_coleta`

Locais físicos para despacho de mercadorias.

| Coluna | Tipo | Nullable | Descrição |
|--------|------|----------|-----------|
| `id` | integer | NO | PK |
| `nome` | varchar(255) | NO | Nome do ponto |
| `horario_corte_padrao` | time | NO | Horário de corte padrão |
| `endereco` | text | YES | Endereço completo |
| `ativo` | boolean | YES | Status |

---

### 2. Pedidos

#### `pedidos`

Pedidos unificados de todas as plataformas. **Entrada do fluxo de produção.**

| Coluna | Tipo | Nullable | Descrição |
|--------|------|----------|-----------|
| `id` | integer | NO | PK |
| `uuid_pedido` | uuid | NO | ID universal único |
| `numero_pedido` | varchar(50) | NO | ID amigável |
| `codigo_pedido_externo` | varchar(100) | NO | ID na plataforma externa |
| `origem` | varchar(50) | NO | `SHOPEE`, `BLING`, `MANUAL`, etc. |
| `canal_venda_id` | integer | YES | FK → canais_venda.id |
| `is_flex` | boolean | YES | **Herdado do canal** |
| `data_limite_envio` | timestamptz | YES | Deadline de envio |
| `servico_logistico` | varchar(255) | YES | Serviço de entrega |
| `payload_canonico` | jsonb | YES | Dados normalizados |
| `channel_snapshot` | jsonb | YES | **Snapshot do canal na criação** |

**Fluxo de Entrada:**

```
┌─────────────────────────────────────────────────────────────────┐
│                    ENTRADA DE PEDIDOS                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  FONTES:                                                        │
│  ───────                                                        │
│  1. Webhook Bling (n8n → Redis → Worker)                        │
│     • order.updated com situacao.id = 15 (Em Andamento)         │
│     • Busca detalhes completos via API Bling                    │
│     • Upsert em pedidos (por codigo_pedido_externo)             │
│                                                                 │
│  2. Consolidação Manual (Upload Excel/CSV)                      │
│     • Shopee, ML, Amazon, Shein                                 │
│     • Processamento assíncrono (Celery)                         │
│     • Persistência em lote                                      │
│                                                                 │
│  3. Pedido Manual (Frontend)                                    │
│     • Venda B2B, reposição interna                              │
│     • Criação direta via API                                    │
│                                                                 │
│  HERANÇA DE ATRIBUTOS:                                          │
│  ──────────────────────                                         │
│  • is_flex ← canais_venda.flex                                  │
│  • fulfillment ← canais_venda.fulfillment                       │
│  • horario_coleta ← canais_venda.horario_coleta                 │
│  • channel_snapshot ← Snapshot completo no momento da criação   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

#### `vinculos_integracao_pedido`

Rastreabilidade de IDs externos por plataforma.

| Coluna | Tipo | Nullable | Descrição |
|--------|------|----------|-----------|
| `id` | uuid | NO | PK |
| `pedido_id` | integer | NO | FK → pedidos.id |
| `plataforma` | varchar(50) | NO | `BLING`, `SHOPEE`, `AMAZON`, etc. |
| `id_na_plataforma` | varchar(100) | NO | ID externo na plataforma |
| `status_na_plataforma` | varchar(50) | YES | Status na plataforma |
| `dados_brutos` | jsonb | YES | Payload original |
| `last_synced_at` | timestamptz | YES | Última sincronização |

**Um pedido pode ter múltiplos vínculos:**
- Vínculo Bling (fonte primária)
- Vínculo Shopee (plataforma de origem)
- Vínculo Mercado Livre (se multi-canal)

---

### 3. Demandas de Produção (NÚCLEO OPERACIONAL)

> **Importante:** Esta é a entidade central para a fábrica. Enquanto `pedidos` representam vendas individuais, `demandas_producao` representam **ordens de fabricação consolidadas**.

#### `demandas_producao`

Demanda consolidada para produção.

| Coluna | Tipo | Nullable | Descrição |
|--------|------|----------|-----------|
| `id` | integer | NO | PK |
| `demanda_id` | varchar(255) | NO | UUID original (Firestore) |
| `descricao` | text | YES | Descrição da demanda |
| `produto_id` | integer | YES | FK → produtos.id |
| `quantidade` | integer | YES | Quantidade a produzir |
| `data_entrega` | date | YES | Data de entrega |
| `prioridade` | integer | YES | **Score calculado** |
| `status` | varchar(50) | YES | `AGUARDANDO`, `EM_PRODUCAO`, `COLETA_PARCIAL`, `CONCLUIDO`, `CANCELADO` |
| `responsavel_id` | integer | YES | FK → usuarios.id |
| `canal_venda_id` | integer | YES | FK → canais_venda.id |
| `horario_coleta` | time | YES | **Horário de coleta** |
| `tipo_demanda` | varchar(50) | YES | `PLATAFORMA`, `B2B`, `FULFILLMENT`, `ESTOQUE_INTERNO` |
| `modalidade_logistica` | varchar(20) | YES | `STANDARD`, `EXPRESS`, `FULFILLMENT`, `RETIRADA` |
| `classificacao_cliente` | varchar(10) | YES | `B2C`, `B2B`, `INTERNO` |
| `is_flex` | boolean | YES | **Entrega urgente** |
| `fulfillment` | boolean | YES | **Fulfillment externo** |
| `prioridade_manual` | integer | YES | Override manual de prioridade |
| `pedido_numero` | varchar(100) | YES | Número do pedido (se único) |
| `data_limite_execucao` | date | YES | Deadline de execução |
| `categoria_temporal` | text | YES | `URGENTE`, `HOJE`, `AMANHA`, `FUTURO` |
| `setores_envolvidos` | jsonb | YES | Setores necessários (via BOM) |
| `channel_snapshot` | jsonb | YES | **Snapshot do canal na criação** |
| `observacoes` | text | YES | Observações |
| `data_conclusao` | timestamp | YES | Data de conclusão |

**Tipos de Demanda:**

| Tipo | Descrição | Origem |
|------|-----------|--------|
| `PLATAFORMA` | Venda consolidada de marketplace | Pedido Shopee, ML, Amazon, Shein |
| `B2B` | Venda corporativa | Pedido empresarial |
| `FULFILLMENT` | Reposição para fulfillment | Canal com `fulfillment=true` |
| `ESTOQUE_INTERNO` | Produção para estoque | Planejamento interno |

**Categorias Temporais:**

| Categoria | Critério | Impacto |
|-----------|----------|---------|
| `URGENTE` | is_flex = true + coleta hoje | Topo da fila |
| `HOJE` | data_entrega = hoje | Prioridade alta |
| `AMANHA` | data_entrega = amanhã | Prioridade média |
| `FUTURO` | data_entrega > amanhã | Prioridade baixa |

**Channel Snapshot (Captura no Momento da Criação):**

```json
{
  "canal_id": 1,
  "canal_nome": "Shopee - CNPJ 01",
  "flex": true,
  "fulfillment": false,
  "horario_coleta": "14:00:00",
  "modalidade_logistica": "EXPRESS",
  "plataforma": "shopee",
  "capturado_em": "2026-04-02T10:30:00Z"
}
```

> **Importante:** O snapshot **NUNCA** é atualizado retroativamente. Pedidos históricos mantêm características originais, mesmo que o canal seja modificado.

---

#### `itens_demanda`

Itens que compõem a demanda. **Controle fino da produção.**

| Coluna | Tipo | Nullable | Descrição |
|--------|------|----------|-----------|
| `id` | integer | NO | PK |
| `demanda_id` | integer | NO | FK → demandas_producao.id |
| `produto_id` | integer | YES | FK → produtos.id (produto principal) |
| `sku` | varchar(100) | YES | SKU do produto |
| `descricao` | varchar(500) | YES | Descrição do item |
| `quantidade` | numeric(15,4) | YES | Quantidade |
| `id_produto_miolo` | integer | YES | FK → produtos.id (miolo) |
| `miolo_nome` | varchar(255) | YES | Nome do miolo |
| `variacao` | varchar(255) | YES | Variação do produto |
| `status_item` | varchar(50) | YES | `PENDENTE`, `PROCESSANDO`, `CONCLUIDO` |
| `capas_impressas_qtd` | numeric(15,4) | YES | Capas impressas |
| `capas_produzidas_qtd` | numeric(15,4) | YES | Capas produzidas |
| `capas_prontas_retirada_qtd` | numeric(15,4) | YES | Capas prontas |
| `miolos_prontos_retirada_qtd` | numeric(15,4) | YES | Miolos prontos |
| `expedicao_capas_retiradas_qtd` | numeric(15,4) | YES | Capas retiradas |
| `expedicao_miolos_retirados_qtd` | numeric(15,4) | YES | Miolos retirados |
| `finalizados_qtd` | numeric(15,4) | YES | **Finalizados** |
| `status_processamento` | varchar(50) | YES | `PENDENTE`, `PROCESSANDO`, `CONCLUIDO` |

**Fluxo de Produção por Item:**

```
┌─────────────────────────────────────────────────────────────────┐
│                    FLUXO DE PRODUÇÃO DO ITEM                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  PENDENTE                                                       │
│     │                                                           │
│     ▼                                                           │
│  IMPRESSÃO (capas_impressas_qtd)                                │
│     │                                                           │
│     ▼                                                           │
│  PRODUÇÃO CAPAS (capas_produzidas_qtd)                          │
│     │                                                           │
│     ▼                                                           │
│  PRODUÇÃO MIOLOS (miolos_prontos_retirada_qtd)                  │
│     │                                                           │
│     ▼                                                           │
│  RETIRADA CAPAS (expedicao_capas_retiradas_qtd)                 │
│     │                                                           │
│     ▼                                                           │
│  RETIRADA MIOLOS (expedicao_miolos_retirados_qtd)               │
│     │                                                           │
│     ▼                                                           │
│  FINALIZAÇÃO (finalizados_qtd) ← Status: CONCLUIDO              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

#### `demandas_pedidos` (Tabela PIVOT N:N)

**Relacionamento Many-to-Many entre Demandas e Pedidos.**

| Coluna | Tipo | Nullable | Descrição |
|--------|------|----------|-----------|
| `id` | bigserial | NO | PK |
| `demanda_id` | bigint | NO | FK → demandas_producao.id |
| `pedido_id` | bigint | NO | FK → pedidos.id |
| `created_at` | timestamptz | YES | Data do vínculo |

**Constraints:**
- UNIQUE (demanda_id, pedido_id) - Evita duplicatas
- FK com ON DELETE CASCADE

**Índices:**
- idx_demandas_pedidos_pedido_id
- idx_demandas_pedidos_demanda_id
- idx_demandas_pedidos_demanda_pedido

**Exemplo de Uso:**

```sql
-- Um pedido pode estar em múltiplas demandas
SELECT
    p.numero_pedido,
    dp.demanda_id,
    dp.descricao,
    dp.status
FROM pedidos p
JOIN demandas_pedidos dp_rel ON p.id = dp_rel.pedido_id
JOIN demandas_producao dp ON dp_rel.demanda_id = dp.id
WHERE p.id = :pedido_id;

-- Uma demanda pode ter múltiplos pedidos
SELECT
    dp.demanda_id,
    dp.descricao,
    p.numero_pedido,
    p.origem,
    p.is_flex
FROM demandas_producao dp
JOIN demandas_pedidos dp_rel ON dp.id = dp_rel.demanda_id
JOIN pedidos p ON dp_rel.pedido_id = p.id
WHERE dp.id = :demanda_id;
```

---

### 4. Acompanhamento e Monitoramento

#### `entrega_producao`

Registro de entregas/coletas parciais de uma demanda.

| Coluna | Tipo | Nullable | Descrição |
|--------|------|----------|-----------|
| `id` | text | NO | PK (UUID) |
| `demanda_id` | integer | NO | FK → demandas_producao.id |
| `item_demanda_id` | integer | YES | FK → itens_demanda.id |
| `quantidade` | integer | NO | Quantidade da entrega |
| `data_entrega` | date | NO | Data da entrega |
| `user_id` | text | YES | Usuário que registrou |

**Regra de Conclusão:**

```sql
-- Demanda é CONCLUÍDA quando:
SELECT 
    demanda_id,
    SUM(quantidade) as total_coletado
FROM entrega_producao
GROUP BY demanda_id
HAVING SUM(quantidade) >= (
    SELECT quantidade FROM demandas_producao WHERE id = :demanda_id
);

-- Atualização do status:
UPDATE demandas_producao
SET status = 'CONCLUIDO', data_conclusao = NOW()
WHERE id = :demanda_id
  AND (SELECT SUM(quantidade) FROM entrega_producao WHERE demanda_id = :demanda_id) >= quantidade;
```

---

#### `alertas_demanda`

Alertas gerados para demandas (ex: estoque insuficiente, produção atrasada).

| Coluna | Tipo | Nullable | Descrição |
|--------|------|----------|-----------|
| `id` | integer | NO | PK |
| `demanda_id` | integer | NO | FK → demandas_producao.id |
| `tipo_alerta` | varchar(50) | NO | Tipo do alerta |
| `severidade` | varchar(20) | NO | `INFO`, `ATENCAO`, `CRITICO` |
| `titulo` | varchar(100) | NO | Título do alerta |
| `mensagem` | text | NO | Mensagem detalhada |
| `dados_impacto` | jsonb | YES | Dados de impacto |
| `requer_acao` | boolean | YES | Se requer ação |
| `resolvido` | boolean | YES | Status de resolução |
| `resolvido_em` | timestamptz | YES | Data de resolução |
| `resolvido_por` | integer | YES | FK → usuarios.id |

---

#### `sinalizacoes_demanda`

Sinalizações visuais para demandas (ex: FLEX, HORARIO_CORTE_PROXIMO).

| Coluna | Tipo | Nullable | Descrição |
|--------|------|----------|-----------|
| `id` | integer | NO | PK |
| `demanda_id` | integer | NO | FK → demandas_producao.id |
| `tipo` | varchar(50) | NO | `FLEX`, `FULFILLMENT`, `HORARIO_CORTE_PROXIMO`, etc. |
| `severidade` | varchar(20) | NO | `INFO`, `ATENCAO`, `CRITICO` |
| `dados` | jsonb | YES | Dados adicionais |
| `visivel` | boolean | YES | Se está visível |
| `lido` | boolean | YES | Se foi lido |

**Tipos de Sinalização:**

| Tipo | Severidade | Gatilho |
|------|------------|---------|
| `FLEX` | INFO/ATENCAO | is_flex = true |
| `FULFILLMENT` | INFO | fulfillment = true |
| `HORARIO_CORTE_PROXIMO` | ATENCAO | horario_coleta em < 2 horas |
| `ESTOQUE_INSUFICIENTE` | CRITICO | Saldo estoque < quantidade demanda |
| `PRODUCAO_ATRASADA` | CRITICO | data_entrega < hoje AND status != CONCLUIDO |

---

### 5. Tabelas Auxiliares

#### `demandas_item_origem`

Rastreabilidade de qual pedido originou cada item da demanda (legado, substituído por `demandas_pedidos`).

| Coluna | Tipo | Nullable | Descrição |
|--------|------|----------|-----------|
| `id` | integer | NO | PK |
| `demanda_item_id` | integer | NO | FK → itens_demanda.id |
| `plataforma` | varchar(50) | NO | Plataforma de origem |
| `pedido_externo_id` | varchar(255) | NO | ID do pedido externo |
| `item_externo_id` | varchar(255) | YES | ID do item externo |
| `sku_externo` | varchar(255) | NO | SKU externo |
| `quantidade_atendida` | integer | NO | Quantidade atendida |

---

#### `previsao_consumo_demanda`

Previsão de consumo de produtos para demandas.

| Coluna | Tipo | Nullable | Descrição |
|--------|------|----------|-----------|
| `id` | uuid | NO | PK |
| `demanda_id` | integer | NO | FK → demandas_producao.id |
| `produto_id` | bigint | NO | FK → produtos.id |
| `quantidade_prevista` | numeric | NO | Quantidade prevista |
| `unidade` | text | YES | Unidade de medida |
| `status` | text | YES | Status da previsão |

---

#### `demanda_estoque_processado`

Processamento de estoque por demanda (event sourcing).

| Coluna | Tipo | Nullable | Descrição |
|--------|------|----------|-----------|
| `id` | uuid | NO | PK |
| `item_id` | integer | NO | FK → itens_demanda.id |
| `demanda_id` | integer | NO | FK → demandas_producao.id |
| `estagio` | varchar(50) | NO | Estágio do processamento |
| `quantidade` | numeric | NO | Quantidade |
| `saldo_acumulado` | numeric | NO | Saldo acumulado |
| `tipo_movimentacao` | varchar(50) | NO | Tipo de movimentação |
| `produto_id` | integer | YES | FK → produtos.id |
| `usuario_id` | integer | YES | FK → usuarios.id |
| `correlation_id` | varchar(100) | YES | ID de correlação |
| `metadata` | jsonb | YES | Metadados |

---

### 6. Fluxo Completo: Webhook → Pedido → Demanda → Dashboard

---

## Fluxo Completo de Geração de Demanda

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    FLUXO COMPLETO DE GERAÇÃO DE DEMANDA                         │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  1. IMPORTAÇÃO DE PEDIDOS                                                       │
│  ─────────────────────────────                                                  │
│     ┌──────────────────────────────────────────┐                                │
│     │  Webhook Bling/Shopee                    │                                │
│     │         ↓                                │                                │
│     │  n8n (valida HMAC, responde 202)         │                                │
│     │         ↓                                │                                │
│     │  Redis (fila: bling:webhooks:pendentes)  │                                │
│     │         ↓                                │                                │
│     │  Worker (consome via Celery)             │                                │
│     │         ↓                                │                                │
│     │  bling_order_processing_service          │                                │
│     │         ↓                                │                                │
│     │  pedidos (upsert)                        │                                │
│     │  vinculos_integracao_pedido (insert)     │                                │
│     └──────────────────────────────────────────┘                                │
│                                                                                 │
│  2. CONSOLIDAÇÃO (Automática ou Planilha)                                       │
│  ─────────────────────────────────────────                                      │
│     ┌──────────────────────────────────────────┐                                │
│     │  Trigger automático ou upload planilha   │                                │
│     │         ↓                                │                                │
│     │  Filtros de agrupamento:                 │                                │
│     │  • Mesmo produto/miolo                   │                                │
│     │  • Mesma data de entrega                 │                                │
│     │  • Mesma plataforma + modalidade         │                                │
│     │  • Mesma janela de coleta                │                                │
│     │         ↓                                │                                │
│     │  Agrupamento por:                        │                                │
│     │  - Produto                               │                                │
│     │  - Miolo                                 │                                │
│     │  - Data de entrega                       │                                │
│     │  - Canal + Modalidade                    │                                │
│     └──────────────────────────────────────────┘                                │
│                                                                                 │
│  3. GERAÇÃO DE DEMANDA                                                          │
│  ───────────────────────                                                        │
│     ┌──────────────────────────────────────────┐                                │
│     │  demanda_service.criar_demanda()         │                                │
│     │         ↓                                │                                │
│     │  demandas_producao (insert)              │                                │
│     │  itens_demanda (insert)                  │                                │
│     │  demandas_pedidos (insert N:N)           │                                │
│     │         ↓                                │                                │
│     │  Snapshots capturados:                   │                                │
│     │  - channel_snapshot (flex, fulfillment)  │                                │
│     │  - horario_coleta                        │                                │
│     │  - modalidade_logistica                  │                                │
│     │  - is_flex                               │                                │
│     └──────────────────────────────────────────┘                                │
│                                                                                 │
│  4. ORDENAÇÃO PARA PRODUÇÃO                                                     │
│  ──────────────────────────────                                                 │
│     ┌──────────────────────────────────────────┐                                │
│     │  Critérios de ordenação:                 │                                │
│     │  1. is_flex = TRUE                       │                                │
│     │  2. modalidade = EXPRESS                 │                                │
│     │  3. horario_coleta (mais próximo)        │                                │
│     │  4. prioridade_calculada (score)         │                                │
│     │  5. data_entrega (mais próxima)          │                                │
│     │         ↓                                │                                │
│     │  Dashboard exibe demandas ordenadas      │                                │
│     └──────────────────────────────────────────┘                                │
│                                                                                 │
│  5. ACOMPANHAMENTO NO DASHBOARD                                                 │
│  ─────────────────────────────                                                  │
│     ┌──────────────────────────────────────────┐                                │
│     │  Usuário atualiza status                 │                                │
│     │         ↓                                │                                │
│     │  itens_demanda.status_item               │                                │
│     │  itens_demanda.capas_*_qtd               │                                │
│     │  itens_demanda.miolos_*_qtd              │                                │
│     │         ↓                                │                                │
│     │  entrega_producao (registro parcial)     │                                │
│     │         ↓                                │                                │
│     │  Verificação automática:                 │                                │
│     │  SUM(entrega) >= demanda.quantidade      │                                │
│     │         ↓                                │                                │
│     │  demandas_producao.status = CONCLUIDO    │                                │
│     └──────────────────────────────────────────┘                                │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Regras de Negócio Operacionais

### 1. Priorização para Produção

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    PRIORIDADE DE PRODUÇÃO                                       │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  PRIORIDADE = f(is_flex, modalidade_logistica, horario_coleta, data_entrega)    │
│                                                                                 │
│  ORDEM DE PRIORIDADE (em ordem decrescente):                                    │
│  ─────────────────────────────────────────                                      │
│                                                                                 │
│  1. is_flex = TRUE (Entrega Rápida/Urgente)                                     │
│     → Coleta no mesmo dia, prioridade máxima                                    │
│                                                                                 │
│  2. modalidade_logistica = EXPRESS                                                │
│     → Entrega expressa, prioridade alta                                         │
│                                                                                 │
│  3. horario_coleta mais próximo                                                   │
│     → Ordenação por tempo real até coleta                                       │
│                                                                                 │
│  4. prioridade_calculada (score)                                                  │
│     → Score baseado em regras configuráveis                                     │
│                                                                                 │
│  5. data_entrega mais próxima                                                     │
│     → Deadline de entrega                                                       │
│                                                                                 │
│  6. modalidade_logistica = STANDARD                                               │
│     → Envio padrão, prioridade normal                                           │
│                                                                                 │
│  7. modalidade_logistica = RETIRADA                                               │
│     → Retirada no balcão, prioridade baixa                                      │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

### 2. Consolidação de Pedidos em Demandas

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    REGRAS DE CONSOLIDAÇÃO                                       │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ✅ AGRUPAR (mesma demanda) quando TODOS os critérios abaixo forem atendidos:   │
│  ───────────────────────────────────────────────────────────────────────────    │
│                                                                                 │
│  • Mesmo produto (ou produto equivalente)                                       │
│  • Mesmo miolo (componente principal)                                           │
│  • Mesma data de entrega (ou janela de 24h)                                     │
│  • Mesma plataforma + modalidade (ex: Shopee+Flex)                              │
│  • Mesma janela de coleta (<4h de diferença)                                    │
│  • Mesmo canal de venda (configurável por canal)                                │
│                                                                                 │
│  ❌ NÃO AGRUPAR (demandas separadas) quando QUALQUER critério abaixo:           │
│  ──────────────────────────────────────────────────────────────────────────     │
│                                                                                 │
│  • Modalidades diferentes (Flex ≠ Normal)                                       │
│  • Janelas de coleta muito distantes (>4h)                                      │
│  • Produtos incompatíveis (linhas de produção diferentes)                       │
│  • Pedido urgente isolado (não compensa agrupar)                                │
│  • Configuração específica do canal proíbe agrupamento                          │
│                                                                                 │
│  RELACIONAMENTO N:N:                                                            │
│  ───────────────────                                                            │
│  • Um pedido pode gerar itens em múltiplas demandas                             │
│  • Uma demanda pode consolidar itens de múltiplos pedidos                       │
│  • demandas_pedidos rastreia essa relação                                       │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

### 3. Channel Snapshot (Captura no Momento da Criação)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    CHANNEL SNAPSHOT                                             │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  O QUE É CAPTURADO NO MOMENTO DA CRIAÇÃO DA DEMANDA:                            │
│  ─────────────────────────────────────────────────────                          │
│                                                                                 │
│  • is_flex, fulfillment: herdados do canal                                      │
│  • horario_coleta: copiado do canal                                             │
│  • modalidade_logistica: derivada das regras do canal                           │
│  • channel_snapshot: JSON completo com estado do canal                          │
│                                                                                 │
│  REGRA DE OURO: NUNCA ATUALIZAR RETROATIVAMENTE                                 │
│  ─────────────────────────────────────────────                                  │
│                                                                                 │
│  • Pedidos históricos mantêm características originais                          │
│  • Mudanças no canal NÃO afetam demandas já criadas                            │
│  • Auditoria completa do estado no momento da criação                           │
│                                                                                 │
│  JUSTIFICATIVA OPERACIONAL:                                                     │
│  ───────────────────────────────                                                │
│  • Fábrica já produziu com base nas regras vigentes                             │
│  • Alteração retroativa causaria confusão operacional                           │
│  • Rastreabilidade completa do "porquê" aquela demanda foi criada assim         │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

### 4. Status de Demanda e Transições

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    FLUXO DE STATUS DE DEMANDA                                   │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  FLUXO PRINCIPAL:                                                               │
│  ──────────────                                                                 │
│                                                                                 │
│    AGUARDANDO ──▶ EM_PRODUCAO ──▶ COLETA_PARCIAL ──▶ CONCLUIDO                 │
│         │                                                                     │
│         └────────────────────────────────────────▶ CANCELADO                    │
│                                                                                 │
│  TRANSIÇÕES PERMITIDAS:                                                         │
│  ──────────────────────                                                         │
│                                                                                 │
│  • AGUARDANDO → EM_PRODUCAO: Início da produção (usuário ou automático)         │
│  • EM_PRODUCAO → COLETA_PARCIAL: Primeira coleta registrada                     │
│  • COLETA_PARCIAL → CONCLUIDO: Todas as coletas completas                       │
│  • QUALQUER → CANCELADO: Cancelamento manual (com justificativa)                │
│                                                                                 │
│  STATUS DOS ITENS (itens_demanda.status_item):                                  │
│  ─────────────────────────────────────────────                                  │
│                                                                                 │
│  • PENDENTE: Item ainda não iniciado                                            │
│  • PROCESSANDO: Item em produção                                                │
│  • CONCLUIDO: Item finalizado e pronto para coleta                              │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Índices de Performance

```sql
-- Demandas
CREATE INDEX idx_demandas_producao_status ON demandas_producao(status);
CREATE INDEX idx_demandas_producao_canal ON demandas_producao(canal_venda_id);
CREATE INDEX idx_demandas_producao_data ON demandas_producao(data_entrega);
CREATE INDEX idx_demandas_producao_categoria ON demandas_producao(categoria_temporal);

-- Itens de Demanda
CREATE INDEX idx_itens_demanda_demanda ON itens_demanda(demanda_id);
CREATE INDEX idx_itens_demanda_produto ON itens_demanda(produto_id);
CREATE INDEX idx_itens_demanda_status ON itens_demanda(status_item);

-- Relacionamento N:N
CREATE INDEX idx_demandas_pedidos_demanda ON demandas_pedidos(demanda_id);
CREATE INDEX idx_demandas_pedidos_pedido ON demandas_pedidos(pedido_id);
CREATE UNIQUE INDEX idx_demandas_pedidos_unique ON demandas_pedidos(demanda_id, pedido_id);

-- Pedidos
CREATE INDEX idx_pedidos_canal ON pedidos(canal_venda_id);
CREATE INDEX idx_pedidos_flex ON pedidos(is_flex);
CREATE INDEX idx_pedidos_data_limite ON pedidos(data_limite_envio);
```

---

## Views e Funções Utilitárias

```sql
-- Verificar se pedido tem demanda
SELECT pedido_tem_demanda(:pedido_id);

-- Buscar demandas de um pedido (JSON)
SELECT get_demandas_do_pedido(:pedido_id);

-- Buscar pedidos de uma demanda (JSON)
SELECT get_pedidos_da_demanda(:demanda_id);

-- Canais próximos de coleta (filtro contextual)
SELECT * FROM fn_canais_proximos_coleta();

-- Contagem de pedidos por canal
SELECT * FROM fn_contar_pedidos_por_canal();
```

---

## Referências

### Documentação Relacionada

| Documento | Descrição |
|-----------|-----------|
| [`ARQUITETURA-SISTEMA.md`](./ARQUITETURA-SISTEMA.md) | Arquitetura geral do sistema |
| [`CONTEXTO_PRODUCAO_UX.md`](./CONTEXTO_PRODUCAO_UX.md) | Contexto de produção e otimização de UX |
| [`REFACTORING-SUMMARY.md`](./REFACTORING-SUMMARY.md) | Resumo da refatoração |
| [`docs/02-features/analise_fluxo_pedido_demanda.md`](./02-features/analise_fluxo_pedido_demanda.md) | Análise do fluxo pedido → demanda |
| [`docs/02-features/webhooks_fluxo_correto.md`](./02-features/webhooks_fluxo_correto.md) | Fluxo correto de webhooks |

### Migrations do Banco de Dados

| Migration | Descrição |
|-----------|-----------|
| `20260324000002_demandas_pedidos_pivot.sql` | Tabela N:N demandas_pedidos |
| `20260328000000_normalize_demand_status.sql` | Normalização de status |
| `20260329000004_contexto_producao_ux.sql` | Contexto de produção e UX |
| `20260401000000_consolidate_catalog.sql` | Consolidação do catálogo de integrações |
| `20260401000001_channel_connections.sql` | Channel connections (nova arquitetura) |

### Código Fonte

| Arquivo | Descrição |
|---------|-----------|
| `packages/shared/nistiprint_shared/models/demanda_producao.py` | Models Python de demandas |
| `packages/shared/nistiprint_shared/services/demanda_producao_service.py` | Service de demandas |
| `packages/shared/nistiprint_shared/services/order_service.py` | Service de pedidos |
| `packages/shared/nistiprint_shared/services/bling_order_processing_service.py` | Processamento de pedidos Bling |
| `apps/frontend/src/types/producao.ts` | Types TypeScript de produção |

---

**Última atualização:** 2026-04-02  
**Autor:** Equipe Nistiprint  
**Status:** Documento operacional completo
