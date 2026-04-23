# Relatório de Aderência: Codebase e Base de Dados vs. Objetivos do Projeto

**Data:** 2026-04-10  
**Projeto:** NistiPrint - Plataforma de Gestão de Pedidos e Produção  
**Base de Dados:** Supabase (PostgreSQL 17) - Projeto `nistiprint-supabase` (cfknrplrqvyirjxovuvi)

---

## 1. Resumo Executivo

O codebase atual demonstra **alta aderência** (≈80%) com os objetivos descritos. A arquitetura já implementa os conceitos fundamentais de:

- ✅ Múltiplas contas Bling com roteamento dinâmico
- ✅ Múltiplas contas de Marketplace (Shopee, ML, Amazon, Shein, TikTok)
- ✅ Associação ERP↔Marketplace via `erp_store_id` e `aggregator_store_id`
- ✅ Sistema de módulos configuráveis (marketplace de integrações)
- ✅ Processamento de webhooks Bling via n8n → Redis → Worker
- ✅ Serviço de IA para pedidos personalizados (Gemini)
- ✅ Mapeamento de dados com mappers canônicos
- ✅ Impressão de pedidos (print_service)

**Pontos que necessitam atenção** estão detalhados nas seções abaixo.

---

## 2. Arquitetura do Sistema

### 2.1 Componentes Existentes

| Componente | Tecnologia | Arquivo Principal | Status |
|---|---|---|---|
| **API Backend** | Flask (Python) | `apps/api/main.py` | ✅ Operacional |
| **Frontend** | React 19 + Vite + Tailwind | `apps/frontend/src/App.jsx` | ✅ Operacional |
| **Worker** | Celery + Redis | `apps/worker/worker_entrypoint.py` | ✅ Operacional |
| **Database** | Supabase (PostgreSQL 17) | `supabase/schema.sql` | ✅ Operacional |
| **Fila/Cache** | Redis 7 | `docker-compose.local.yml` | ✅ Operacional |
| **Shared Lib** | Python Package | `packages/shared/` | ✅ Operacional |
| **n8n** | Externo (webhook receiver) | Documentado em rotas | ⚠️ Não embutido |

### 2.2 Fluxo de Webhooks (Conforme Documentado)

```
Bling Webhook → n8n (valida HMAC) → Redis (fila) → Worker (consome) → Supabase
```

**Arquivos relacionados:**
- `packages/shared/nistiprint_shared/services/webhook_service.py` - Validação HMAC e logging
- `apps/api/routes/webhooks.py` - Endpoint `/api/v2/webhooks/pedido-cancelado`
- `packages/shared/nistiprint_shared/services/redis_queue_tasks.py` - Task `consumir_fila_bling`
- `apps/worker/tasks/pedidos_fetch_tasks.py` - Task `fetch_pedidos_em_andamento`

---

## 3. Sistema de Integrações

### 3.1 Módulos de Integração Existentes

| Módulo | Tipo | Arquivo Definição | Config Schema |
|---|---|---|---|
| **Bling ERP** | ERP | `apps/api/modules/platform_modules.py:get_bling_module_definition()` | ✅ OAuth2 + config schema completo |
| **Shopee** | Marketplace | `get_shopee_module_definition()` | ✅ OAuth2 + shop_id, partner_id, partner_key |
| **Mercado Livre** | Marketplace | `get_mercadolivre_module_definition()` | ✅ OAuth2 + client_id, client_secret |
| **Amazon** | Marketplace | `get_amazon_module_definition()` | ✅ OAuth2 + seller_id, mws_auth_token |
| **Shein** | Marketplace | `get_shein_module_definition()` | ✅ API Key + vendor_id |
| **TikTok Shop** | Marketplace | `get_tiktok_shop_module_definition()` | ✅ OAuth2 + app_key, app_secret |
| **Loja Integrada** | E-commerce | `get_loja_integrada_module_definition()` | ✅ API Key + app_key |

**Conclusão:** O sistema de módulos **já existe** e é baseado em `IntegrationModule` com:
- `config_schema` - Campos de configuração que a UI exibe dinamicamente
- `auth_config` - Configuração de OAuth/API
- `data_mapping_spec` - Mapeamento de campos
- Tags e categorias para organização

### 3.2 Serviços de Plataforma

| Serviço | Arquivo | Função |
|---|---|---|
| Platform Auth | `platform_auth_service.py` | Gera URLs OAuth, exchange tokens, refresh |
| Platform API | `platform_api_service.py` | Chamadas genéricas a APIs de plataformas |
| Platform Drivers | `platform_drivers/*.py` | Drivers específicos: `shopee.py`, `mercadolivre.py`, `amazon.py`, `shein.py`, `tiktok.py` |
| Platform Processor Registry | `platform_processor_registry.py` | Registro de processadores por plataforma |

### 3.3 Roteamento Multi-Conta

**Tabela:** `integration_account_routing`

| Campo | Tipo | Descrição |
|---|---|---|
| `id` | UUID | Primary Key |
| `module` | VARCHAR(50) | Módulo (ex: 'bling') |
| `function_name` | VARCHAR(50) | Função (ORDER_IMPORT, NFE_EMISSION, STOCK_SYNC, CATALOG_SYNC) |
| `scope_type` | VARCHAR(20) | Escopo: GLOBAL, PLATFORM, CHANNEL |
| `scope_id` | VARCHAR(100) | ID do escopo (null para global) |
| `account_id` | VARCHAR(255) | ID da conta vinculada |
| `is_active` | BOOLEAN | Status da regra |

**Serviço:** `integration_routing_service.py`

**Hierarquia de resolução:**
1. **Canal** (mais específico) → `scope_type='CHANNEL'`, `scope_id=channel_id`
2. **Plataforma** → `scope_type='PLATFORM'`, `scope_id=platform_name`
3. **Global** (fallback) → `scope_type='GLOBAL'`, `scope_id=NULL`

### 3.4 Associação ERP ↔ Marketplace (Store ID Mapping)

**Serviço:** `integracao_canal_service.py`

| Método | Função |
|---|---|
| `get_canal_by_bling_loja_id(bling_loja_id)` | Resolve canal de venda a partir do ID de loja Bling |
| `get_bling_loja_id_by_canal(canal_venda_id)` | Resolve ID de loja Bling a partir do canal |
| `criar_vinculo(canal_venda_id, bling_loja_id, ...)` | Cria vínculo canal↔loja |
| `resolver_canal_para_pedido(bling_loja_id)` | Resolve canal para pedido |

**Tabelas envolvidas:**
- `channel_connections` - Tabela moderna com `aggregator_store_id`
- `integracao_canal_config` - Tabela legado com `bling_loja_id`
- `canais_venda` - Tabela de canais de venda com `bling_loja_id_principal`

**Conclusão:** O mapeamento **Bling Loja ID → Conta Shopee** já é implementado dinamicamente, substituindo o `constants.py` legado (`BLING_ID_LOJA`).

### 3.5 Features/Capacidades por Integração

O sistema atual define capacidades implicitamente via:
- `integration_account_routing.function_name` - Funções disponíveis (ORDER_IMPORT, NFE_EMISSION, etc.)
- Módulos possuem `data_mapping_spec` e `auth_config` que definem o que cada integração permite

**⚠️ Gap Identificado:** Não há um sistema explícito de "features/capacidades" por instância de integração (ex: "Bling 01 pode emitir NFe, Bling 02 não"). Isso poderia ser adicionado como um campo `capabilities` ou `features` no schema de módulo.

---

## 4. Pedidos

### 4.1 Fluxo de Ingestão

```
┌─────────────────────────────────────────────────┐
│                 Fontes de Pedidos                │
├─────────────────────────────────────────────────┤
│ 1. Webhook Bling → n8n → Redis → Worker        │
│ 2. Upload de planilha (consolidação)            │
│ 3. Importação manual via worker task            │
│ 4. Legacy sync (MySQL → Supabase)               │
└─────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────┐
│              Order Service (Core)                │
│  order_service.upsert_order()                    │
│  - Mappers: BlingMapper, ShopeeMapper            │
│  - Payload canônico                              │
│  - Timeline de eventos                           │
│  - Vínculos de integração                        │
└─────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────┐
│                Tabelas Core                      │
│  pedidos (tabela principal)                      │
│  itens_pedido                                   │
│  vinculos_integracao_pedido                      │
│  eventos_pedido                                  │
└─────────────────────────────────────────────────┘
```

### 4.2 Tabelas de Pedidos

| Tabela | Finalidade | RLS |
|---|---|---|
| `pedidos` | Tabela core de pedidos | ✅ |
| `itens_pedido` | Itens de cada pedido | ✅ |
| `vinculos_integracao_pedido` | Links com plataformas externas | ✅ |
| `eventos_pedido` | Timeline de eventos | ✅ |
| `bling_pedidos` | Dados brutos Bling (legado) | ✅ |
| `bling_pedido_itens` | Itens brutos Bling | ✅ |
| `shopee_orders` | Pedidos Shopee (legado) | ✅ |

### 4.3 Campos Principais da Tabela `pedidos`

| Campo | Tipo | Descrição |
|---|---|---|
| `id` | INTEGER | PK auto |
| `numero_pedido` | VARCHAR | Número interno |
| `codigo_pedido_externo` | VARCHAR | ID externo (único) |
| `origem` | VARCHAR | Plataforma de origem (BLING, SHOPEE, etc.) |
| `canal_venda_id` | INTEGER | FK → canais_venda |
| `situacao_pedido_id` | INTEGER | FK → situacoes_pedido |
| `is_flex` | BOOLEAN | Flag entrega Flex |
| `servico_logistico` | VARCHAR | Serviço logístico |
| `data_limite_envio` | TIMESTAMPTZ | Ship by date |
| `payload_canonico` | JSONB | Payload normalizado |
| `informacoes_cliente` | JSONB | Dados enriquecidos (buyer_username, shipping_carrier) |
| `cliente_nome`, `cliente_email`, `cliente_telefone` | VARCHAR | Dados do cliente |
| `total_pedido` | NUMERIC | Total do pedido |

### 4.4 Identificação de Marketplace via Loja ID

**Implementação atual:** `order_sync_service.py` + `integracao_canal_service.py`

```python
# Quando chega webhook Bling com loja_id=204047801:
loja_id = full_order_data.get('loja', {}).get('id')  # 204047801
canal_id = integracao_canal_service.get_canal_by_bling_loja_id(loja_id)
# → Retorna canal Shopee configurado
```

**✅ Funcionalidade implementada** - O sistema reconhece a origem do pedido e busca dados complementares do marketplace correto.

### 4.5 Dados Shopee Específicos

Os campos `buyer_username` e `shipping_carrier` são:
- ✅ Extraídos do payload Shopee no `ShopeeMapper`
- ✅ Armazenados em `informacoes_cliente` (JSONB)
- ✅ Usados para cálculo automático de `is_flex` via trigger SQL

### 4.6 Importação de Pedidos

**Serviços existentes:**
| Serviço | Arquivo | Função |
|---|---|---|
| Bling Order Processing | `bling_order_processing_service.py` | Processa webhooks Bling por situação |
| Order Sync | `order_sync_service.py` | Sync Bling + Shopee unificado |
| Pedidos Bling Import | `pedidos_bling_import_service.py` | Importação em lote do Bling |
| File Processors | `file_processors.py` (legado) | Processa planilhas ML, Shopee, Amazon, Shein |
| Consolidation | `consolidation_service.py` | Consolidação automática |

**Worker Tasks:**
| Task | Arquivo | Frequência |
|---|---|---|
| `consumir_fila_bling` | `redis_queue_tasks.py` | 30s |
| `fetch_pedidos_em_andamento` | `pedidos_fetch_tasks.py` | Periódica |
| `process_consolidacao` | `consolidation_tasks.py` | On-demand |
| `sync_orders_with_bling` | `consolidation_tasks.py` | On-demand |

**⚠️ Gap Identificado:** Cada módulo de integração **já tem** funções de importação específicas, mas a UI de seleção de instâncias para importação pode precisar de enhancements.

### 4.7 Pedidos Personalizados (IA)

**Fluxo legado convertido:**

| Função Legada | Equivalente Novo | Arquivo |
|---|---|---|
| `kb/API/api.php` → recebe msgs Chrome | `routes/personalizados.py` → `/chat/<username>` | Novo |
| `kb/baixar_pedidos_bling/baixar_pedidos_bling.php` | `pedidos_bling_import_service.py` | Novo |
| `kb/legado/services/file_processors.py` | `file_processors.py` (shared) | Migrado |
| `kb/legado/services/ai_personalization_service.py` | `ai_personalization_service.py` (shared) | Migrado |

**Serviço de IA:**
- **Arquivo:** `packages/shared/nistiprint_shared/services/ai_personalization_service.py` (639 linhas)
- **Modelo:** Google Gemini `gemini-2.5-flash` via `GEMINI_API_KEY`
- **Funcionalidades:**
  - `process_orders()` - Processa pedidos com IA
  - `get_orders_with_chats()` - Busca pedidos com chats
  - `get_logs_by_order_sn()` - Logs de execução
  - `load_prompt_template()` - Carrega prompt de arquivo/env
  - `save_processing_log()` - Salva logs em `temp/`

**Endpoints API:**
- `GET /api/v2/personalizados` - Lista personalizados
- `POST /api/v2/personalizados/processar` - Dispara IA (Celery ou sync)
- `GET /api/v2/personalizados/status/<task_id>` - Status da task
- `POST /api/v2/personalizados/reprocessar/<order_sn>` - Reprocessa
- `GET /api/v2/personalizados/logs/<order_sn>` - Logs
- `POST /api/v2/personalizados/feedback` - Feedback 1-5
- `GET/PUT /api/v2/personalizados/config` - Config IA
- `GET /api/v2/personalizados/chat/<username>` - Mensagens de chat

**Worker Task:** `processar_personalizacoes_task` em `personalizados_tasks.py`

**✅ Funcionalidade convertida** para a nova aplicação.

---

## 5. Impressão de Pedidos

### 5.1 Serviços Existentes

| Serviço | Arquivo | Função |
|---|---|---|
| Print Service | `print_service.py` | Gestão de jobs de impressão |
| Printing Routes | `routes/printing.py` | Endpoints `/api/v2/printing/*` |

### 5.2 Endpoints de Impressão

| Endpoint | Método | Função |
|---|---|---|
| `/api/v2/printing/jobs` | GET | Lista jobs de impressão |
| `/api/v2/printing/job/<id>` | GET | Detalhe de job |
| `/api/v2/printing/demanda/<id>/print` | POST | Imprimir demanda |
| `/api/v2/printing/item/<id>/print` | POST | Imprimir item |

### 5.3 Templates de Impressão

**Legado:** `kb/legado/templates/results.html` (466 linhas) - Template Jinja2 para impressão de pedidos por plataforma.

**Novo:** A funcionalidade de impressão agora pode buscar dados diretamente da base interna (`pedidos`, `itens_pedido`) ao invés de consultar APIs externas.

**⚠️ Oportunidade:** O template `results.html` legado pode ser adaptado para usar os dados normalizados da base Supabase, otimizando a geração de documentos de produção.

---

## 6. Base de Dados - Resumo

### 6.1 Estatísticas

| Métrica | Valor |
|---|---|
| Total de Migrações | 66 |
| Extensões Instaladas | 9 (pgcrypto, pg_stat_statements, supabase_vault, uuid-ossp, pg_graphql, index_advisor, hypopg) |
| Extensões Disponíveis | 80+ |
| Tabelas Principais | ~50+ |
| Schemas | public, auth, storage |

### 6.2 Tabelas Principais por Domínio

#### Pedidos
| Tabela | Linhas | Descrição |
|---|---|---|
| `pedidos` | Core | Pedidos normalizados |
| `itens_pedido` | Core | Itens de pedidos |
| `vinculos_integracao_pedido` | Core | Links com plataformas externas |
| `eventos_pedido` | Core | Timeline de eventos |
| `bling_pedidos` | Legado | Dados brutos Bling |
| `bling_pedido_itens` | Legado | Itens brutos Bling |
| `shopee_orders` | Legado | Pedidos Shopee |

#### Integrações
| Tabela | Linhas | Descrição |
|---|---|---|
| `installed_integrations` | Core | Integrações instaladas |
| `integration_account_routing` | Core | Roteamento multi-conta |
| `integration_modules` | Core | Módulos disponíveis |
| `channel_connections` | Core | Conexões canal↔agregador |
| `integracao_canal_config` | Core | Configuração canal↔Bling |
| `erp_marketplace_links` | Core | Links ERP↔Marketplace |
| `canais_venda` | Core | Canais de venda |
| `plataformas` | Core | Plataformas disponíveis |
| `contas_bling` | Legado | Contas Bling (legado) |

#### Produção e Demanda
| Tabela | Linhas | Descrição |
|---|---|---|
| `demandas_producao` | Core | Demandas de produção |
| `ordens_producao` | Core | Ordens de produção |
| `eventos_producao_v2` | Core | Eventos de produção (Event Sourcing) |
| `logs_producao_diaria` | Core | Logs diários |

#### Estoque
| Tabela | Linhas | Descrição |
|---|---|---|
| `produtos` | Core | Produtos |
| `estoque` | Core | Estoque |
| `movimentacoes_estoque` | Core | Movimentações |
| `depositos` | Core | Depósitos |

#### IA e Personalização
| Tabela | Linhas | Descrição |
|---|---|---|
| `order_personalizations` | Core | Personalizações de pedidos |
| `ai_execution_log` | Core | Logs de execução IA |
| `v2_chat_events` | Core | Eventos de chat |

#### Impressão
| Tabela | Linhas | Descrição |
|---|---|---|
| `print_jobs` | Core | Jobs de impressão |
| `product_artworks` | Core | Artes de produtos |

#### Usuários e Permissões
| Tabela | Linhas | Descrição |
|---|---|---|
| `usuarios` | 5 | Usuários |
| `setores` | 5 | Setores |
| `recursos` | 8 | Recursos |
| `permissoes_setor` | 32 | Permissões por setor |

### 6.3 Views Principais

| View | Descrição |
|---|---|
| `vendas_personalizadas` | Vendas com personalizações IA |
| `pedidos_consolidar_v2` | Pedidos para consolidação |
| `pedidos_para_consolidar` | Pedidos pendentes de consolidação |
| `mensagens_chat` | Mensagens de chat unificadas |

### 6.4 Funções RPC Principais

| Função | Descrição |
|---|---|
| `get_pedidos_com_filtros_avancados` | Consulta avançada de pedidos |
| `get_pedidos_similares` | Encontra pedidos similares |
| `get_demandas_por_pedido_externo` | Demandas por pedido |
| `get_pedidos_por_demanda` | Pedidos por demanda |
| `get_alertas_producao` | Alertas de produção |
| `rpc_reconciliar_item_estoque` | Reconciliação de estoque |

---

## 7. Código Legado (Referência)

### 7.1 Estrutura `kb/legado/`

| Arquivo/Diretório | Função | Status na Nova Aplicação |
|---|---|---|
| `app.py` | App Flask legado | ✅ Substituído por `apps/api/main.py` |
| `constants.py` | Constantes (BLING_ID_LOJA, SITUACOES, etc.) | ✅ Substituído por `integracao_canal_service.py` |
| `models/` (9 arquivos) | Modelos SQLAlchemy legado | ✅ Migrados para `packages/shared/models/` |
| `routes/` (21 arquivos) | Rotas Flask legado | ✅ Migrados para `apps/api/routes/` |
| `services/` (28 arquivos) | Serviços legado | ✅ Migrados para `packages/shared/services/` |
| `templates/results.html` | Template de impressão | ⚠️ Pode ser adaptado |

### 7.2 Código PHP Legado

| Arquivo | Função | Equivalente Novo |
|---|---|---|
| `kb/API/api.php` | Recebe msgs Chrome, salva na base | `routes/personalizados.py` |
| `kb/atualizar base - pedidos/baixar_pedidos_bling.php` | Baixa pedidos do Bling | `pedidos_bling_import_service.py` |
| `kb/bling_token_manager/` | Gestão de tokens Bling | `token_manager/` (shared) |

---

## 8. Gaps e Recomendações

### 8.1 Gaps Identificados

| # | Gap | Severidade | Recomendação |
|---|---|---|---|
| 1 | **Sistema de Features/Capacidades por Integração** | Baixa | Adicionar campo `capabilities` ou `features` no schema de módulo/integração para indicar o que cada instância permite (ex: emissão de NFe, sync de estoque) |
| 2 | **Configuração Dinâmica de Campos de Integração** | Média | O `config_schema` já existe nos módulos, mas a UI (`BlingInstanceConfigModal.tsx`) pode precisar de melhorias para renderizar campos dinamicamente a partir do schema |
| 3 | **Template de Impressão Normalizado** | Média | Adaptar `kb/legado/templates/results.html` para usar dados da base Supabase ao invés de chamadas externas |
| 4 | **Documentação do Fluxo n8n** | Baixa | O n8n é mencionado como receptor de webhooks, mas não há workflows/arquivos de configuração do n8n no repositório |

### 8.2 Pontos Fortes

| # | Ponto Forte | Descrição |
|---|---|---|
| 1 | **Arquitetura de Módulos** | Sistema de `IntegrationModule` com `config_schema` permite adicionar novas integrações sem alterar código core |
| 2 | **Roteamento Multi-Conta** | `integration_account_routing` com hierarquia GLOBAL → PLATFORM → CHANNEL resolve o problema de múltiplas contas elegantemente |
| 3 | **Mappers Canônicos** | `BlingMapper` e `ShopeeMapper` normalizam payloads de diferentes plataformas |
| 4 | **Payload Canônico** | Campo `payload_canonico` (JSONB) armazena dados normalizados para consulta |
| 5 | **Timeline de Eventos** | `eventos_pedido` rastreia todas as mudanças de status e origem dos dados |
| 6 | **Proteção de Dados Flex** | Lógica de proteção contra sobrescrita de dados Flex já implementada no `order_service.py` |
| 7 | **IA de Personalização** | Serviço completo com Gemini, prompts configuráveis, feedback do usuário, e logs detalhados |

---

## 9. Mapa Completa de Arquivos por Objetivo

### 9.1 Webhooks (Bling, Shopee)

| Arquivo | Função |
|---|---|
| `packages/shared/nistiprint_shared/services/webhook_service.py` | Validação HMAC e logging de webhooks |
| `packages/shared/nistiprint_shared/services/bling_order_processing_service.py` | Processa webhooks Bling por situação |
| `packages/shared/nistiprint_shared/services/redis_queue_tasks.py` | Task Celery para consumir fila Redis |
| `apps/worker/tasks/pedidos_fetch_tasks.py` | Fetch manual de pedidos "Em Andamento" |
| `apps/api/routes/webhooks.py` | Endpoint `/api/v2/webhooks/pedido-cancelado` |
| `apps/api/routes/integracoes.py` | Rotas de integração (status, renovar token, routing) |

### 9.2 Integrações (ERP + Marketplace)

| Arquivo | Função |
|---|---|
| `apps/api/modules/platform_modules.py` | Definição de módulos de plataforma |
| `apps/api/modules/register_modules.py` | Registro de módulos no marketplace |
| `packages/shared/nistiprint_shared/services/integration_module_service.py` | Gestão de módulos de integração |
| `packages/shared/nistiprint_shared/services/installed_integration_service.py` | Gestão de instalações ativas |
| `packages/shared/nistiprint_shared/services/integration_routing_service.py` | Roteamento multi-conta |
| `packages/shared/nistiprint_shared/services/integracao_canal_service.py` | Vínculos canal↔loja Bling |
| `packages/shared/nistiprint_shared/services/erp_marketplace_links_service.py` | Links ERP↔Marketplace |
| `packages/shared/nistiprint_shared/services/platform_auth_service.py` | OAuth para plataformas |
| `packages/shared/nistiprint_shared/services/platform_api_service.py` | Chamadas genéricas a APIs |
| `packages/shared/nistiprint_shared/services/platform_drivers/*.py` | Drivers: shopee, ml, amazon, shein, tiktok |
| `packages/shared/nistiprint_shared/services/bling/bling_client.py` | Cliente API Bling (1134 linhas) |
| `packages/shared/nistiprint_shared/services/conta_bling_service.py` | Gestão de contas Bling |
| `apps/api/routes/marketplace_api_routes.py` | CRUD de marketplace de integrações |
| `apps/api/routes/integracoes.py` | Rotas de integração |
| `apps/api/routes/integrations.py` | Rotas admin de contas Bling |
| `apps/api/routes/erp_links.py` | Links ERP-Marketplace |
| `apps/frontend/src/pages/integracoes/BlingInstanceConfigModal.tsx` | Modal config Bling |
| `apps/frontend/src/components/marketplace/InstallWizard.jsx` | Wizard de instalação |
| `apps/frontend/src/services/MarketplaceService.js` | Serviço frontend marketplace |
| `kb/legado/constants.py` | Constantes legado (referência) |

### 9.3 Pedidos

| Arquivo | Função |
|---|---|
| `packages/shared/nistiprint_shared/services/order_service.py` | Serviço core de pedidos (upsert, mappers, eventos) |
| `packages/shared/nistiprint_shared/mappers/order_mappers.py` | Mappers Bling e Shopee |
| `packages/shared/nistiprint_shared/services/order_sync_service.py` | Sync de pedidos Bling + Shopee |
| `packages/shared/nistiprint_shared/services/bling_order_processing_service.py` | Processamento webhooks Bling |
| `packages/shared/nistiprint_shared/services/pedidos_bling_import_service.py` | Importação em lote do Bling |
| `packages/shared/nistiprint_shared/services/file_processors.py` | Processamento de planilhas |
| `packages/shared/nistiprint_shared/services/consolidation_service.py` | Consolidação de pedidos |
| `apps/api/routes/pedidos.py` | Rotas de gestão de pedidos |
| `apps/api/routes/orders.py` | Rotas de consulta de pedidos |
| `apps/api/routes/unified_orders.py` | Visão unificada de pedidos |
| `apps/api/routes/pedidos_gestao.py` | Gestão avançada de pedidos |
| `apps/api/routes/vendas.py` | Rotas de vendas |
| `apps/worker/tasks/consolidation_tasks.py` | Tasks de consolidação |
| `apps/frontend/src/pages/pedidos/PedidosListPage.jsx` | Lista de pedidos |
| `apps/frontend/src/pages/pedidos/PedidoDetalhePage.jsx` | Detalhe do pedido |
| `apps/frontend/src/services/orderService.js` | Serviço de pedidos |
| `packages/shared/nistiprint_shared/models/pedido.py` | Modelo de pedido |
| `packages/shared/nistiprint_shared/models/bling_pedidos.py` | Modelo Bling pedidos |
| `packages/shared/nistiprint_shared/models/shopee_orders.py` | Modelo Shopee pedidos |
| `packages/shared/nistiprint_shared/models/vinculos_integracao_pedido.py` | Modelo de vínculos |
| `packages/shared/nistiprint_shared/models/eventos_pedido.py` | Modelo de eventos |
| `kb/legado/services/file_processors.py` | File processors legado (referência) |
| `kb/API/api.php` | API PHP legado (referência) |
| `kb/atualizar base - pedidos/baixar_pedidos_bling.php` | Script PHP legado (referência) |

### 9.4 IA de Personalização

| Arquivo | Função |
|---|---|
| `packages/shared/nistiprint_shared/services/ai_personalization_service.py` | Serviço de IA (Gemini) - 639 linhas |
| `apps/api/routes/personalizados.py` | Endpoints de personalizados |
| `apps/worker/tasks/personalizados_tasks.py` | Task Celery de personalização |
| `packages/shared/nistiprint_shared/models/order_personalizations.py` | Modelo de personalizações |
| `packages/shared/nistiprint_shared/models/ai_execution_log.py` | Modelo de logs IA |
| `packages/shared/nistiprint_shared/models/supabase_ai_log.py` | Modelo de logs Supabase |
| `packages/shared/nistiprint_shared/templates/prompts/` | Templates de prompt |
| `apps/frontend/src/pages/ai/AIDashboardPage.jsx` | Dashboard IA |
| `apps/frontend/src/pages/ai/AIStatusBadge.jsx` | Badge de status |
| `apps/frontend/src/pages/ai/ChatViewer.jsx` | Visualizador de chats |
| `apps/frontend/src/pages/configuracoes/ConfiguracoesIA` | Configuração IA |
| `apps/frontend/src/services/aiService.ts` | Serviço frontend IA |
| `kb/legado/services/ai_personalization_service.py` | IA legado (referência) |

### 9.5 Impressão

| Arquivo | Função |
|---|---|
| `packages/shared/nistiprint_shared/services/print_service.py` | Serviço de impressão |
| `apps/api/routes/printing.py` | Endpoints de impressão |
| `packages/shared/nistiprint_shared/models/print_job.py` | Modelo de job |
| `packages/shared/nistiprint_shared/models/product_artwork.py` | Modelo de arte |
| `apps/frontend/src/pages/impressao/FilaImpressao.jsx` | Fila de impressão |
| `apps/frontend/src/services/PrintService.js` | Serviço frontend |
| `kb/legado/templates/results.html` | Template de impressão legado (referência) |

---

## 10. Conclusão

O codebase atual demonstra **alta aderência** com os objetivos descritos. A arquitetura já implementa:

1. ✅ **Múltiplas contas Bling** com roteamento dinâmico via `integration_account_routing`
2. ✅ **Múltiplas contas de Marketplace** com drivers específicos por plataforma
3. ✅ **Associação ERP↔Marketplace** via `erp_store_id`, `aggregator_store_id`, e `integracao_canal_service`
4. ✅ **Sistema de módulos configuráveis** com `config_schema` para UI dinâmica
5. ✅ **Processamento de webhooks** via n8n → Redis → Worker
6. ✅ **IA para pedidos personalizados** com Gemini, prompts configuráveis, e feedback
7. ✅ **Mapeamento de dados** com mappers canônicos (BlingMapper, ShopeeMapper)
8. ✅ **Impressão de pedidos** com print_service e endpoints dedicados

**Principais gaps:**
- Sistema explícito de features/capacidades por instância de integração
- Template de impressão adaptado para base normalizada
- Configuração n8n embutida no repositório

O sistema está em **estado avançado de maturidade** e pronto para evolução contínua.
