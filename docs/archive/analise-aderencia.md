> Documento legado.
> Pode descrever regras e fluxos anteriores ao modelo atual de integracoes instaladas e pedido canonico.
> Fonte atual: [Spec de Integracoes](../specs/02-domains/integracoes/spec.md), [Spec de Pedidos](../specs/02-domains/pedidos/spec.md), [Arquitetura Tecnica](../tecnico/ARQUITETURA.md) e [Modelo de Dados](../tecnico/MODELO-DADOS.md).

# RelatÃ³rio de AderÃªncia: Codebase e Base de Dados vs. Objetivos do Projeto

**Data:** 2026-04-10  
**Projeto:** NistiPrint - Plataforma de GestÃ£o de Pedidos e ProduÃ§Ã£o  
**Base de Dados:** Supabase (PostgreSQL 17) - Projeto `nistiprint-supabase` (cfknrplrqvyirjxovuvi)

---

## 1. Resumo Executivo

O codebase atual demonstra **alta aderÃªncia** (â‰ˆ80%) com os objetivos descritos. A arquitetura jÃ¡ implementa os conceitos fundamentais de:

- âœ… MÃºltiplas contas Bling com roteamento dinÃ¢mico
- âœ… MÃºltiplas contas de Marketplace (Shopee, ML, Amazon, Shein, TikTok)
- âœ… AssociaÃ§Ã£o ERPâ†”Marketplace via `erp_store_id` e `aggregator_store_id`
- âœ… Sistema de mÃ³dulos configurÃ¡veis (marketplace de integraÃ§Ãµes)
- âœ… Processamento de webhooks Bling via n8n â†’ Redis â†’ Worker
- âœ… ServiÃ§o de IA para pedidos personalizados (Gemini)
- âœ… Mapeamento de dados com mappers canÃ´nicos
- âœ… ImpressÃ£o de pedidos (print_service)

**Pontos que necessitam atenÃ§Ã£o** estÃ£o detalhados nas seÃ§Ãµes abaixo.

---

## 2. Arquitetura do Sistema

### 2.1 Componentes Existentes

| Componente | Tecnologia | Arquivo Principal | Status |
|---|---|---|---|
| **API Backend** | Flask (Python) | `apps/api/main.py` | âœ… Operacional |
| **Frontend** | React 19 + Vite + Tailwind | `apps/frontend/src/App.jsx` | âœ… Operacional |
| **Worker** | Celery + Redis | `apps/worker/worker_entrypoint.py` | âœ… Operacional |
| **Database** | Supabase (PostgreSQL 17) | `supabase/schema.sql` | âœ… Operacional |
| **Fila/Cache** | Redis 7 | `docker-compose.local.yml` | âœ… Operacional |
| **Shared Lib** | Python Package | `packages/shared/` | âœ… Operacional |
| **n8n** | Externo (webhook receiver) | Documentado em rotas | âš ï¸ NÃ£o embutido |

### 2.2 Fluxo de Webhooks (Conforme Documentado)

```
Bling Webhook â†’ n8n (valida HMAC) â†’ Redis (fila) â†’ Worker (consome) â†’ Supabase
```

**Arquivos relacionados:**
- `packages/shared/nistiprint_shared/services/webhook_service.py` - ValidaÃ§Ã£o HMAC e logging
- `apps/api/routes/webhooks.py` - Endpoint `/api/v2/webhooks/pedido-cancelado`
- `packages/shared/nistiprint_shared/services/redis_queue_tasks.py` - Task `consumir_fila_bling`
- `apps/worker/tasks/pedidos_fetch_tasks.py` - Task `fetch_pedidos_em_andamento`

---

## 3. Sistema de IntegraÃ§Ãµes

### 3.1 MÃ³dulos de IntegraÃ§Ã£o Existentes

| MÃ³dulo | Tipo | Arquivo DefiniÃ§Ã£o | Config Schema |
|---|---|---|---|
| **Bling ERP** | ERP | `apps/api/modules/platform_modules.py:get_bling_module_definition()` | âœ… OAuth2 + config schema completo |
| **Shopee** | Marketplace | `get_shopee_module_definition()` | âœ… OAuth2 + shop_id, partner_id, partner_key |
| **Mercado Livre** | Marketplace | `get_mercadolivre_module_definition()` | âœ… OAuth2 + client_id, client_secret |
| **Amazon** | Marketplace | `get_amazon_module_definition()` | âœ… OAuth2 + seller_id, mws_auth_token |
| **Shein** | Marketplace | `get_shein_module_definition()` | âœ… API Key + vendor_id |
| **TikTok Shop** | Marketplace | `get_tiktok_shop_module_definition()` | âœ… OAuth2 + app_key, app_secret |
| **Loja Integrada** | E-commerce | `get_loja_integrada_module_definition()` | âœ… API Key + app_key |

**ConclusÃ£o:** O sistema de mÃ³dulos **jÃ¡ existe** e Ã© baseado em `IntegrationModule` com:
- `config_schema` - Campos de configuraÃ§Ã£o que a UI exibe dinamicamente
- `auth_config` - ConfiguraÃ§Ã£o de OAuth/API
- `data_mapping_spec` - Mapeamento de campos
- Tags e categorias para organizaÃ§Ã£o

### 3.2 ServiÃ§os de Plataforma

| ServiÃ§o | Arquivo | FunÃ§Ã£o |
|---|---|---|
| Platform Auth | `platform_auth_service.py` | Gera URLs OAuth, exchange tokens, refresh |
| Platform API | `platform_api_service.py` | Chamadas genÃ©ricas a APIs de plataformas |
| Platform Drivers | `platform_drivers/*.py` | Drivers especÃ­ficos: `shopee.py`, `mercadolivre.py`, `amazon.py`, `shein.py`, `tiktok.py` |
| Platform Processor Registry | `platform_processor_registry.py` | Registro de processadores por plataforma |

### 3.3 Roteamento Multi-Conta

**Tabela:** `integration_account_routing`

| Campo | Tipo | DescriÃ§Ã£o |
|---|---|---|
| `id` | UUID | Primary Key |
| `module` | VARCHAR(50) | MÃ³dulo (ex: 'bling') |
| `function_name` | VARCHAR(50) | FunÃ§Ã£o (ORDER_IMPORT, NFE_EMISSION, STOCK_SYNC, CATALOG_SYNC) |
| `scope_type` | VARCHAR(20) | Escopo: GLOBAL, PLATFORM, CHANNEL |
| `scope_id` | VARCHAR(100) | ID do escopo (null para global) |
| `account_id` | VARCHAR(255) | ID da conta vinculada |
| `is_active` | BOOLEAN | Status da regra |

**ServiÃ§o:** `integration_routing_service.py`

**Hierarquia de resoluÃ§Ã£o:**
1. **Canal** (mais especÃ­fico) â†’ `scope_type='CHANNEL'`, `scope_id=channel_id`
2. **Plataforma** â†’ `scope_type='PLATFORM'`, `scope_id=platform_name`
3. **Global** (fallback) â†’ `scope_type='GLOBAL'`, `scope_id=NULL`

### 3.4 AssociaÃ§Ã£o ERP â†” Marketplace (Store ID Mapping)

**ServiÃ§o:** `integracao_canal_service.py`

| MÃ©todo | FunÃ§Ã£o |
|---|---|
| `get_canal_by_bling_loja_id(bling_loja_id)` | Resolve canal de venda a partir do ID de loja Bling |
| `get_bling_loja_id_by_canal(canal_venda_id)` | Resolve ID de loja Bling a partir do canal |
| `criar_vinculo(canal_venda_id, bling_loja_id, ...)` | Cria vÃ­nculo canalâ†”loja |
| `resolver_canal_para_pedido(bling_loja_id)` | Resolve canal para pedido |

**Tabelas envolvidas:**
- `channel_connections` - Tabela moderna com `aggregator_store_id`
- `integracao_canal_config` - Tabela legado com `bling_loja_id`
- `canais_venda` - Tabela de canais de venda com `bling_loja_id_principal`

**ConclusÃ£o:** O mapeamento **Bling Loja ID â†’ Conta Shopee** jÃ¡ Ã© implementado dinamicamente, substituindo o `constants.py` legado (`BLING_ID_LOJA`).

### 3.5 Features/Capacidades por IntegraÃ§Ã£o

O sistema atual define capacidades implicitamente via:
- `integration_account_routing.function_name` - FunÃ§Ãµes disponÃ­veis (ORDER_IMPORT, NFE_EMISSION, etc.)
- MÃ³dulos possuem `data_mapping_spec` e `auth_config` que definem o que cada integraÃ§Ã£o permite

**âš ï¸ Gap Identificado:** NÃ£o hÃ¡ um sistema explÃ­cito de "features/capacidades" por instÃ¢ncia de integraÃ§Ã£o (ex: "Bling 01 pode emitir NFe, Bling 02 nÃ£o"). Isso poderia ser adicionado como um campo `capabilities` ou `features` no schema de mÃ³dulo.

---

## 4. Pedidos

### 4.1 Fluxo de IngestÃ£o

```
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚                 Fontes de Pedidos                â”‚
â”œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¤
â”‚ 1. Webhook Bling â†’ n8n â†’ Redis â†’ Worker        â”‚
â”‚ 2. Upload de planilha (consolidaÃ§Ã£o)            â”‚
â”‚ 3. ImportaÃ§Ã£o manual via worker task            â”‚
â”‚ 4. Legacy sync (MySQL â†’ Supabase)               â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                         â”‚
                         â–¼
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚              Order Service (Core)                â”‚
â”‚  order_service.upsert_order()                    â”‚
â”‚  - Mappers: BlingMapper, ShopeeMapper            â”‚
â”‚  - Payload canÃ´nico                              â”‚
â”‚  - Timeline de eventos                           â”‚
â”‚  - VÃ­nculos de integraÃ§Ã£o                        â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                         â”‚
                         â–¼
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚                Tabelas Core                      â”‚
â”‚  pedidos (tabela principal)                      â”‚
â”‚  itens_pedido                                   â”‚
â”‚  vinculos_integracao_pedido                      â”‚
â”‚  eventos_pedido                                  â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
```

### 4.2 Tabelas de Pedidos

| Tabela | Finalidade | RLS |
|---|---|---|
| `pedidos` | Tabela core de pedidos | âœ… |
| `itens_pedido` | Itens de cada pedido | âœ… |
| `vinculos_integracao_pedido` | Links com plataformas externas | âœ… |
| `eventos_pedido` | Timeline de eventos | âœ… |
| `bling_pedidos` | Dados brutos Bling (legado) | âœ… |
| `bling_pedido_itens` | Itens brutos Bling | âœ… |
| `shopee_orders` | Pedidos Shopee (legado) | âœ… |

### 4.3 Campos Principais da Tabela `pedidos`

| Campo | Tipo | DescriÃ§Ã£o |
|---|---|---|
| `id` | INTEGER | PK auto |
| `numero_pedido` | VARCHAR | NÃºmero interno |
| `codigo_pedido_externo` | VARCHAR | ID externo (Ãºnico) |
| `origem` | VARCHAR | Plataforma de origem (BLING, SHOPEE, etc.) |
| `canal_venda_id` | INTEGER | FK â†’ canais_venda |
| `situacao_pedido_id` | INTEGER | FK â†’ situacoes_pedido |
| `is_flex` | BOOLEAN | Flag entrega Flex |
| `servico_logistico` | VARCHAR | ServiÃ§o logÃ­stico |
| `data_limite_envio` | TIMESTAMPTZ | Ship by date |
| `payload_canonico` | JSONB | Payload normalizado |
| `informacoes_cliente` | JSONB | Dados enriquecidos (buyer_username, shipping_carrier) |
| `cliente_nome`, `cliente_email`, `cliente_telefone` | VARCHAR | Dados do cliente |
| `total_pedido` | NUMERIC | Total do pedido |

### 4.4 IdentificaÃ§Ã£o de Marketplace via Loja ID

**ImplementaÃ§Ã£o atual:** `order_sync_service.py` + `integracao_canal_service.py`

```python
# Quando chega webhook Bling com loja_id=204047801:
loja_id = full_order_data.get('loja', {}).get('id')  # 204047801
canal_id = integracao_canal_service.get_canal_by_bling_loja_id(loja_id)
# â†’ Retorna canal Shopee configurado
```

**âœ… Funcionalidade implementada** - O sistema reconhece a origem do pedido e busca dados complementares do marketplace correto.

### 4.5 Dados Shopee EspecÃ­ficos

Os campos `buyer_username` e `shipping_carrier` sÃ£o:
- âœ… ExtraÃ­dos do payload Shopee no `ShopeeMapper`
- âœ… Armazenados em `informacoes_cliente` (JSONB)
- âœ… Usados para cÃ¡lculo automÃ¡tico de `is_flex` via trigger SQL

### 4.6 ImportaÃ§Ã£o de Pedidos

**ServiÃ§os existentes:**
| ServiÃ§o | Arquivo | FunÃ§Ã£o |
|---|---|---|
| Bling Order Processing | `bling_order_processing_service.py` | Processa webhooks Bling por situaÃ§Ã£o |
| Order Sync | `order_sync_service.py` | Sync Bling + Shopee unificado |
| Pedidos Bling Import | `pedidos_bling_import_service.py` | ImportaÃ§Ã£o em lote do Bling |
| File Processors | `file_processors.py` (legado) | Processa planilhas ML, Shopee, Amazon, Shein |
| Consolidation | `consolidation_service.py` | ConsolidaÃ§Ã£o automÃ¡tica |

**Worker Tasks:**
| Task | Arquivo | FrequÃªncia |
|---|---|---|
| `consumir_fila_bling` | `redis_queue_tasks.py` | 30s |
| `fetch_pedidos_em_andamento` | `pedidos_fetch_tasks.py` | PeriÃ³dica |
| `process_consolidacao` | `consolidation_tasks.py` | On-demand |
| `sync_orders_with_bling` | `consolidation_tasks.py` | On-demand |

**âš ï¸ Gap Identificado:** Cada mÃ³dulo de integraÃ§Ã£o **jÃ¡ tem** funÃ§Ãµes de importaÃ§Ã£o especÃ­ficas, mas a UI de seleÃ§Ã£o de instÃ¢ncias para importaÃ§Ã£o pode precisar de enhancements.

### 4.7 Pedidos Personalizados (IA)

**Fluxo legado convertido:**

| FunÃ§Ã£o Legada | Equivalente Novo | Arquivo |
|---|---|---|
| `kb/API/api.php` â†’ recebe msgs Chrome | `routes/personalizados.py` â†’ `/chat/<username>` | Novo |
| `kb/baixar_pedidos_bling/baixar_pedidos_bling.php` | `pedidos_bling_import_service.py` | Novo |
| `kb/legado/services/file_processors.py` | `file_processors.py` (shared) | Migrado |
| `kb/legado/services/ai_personalization_service.py` | `ai_personalization_service.py` (shared) | Migrado |

**ServiÃ§o de IA:**
- **Arquivo:** `packages/shared/nistiprint_shared/services/ai_personalization_service.py` (639 linhas)
- **Modelo:** Google Gemini `gemini-2.5-flash` via `GEMINI_API_KEY`
- **Funcionalidades:**
  - `process_orders()` - Processa pedidos com IA
  - `get_orders_with_chats()` - Busca pedidos com chats
  - `get_logs_by_order_sn()` - Logs de execuÃ§Ã£o
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

**âœ… Funcionalidade convertida** para a nova aplicaÃ§Ã£o.

---

## 5. ImpressÃ£o de Pedidos

### 5.1 ServiÃ§os Existentes

| ServiÃ§o | Arquivo | FunÃ§Ã£o |
|---|---|---|
| Print Service | `print_service.py` | GestÃ£o de jobs de impressÃ£o |
| Printing Routes | `routes/printing.py` | Endpoints `/api/v2/printing/*` |

### 5.2 Endpoints de ImpressÃ£o

| Endpoint | MÃ©todo | FunÃ§Ã£o |
|---|---|---|
| `/api/v2/printing/jobs` | GET | Lista jobs de impressÃ£o |
| `/api/v2/printing/job/<id>` | GET | Detalhe de job |
| `/api/v2/printing/demanda/<id>/print` | POST | Imprimir demanda |
| `/api/v2/printing/item/<id>/print` | POST | Imprimir item |

### 5.3 Templates de ImpressÃ£o

**Legado:** `kb/legado/templates/results.html` (466 linhas) - Template Jinja2 para impressÃ£o de pedidos por plataforma.

**Novo:** A funcionalidade de impressÃ£o agora pode buscar dados diretamente da base interna (`pedidos`, `itens_pedido`) ao invÃ©s de consultar APIs externas.

**âš ï¸ Oportunidade:** O template `results.html` legado pode ser adaptado para usar os dados normalizados da base Supabase, otimizando a geraÃ§Ã£o de documentos de produÃ§Ã£o.

---

## 6. Base de Dados - Resumo

### 6.1 EstatÃ­sticas

| MÃ©trica | Valor |
|---|---|
| Total de MigraÃ§Ãµes | 66 |
| ExtensÃµes Instaladas | 9 (pgcrypto, pg_stat_statements, supabase_vault, uuid-ossp, pg_graphql, index_advisor, hypopg) |
| ExtensÃµes DisponÃ­veis | 80+ |
| Tabelas Principais | ~50+ |
| Schemas | public, auth, storage |

### 6.2 Tabelas Principais por DomÃ­nio

#### Pedidos
| Tabela | Linhas | DescriÃ§Ã£o |
|---|---|---|
| `pedidos` | Core | Pedidos normalizados |
| `itens_pedido` | Core | Itens de pedidos |
| `vinculos_integracao_pedido` | Core | Links com plataformas externas |
| `eventos_pedido` | Core | Timeline de eventos |
| `bling_pedidos` | Legado | Dados brutos Bling |
| `bling_pedido_itens` | Legado | Itens brutos Bling |
| `shopee_orders` | Legado | Pedidos Shopee |

#### IntegraÃ§Ãµes
| Tabela | Linhas | DescriÃ§Ã£o |
|---|---|---|
| `installed_integrations` | Core | IntegraÃ§Ãµes instaladas |
| `integration_account_routing` | Core | Roteamento multi-conta |
| `integration_modules` | Core | MÃ³dulos disponÃ­veis |
| `channel_connections` | Core | ConexÃµes canalâ†”agregador |
| `integracao_canal_config` | Core | ConfiguraÃ§Ã£o canalâ†”Bling |
| `erp_marketplace_links` | Core | Links ERPâ†”Marketplace |
| `canais_venda` | Core | Canais de venda |
| `plataformas` | Core | Plataformas disponÃ­veis |
| `contas_bling` | Legado | Contas Bling (legado) |

#### ProduÃ§Ã£o e Demanda
| Tabela | Linhas | DescriÃ§Ã£o |
|---|---|---|
| `demandas_producao` | Core | Demandas de produÃ§Ã£o |
| `ordens_producao` | Core | Ordens de produÃ§Ã£o |
| `eventos_producao_v2` | Core | Eventos de produÃ§Ã£o (Event Sourcing) |
| `logs_producao_diaria` | Core | Logs diÃ¡rios |

#### Estoque
| Tabela | Linhas | DescriÃ§Ã£o |
|---|---|---|
| `produtos` | Core | Produtos |
| `estoque` | Core | Estoque |
| `movimentacoes_estoque` | Core | MovimentaÃ§Ãµes |
| `depositos` | Core | DepÃ³sitos |

#### IA e PersonalizaÃ§Ã£o
| Tabela | Linhas | DescriÃ§Ã£o |
|---|---|---|
| `order_personalizations` | Core | PersonalizaÃ§Ãµes de pedidos |
| `ai_execution_log` | Core | Logs de execuÃ§Ã£o IA |
| `v2_chat_events` | Core | Eventos de chat |

#### ImpressÃ£o
| Tabela | Linhas | DescriÃ§Ã£o |
|---|---|---|
| `print_jobs` | Core | Jobs de impressÃ£o |
| `product_artworks` | Core | Artes de produtos |

#### UsuÃ¡rios e PermissÃµes
| Tabela | Linhas | DescriÃ§Ã£o |
|---|---|---|
| `usuarios` | 5 | UsuÃ¡rios |
| `setores` | 5 | Setores |
| `recursos` | 8 | Recursos |
| `permissoes_setor` | 32 | PermissÃµes por setor |

### 6.3 Views Principais

| View | DescriÃ§Ã£o |
|---|---|
| `vendas_personalizadas` | Vendas com personalizaÃ§Ãµes IA |
| `pedidos_consolidar_v2` | Pedidos para consolidaÃ§Ã£o |
| `pedidos_para_consolidar` | Pedidos pendentes de consolidaÃ§Ã£o |
| `mensagens_chat` | Mensagens de chat unificadas |

### 6.4 FunÃ§Ãµes RPC Principais

| FunÃ§Ã£o | DescriÃ§Ã£o |
|---|---|
| `get_pedidos_com_filtros_avancados` | Consulta avanÃ§ada de pedidos |
| `get_pedidos_similares` | Encontra pedidos similares |
| `get_demandas_por_pedido_externo` | Demandas por pedido |
| `get_pedidos_por_demanda` | Pedidos por demanda |
| `get_alertas_producao` | Alertas de produÃ§Ã£o |
| `rpc_reconciliar_item_estoque` | ReconciliaÃ§Ã£o de estoque |

---

## 7. CÃ³digo Legado (ReferÃªncia)

### 7.1 Estrutura `kb/legado/`

| Arquivo/DiretÃ³rio | FunÃ§Ã£o | Status na Nova AplicaÃ§Ã£o |
|---|---|---|
| `app.py` | App Flask legado | âœ… SubstituÃ­do por `apps/api/main.py` |
| `constants.py` | Constantes (BLING_ID_LOJA, SITUACOES, etc.) | âœ… SubstituÃ­do por `integracao_canal_service.py` |
| `models/` (9 arquivos) | Modelos SQLAlchemy legado | âœ… Migrados para `packages/shared/models/` |
| `routes/` (21 arquivos) | Rotas Flask legado | âœ… Migrados para `apps/api/routes/` |
| `services/` (28 arquivos) | ServiÃ§os legado | âœ… Migrados para `packages/shared/services/` |
| `templates/results.html` | Template de impressÃ£o | âš ï¸ Pode ser adaptado |

### 7.2 CÃ³digo PHP Legado

| Arquivo | FunÃ§Ã£o | Equivalente Novo |
|---|---|---|
| `kb/API/api.php` | Recebe msgs Chrome, salva na base | `routes/personalizados.py` |
| `kb/atualizar base - pedidos/baixar_pedidos_bling.php` | Baixa pedidos do Bling | `pedidos_bling_import_service.py` |
| `kb/bling_token_manager/` | GestÃ£o de tokens Bling | `token_manager/` (shared) |

---

## 8. Gaps e RecomendaÃ§Ãµes

### 8.1 Gaps Identificados

| # | Gap | Severidade | RecomendaÃ§Ã£o |
|---|---|---|---|
| 1 | **Sistema de Features/Capacidades por IntegraÃ§Ã£o** | Baixa | Adicionar campo `capabilities` ou `features` no schema de mÃ³dulo/integraÃ§Ã£o para indicar o que cada instÃ¢ncia permite (ex: emissÃ£o de NFe, sync de estoque) |
| 2 | **ConfiguraÃ§Ã£o DinÃ¢mica de Campos de IntegraÃ§Ã£o** | MÃ©dia | O `config_schema` jÃ¡ existe nos mÃ³dulos, mas a UI (`BlingInstanceConfigModal.tsx`) pode precisar de melhorias para renderizar campos dinamicamente a partir do schema |
| 3 | **Template de ImpressÃ£o Normalizado** | MÃ©dia | Adaptar `kb/legado/templates/results.html` para usar dados da base Supabase ao invÃ©s de chamadas externas |
| 4 | **DocumentaÃ§Ã£o do Fluxo n8n** | Baixa | O n8n Ã© mencionado como receptor de webhooks, mas nÃ£o hÃ¡ workflows/arquivos de configuraÃ§Ã£o do n8n no repositÃ³rio |

### 8.2 Pontos Fortes

| # | Ponto Forte | DescriÃ§Ã£o |
|---|---|---|
| 1 | **Arquitetura de MÃ³dulos** | Sistema de `IntegrationModule` com `config_schema` permite adicionar novas integraÃ§Ãµes sem alterar cÃ³digo core |
| 2 | **Roteamento Multi-Conta** | `integration_account_routing` com hierarquia GLOBAL â†’ PLATFORM â†’ CHANNEL resolve o problema de mÃºltiplas contas elegantemente |
| 3 | **Mappers CanÃ´nicos** | `BlingMapper` e `ShopeeMapper` normalizam payloads de diferentes plataformas |
| 4 | **Payload CanÃ´nico** | Campo `payload_canonico` (JSONB) armazena dados normalizados para consulta |
| 5 | **Timeline de Eventos** | `eventos_pedido` rastreia todas as mudanÃ§as de status e origem dos dados |
| 6 | **ProteÃ§Ã£o de Dados Flex** | LÃ³gica de proteÃ§Ã£o contra sobrescrita de dados Flex jÃ¡ implementada no `order_service.py` |
| 7 | **IA de PersonalizaÃ§Ã£o** | ServiÃ§o completo com Gemini, prompts configurÃ¡veis, feedback do usuÃ¡rio, e logs detalhados |

---

## 9. Mapa Completa de Arquivos por Objetivo

### 9.1 Webhooks (Bling, Shopee)

| Arquivo | FunÃ§Ã£o |
|---|---|
| `packages/shared/nistiprint_shared/services/webhook_service.py` | ValidaÃ§Ã£o HMAC e logging de webhooks |
| `packages/shared/nistiprint_shared/services/bling_order_processing_service.py` | Processa webhooks Bling por situaÃ§Ã£o |
| `packages/shared/nistiprint_shared/services/redis_queue_tasks.py` | Task Celery para consumir fila Redis |
| `apps/worker/tasks/pedidos_fetch_tasks.py` | Fetch manual de pedidos "Em Andamento" |
| `apps/api/routes/webhooks.py` | Endpoint `/api/v2/webhooks/pedido-cancelado` |
| `apps/api/routes/integracoes.py` | Rotas de integraÃ§Ã£o (status, renovar token, routing) |

### 9.2 IntegraÃ§Ãµes (ERP + Marketplace)

| Arquivo | FunÃ§Ã£o |
|---|---|
| `apps/api/modules/platform_modules.py` | DefiniÃ§Ã£o de mÃ³dulos de plataforma |
| `apps/api/modules/register_modules.py` | Registro de mÃ³dulos no marketplace |
| `packages/shared/nistiprint_shared/services/integration_module_service.py` | GestÃ£o de mÃ³dulos de integraÃ§Ã£o |
| `packages/shared/nistiprint_shared/services/installed_integration_service.py` | GestÃ£o de instalaÃ§Ãµes ativas |
| `packages/shared/nistiprint_shared/services/integration_routing_service.py` | Roteamento multi-conta |
| `packages/shared/nistiprint_shared/services/integracao_canal_service.py` | VÃ­nculos canalâ†”loja Bling |
| `packages/shared/nistiprint_shared/services/erp_marketplace_links_service.py` | Links ERPâ†”Marketplace |
| `packages/shared/nistiprint_shared/services/platform_auth_service.py` | OAuth para plataformas |
| `packages/shared/nistiprint_shared/services/platform_api_service.py` | Chamadas genÃ©ricas a APIs |
| `packages/shared/nistiprint_shared/services/platform_drivers/*.py` | Drivers: shopee, ml, amazon, shein, tiktok |
| `packages/shared/nistiprint_shared/services/bling/bling_client.py` | Cliente API Bling (1134 linhas) |
| `packages/shared/nistiprint_shared/services/conta_bling_service.py` | GestÃ£o de contas Bling |
| `apps/api/routes/marketplace_api_routes.py` | CRUD de marketplace de integraÃ§Ãµes |
| `apps/api/routes/integracoes.py` | Rotas de integraÃ§Ã£o |
| `apps/api/routes/integrations.py` | Rotas admin de contas Bling |
| `apps/api/routes/erp_links.py` | Links ERP-Marketplace |
| `apps/frontend/src/pages/integracoes/BlingInstanceConfigModal.tsx` | Modal config Bling |
| `apps/frontend/src/components/marketplace/InstallWizard.jsx` | Wizard de instalaÃ§Ã£o |
| `apps/frontend/src/services/MarketplaceService.js` | ServiÃ§o frontend marketplace |
| `kb/legado/constants.py` | Constantes legado (referÃªncia) |

### 9.3 Pedidos

| Arquivo | FunÃ§Ã£o |
|---|---|
| `packages/shared/nistiprint_shared/services/order_service.py` | ServiÃ§o core de pedidos (upsert, mappers, eventos) |
| `packages/shared/nistiprint_shared/mappers/order_mappers.py` | Mappers Bling e Shopee |
| `packages/shared/nistiprint_shared/services/order_sync_service.py` | Sync de pedidos Bling + Shopee |
| `packages/shared/nistiprint_shared/services/bling_order_processing_service.py` | Processamento webhooks Bling |
| `packages/shared/nistiprint_shared/services/pedidos_bling_import_service.py` | ImportaÃ§Ã£o em lote do Bling |
| `packages/shared/nistiprint_shared/services/file_processors.py` | Processamento de planilhas |
| `packages/shared/nistiprint_shared/services/consolidation_service.py` | ConsolidaÃ§Ã£o de pedidos |
| `apps/api/routes/pedidos.py` | Rotas de gestÃ£o de pedidos |
| `apps/api/routes/orders.py` | Rotas de consulta de pedidos |
| `apps/api/routes/unified_orders.py` | VisÃ£o unificada de pedidos |
| `apps/api/routes/pedidos_gestao.py` | GestÃ£o avanÃ§ada de pedidos |
| `apps/api/routes/vendas.py` | Rotas de vendas |
| `apps/worker/tasks/consolidation_tasks.py` | Tasks de consolidaÃ§Ã£o |
| `apps/frontend/src/pages/pedidos/PedidosListPage.jsx` | Lista de pedidos |
| `apps/frontend/src/pages/pedidos/PedidoDetalhePage.jsx` | Detalhe do pedido |
| `apps/frontend/src/services/orderService.js` | ServiÃ§o de pedidos |
| `packages/shared/nistiprint_shared/models/pedido.py` | Modelo de pedido |
| `packages/shared/nistiprint_shared/models/bling_pedidos.py` | Modelo Bling pedidos |
| `packages/shared/nistiprint_shared/models/shopee_orders.py` | Modelo Shopee pedidos |
| `packages/shared/nistiprint_shared/models/vinculos_integracao_pedido.py` | Modelo de vÃ­nculos |
| `packages/shared/nistiprint_shared/models/eventos_pedido.py` | Modelo de eventos |
| `kb/legado/services/file_processors.py` | File processors legado (referÃªncia) |
| `kb/API/api.php` | API PHP legado (referÃªncia) |
| `kb/atualizar base - pedidos/baixar_pedidos_bling.php` | Script PHP legado (referÃªncia) |

### 9.4 IA de PersonalizaÃ§Ã£o

| Arquivo | FunÃ§Ã£o |
|---|---|
| `packages/shared/nistiprint_shared/services/ai_personalization_service.py` | ServiÃ§o de IA (Gemini) - 639 linhas |
| `apps/api/routes/personalizados.py` | Endpoints de personalizados |
| `apps/worker/tasks/personalizados_tasks.py` | Task Celery de personalizaÃ§Ã£o |
| `packages/shared/nistiprint_shared/models/order_personalizations.py` | Modelo de personalizaÃ§Ãµes |
| `packages/shared/nistiprint_shared/models/ai_execution_log.py` | Modelo de logs IA |
| `packages/shared/nistiprint_shared/models/supabase_ai_log.py` | Modelo de logs Supabase |
| `packages/shared/nistiprint_shared/templates/prompts/` | Templates de prompt |
| `apps/frontend/src/pages/ai/AIDashboardPage.jsx` | Dashboard IA |
| `apps/frontend/src/pages/ai/AIStatusBadge.jsx` | Badge de status |
| `apps/frontend/src/pages/ai/ChatViewer.jsx` | Visualizador de chats |
| `apps/frontend/src/pages/configuracoes/ConfiguracoesIA` | ConfiguraÃ§Ã£o IA |
| `apps/frontend/src/services/aiService.ts` | ServiÃ§o frontend IA |
| `kb/legado/services/ai_personalization_service.py` | IA legado (referÃªncia) |

### 9.5 ImpressÃ£o

| Arquivo | FunÃ§Ã£o |
|---|---|
| `packages/shared/nistiprint_shared/services/print_service.py` | ServiÃ§o de impressÃ£o |
| `apps/api/routes/printing.py` | Endpoints de impressÃ£o |
| `packages/shared/nistiprint_shared/models/print_job.py` | Modelo de job |
| `packages/shared/nistiprint_shared/models/product_artwork.py` | Modelo de arte |
| `apps/frontend/src/pages/impressao/FilaImpressao.jsx` | Fila de impressÃ£o |
| `apps/frontend/src/services/PrintService.js` | ServiÃ§o frontend |
| `kb/legado/templates/results.html` | Template de impressÃ£o legado (referÃªncia) |

---

## 10. ConclusÃ£o

O codebase atual demonstra **alta aderÃªncia** com os objetivos descritos. A arquitetura jÃ¡ implementa:

1. âœ… **MÃºltiplas contas Bling** com roteamento dinÃ¢mico via `integration_account_routing`
2. âœ… **MÃºltiplas contas de Marketplace** com drivers especÃ­ficos por plataforma
3. âœ… **AssociaÃ§Ã£o ERPâ†”Marketplace** via `erp_store_id`, `aggregator_store_id`, e `integracao_canal_service`
4. âœ… **Sistema de mÃ³dulos configurÃ¡veis** com `config_schema` para UI dinÃ¢mica
5. âœ… **Processamento de webhooks** via n8n â†’ Redis â†’ Worker
6. âœ… **IA para pedidos personalizados** com Gemini, prompts configurÃ¡veis, e feedback
7. âœ… **Mapeamento de dados** com mappers canÃ´nicos (BlingMapper, ShopeeMapper)
8. âœ… **ImpressÃ£o de pedidos** com print_service e endpoints dedicados

**Principais gaps:**
- Sistema explÃ­cito de features/capacidades por instÃ¢ncia de integraÃ§Ã£o
- Template de impressÃ£o adaptado para base normalizada
- ConfiguraÃ§Ã£o n8n embutida no repositÃ³rio

O sistema estÃ¡ em **estado avanÃ§ado de maturidade** e pronto para evoluÃ§Ã£o contÃ­nua.
