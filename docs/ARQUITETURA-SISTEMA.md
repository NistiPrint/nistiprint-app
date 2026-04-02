# Arquitetura do Sistema - Nistiprint

> **Nota:** Para documentação detalhada do modelo ER de demandas de produção, incluindo fluxo operacional da fábrica e regras de consolidação, consulte:
> - [`LEVANTAMENTO-ER-DEMANDAS.md`](./LEVANTAMENTO-ER-DEMANDAS.md) - Modelo ER completo com foco operacional
> - [`CONTEXTO_PRODUCAO_UX.md`](./CONTEXTO_PRODUCAO_UX.md) - Contexto de produção e otimização de UX

## Visão Geral

O sistema Nistiprint segue uma **arquitetura de microsserviços** com os seguintes componentes principais:

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Frontend   │────▶│     API     │────▶│    Redis    │
│   (React)   │     │   (Flask)   │     │   (Broker)  │
└─────────────┘     └─────────────┘     └──────┬──────┘
                                               │
                                               ▼
┌─────────────┐                         ┌─────────────┐
│   Supabase  │◀────────────────────────│   Worker    │
│  (PostgreSQL│                         │  (Celery)   │
└─────────────┘                         └─────────────┘
```

### Componentes

| Componente | Tecnologia | Função |
|------------|------------|--------|
| Frontend | React + TypeScript | Interface do usuário |
| API | Flask (Python) | endpoints REST |
| Worker | Celery + Redis | Processamento assíncrono |
| Banco de Dados | Supabase (PostgreSQL) | Armazenamento persistente |

---

## 1. Plataformas

### Definição

Uma **plataforma** representa um sistema externo que se integra ao Nistiprint para troca de dados de pedidos, produtos e clientes.

### Modelo de Dados

**Tabela:** `plataformas`  
**Model:** `packages/shared/nistiprint_shared/models/plataforma.py`  
**Service:** `packages/shared/nistiprint_shared/services/plataforma_service.py`

```sql
CREATE TABLE plataformas (
    id integer PRIMARY KEY,
    nome varchar(100) NOT NULL UNIQUE,
    descricao text,
    tipo varchar(50),           -- MARKETPLACE, ERP, ECOMMERCE
    ativa boolean DEFAULT true,
    configuracao jsonb,         -- Config específica da plataforma
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);
```

### Tipos de Plataforma

| Tipo | Descrição | Exemplos |
|------|-----------|----------|
| `MARKETPLACE` | Plataformas de venda online | Shopee, Mercado Livre, Amazon, Shein |
| `ERP` | Sistema de gestão empresarial | Bling |
| `ECOMMERCE` | Loja virtual própria | N/A (futuro) |

### Plataformas Suportadas

| Plataforma | Tipo | Driver |
|------------|------|--------|
| Shopee | MARKETPLACE | `platform_drivers/shopee.py` |
| Mercado Livre | MARKETPLACE | `platform_drivers/mercadolivre.py` |
| Amazon | MARKETPLACE | `platform_drivers/amazon.py` |
| Shein | MARKETPLACE | `platform_drivers/shein.py` |
| Bling | ERP | `bling/bling_client.py` |

---

## 2. Canais de Venda

### Definição

Um **canal de venda** é uma instância específica de uma plataforma. Por exemplo, uma conta Shopee específica ou uma loja específica dentro do Bling.

### Modelo de Dados

**Tabela:** `canais_venda`  
**Model:** `packages/shared/nistiprint_shared/models/canal_venda.py`  
**Service:** `packages/shared/nistiprint_shared/services/canal_venda_service.py`

```sql
CREATE TABLE canais_venda (
    id integer PRIMARY KEY,
    nome varchar(100) NOT NULL UNIQUE,
    plataforma_id integer REFERENCES plataformas(id),
    descricao text,
    configuracao jsonb,
    ativo boolean DEFAULT true,
    slug varchar(100),
    
    -- Vínculo com ERP
    conta_bling_id varchar(255),    -- ID da conta Bling vinculada
    
    -- Logística
    horario_coleta time,            -- Horário de coleta definido
    
    -- ✅ ATRIBUTOS ESPECIAIS
    flex boolean DEFAULT false,         -- Entrega Rápida / Flexível
    fulfillment boolean DEFAULT false,  -- Serviço de Fulfillment Externo
    
    -- UI
    color varchar(7) DEFAULT '#007bff', -- Cor para identificação visual
    
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);
```

### Atributos Especiais

#### `flex` (Entrega Rápida)

Indica se o canal suporta **entrega flexível/urgente**.

- **Quando `true`**: Pedidos deste canal têm prioridade logística
- **Exemplo de uso**: Entrega Rápida Shopee
- **Impacto**: 
  - Filtros contextuais na UI destacam canais flex
  - Pedidos recebem badge "FLEX"
  - Prioridade na fila de produção

#### `fulfillment` (Fulfillment Externo)

Indica se o canal usa **serviço de fulfillment externo**.

- **Quando `true`**: Pedidos são enviados para armazém externo
- **Impacto**:
  - Modalidade logística `FULFILLMENT`
  - Regras de expedição específicas
  - Classificação como demanda do tipo `FULFILLMENT`

### Tipos TypeScript (Frontend)

```typescript
// apps/frontend/src/types/producao.ts
interface CanalVenda {
  id: number;
  nome: string;
  plataforma_id: number | null;
  descricao: string | null;
  configuracao: Record<string, unknown> | null;
  ativo: boolean;
  slug: string | null;
  conta_bling_id: string | null;
  horario_coleta: string | null;
  flex: boolean;        // ✅ Atributo Flex
  fulfillment: boolean; // ✅ Atributo Full/Fulfillment
  color: string;
  created_at: string;
  updated_at: string;
}
```

---

## 3. Integrações

### Arquitetura de Integrações

O sistema possui um **Integration Store** que gerencia conectores com plataformas externas.

```
┌─────────────────────┐
│  Integration Module │  ← Catálogo de conectores disponíveis
│  (integration_      │     ex: 'shopee', 'amazon', 'mercadolivre'
│   modules)          │
└─────────┬───────────┘
          │ instala
          ▼
┌─────────────────────┐
│ Installed           │  ← Instância ativa de integração
│ Integration         │     com tokens e configuração
│ (installed_         │
│  integrations)      │
└─────────┬───────────┘
          │ vincula
          ▼
┌─────────────────────┐
│ Integracao Canais   │  ← Mapeia canal → integração → loja Bling
│ Config              │
│ (integracao_canais_ │
│  config)            │
└─────────────────────┘
```

### 3.1 Módulos de Integração (Catálogo)

**Tabela:** `integration_modules`  
**Model:** `packages/shared/nistiprint_shared/models/integration_module.py`

```sql
CREATE TABLE integration_modules (
    id text PRIMARY KEY,          -- ex: 'shopee', 'amazon', 'mercadolivre'
    name text NOT NULL,
    description text,
    version text,
    author text,
    icon_url text,
    category text,
    tags text[],
    is_active boolean DEFAULT true,
    
    -- Configuração
    config_schema jsonb,          -- Schema de configuração (JSON Schema)
    auth_flow text,               -- OAuth2, API_KEY, etc.
    auth_config jsonb,
    
    -- Mapeamento de dados
    data_mapping_spec jsonb,
    
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);
```

### 3.2 Integrações Instaladas

**Tabela:** `installed_integrations`  
**Model:** `packages/shared/nistiprint_shared/models/installed_integration.py`  
**Service:** `packages/shared/nistiprint_shared/services/installed_integration_service.py`

```sql
CREATE TABLE installed_integrations (
    id integer PRIMARY KEY,
    module_id varchar(100) NOT NULL,    -- Referência ao módulo
    instance_name varchar(255) NOT NULL, -- Nome da instância
    user_id varchar(255),
    config jsonb DEFAULT '{}',
    
    -- Autenticação
    access_token text,
    refresh_token text,
    expires_at timestamp with time zone,
    
    -- Status
    is_active boolean DEFAULT true,
    last_sync timestamp with time zone,
    sync_status varchar(50) DEFAULT 'pending',
    
    -- Credenciais
    credentials jsonb DEFAULT '{}',
    last_refresh_attempt timestamp with time zone,
    refresh_error text,
    
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);
```

### 3.3 Vínculos entre Canais e Integrações

**Tabela:** `integracao_canais_config`
**Service:** `packages/shared/nistiprint_shared/services/integracao_canal_service.py`
**Controller:** `apps/api/routes/integracao_canais.py`

Esta tabela mapeia qual canal de venda está vinculado a qual:
- Loja Bling (`bling_loja_id`)
- Instância de integração (`integration_id`)
- Plataforma (`plataforma_nome`)

```sql
-- Estrutura conceitual (pode variar)
CREATE TABLE integracao_canais_config (
    id integer PRIMARY KEY,
    canal_venda_id integer REFERENCES canais_venda(id),
    bling_loja_id varchar(255),
    integration_id integer REFERENCES installed_integrations(id),
    plataforma_nome varchar(100),
    configuracao jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);
```

### 3.4 Resolução de Canal no Webhook (Bling → Canal)

**Problema:** Quando o Bling envia um webhook com um pedido, ele inclui apenas `numeroLoja` (ID da loja Bling). O sistema precisa resolver qual `canal_venda_id` pertence a essa loja.

**Fluxo de Resolução:**

```
┌─────────────────────────────────────────────────────────────────┐
│                    RESOLUÇÃO: bling_loja_id → canal_venda_id    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. Webhook Bling chega com:                                    │
│     • numeroLoja = "204047801"                                  │
│     • pedido = {...}                                            │
│                                                                 │
│  2. Buscar em channel_connections:                              │
│     SELECT channel_id                                           │
│     FROM channel_connections                                    │
│     WHERE aggregator_store_id = '204047801'                     │
│       AND is_active = true                                      │
│                                                                 │
│  3. Seguir FK para canais_venda:                                │
│     SELECT * FROM canais_venda WHERE id = {channel_id}          │
│                                                                 │
│  4. Resultado:                                                  │
│     • canal_venda_id = 1                                        │
│     • canal_nome = "Shopee - CNPJ 01"                           │
│     • flex = true                                               │
│     • horario_coleta = "14:00"                                  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Service:** `packages/shared/nistiprint_shared/services/canal_venda_service.py`

```python
def resolve_canal_from_bling_store(self, bling_loja_id: str):
    """
    Resolve canal de venda a partir de uma loja Bling.
    
    FLUXO DE RESOLUÇÃO:
    1. Buscar em channel_connections.aggregator_store_id = bling_loja_id
    2. Seguir FK para channel_connections.channel_id → canais_venda.id
    3. Retornar dados do canal
    """
```

**Tratamento de Ambiguidade:**

Se múltiplos canais forem encontrados para a mesma `bling_loja_id`:
- Logar erro com lista de canais conflitantes
- Usar primeiro resultado (fallback)
- **Recomendado:** Intervenção manual para corrigir vínculo

**Tabela Utilizada:** `channel_connections` (nova arquitetura, substitui `integracao_canais_config`)

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | uuid | PK |
| `channel_id` | integer | FK → canais_venda.id |
| `integration_id` | integer | FK → installed_integrations.id |
| `aggregator_store_id` | varchar(255) | Loja no agregador (ex: bling_loja_id) |
| `aggregator_store_name` | varchar(255) | Nome amigável da loja |
| `is_active` | boolean | Status do vínculo |

### 3.5 Platform Drivers (Conectores Específicos)

**Pasta:** `packages/shared/nistiprint_shared/services/platform_drivers/`

| Arquivo | Plataforma | Função |
|---------|------------|--------|
| `shopee.py` | Shopee | Busca pedidos, atualiza status |
| `amazon.py` | Amazon | Busca pedidos, atualiza status |
| `mercadolivre.py` | Mercado Livre | Busca pedidos, atualiza status |
| `shein.py` | Shein | Busca pedidos, atualiza status |
| `tiktok.py` | TikTok | Busca pedidos, atualiza status |

### 3.6 Bling Client

**Pasta:** `packages/shared/nistiprint_shared/services/bling/`

| Arquivo | Função |
|---------|--------|
| `bling_client.py` | Cliente principal da API Bling |
| `bling_client_updated.py` | Versão atualizada do cliente |
| `bling.py` | Wrapper adicional |

O Bling é a **fonte primária de pedidos** do sistema. A integração com Bling:
- Busca pedidos de todas as plataformas conectadas ao Bling
- Normaliza dados para o formato canônico
- Atualiza status de envio no Bling

---

## 4. Pedidos

### Arquitetura Core Order + Integration Links

O sistema utiliza uma arquitetura de **dois níveis** para pedidos:

```
┌─────────────────────────────────────────────────────────┐
│                    PEDIDO CORE                          │
│  (tabela: pedidos)                                      │
│  • Dados normalizados e operacionais                    │
│  • payload_canonico (formato padrão)                    │
│  • Informações do cliente desnormalizadas               │
│  • Vínculo com canal_venda_id                           │
└─────────────────────────────────────────────────────────┘
                          │
                          │ (1:N)
                          ▼
┌─────────────────────────────────────────────────────────┐
│              VÍNCULOS DE INTEGRAÇÃO                     │
│  (tabela: vinculos_integracao_pedido)                   │
│  • Links para plataformas externas                      │
│  • Dados brutos (payload original)                      │
│  • Status na plataforma externa                         │
│  • Um pedido pode ter múltiplos vínculos:               │
│    - Vínculo Bling (fonte primária)                     │
│    - Vínculo Shopee (plataforma de origem)              │
│    - Vínculo Mercado Livre (se multi-canal)             │
└─────────────────────────────────────────────────────────┘
```

### 4.1 Tabela Core de Pedidos

**Tabela:** `pedidos`  
**Model:** `packages/shared/nistiprint_shared/models/pedido.py`  
**Service:** `packages/shared/nistiprint_shared/services/order_service.py`

```sql
CREATE TABLE pedidos (
    id integer PRIMARY KEY,
    uuid_pedido varchar(36) UNIQUE NOT NULL,  -- ID universal único
    numero_pedido varchar(50) UNIQUE NOT NULL, -- ID amigável
    codigo_pedido_externo varchar(100),       -- ID na Shopee/Bling
    
    -- Origem
    origem varchar(50) NOT NULL,              -- 'SHOPEE', 'BLING', 'MANUAL'
    
    -- Dados do cliente (desnormalizados para performance)
    cliente_nome varchar(255),
    cliente_documento varchar(50),
    cliente_telefone varchar(50),
    cliente_email varchar(255),
    informacoes_cliente jsonb,
    
    -- Status e valores
    situacao_pedido_id integer REFERENCES situacoes_pedido(id),
    total_pedido numeric(15,2),
    moeda varchar(10) DEFAULT 'BRL',
    data_venda timestamp,
    
    -- Logística
    canal_venda_id integer REFERENCES canais_venda(id),
    is_flex boolean DEFAULT false,            -- Herda do canal
    servico_logistico varchar(255),
    data_limite_envio timestamp,
    
    -- Controle
    payload_canonico jsonb,       -- Dados normalizados (formato padrão)
    
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);
```

### 4.2 Itens do Pedido

**Tabela:** `itens_pedido`  
**Model:** `packages/shared/nistiprint_shared/models/pedido.py` (classe `ItemPedido`)

```sql
CREATE TABLE itens_pedido (
    id integer PRIMARY KEY,
    pedido_id integer REFERENCES pedidos(id),
    produto_id integer REFERENCES produtos(id),
    sku_externo varchar(100),
    descricao varchar(500),
    quantidade numeric(10,4),
    preco_unitario numeric(15,2),
    subtotal numeric(15,2),
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);
```

### 4.3 Vínculos de Integração de Pedidos

**Tabela:** `vinculos_integracao_pedido`

```sql
CREATE TABLE vinculos_integracao_pedido (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    pedido_id integer NOT NULL REFERENCES pedidos(id),
    plataforma varchar(50) NOT NULL,      -- 'BLING', 'SHOPEE', etc.
    id_na_plataforma varchar(100) NOT NULL, -- ID externo
    status_na_plataforma varchar(50),
    dados_brutos jsonb,                   -- Payload original da API
    last_synced_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now()
);

-- Índice para busca rápida por plataforma + ID
CREATE INDEX idx_vinculos_plataforma_id 
ON vinculos_integracao_pedido(plataforma, id_na_plataforma);
```

### 4.4 Eventos/Timeline de Pedidos

**Tabela:** `eventos_pedido`

Registra todas as transições de status e eventos do pedido:

```sql
CREATE TABLE eventos_pedido (
    id integer PRIMARY KEY,
    pedido_id integer REFERENCES pedidos(id),
    tipo_evento varchar(50),      -- 'STATUS_CHANGE', 'SYNC', 'IMPORT', etc.
    descricao text,
    dados_evento jsonb,
    created_at timestamp with time zone DEFAULT now()
);
```

### 4.5 Mappers de Pedido

**Arquivo:** `packages/shared/nistiprint_shared/mappers/order_mappers.py`

Responsável por converter payloads de diferentes plataformas para o **formato canônico**:

```
Shopee Payload ─────┐
                    │
Mercado Livre ──────┼──▶ order_mappers.py ──▶ payload_canonico
                    │
Bling ──────────────┘
```

---

## 5. Demandas de Produção

> **Importante:** Para documentação completa do fluxo operacional, regras de consolidação e modelo ER detalhado, consulte [`LEVANTAMENTO-ER-DEMANDAS.md`](./LEVANTAMENTO-ER-DEMANDAS.md).

### Definição

Uma **demanda de produção** é uma ordem de fabricação gerada a partir de pedidos ou outras necessidades (reposição, B2B, etc.).

**Princípio Operacional:** A fábrica não produz "pedidos", produz "demandas consolidadas". Múltiplos pedidos são agrupados em uma única demanda quando compartilham produto, miolo, data de entrega e modalidade logística.

### Modelo de Dados

**Tabela:** `demandas_producao`  
**Model:** `packages/shared/nistiprint_shared/models/demanda_producao.py`  
**Service:** `packages/shared/nistiprint_shared/services/demanda_producao_service.py`

```sql
CREATE TABLE demandas_producao (
    id integer PRIMARY KEY,
    demanda_id varchar(255) UNIQUE NOT NULL,  -- ID original (Firestore)
    descricao text,
    produto_id integer REFERENCES produtos(id),
    quantidade integer,
    data_entrega date,
    prioridade integer DEFAULT 0,
    status varchar(50) DEFAULT 'AGUARDANDO',
    responsavel_id integer REFERENCES usuarios(id),
    
    -- Vínculos
    canal_venda_id integer REFERENCES canais_venda(id),
    horario_coleta time,
    
    -- Tipo e classificação
    tipo_demanda varchar(50),     -- 'PLATAFORMA', 'B2B', 'FULFILLMENT', 'ESTOQUE_INTERNO'
    modalidade_logistica varchar(20), -- 'STANDARD', 'EXPRESS', 'FULFILLMENT', 'RETIRADA'
    classificacao_cliente varchar(10),  -- 'B2C', 'B2B', 'INTERNO'
    
    -- Flags (herdados do canal)
    is_flex boolean DEFAULT false,
    fulfillment boolean DEFAULT false,
    
    -- Planejamento
    observacoes text,
    prioridade_manual integer DEFAULT 0,
    pedido_numero varchar(100),
    data_conclusao timestamp,
    data_limite_execucao date,
    setores_envolvidos jsonb,
    categoria_temporal text,    -- 'URGENTE', 'HOJE', 'AMANHA', 'FUTURO'
    
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);
```

### Tipos de Demanda

| Tipo | Descrição | Origem |
|------|-----------|--------|
| `PLATAFORMA` | Venda consolidada de marketplace | Pedido Shopee, ML, etc. |
| `B2B` | Venda corporativa | Pedido empresarial |
| `FULFILLMENT` | Reposição para fulfillment | Canal com `fulfillment=true` |
| `ESTOQUE_INTERNO` | Produção para estoque interno | Planejamento interno |

### Modalidades Logísticas

| Modalidade | Descrição |
|------------|-----------|
| `STANDARD` | Envio padrão |
| `EXPRESS` | Entrega expressa (Flex/Urgente) |
| `FULFILLMENT` | Armazém externo |
| `RETIRADA` | Retirada no local |

### Itens da Demanda

**Tabela:** `itens_demanda`

```sql
CREATE TABLE itens_demanda (
    id integer PRIMARY KEY,
    demanda_id integer REFERENCES demandas_producao(id),
    produto_id integer REFERENCES produtos(id),
    sku varchar(100),
    descricao varchar(500),
    quantidade integer,

    -- Controle de produção
    capas_impressas_qtd integer DEFAULT 0,
    capas_produzidas_qtd integer DEFAULT 0,
    capas_prontas_retirada_qtd integer DEFAULT 0,
    miolos_prontos_retirada_qtd integer DEFAULT 0,
    expedicao_capas_retiradas_qtd integer DEFAULT 0,
    expedicao_miolos_retirados_qtd integer DEFAULT 0,
    status_item varchar(50) DEFAULT 'Pendente',

    -- Miolo
    miolo_nome varchar(255),
    id_produto_miolo integer REFERENCES produtos(id),
    variacao varchar(255),

    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);
```

### Rastreabilidade: Vínculo Demandas ↔ Pedidos

**Tabela:** `demandas_pedidos` (tabela pivot N:N)

**Importante:** Esta tabela substitui o legado `demandas_item_origem` para rastreabilidade.

```sql
CREATE TABLE demandas_pedidos (
    id BIGSERIAL PRIMARY KEY,
    demanda_id BIGINT NOT NULL REFERENCES demandas_producao(id),
    pedido_id BIGINT NOT NULL REFERENCES pedidos(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    CONSTRAINT uq_demandas_pedidos_demanda_pedido UNIQUE (demanda_id, pedido_id)
);
```

**Função:** Permitir relacionamento N:N entre demandas e pedidos, possibilitando:
- Saber quais pedidos compõem uma demanda
- Saber a qual demanda um pedido pertence
- Rastreabilidade completa do fluxo Pedido → Demanda → Produção

**Funções Utilitárias (SQL):**

```sql
-- Verificar se pedido tem demanda
SELECT pedido_tem_demanda(123);  -- true/false

-- Buscar demandas de um pedido (JSON)
SELECT get_demandas_do_pedido(123);

-- Buscar pedidos de uma demanda (JSON)
SELECT get_pedidos_da_demanda(456);
```

**Migration:** `supabase/migrations/20260324000002_demandas_pedidos_pivot.sql`

---

## 6. Regras Logísticas por Canal

### Definição

Cada canal de venda pode ter **regras logísticas específicas** que definem horários de corte, pontos de coleta e prioridades.

### Modelo de Dados

**Tabela:** `regras_logisticas_canal`  
**Model:** `packages/shared/nistiprint_shared/models/regra_logistica.py`  
**Service:** `packages/shared/nistiprint_shared/services/regra_logistica_service.py`

```sql
CREATE TABLE regras_logisticas_canal (
    id integer PRIMARY KEY,
    canal_venda_id integer NOT NULL REFERENCES canais_venda(id),
    modalidade varchar(50) NOT NULL,   -- 'STANDARD', 'EXPRESS', 'FULFILLMENT', 'RETIRADA'
    tipo_envio varchar(50) NOT NULL,   -- 'COLETA_LOCAL', 'PONTO_COLETA'
    horario_limite time NOT NULL,      -- Horário de corte para despacho
    ponto_coleta_id integer REFERENCES pontos_coleta(id),
    prioridade_uso integer DEFAULT 1,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);
```

### Pontos de Coleta

**Tabela:** `pontos_coleta`

```sql
CREATE TABLE pontos_coleta (
    id integer PRIMARY KEY,
    nome varchar(255) NOT NULL,
    horario_corte_padrao time NOT NULL,
    endereco text,
    ativo boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);
```

---

## 7. Diagrama de Relacionamentos

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         RELACIONAMENTOS DO SISTEMA                      │
└─────────────────────────────────────────────────────────────────────────┘

┌──────────────┐
│  plataformas │
│              │
│  id (PK)     │
│  nome        │
│  tipo        │
└──────┬───────┘
       │ 1:N
       │
       ▼
┌──────────────────────────────────────────────────────────────────────┐
│                           canais_venda                                │
│                                                                      │
│  id (PK)                     ┌────────────────────────────────────┐  │
│  nome                        │   ATRIBUTOS ESPECIAIS              │  │
│  plataforma_id (FK)          │   • flex: boolean                  │  │
│  conta_bling_id              │   • fulfillment: boolean           │  │
│  horario_coleta              │   • color: string                  │  │
│  flex ───────────────────────┘                                    │  │
│  fulfillment ─────────────────────────────────────────────────────┘  │
└──────┬───────────────────────────────────────────────────────────────┘
       │ 1:N
       ├────────────────────────────────────────────────────┐
       │                                                    │
       ▼                                                    ▼
┌──────────────────────────┐                  ┌─────────────────────────┐
│    regras_logisticas_    │                  │    integracao_canais_   │
│         canal            │                  │         config          │
│                          │                  │                         │
│  canal_venda_id (FK)     │                  │  canal_venda_id (FK)    │
│  modalidade              │                  │  bling_loja_id          │
│  tipo_envio              │                  │  integration_id (FK)    │
│  horario_limite          │                  │  plataforma_nome        │
│  ponto_coleta_id (FK)    │                  └────────────┬────────────┘
└──────────┬─────────────┘                               │
           │                                             │
           ▼                                             ▼
┌──────────────────────────┐                  ┌─────────────────────────┐
│     pontos_coleta        │                  │  installed_integrations │
│                          │                  │                         │
│  id (PK)                 │                  │  id (PK)                │
│  nome                    │                  │  module_id              │
│  horario_corte_padrao    │                  │  access_token           │
│  endereco                │                  │  refresh_token          │
└──────────────────────────┘                  │  config                 │
                                              └──────────┬──────────────┘
                                                         │
                                                         │ referencia
                                                         ▼
                                              ┌─────────────────────────┐
                                              │   integration_modules   │
                                              │                         │
                                              │  id (PK)                │
                                              │  name                   │
                                              │  config_schema          │
                                              │  auth_flow              │
                                              │  data_mapping_spec      │
                                              └─────────────────────────┘


       │ 1:N
       ▼
┌──────────────────────────────────────────────────────────────────────┐
│                              pedidos                                 │
│                                                                      │
│  id (PK)                                                             │
│  uuid_pedido                                                         │
│  numero_pedido                                                       │
│  codigo_pedido_externo                                               │
│  origem                                                              │
│  canal_venda_id (FK) ─────────────────────────────────────────────┐  │
│  is_flex ─────────────────────────────────────────────────────────┼──┘
│  payload_canonico                                                 │
└──────┬─────────────────────────────────────────────────────────────┘
       │ 1:N
       ├───────────────────┬───────────────────┬───────────────────┐
       │                   │                   │                   │
       ▼                   ▼                   ▼                   ▼
┌─────────────┐   ┌─────────────────┐ ┌─────────────────┐ ┌─────────────┐
│ itens_pedido│   │vinculos_integ.  │ │  eventos_pedido │ │demandas_    │
│             │   │   _pedido       │ │                 │ │ producao    │
│ pedido_id   │   │                 │ │  pedido_id      │ │             │
│ produto_id  │   │  pedido_id (FK) │ │  tipo_evento    │ │             │
│ sku_externo │   │  plataforma     │ │  descricao      │ │  id (PK)    │
│ quantidade  │   │  id_na_plat.    │ │  dados_evento   │ │  demanda_id │
│ preco_unit. │   │  status_na_plat.│ │                 │ │  canal_venda│
│ subtotal    │   │  dados_brutos   │ │                 │ │  is_flex    │
└─────────────┘   └─────────────────┘ └─────────────────┘ │  fulfillment│
                                                          │  tipo_demanda│
                                                          │  modalidade_ │
                                                          │   logistica  │
                                                          └──────┬───────┘
                                                                 │ 1:N
                                                                 ▼
                                                          ┌─────────────┐
                                                          │itens_demanda│
                                                          │             │
                                                          │ demanda_id  │
                                                          │ produto_id  │
                                                          │ quantidade  │
                                                          │ status_item │
                                                          └─────────────┘
```

---

## 8. Fluxo de Dados

### 8.1 Fluxo de Importação de Pedidos

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    FLUXO DE IMPORTAÇÃO DE PEDIDOS                       │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  1. CAPTURA                                                             │
│     ┌─────────────┐    ┌─────────────┐                                 │
│     │   Webhook   │    │  Polling    │                                 │
│     │  (Shopee)   │    │  (Bling)    │                                 │
│     └──────┬──────┘    └──────┬──────┘                                 │
│            │                  │                                        │
│            └────────┬─────────┘                                        │
│                     ▼                                                  │
│            ┌─────────────────┐                                         │
│            │  Worker (Celery)│                                         │
│            └────────┬────────┘                                         │
│                                                                         │
│  2. PROCESSAMENTO (Worker)                                              │
│     ┌─────────────────────────────────────────────────────────────┐    │
│     │  tasks/pedidos_fetch_tasks.py                               │    │
│     │  tasks/consolidation_tasks.py                               │    │
│     │                                                             │    │
│     │  • BlingClient.create_client_for_platform()                 │    │
│     │  • order_service.upsert_order()                             │    │
│     │  • vinculos_integracao_pedido (registro)                    │    │
│     │  • order_mappers.py → payload_canonico                      │    │
│     └─────────────────────────────────────────────────────────────┘    │
│                                                                         │
│  3. ARMAZENAMENTO (Supabase)                                            │
│     ┌─────────────────────────────────────────────────────────────┐    │
│     │  • pedidos (core)                                           │    │
│     │  • itens_pedido                                             │    │
│     │  • vinculos_integracao_pedido (Bling, Shopee, etc.)         │    │
│     │  • eventos_pedido (timeline)                                │    │
│     └─────────────────────────────────────────────────────────────┘    │
│                                                                         │
│  4. GERAÇÃO DE DEMANDA                                                  │
│     ┌─────────────────────────────────────────────────────────────┐    │
│     │  • demandas_producao (se necessário)                        │    │
│     │  • itens_demanda                                            │    │
│     │  • demandas_pedidos (rastreabilidade N:N)                   │    │
│     └─────────────────────────────────────────────────────────────┘    │
│                                                                         │
│  5. CONSULTA (API → Frontend)                                           │
│     ┌─────────────────────────────────────────────────────────────┐    │
│     │  • /api/v2/pedidos                                          │    │
│     │  • /api/v2/pedidos/{id}                                     │    │
│     │  • /api/v2/pedidos/canais-proximos-coleta                   │    │
│     │  • /api/v2/pedidos/contagem-por-canal                       │    │
│     └─────────────────────────────────────────────────────────────┘    │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 8.2 Fluxo de Síncrono com Bling

```
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│    Bling     │─────▶│  API Client  │─────▶│  Mappers     │
│    API       │      │  (bling_     │      │  (order_     │
│              │      │   client.py) │      │   mappers.py)│
└──────────────┘      └──────────────┘      └──────┬───────┘
                                                   │
                                                   ▼
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│   Supabase   │◀─────│   Service    │◀─────│  Normalizado │
│   (pedidos)  │      │  (order_     │      │  (canônico)  │
│              │      │   service.py)│      │              │
└──────────────┘      └──────────────┘      └──────────────┘
```

---

## 9. Conceitos Arquiteturais

### 9.1 Core Order + Integration Links

A arquitetura de pedidos é dividida em duas camadas:

| Camada | Tabela | Propósito |
|--------|--------|-----------|
| **Core** | `pedidos` | Dados normalizados e operacionais |
| **Links** | `vinculos_integracao_pedido` | Links para plataformas externas com dados brutos |

**Vantagens:**
- Desacoplamento entre dados operacionais e dados externos
- Um pedido pode ter múltiplos vínculos (ex: Bling + Shopee)
- Facilita migração entre plataformas
- Histórico completo de dados brutos

### 9.2 Payload Canônico

O campo `payload_canonico` na tabela `pedidos` armazena dados no **formato padrão** do sistema, independente da plataforma de origem.

**Mappers:** `packages/shared/nistiprint_shared/mappers/order_mappers.py`

```
┌─────────────┐
│  Shopee     │──────┐
│  Payload    │      │
└─────────────┘      │
                     │   ┌─────────────────┐
┌─────────────┐      │   │  order_mappers  │
│  Mercado    │──────┼──▶│     .py         │
│  Livre      │      │   │                 │
│  Payload    │      │   └────────┬────────┘
└─────────────┘      │            │
                     │            ▼
┌─────────────┐      │   ┌─────────────────┐
│  Bling      │──────┘   │  payload_       │
│  Payload    │          │  canonico       │
└─────────────┘          └─────────────────┘
```

### 9.3 Filtros Contextuais

O sistema possui funções SQL para identificar **canais próximos da coleta**:

**Funções:**
- `fn_canais_proximos_coleta()` - Identifica canais com coleta mais próxima do horário atual
- `fn_contar_pedidos_por_canal()` - Conta pedidos por canal

**UI:**
- Badges "FLEX" para canais com `flex=true`
- Contagens de pedidos por canal
- Ordenação por proximidade do horário de coleta

### 9.4 Classificação de Demandas

As demandas de produção são classificadas por:

| Dimensão | Valores |
|----------|---------|
| **Tipo** | `PLATAFORMA`, `B2B`, `FULFILLMENT`, `ESTOQUE_INTERNO` |
| **Modalidade Logística** | `STANDARD`, `EXPRESS`, `FULFILLMENT`, `RETIRADA` |
| **Classificação Cliente** | `B2C`, `B2B`, `INTERNO` |
| **Categoria Temporal** | `URGENTE`, `HOJE`, `AMANHA`, `FUTURO` |

---

## 10. Arquivos Principais por Categoria

### Models/Entidades

| Arquivo | Entidade |
|---------|----------|
| `packages/shared/nistiprint_shared/models/plataforma.py` | Plataforma |
| `packages/shared/nistiprint_shared/models/canal_venda.py` | CanalVenda |
| `packages/shared/nistiprint_shared/models/pedido.py` | Pedido, ItemPedido |
| `packages/shared/nistiprint_shared/models/demanda_producao.py` | DemandaProducao, DemandaProducaoItem |
| `packages/shared/nistiprint_shared/models/regra_logistica.py` | RegraLogistica |
| `packages/shared/nistiprint_shared/models/installed_integration.py` | InstalledIntegration |
| `packages/shared/nistiprint_shared/models/integration_module.py` | IntegrationModule |

### Services

| Arquivo | Serviço |
|---------|---------|
| `packages/shared/nistiprint_shared/services/plataforma_service.py` | PlataformaService |
| `packages/shared/nistiprint_shared/services/canal_venda_service.py` | CanalVendaService |
| `packages/shared/nistiprint_shared/services/order_service.py` | OrderService |
| `packages/shared/nistiprint_shared/services/demanda_producao_service.py` | DemandaProducaoService |
| `packages/shared/nistiprint_shared/services/regra_logistica_service.py` | RegraLogisticaService |
| `packages/shared/nistiprint_shared/services/integracao_canal_service.py` | IntegracaoCanalService |
| `packages/shared/nistiprint_shared/services/installed_integration_service.py` | InstalledIntegrationService |
| `packages/shared/nistiprint_shared/services/bling/bling_client.py` | BlingClient |
| `packages/shared/nistiprint_shared/services/platform_drivers/*.py` | Platform Drivers |

### Controllers/Rotas API

| Arquivo | Rotas |
|---------|-------|
| `apps/api/routes/pedidos.py` | `/api/v2/pedidos/*` |
| `apps/api/routes/pedidos_gestao.py` | `/api/v2/pedidos/canais-proximos-coleta`, `/api/v2/pedidos/contagem-por-canal` |
| `apps/api/routes/integracao_canais.py` | `/api/v2/integracao-canais/*` |
| `apps/api/routes/integracoes.py` | `/api/v2/integracoes/*` |
| `apps/api/routes/orders.py` | `/api/v2/orders/{platform}/{id}` (Live Query) |

### Worker Tasks

| Arquivo | Tasks |
|---------|-------|
| `apps/worker/tasks/pedidos_fetch_tasks.py` | `fetch_pedidos_em_andamento` |
| `apps/worker/tasks/consolidation_tasks.py` | `sync_orders_with_bling`, `persist_orders_batch` |
| `apps/worker/tasks/eventos_tasks.py` | Processamento de eventos |

### Tipos Frontend

| Arquivo | Tipos |
|---------|-------|
| `apps/frontend/src/types/producao.ts` | `ContextoProducao`, `CanalVenda`, `Plataforma`, `InstalledIntegration`, `DemandaProducao`, `RegraLogisticaCanal`, etc. |

### Schema Banco de Dados

| Arquivo | Descrição |
|---------|-----------|
| `supabase/schema.sql` | Schema completo do PostgreSQL |
| `supabase/migrations/` | Migrações incrementais |

---

## 11. Glossário

| Termo | Definição |
|-------|-----------|
| **Plataforma** | Sistema externo de integração (ex: Shopee, Bling) |
| **Canal de Venda** | Instância específica de uma plataforma |
| **Flex** | Atributo que indica entrega rápida/urgente |
| **Fulfillment (Full)** | Atributo que indica uso de fulfillment externo |
| **Payload Canônico** | Formato padrão de dados de pedido |
| **Vínculo de Integração** | Link entre pedido core e plataforma externa |
| **Demanda de Produção** | Ordem de fabricação gerada a partir de pedidos |
| **Modalidade Logística** | Tipo de envio (Standard, Express, Fulfillment, Retirada) |

---

## Referências

- Schema do banco: `supabase/schema.sql`
- Documentação API Bling: `docs/02-features/api_bling.md`
- Documentação API Shopee: `docs/02-features/api_shopee.md`
- Arquitetura de microsserviços: `docs/01-architecture/microservices.md`
- Integration Store V3: `docs/02-features/integration_store.md`
