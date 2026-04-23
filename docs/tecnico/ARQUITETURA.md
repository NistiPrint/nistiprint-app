# Arquitetura Técnica - Nistiprint

**Última atualização:** 2026-04-02  
**Status:** Consolidado

Este documento descreve a arquitetura técnica do sistema Nistiprint, incluindo componentes, fluxos de dados, serviços e padrões de implementação.

---

## 1. Visão Geral da Arquitetura

### 1.1 Diagrama de Componentes

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              ARQUITETURA DO SISTEMA                             │
└─────────────────────────────────────────────────────────────────────────────────┘

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
       ▲
       │
┌─────────────┐
│ Plataformas │
│   Externas  │
│  (Bling,    │
│   Shopee)   │
└─────────────┘
```

### 1.2 Componentes Principais

| Componente | Tecnologia | Função |
|------------|------------|--------|
| **Frontend** | React + TypeScript | Interface do usuário |
| **API** | Flask (Python) | Endpoints REST |
| **Worker** | Celery + Redis | Processamento assíncrono |
| **Banco de Dados** | Supabase (PostgreSQL) | Armazenamento persistente |
| **Cache/Broker** | Redis | Filas Celery e cache |

---

## 2. Estrutura de Pacotes

```
nistiprint-app/
├── apps/
│   ├── api/                     # API Flask
│   │   ├── routes/              # Rotas da API
│   │   │   ├── producao_contexto.py
│   │   │   ├── demandas.py
│   │   │   ├── pedidos.py
│   │   │   └── integracoes.py
│   │   └── app.py
│   │
│   └── frontend/                # React + TypeScript
│       ├── src/
│       │   ├── types/           # Tipos TypeScript
│       │   ├── services/        # Serviços HTTP
│       │   └── components/      # Componentes React
│       └── package.json
│
├── packages/
│   └── shared/
│       └── nistiprint_shared/
│           ├── models/          # Modelos de dados
│           │   ├── pedido.py
│           │   ├── demanda_producao.py
│           │   ├── canal_venda.py
│           │   ├── canal_modalidade_mapeamento.py
│           │   └── regras_consolidacao_canal.py
│           │
│           ├── services/        # Serviços de negócio
│           │   ├── order_service.py
│           │   ├── demanda_producao_service.py
│           │   ├── consolidation_service.py      # ⭐ Consolidação
│           │   ├── canal_modalidade_service.py   # ⭐ Mapeamento
│           │   ├── regras_consolidacao_service.py # ⭐ Regras
│           │   ├── regra_logistica_service.py
│           │   └── canal_venda_service.py
│           │
│           ├── database/        # Conexão DB
│           │   └── supabase_db_service.py
│           │
│           ├── mappers/         # Mappers de dados
│           │   └── order_mappers.py
│           │
│           └── utils/           # Utilitários
│               └── date_utils.py
│
├── supabase/
│   └── migrations/              # Migrations SQL
│       ├── 20260402000014_consolidacao_simples.sql
│       ├── 20260402000004_regras_consolidacao_canal.sql
│       └── ...
│
└── docs/                        # Documentação
    ├── TECNICO-MODELO-DADOS.md
    ├── TECNICO-ARQUITETURA.md
    ├── NEGOCIO-REGRAS.md
    └── MANUAL-USUARIO.md
```

---

## 3. Fluxo de Consolidação de Demandas

### 3.1 Visão Geral

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    FLUXO DE CONSOLIDAÇÃO DE PEDIDOS EM DEMANDAS                 │
└─────────────────────────────────────────────────────────────────────────────────┘

Webhook Bling/Shopee
       │
       ▼
Worker (upsert_order)
       │
       ▼
consolidation_service.consolidar_pedido(pedido_id)
       │
       ├────────────────────────────────────────────────────────────┐
       │                                                            │
       ▼                                                            ▼
1. resolver_modalidade()                                  2. resolver_horario()
   canal_modalidade_mapeamento                              regras_logisticas_canal
       │                                                            │
       ▼                                                            ▼
3. get_regra_consolidacao()                                4. calcular_chave()
   regras_consolidacao_canal                                  (produto, miolo, data)
       │
       ▼
5. buscar_rascunho_compativel()
   demandas_producao WHERE status=RASCUNHO
       │
       ├──────────────────────┬──────────────────────┐
       │                      │                      │
       ▼                      ▼                      ▼
  ENCONTROU            NÃO ENCONTROU           janela=0
       │                      │                      │
       ▼                      ▼                      ▼
  adicionar_ao_          criar_rascunho()      criar_demanda_direta()
  rascunho()
       │
       ▼
  Demanda em status RASCUNHO
```

### 3.2 Serviço de Consolidação

**Arquivo:** `packages/shared/nistiprint_shared/services/consolidation_service.py`

**Classe Principal:** `ConsolidationService`

**Método Central:**
```python
def consolidar_pedido(self, pedido_id: int) -> Optional[Dict[str, Any]]:
    """
    Consolida um pedido em uma demanda de produção.
    
    Fluxo:
    1. Buscar pedido e dados do canal
    2. Resolver modalidade (canal_modalidade_mapeamento)
    3. Resolver horário de coleta (regras_logisticas_canal)
    4. Buscar regra de consolidação (regras_consolidacao_canal)
    5. Calcular chave de agrupamento
    6. Buscar rascunho compatível
    7. Adicionar ao rascunho OU criar novo rascunho
    """
```

**Classes Auxiliares:**
- `ConsolidacaoChave` - Chave de agrupamento para consolidação

### 3.3 Serviços de Suporte

#### Canal Modalidade Service
**Arquivo:** `packages/shared/nistiprint_shared/services/canal_modalidade_service.py`

```python
def derivar_modalidade(
    self,
    canal_venda_id: int,
    servico_logistico: str
) -> Optional[str]:
    """
    Deriva modalidade logística a partir do servico_logístico.
    
    Exemplo:
        >>> service.derivar_modalidade(1, "Entrega Rápida Shopee")
        'EXPRESS'
    """
```

#### Regras Consolidacao Service
**Arquivo:** `packages/shared/nistiprint_shared/services/regras_consolidacao_service.py`

```python
def get_regra_para_pedido(
    self,
    canal_venda_id: int,
    modalidade: str
) -> RegrasConsolidacaoCanal:
    """Busca regra específica para um pedido (canal + modalidade)."""
```

---

## 4. Resolução de Canal no Webhook

### 4.1 Problema

Quando o Bling envia um webhook com um pedido, ele inclui apenas `numeroLoja` (ID da loja Bling). O sistema precisa resolver qual `canal_venda_id` pertence a essa loja.

### 4.2 Fluxo de Resolução

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

### 4.3 Implementação

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

---

## 5. Arquitetura de Pedidos

### 5.1 Core Order + Integration Links

O sistema utiliza uma **arquitetura de dois níveis** para pedidos:

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

### 5.2 Mappers de Pedido

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

## 6. Platform Drivers

### 6.1 Visão Geral

**Pasta:** `packages/shared/nistiprint_shared/services/platform_drivers/`

| Arquivo | Plataforma | Função |
|---------|------------|--------|
| `shopee.py` | Shopee | Busca pedidos, atualiza status |
| `amazon.py` | Amazon | Busca pedidos, atualiza status |
| `mercadolivre.py` | Mercado Livre | Busca pedidos, atualiza status |
| `shein.py` | Shein | Busca pedidos, atualiza status |
| `tiktok.py` | TikTok | Busca pedidos, atualiza status |

### 6.2 Bling Client

**Pasta:** `packages/shared/nistiprint_shared/services/bling/`

| Arquivo | Função |
|---------|--------|
| `bling_client.py` | Cliente principal da API Bling |
| `bling_client_updated.py` | Versão atualizada do cliente |
| `bling.py` | Wrapper adicional |

O Bling é a **fonte primária de pedidos** do sistema.

---

## 7. Integration Store

### 7.1 Arquitetura de Integrações

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

### 7.2 Tabelas de Integração

#### integration_modules (Catálogo)
```sql
CREATE TABLE integration_modules (
    id text PRIMARY KEY,          -- ex: 'shopee', 'amazon'
    name text NOT NULL,
    description text,
    version text,
    config_schema jsonb,          -- JSON Schema de configuração
    auth_flow text,               -- OAuth2, API_KEY, etc.
    is_active boolean DEFAULT true
);
```

#### installed_integrations (Instâncias)
```sql
CREATE TABLE installed_integrations (
    id integer PRIMARY KEY,
    module_id varchar(100) NOT NULL,
    instance_name varchar(255) NOT NULL,
    access_token text,
    refresh_token text,
    expires_at timestamp with time zone,
    config jsonb DEFAULT '{}',
    is_active boolean DEFAULT true,
    last_sync timestamp with time zone,
    sync_status varchar(50) DEFAULT 'pending'
);
```

#### channel_connections (Vínculos)
```sql
CREATE TABLE channel_connections (
    id uuid PRIMARY KEY,
    channel_id integer NOT NULL,    -- FK → canais_venda.id
    integration_id integer,         -- FK → installed_integrations.id
    aggregator_store_id varchar(255), -- ex: bling_loja_id
    aggregator_store_name varchar(255),
    is_active boolean DEFAULT true,
    last_sync timestamp with time zone
);
```

---

## 8. Arquitetura de Contexto de Produção e UX

### 8.1 Visão Geral

Este módulo implementa:
1. **Ordenação inteligente** de produção baseada em regras de negócio
2. **Sinalização contextual** para guiar o usuário
3. **Otimização de UX** para reduzir carga cognitiva
4. **Autopreenchimento inteligente** aproveitando dados cadastrados

### 8.2 Componentes

#### Contexto de Produção
**Tabela:** `contextos_producao`

Snapshot unificado que sintetiza todas as relações de uma demanda/pedido.

**Snapshots:**
- `snapshot_plataforma` - Dados da plataforma externa
- `snapshot_integracao` - Dados da integração
- `snapshot_logistica` - Modalidade, horário de corte
- `snapshot_temporal` - Prazos e categoria temporal
- `snapshot_priorizacao` - Score e fatores de prioridade

#### Regras de Priorização
**Tabela:** `regras_priorizacao`

Regras configuráveis para ordenação de produção.

**Tipos de Ação:**
- `ADD_SCORE` - Adiciona pontos ao score
- `SET_PRIORIDADE` - Define prioridade fixa
- `MOVER_TOPO` - Move para o topo da lista

#### Sinalizações de Demanda
**Tabela:** `sinalizacoes_demanda`

Alertas visuais para guiar o usuário.

**Tipos:**
| Tipo | Severidade | Descrição |
|------|------------|-----------|
| `FLEX` | INFO/ATENCAO | Entrega no mesmo dia |
| `FULFILLMENT` | INFO | Reposição externa |
| `HORARIO_CORTE_PROXIMO` | ATENCAO | Corte nas próximas 2h |
| `ESTOQUE_INSUFICIENTE` | CRITICO | Produção incompleta |
| `PRODUCAO_ATRASADA` | CRITICO | Risco de atraso |

### 8.3 Serviços Implementados

| Serviço | Arquivo | Responsabilidade |
|---------|---------|------------------|
| `ContextoProducaoService` | `contexto_producao_service.py` | Construir contextos unificados |
| `PriorizacaoService` | `priorizacao_service.py` | Aplicar regras de priorização |
| `SinalizacaoService` | `sinalizacao_service.py` | Gerar sinalizações visuais |
| `DemandaAutoFillService` | `demanda_autofill_service.py` | Autopreenchimento inteligente |
| `UserPreferenceService` | `user_preference_service.py` | Gerenciar preferências de UX |

---

## 9. Endpoints da API

### 9.1 Demandas de Produção

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| GET | `/api/v2/demandas` | Listar demandas |
| GET | `/api/v2/demandas/{id}` | Buscar demanda por ID |
| POST | `/api/v2/demandas` | Criar demanda |
| PUT | `/api/v2/demandas/{id}` | Atualizar demanda |
| DELETE | `/api/v2/demandas/{id}` | Excluir demanda |
| PATCH | `/api/v2/demandas/{id}/publicar` | Publicar rascunho |

### 9.2 Pedidos

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| GET | `/api/v2/pedidos` | Listar pedidos |
| GET | `/api/v2/pedidos/{id}` | Buscar pedido |
| POST | `/api/v2/pedidos/sync` | Sincronizar pedidos |
| GET | `/api/v2/pedidos/nao-classificados` | Pedidos sem classificação |

### 9.3 Consolidação

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| GET | `/api/v2/consolidacao/rascunhos` | Listar rascunhos |
| GET | `/api/v2/consolidacao/rascunhos/{id}/pedidos` | Pedidos do rascunho |
| PATCH | `/api/v2/consolidacao/rascunhos/{id}` | Editar rascunho |
| POST | `/api/v2/consolidacao/{pedido_id}` | Consolida pedido (worker) |

### 9.4 Contexto de Produção (UX)

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| GET | `/api/v2/producao-contexto/producao/contexto/ordenacao` | Lista ordenada |
| GET | `/api/v2/producao-contexto/producao/contexto/demanda/{id}` | Contexto da demanda |
| GET | `/api/v2/producao-contexto/producao/regras-priorizacao` | Listar regras |
| POST | `/api/v2/producao-contexto/producao/regras-priorizacao` | Criar regra |
| GET | `/api/v2/producao-contexto/producao/sinalizacoes/demanda/{id}` | Sinalizações |
| GET | `/api/v2/producao-contexto/producao/autofill/canal/{canal_id}` | Defaults por canal |
| GET | `/api/v2/producao-contexto/producao/preferencias` | Preferências do usuário |

---

## 10. Workers e Tarefas Assíncronas

### 10.1 Arquitetura Celery

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│     API     │────▶│    Redis    │────▶│   Worker    │
│   (Flask)   │     │   (Broker)  │     │  (Celery)   │
└─────────────┘     └─────────────┘     └──────┬──────┘
                                               │
                                               ▼
                                       ┌─────────────┐
                                       │  Supabase   │
                                       │ (PostgreSQL)│
                                       └─────────────┘
```

### 10.2 Tarefas Principais

| Tarefa | Arquivo | Descrição |
|--------|---------|-----------|
| `upsert_order` | `bling_order_processing_service.py` | Processa pedido do Bling |
| `sync_pedidos_shopee` | `shopee_tasks.py` | Sincroniza pedidos Shopee |
| `consolidar_pedido` | `consolidation_service.py` | Consolida pedido em demanda |
| `atualizar_status_producao` | `demanda_tasks.py` | Atualiza status de produção |

### 10.3 Integração no Worker

Para ativar a consolidação automática:

```python
from nistiprint_shared.services.consolidation_service import consolidation_service

# Após upsert_order():
async def process_order(pedido_id: int):
    await upsert_order(pedido_id)
    consolidation_service.consolidar_pedido(pedido_id)
```

---

## 11. Banco de Dados

### 11.1 Supabase (PostgreSQL)

**Conexão:** `packages/shared/nistiprint_shared/database/supabase_db_service.py`

```python
from nistiprint_shared.database.supabase_db_service import supabase_db

# Exemplo de uso
response = supabase_db.table('pedidos').select('*').eq('id', pedido_id).execute()
```

### 11.2 Migrations

**Pasta:** `supabase/migrations/`

| Migration | Descrição |
|-----------|-----------|
| `20260402000014_consolidacao_simples.sql` | Consolidação (tabelas principais) |
| `20260402000004_regras_consolidacao_canal.sql` | Regras de consolidação |
| `20260324000002_demandas_pedidos_pivot.sql` | Tabela pivot N:N |
| `20260329000004_contexto_producao_ux.sql` | Contexto de produção e UX |

### 11.3 Funções SQL

```sql
-- Derivar modalidade
derivar_modalidade_logistica(p_canal_venda_id BIGINT, p_servico_logistico TEXT)
RETURNS VARCHAR(50)

-- Buscar regras de consolidação
get_regras_consolidacao_canal(p_canal_venda_id BIGINT, p_modalidade VARCHAR)
RETURNS TABLE (...)

-- Verificar rascunho expirado
rascunho_expirado(p_demanda_id BIGINT)
RETURNS BOOLEAN

-- Contar pedidos após edição
contar_pedidos_novos_apos_edicao(p_demanda_id BIGINT)
RETURNS INTEGER
```

---

## 12. Segurança

### 12.1 RLS (Row Level Security)

Todas as tabelas principais possuem políticas RLS habilitadas:

```sql
ALTER TABLE canal_modalidade_mapeamento ENABLE ROW LEVEL SECURITY;

CREATE POLICY "authenticated_view_canal_modalidade"
ON canal_modalidade_mapeamento FOR SELECT TO authenticated USING (true);

CREATE POLICY "authenticated_insert_canal_modalidade"
ON canal_modalidade_mapeamento FOR INSERT TO authenticated WITH CHECK (true);
```

### 12.2 Chaves de API

**Arquivo:** `packages/shared/nistiprint_shared/database/supabase_db_service.py`

O sistema utiliza chaves publishable do Supabase para autenticação.

---

## 13. Referências de Implementação

### Models Python
| Arquivo | Entidade |
|---------|----------|
| `models/pedido.py` | Pedidos, ItensPedido |
| `models/demanda_producao.py` | Demandas, ItensDemanda |
| `models/canal_venda.py` | Canais de Venda |
| `models/canal_modalidade_mapeamento.py` | Mapeamento de Modalidade |
| `models/regras_consolidacao_canal.py` | Regras de Consolidação |

### Services Python
| Arquivo | Responsabilidade |
|---------|------------------|
| `services/consolidation_service.py` | **Serviço principal** de consolidação |
| `services/canal_modalidade_service.py` | CRUD de mapeamentos |
| `services/regras_consolidacao_service.py` | CRUD de regras |
| `services/order_service.py` | Gestão de pedidos |
| `services/demanda_producao_service.py` | Gestão de demandas |
| `services/canal_venda_service.py` | Resolução de canal |

### Tipos TypeScript
| Arquivo | Descrição |
|---------|-----------|
| `apps/frontend/src/types/producao.ts` | Tipos de produção e UX |

---

*Documento consolidado em 2026-04-02*
