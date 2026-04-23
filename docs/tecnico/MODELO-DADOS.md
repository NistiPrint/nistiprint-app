# Modelo de Dados - Nistiprint

**Última atualização:** 2026-04-02  
**Status:** Consolidado

Este documento consolida o modelo entidade-relacionamento (ER) do sistema Nistiprint, com foco nas entidades de produção, pedidos e integrações.

---

## Visão Geral do Modelo

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                            ECOSSISTEMA DE PRODUÇÃO                              │
└─────────────────────────────────────────────────────────────────────────────────┘

                                    ┌─────────────────┐
                                    │   PLATAFORMA    │
                                    │  (sistema ext.) │
                                    │  Shopee, Amazon │
                                    └────────┬────────┘
                                             │ 1:N
                                             ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              CANAL DE VENDA                                     │
│  - Instância que se relaciona com uma plataforma                                │
│  - Possui configurações específicas                                             │
│  - Pode ter múltiplas integrações                                               │
│                                                                                 │
│  ATRIBUTOS ESPECIAIS:                                                           │
│  • flex: boolean           → Entrega rápida/urgente                             │
│  • fulfillment: boolean    → Fulfillment externo                                │
│  • horario_coleta: time    → Horário de coleta padrão                           │
│  • color: string           → Cor para UI                                        │
└─────────────────────────────────────────────────────────────────────────────────┘
          │                              │                              │
          │ 1:N                          │ 1:N                          │ 1:N
          ▼                              ▼                              ▼
┌──────────────────┐          ┌──────────────────┐          ┌──────────────────┐
│   INTEGRAÇÕES    │          │  MODALIDADE      │          │   PONTOS DE      │
│ (configuração)   │          │  LOGÍSTICA       │          │   COLETA         │
│ - Bling ERP      │          │ - STANDARD       │          │ - Regras de      │
│ - Shopee         │          │ - EXPRESS (FLEX) │          │   horário        │
│ - Amazon         │          │ - FULFILLMENT    │          │                  │
│ - Mercado Livre  │          │ - RETIRADA       │          │                  │
└──────────────────┘          └────────┬─────────┘          └────────┬─────────┘
                                       │                              │
                                       │ N:1                          │ N:1
                                       ▼                              │
                              ┌──────────────────┐                    │
                              │     PEDIDOS      │◄───────────────────┘
                              │  (vendas indiv.) │  (recebe pedidos)
                              └────────┬─────────┘
                                       │ N:M
                                       │ consolidado em
                                       ▼
                              ┌──────────────────┐
                              │ DEMANDAS_PEDIDOS │
                              │   (tabela N:N)   │
                              └────────┬─────────┘
                                       │ N:1
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         DEMANDAS_PRODUCAO (CENTRO)                              │
│  (ordem de fabricação para a fábrica)                                           │
│                                                                                 │
│  ATRIBUTOS PRINCIPAIS:                                                          │
│  • status: AGUARDANDO, EM_PRODUCAO, CONCLUIDO                                   │
│  • modalidade_logistica: STANDARD, EXPRESS, FULFILLMENT, RETIRADA               │
│  • is_flex: boolean          → Entrega urgente (mesmo dia)                      │
│  • fulfillment: boolean      → Reposição externa                                │
│  • categoria_temporal: URGENTE, HOJE, AMANHA, FUTURO                            │
│  • horario_coleta: time      → Quando deve ser coletado                         │
│                                                                                 │
│  CICLO DE VIDA DA CONSOLIDAÇÃO:                                                 │
│  RASCUNHO → AGUARDANDO → EM_PRODUCAO → COLETA_PARCIAL → CONCLUIDO               │
│                                                                                 │
│  ┌───────────────────────────────────────────────────────────────────────────┐ │
│  │ ITENS_DEMANDA (1:N) - Controle de Produção                                │ │
│  │ • capas_impressas_qtd, capas_produzidas_qtd                               │ │
│  │ • miolos_prontos_retirada_qtd, finalizados_qtd                            │ │
│  │ • status_item: PENDENTE, PROCESSANDO, CONCLUIDO                           │ │
│  └───────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 1. Integrações e Canais

### 1.1 `plataformas`

Sistemas externos que se integram ao Nistiprint.

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | integer | PK |
| `nome` | varchar(100) | Nome único (ex: "Shopee", "Bling") |
| `tipo` | varchar(50) | `MARKETPLACE`, `ERP`, `ECOMMERCE` |
| `ativa` | boolean | Status da plataforma |
| `configuracao` | jsonb | Config específica |

### 1.2 `integration_modules`

Catálogo de conectores disponíveis.

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | text | PK (ex: 'shopee', 'amazon', 'bling') |
| `name` | text | Nome amigável |
| `tipo` | varchar(50) | `MARKETPLACE`, `ERP`, `ECOMMERCE` |
| `slug` | varchar(100) | Identificador URL-friendly |
| `is_aggregator` | boolean | True se é agregador (ex: Bling) |
| `config_schema` | jsonb | Schema de configuração (JSON Schema) |
| `auth_flow` | text | `OAuth2`, `API_KEY`, etc. |
| `is_active` | boolean | Status do módulo |

### 1.3 `installed_integrations`

Instâncias ativas de integrações.

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | integer | PK |
| `module_id` | varchar(100) | FK → integration_modules.id |
| `instance_name` | varchar(255) | Nome da instância |
| `access_token` | text | Token de acesso |
| `refresh_token` | text | Token de refresh |
| `expires_at` | timestamptz | Expiração do token |
| `config` | jsonb | Configurações específicas |
| `is_active` | boolean | Status |
| `last_sync` | timestamptz | Última sincronização |
| `sync_status` | varchar(50) | `pending`, `success`, `error` |

### 1.4 `channel_connections`

**Nova arquitetura.** Vínculo entre canal e integração.

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | uuid | PK |
| `channel_id` | integer | FK → canais_venda.id |
| `integration_id` | integer | FK → installed_integrations.id |
| `aggregator_store_id` | varchar(255) | Loja no agregador (ex: bling_loja_id) |
| `aggregator_store_name` | varchar(255) | Nome da loja |
| `bling_integration_id` | integer | FK → installed_integrations (Bling) |
| `marketplace_integration_id` | integer | FK → installed_integrations |
| `config` | jsonb | Configurações |
| `is_active` | boolean | Status |
| `last_sync` | timestamptz | Última sincronização |

### 1.5 `canais_venda`

Instâncias específicas de venda.

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | integer | PK |
| `nome` | varchar(100) | Nome único |
| `plataforma_id` | integer | FK → plataformas.id |
| `conta_bling_id` | varchar(255) | ID da conta Bling vinculada |
| `horario_coleta` | time | Horário de coleta padrão |
| `flex` | boolean | Entrega rápida/urgente |
| `fulfillment` | boolean | Fulfillment externo |
| `color` | varchar(7) | Cor para UI |
| `ativo` | boolean | Status |

---

## 2. Regras Logísticas

### 2.1 `pontos_coleta`

Locais de coleta/entrega.

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | integer | PK |
| `nome` | varchar(255) | Nome do ponto |
| `horario_corte_padrao` | time | Horário de corte |
| `endereco` | text | Endereço completo |
| `ativo` | boolean | Status |

### 2.2 `regras_logisticas_canal`

Regras de logística por canal e modalidade.

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | integer | PK |
| `canal_venda_id` | integer | FK → canais_venda.id |
| `modalidade` | varchar(50) | `STANDARD`, `EXPRESS`, `FULFILLMENT`, `RETIRADA` |
| `tipo_envio` | varchar(50) | `COLETA_LOCAL`, `PONTO_COLETA` |
| `horario_limite` | time | Horário de corte para despacho |
| `ponto_coleta_id` | integer | FK → pontos_coleta.id |
| `prioridade_uso` | integer | Prioridade de aplicação |

### 2.3 `canal_modalidade_mapeamento`

**Consolidação.** Mapeia `servico_logistico` → `modalidade`.

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | bigserial | PK |
| `canal_venda_id` | bigint | FK → canais_venda.id |
| `padrao_servico` | varchar(255) | Padrão LIKE (ex: '%flex%') |
| `modalidade` | varchar(50) | `STANDARD`, `EXPRESS`, `FULFILLMENT`, `RETIRADA` |
| `prioridade` | integer | Maior = mais específico |
| `ativo` | boolean | Status |

**Exemplo:**
```sql
INSERT INTO canal_modalidade_mapeamento (canal_venda_id, padrao_servico, modalidade, prioridade) VALUES
  (1, '%flex%', 'EXPRESS', 10),
  (1, '%rápida%', 'EXPRESS', 10),
  (1, '%normal%', 'STANDARD', 5);
```

### 2.4 `regras_consolidacao_canal`

**Consolidação.** Configura agrupamento de pedidos por canal/modalidade.

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | bigserial | PK |
| `canal_venda_id` | bigint | FK → canais_venda.id (NULL = regra global) |
| `modalidade` | varchar(50) | (NULL = todas) |
| `agrupar_por_produto` | boolean | Agrupa por produto |
| `agrupar_por_miolo` | boolean | Agrupa por miolo |
| `agrupar_por_data_entrega` | boolean | Agrupa por data |
| `janela_agrupamento_horas` | integer | Janela deslizante (0 = demanda direta) |
| `comportamento_pos_edicao` | varchar(30) | `ADICIONAR_COM_SINALIZACAO`, `CRIAR_NOVO_RASCUNHO` |
| `comportamento_pos_publicacao` | varchar(30) | `CRIAR_NOVO_RASCUNHO`, `SUGERIR_FUSAO` |
| `ativo` | boolean | Status |

**Exemplo:**
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

---

## 3. Pedidos

### 3.1 `pedidos`

Pedido core (dados normalizados).

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | integer | PK |
| `uuid_pedido` | varchar(36) | ID universal único |
| `numero_pedido` | varchar(50) | ID amigável |
| `codigo_pedido_externo` | varchar(100) | ID na plataforma externa |
| `origem` | varchar(50) | `SHOPEE`, `BLING`, `MANUAL` |
| `canal_venda_id` | integer | FK → canais_venda.id |
| `cliente_nome` | varchar(255) | Nome do cliente |
| `cliente_documento` | varchar(50) | CPF/CNPJ |
| `cliente_telefone` | varchar(50) | Telefone |
| `cliente_email` | varchar(255) | E-mail |
| `situacao_pedido_id` | integer | FK → situacoes_pedido.id |
| `total_pedido` | numeric(15,2) | Valor total |
| `data_venda` | timestamp | Data da venda |
| `is_flex` | boolean | Herdado do canal |
| `servico_logistico` | varchar(255) | Serviço recebido (ex: "Entrega Rápida Shopee") |
| `data_limite_envio` | timestamp | Deadline de envio |
| `payload_canonico` | jsonb | Dados normalizados |

### 3.2 `itens_pedido`

Itens dos pedidos.

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | integer | PK |
| `pedido_id` | integer | FK → pedidos.id |
| `produto_id` | integer | FK → produtos.id |
| `sku_externo` | varchar(100) | SKU na plataforma |
| `descricao` | varchar(500) | Descrição do item |
| `quantidade` | numeric(10,4) | Quantidade |
| `preco_unitario` | numeric(15,2) | Preço unitário |
| `subtotal` | numeric(15,2) | Subtotal |

### 3.3 `vinculos_integracao_pedido`

Vínculos com plataformas externas.

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | uuid | PK |
| `pedido_id` | integer | FK → pedidos.id |
| `plataforma` | varchar(50) | `BLING`, `SHOPEE`, etc. |
| `id_na_plataforma` | varchar(100) | ID externo |
| `status_na_plataforma` | varchar(50) | Status na plataforma |
| `dados_brutos` | jsonb | Payload original |
| `last_synced_at` | timestamptz | Última sincronização |

### 3.4 `pedidos_nao_classificados`

**Consolidação.** Fila de atenção para pedidos sem modalidade mapeada.

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | bigserial | PK |
| `pedido_id` | bigint | FK → pedidos.id |
| `canal_venda_id` | bigint | FK → canais_venda.id |
| `servico_logistico_recebido` | varchar(500) | Serviço recebido |
| `tentativas_classificacao` | integer | Tentativas de classificação |
| `resolvido` | boolean | Status da resolução |
| `resolvido_em` | timestamptz | Data da resolução |
| `resolvido_por` | integer | FK → usuarios.id |
| `modalidade_atribuida` | varchar(50) | Modalidade atribuída manualmente |

---

## 4. Demandas de Produção

### 4.1 `demandas_producao`

Ordem de fabricação para a fábrica.

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | integer | PK |
| `demanda_id` | varchar(255) | ID único (Firestore) |
| `descricao` | text | Descrição |
| `produto_id` | integer | FK → produtos.id |
| `quantidade` | integer | Quantidade total |
| `data_entrega` | date | Deadline de entrega |
| `prioridade` | integer | Score calculado |
| `prioridade_manual` | integer | Boost manual |
| `status` | varchar(50) | `RASCUNHO`, `AGUARDANDO`, `EM_PRODUCAO`, `CONCLUIDO` |
| `canal_venda_id` | integer | FK → canais_venda.id |
| `modalidade_logistica` | varchar(20) | `STANDARD`, `EXPRESS`, `FULFILLMENT`, `RETIRADA` |
| `horario_coleta` | time | Horário de coleta |
| `is_flex` | boolean | Entrega urgente |
| `fulfillment` | boolean | Reposição externa |
| `tipo_demanda` | varchar(50) | `PLATAFORMA`, `B2B`, `FULFILLMENT`, `ESTOQUE_INTERNO` |
| `classificacao_cliente` | varchar(10) | `B2C`, `B2B`, `INTERNO` |
| `categoria_temporal` | text | `URGENTE`, `HOJE`, `AMANHA`, `FUTURO` |
| `observacoes` | text | Observações |
| `pedido_numero` | varchar(100) | Número do pedido (demanda direta) |
| `data_conclusao` | timestamp | Data de conclusão |
| `data_limite_execucao` | date | Deadline de produção |
| `setores_envolvidos` | jsonb | Setores necessários (BOM) |

#### Colunas de Consolidação (Rascunho)

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `rascunho_expira_em` | timestamptz | Janela deslizante de agrupamento |
| `editado_pelo_usuario` | boolean | Edição humana realizada |
| `editado_em` | timestamptz | Data da edição |
| `editado_por` | integer | FK → usuarios.id |
| `pedidos_apos_edicao_qtd` | integer | Pedidos chegados após edição |
| `requer_revisao` | boolean | Flag de revisão pendente |
| `publicado_em` | timestamptz | Data da publicação |
| `publicado_por` | integer | FK → usuarios.id |

### 4.2 `itens_demanda`

Itens da demanda com controle de produção.

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | integer | PK |
| `demanda_id` | integer | FK → demandas_producao.id |
| `produto_id` | integer | FK → produtos.id |
| `sku` | varchar(100) | SKU |
| `descricao` | varchar(500) | Descrição |
| `quantidade` | integer | Quantidade planejada |
| `miolo_nome` | varchar(255) | Nome do miolo |
| `id_produto_miolo` | integer | FK → produtos.id |
| `variacao` | varchar(255) | Variação |

#### Controle de Produção

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `capas_impressas_qtd` | integer | Capas impressas |
| `capas_produzidas_qtd` | integer | Capas finalizadas |
| `capas_prontas_retirada_qtd` | integer | Capas disponíveis |
| `miolos_prontos_retirada_qtd` | integer | Miolos disponíveis |
| `expedicao_capas_retiradas_qtd` | integer | Capas retiradas |
| `expedicao_miolos_retirados_qtd` | integer | Miolos retirados |
| `finalizados_qtd` | integer | Total finalizado |
| `status_item` | varchar(50) | `PENDENTE`, `PROCESSANDO`, `CONCLUIDO` |

### 4.3 `demandas_pedidos`

**Consolidação.** Tabela pivot N:N para rastreabilidade.

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | bigserial | PK |
| `demanda_id` | bigint | FK → demandas_producao.id |
| `pedido_id` | bigint | FK → pedidos.id |
| `adicionado_apos_edicao` | boolean | Pedido chegou após edição |
| `adicionado_em` | timestamptz | Data do vínculo |

**Restrição:**
```sql
CONSTRAINT uq_demandas_pedidos_demanda_pedido UNIQUE (demanda_id, pedido_id)
```

### 4.4 `entregas_producao`

Coletas parciais de demandas.

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | integer | PK |
| `demanda_id` | integer | FK → demandas_producao.id |
| `item_demanda_id` | integer | FK → itens_demanda.id |
| `quantidade` | integer | Quantidade entregue |
| `data_entrega` | date | Data da entrega |
| `user_id` | integer | FK → usuarios.id |

---

## 5. Produtos e Estoque

### 5.1 `produtos`

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | integer | PK |
| `sku` | varchar(100) | SKU único |
| `nome` | varchar(255) | Nome do produto |
| `formato` | varchar(50) | `SIMPLES`, `COM_VARIACAO`, `VARIACAO`, `COMPOSICAO`, `KIT` |
| `parent_id` | integer | FK → produtos.id (produto pai) |
| `herdar_dados_pai` | boolean | Herda dados do pai |
| `herdar_bom_pai` | boolean | Herda BOM do pai |
| `preco_custo` | numeric(15,2) | Preço de custo |
| `setor_responsavel_id` | integer | FK → setores.id |
| `material_type` | varchar(50) | `MATERIA_PRIMA`, `INTERMEDIARIO`, `PRODUTO_ACABADO`, `SERVICO` |
| `status` | varchar(50) | `ATIVO`, `RASCUNHO`, `INATIVO` |

### 5.2 `produtos_externos`

Mapeamento de produtos externos.

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | integer | PK |
| `produto_id` | integer | FK → produtos.id |
| `codigo_externo` | varchar(100) | SKU externo |
| `plataforma` | varchar(50) | `BLING`, `SHOPEE`, `MERCADOLIVRE`, `AMAZON` |

### 5.3 `bom_producao`

Ficha técnica (BOM).

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | integer | PK |
| `produto_pai_id` | integer | FK → produtos.id |
| `componente_id` | integer | FK → produtos.id |
| `quantidade` | numeric(10,4) | Quantidade do componente |

### 5.4 `estoque_atual`

Saldos de estoque.

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | integer | PK |
| `produto_id` | integer | FK → produtos.id |
| `deposito_id` | integer | FK → depositos.id |
| `saldo_atual` | numeric(15,4) | Saldo atual |
| `reservado` | numeric(15,4) | Quantidade reservada |

### 5.5 `movimentacoes_estoque`

Histórico de movimentações.

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | integer | PK |
| `produto_id` | integer | FK → produtos.id |
| `tipo_movimentacao` | varchar(50) | `ENTRADA`, `SAIDA`, `BALANCO`, `TRANSFERENCIA` |
| `quantidade` | numeric(15,4) | Quantidade |
| `deposito_id` | integer | FK → depositos.id |
| `user_id` | integer | FK → usuarios.id |

---

## 6. Contexto de Produção e UX

### 6.1 `contextos_producao`

**UX.** Snapshot unificado para ordenação inteligente.

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | uuid | PK |
| `tipo` | varchar(50) | `PEDIDO_UNICO`, `DEMANDA_CONSOLIDADA` |
| `demanda_id` | integer | FK → demandas_producao.id |
| `pedido_id` | integer | FK → pedidos.id |
| `snapshot_plataforma` | jsonb | {nome, tipo, pedido_externo_id} |
| `snapshot_integracao` | jsonb | {marketplace_integration_id, bling_loja_id} |
| `snapshot_logistica` | jsonb | {modalidade, horario_corte, is_flex} |
| `snapshot_temporal` | jsonb | {data_pedido, data_limite_envio, categoria_temporal} |
| `snapshot_priorizacao` | jsonb | {score, fatores, prioridade_manual} |

### 6.2 `regras_priorizacao`

**UX.** Regras configuráveis de ordenação.

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | integer | PK |
| `nome` | varchar(255) | Nome da regra |
| `condicoes` | jsonb | {modalidade_logistica: ['EXPRESS'], is_flex: true} |
| `acao_tipo` | varchar(50) | `ADD_SCORE`, `SET_PRIORIDADE`, `MOVER_TOPO` |
| `acao_valor` | integer | Valor da ação |
| `prioridade_regra` | integer | Prioridade da regra |
| `ativa` | boolean | Status |

### 6.3 `sinalizacoes_demanda`

**UX.** Alertas visuais para o usuário.

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | integer | PK |
| `demanda_id` | integer | FK → demandas_producao.id |
| `tipo` | varchar(50) | `FLEX`, `FULFILLMENT`, `HORARIO_CORTE_PROXIMO`, `ESTOQUE_INSUFICIENTE` |
| `severidade` | varchar(20) | `INFO`, `ATENCAO`, `CRITICO` |
| `mensagem` | text | Mensagem do alerta |
| `lida` | boolean | Status de leitura |

### 6.4 `preferencias_ux_usuario`

**UX.** Preferências de interface.

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | integer | PK |
| `user_id` | integer | FK → usuarios.id |
| `vista_padrao` | varchar(50) | `KANBAN`, `LISTA`, `CALENDARIO` |
| `ordenacao_padrao` | varchar(50) | `PRIORIDADE`, `HORARIO_CORTE`, `DATA_ENTREGA` |
| `agrupamento_padrao` | varchar(50) | `CANAL`, `MODALIDADE`, `SETOR`, `STATUS` |
| `auto_fill_enabled` | boolean | Habilitar autopreenchimento |
| `filtros_salvos` | jsonb | Presets de filtros |

---

## 7. Funções e Triggers SQL

### 7.1 Funções de Consolidação

```sql
-- Derivar modalidade a partir de servico_logistico
derivar_modalidade_logistica(p_canal_venda_id BIGINT, p_servico_logistico TEXT)
RETURNS VARCHAR(50)

-- Buscar regras de consolidação
get_regras_consolidacao_canal(p_canal_venda_id BIGINT, p_modalidade VARCHAR)
RETURNS TABLE (...)

-- Verificar se rascunho expirou
rascunho_expirado(p_demanda_id BIGINT)
RETURNS BOOLEAN

-- Contar pedidos novos após edição
contar_pedidos_novos_apos_edicao(p_demanda_id BIGINT)
RETURNS INTEGER
```

### 7.2 Triggers

```sql
-- Atualizar requer_revisao quando pedidos_apos_edicao_qtd > 0
CREATE TRIGGER trg_atualizar_requer_revisao
BEFORE INSERT OR UPDATE OF pedidos_apos_edicao_qtd
ON demandas_producao
FOR EACH ROW EXECUTE FUNCTION fn_atualizar_requer_revisao();

-- Atualizar updated_at automaticamente
CREATE TRIGGER update_canal_modalidade_mapeamento_updated_at
BEFORE UPDATE ON canal_modalidade_mapeamento
FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
```

---

## 8. Índices Principais

```sql
-- Canal Modalidade
CREATE INDEX idx_canal_modalidade_canal ON canal_modalidade_mapeamento(canal_venda_id) WHERE ativo = true;
CREATE INDEX idx_canal_modalidade_canal_modalidade ON canal_modalidade_mapeamento(canal_venda_id, modalidade) WHERE ativo = true;

-- Regras de Consolidação
CREATE INDEX idx_regras_consolidacao_canal ON regras_consolidacao_canal(canal_venda_id) WHERE ativo = true;
CREATE INDEX idx_regras_consolidacao_global ON regras_consolidacao_canal(modalidade) WHERE ativo = true AND canal_venda_id IS NULL;

-- Pedidos Não Classificados
CREATE INDEX idx_pedidos_nao_classificados_canal ON pedidos_nao_classificados(canal_venda_id) WHERE resolvido = false;
CREATE INDEX idx_pedidos_nao_classificados_pendentes ON pedidos_nao_classificados(created_at DESC) WHERE resolvido = false;

-- Demandas Pedidos
CREATE INDEX idx_demandas_pedidos_demanda ON demandas_pedidos(demanda_id);
CREATE INDEX idx_demandas_pedidos_pedido ON demandas_pedidos(pedido_id);

-- Vínculos de Integração
CREATE INDEX idx_vinculos_plataforma_id ON vinculos_integracao_pedido(plataforma, id_na_plataforma);
```

---

## 9. Políticas de RLS (Row Level Security)

Todas as tabelas principais possuem políticas para usuários autenticados:

```sql
-- Exemplo: canal_modalidade_mapeamento
CREATE POLICY "authenticated_view_canal_modalidade"
ON canal_modalidade_mapeamento FOR SELECT TO authenticated USING (true);

CREATE POLICY "authenticated_insert_canal_modalidade"
ON canal_modalidade_mapeamento FOR INSERT TO authenticated WITH CHECK (true);

CREATE POLICY "authenticated_update_canal_modalidade"
ON canal_modalidade_mapeamento FOR UPDATE TO authenticated USING (true);

CREATE POLICY "authenticated_delete_canal_modalidade"
ON canal_modalidade_mapeamento FOR DELETE TO authenticated USING (true);
```

---

## 10. Referências de Implementação

### Models Python
| Arquivo | Entidade |
|---------|----------|
| `packages/shared/nistiprint_shared/models/canal_venda.py` | Canais de Venda |
| `packages/shared/nistiprint_shared/models/pedido.py` | Pedidos, ItensPedido |
| `packages/shared/nistiprint_shared/models/demanda_producao.py` | Demandas, ItensDemanda |
| `packages/shared/nistiprint_shared/models/canal_modalidade_mapeamento.py` | Mapeamento de Modalidade |
| `packages/shared/nistiprint_shared/models/regras_consolidacao_canal.py` | Regras de Consolidação |
| `packages/shared/nistiprint_shared/models/regra_logistica.py` | Regras Logísticas |

### Migrations
| Arquivo | Descrição |
|---------|-----------|
| `supabase/migrations/20260402000014_consolidacao_simples.sql` | Consolidação (tabelas principais) |
| `supabase/migrations/20260402000004_regras_consolidacao_canal.sql` | Regras de consolidação |
| `supabase/migrations/20260324000002_demandas_pedidos_pivot.sql` | Tabela pivot N:N |
| `supabase/migrations/20260329000004_contexto_producao_ux.sql` | Contexto de produção e UX |

---

*Documento consolidado em 2026-04-02*
