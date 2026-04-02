# Arquitetura de Contexto de Produção e Otimização de UX

## Visão Geral

Este documento descreve a arquitetura implementada para sintetizar o relacionamento entre as entidades do sistema de produção, com foco em:

1. **Ordenação inteligente de produção** baseada em regras de negócio
2. **Sinalização contextual** para guiar o usuário
3. **Otimização de UX** para reduzir carga cognitiva
4. **Autopreenchimento inteligente** aproveitando dados cadastrados

---

## Diagrama de Relacionamento entre Entidades

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
                                             │
                                             ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              CANAL DE VENDA                                     │
│  - Instância que se relaciona com uma plataforma                                │
│  - Possui configurações específicas                                             │
│  - Pode ter múltiplas integrações                                               │
└─────────────────────────────────────────────────────────────────────────────────┘
          │                              │                              │
          │ 1:N                          │ 1:N                          │ 1:N
          ▼                              ▼                              ▼
┌──────────────────┐          ┌──────────────────┐          ┌──────────────────┐
│   INTEGRAÇÕES    │          │  MODALIDADE      │          │   PONTOS DE      │
│ (configuração)   │          │  LOGÍSTICA       │          │   COLETA         │
│ - Bling ERP      │          │ - STANDARD       │          │ - Comércio de    │
│ - Shopee         │          │ - EXPRESS (FLEX) │          │   terceiros      │
│ - Amazon         │          │ - FULFILLMENT    │          │ - Regras de      │
│ - Mercado Livre  │          │ - RETIRADA       │          │   horário        │
└──────────────────┘          └────────┬─────────┘          └────────┬─────────┘
                                       │                              │
                                       │ N:1                          │ N:1
                                       ▼                              │
                              ┌──────────────────┐                    │
                              │     PEDIDOS      │◄───────────────────┘
                              │  (venda externa) │  (recebe pedidos)
                              │ - Registro de    │
                              │   venda          │
                              └────────┬─────────┘
                                       │ 1:N
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              DEMANDAS                                           │
│  (conjunto de pedidos para acompanhamento da produção)                          │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                    CONTEXTO DE PRODUÇÃO                                 │   │
│  │  (nova entidade que sintetiza todas as relações)                        │   │
│  │                                                                         │   │
│  │  - Snapshot da plataforma                                               │   │
│  │  - Snapshot da integração                                               │   │
│  │  - Snapshot logístico                                                   │   │
│  │  - Snapshot temporal                                                    │   │
│  │  - Score de priorização                                                 │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                    SINALIZAÇÕES                                         │   │
│  │  (alertas visuais para guiar o usuário)                                 │   │
│  │                                                                         │   │
│  │  - FLEX (entrega no mesmo dia)                                          │   │
│  │  - FULFILLMENT (reposição externa)                                      │   │
│  │  - HORÁRIO_CORTE_PRÓXIMO (alerta de prazo)                              │   │
│  │  - ESTOQUE_INSUFICIENTE (produção incompleta)                           │   │
│  │  - PRODUÇÃO_ATRASADA (risco de atraso)                                  │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Entidades Implementadas

### 1. Contexto de Produção (`contextos_producao`)

**Propósito:** Sintetizar todas as relações para uma demanda/pedido em uma única estrutura.

**Campos principais:**
- `tipo`: PEDIDO_UNICO ou DEMANDA_CONSOLIDADA
- `snapshot_plataforma`: {nome, tipo, pedido_externo_id}
- `snapshot_integracao`: {marketplace_integration_id, bling_integration_id, bling_loja_id}
- `snapshot_logistica`: {modalidade, tipo_envio, ponto_coleta, horario_corte, is_flex, is_fulfillment}
- `snapshot_temporal`: {data_pedido, data_limite_envio, categoria_temporal, deadline_final}
- `snapshot_priorizacao`: {score, fatores, prioridade_manual}

**Benefícios:**
- Consulta rápida sem joins complexos
- Base para ordenação inteligente
- Facilita frontend com dados pré-processados

---

### 2. Regras de Priorização (`regras_priorizacao`)

**Propósito:** Modelar regras de negócio para ordenação de produção de forma configurável.

**Estrutura:**
```json
{
  "nome": "Prioridade FLEX",
  "descricao": "Pedidos FLEX têm prioridade máxima",
  "condicoes": {
    "modalidade_logistica": ["EXPRESS"],
    "is_flex": true
  },
  "acao": {
    "tipo": "ADD_SCORE",
    "valor": 100,
    "fatores": ["FLEX"]
  },
  "ativa": true,
  "prioridade_regra": 100
}
```

**Tipos de ação:**
- `ADD_SCORE`: Adiciona pontos ao score
- `SET_PRIORIDADE`: Define prioridade fixa
- `MOVER_TOPO`: Move para o topo da lista
- `ADIAR`: Reduz prioridade

---

### 3. Sinalizações de Demanda (`sinalizacoes_demanda`)

**Propósito:** Alertas visuais para guiar o usuário com informações contextuais.

**Tipos:**
| Tipo | Severidade | Descrição |
|------|------------|-----------|
| FLEX | INFO/ATENCAO | Destaca pedidos com entrega no mesmo dia |
| FULFILLMENT | INFO | Reposição de fulfillment externo |
| HORARIO_CORTE_PROXIMO | ATENCAO | Horário de corte nas próximas 2 horas |
| ESTOQUE_INSUFICIENTE | CRITICO | Produção incompleta |
| PRODUCAO_ATRASADA | CRITICO | Risco de atraso na entrega |
| INTEGRACAO_ERRO | CRITICO | Erro de sincronização com plataforma |

---

### 4. Preferências de UX (`preferencias_ux_usuario`)

**Propósito:** Personalizar a experiência do usuário e reduzir carga cognitiva.

**Configurações:**
- `vista_padrao`: KANBAN, LISTA, CALENDARIO
- `ordenacao_padrao`: PRIORIDADE, HORARIO_CORTE, DATA_ENTREGA
- `agrupamento_padrao`: CANAL, MODALIDADE, SETOR, STATUS
- `auto_fill_enabled`: Habilitar autopreenchimento
- `filtros_salvos`: Presets de filtros
- `atalhos_personalizados`: Atalhos de teclado customizados

---

### 5. Templates de Observações (`templates_obs_canal`)

**Propósito:** Autopreencher observações baseadas em templates configuráveis.

**Exemplo:**
```
Template: "Pedido {{pedido_numero}} - Entrega {{data_entrega}} - {{plataforma}}"
Variáveis: ['pedido_numero', 'data_entrega', 'plataforma']
```

---

## Fluxo de Ordenação para Produção

```
┌─────────────────────────────────────────────────────────────────┐
│                    ORDEM DE PRODUÇÃO                            │
├─────────────────────────────────────────────────────────────────┤
│  1. Coletar demandas AGUARDANDO/EM_PRODUCAO                     │
│                                                                 │
│  2. Para cada demanda, construir ContextoProducao:              │
│     - Buscar dados da demanda                                   │
│     - Buscar canal de venda                                     │
│     - Buscar regras logísticas                                  │
│     - Buscar integração                                         │
│     - Calcular snapshots                                        │
│                                                                 │
│  3. Aplicar RegrasPriorizacao → calcular score                 │
│     - Verificar condições de cada regra                         │
│     - Aplicar ações (ADD_SCORE, SET_PRIORIDADE, etc)            │
│     - Coletar fatores de priorização                            │
│                                                                 │
│  4. Gerar SinalizacoesDemanda:                                  │
│     - check_flex()                                              │
│     - check_fulfillment()                                       │
│     - check_horario_corte_proximo()                             │
│     - check_estoque_insuficiente()                              │
│     - check_producao_atrasada()                                 │
│                                                                 │
│  5. Ordenar por:                                                │
│     a) mover_topo (desc)                                        │
│     b) prioridade_calculada (desc)                              │
│     c) priority_score (desc)                                    │
│     d) is_flex (desc)                                           │
│     e) horario_coleta (asc)                                     │
│     f) data_entrega (asc)                                       │
│                                                                 │
│  6. Retornar lista ordenada com contextos e sinalizações        │
└─────────────────────────────────────────────────────────────────┘
```

---

## Fluxo de Criação de Demanda com UX Otimizada

```
┌─────────────────────────────────────────────────────────────────┐
│              CRIAÇÃO DE DEMANDA - UX OTIMIZADA                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  PASSO 1: Selecionar Origem                                     │
│  → [Importar de Pedido] ou [Criar Manualmente]                  │
│                                                                 │
│  PASSO 2: Selecionar Canal                                      │
│  → Sistema carrega regras logísticas do canal                   │
│  → Autopreenche: modalidade, horario_coleta, ponto_coleta       │
│                                                                 │
│  PASSO 3: Selecionar Modalidade (se múltiplas)                  │
│  → Sistema atualiza horário de coleta                           │
│  → Sistema define flags is_flex, fulfillment                    │
│                                                                 │
│  PASSO 4: Adicionar Produtos                                    │
│  → Sistema calcula setores envolvidos (via BOM)                 │
│  → Sistema estima tempo de produção                             │
│  → Sistema sugere data_limite_execucao                          │
│                                                                 │
│  PASSO 5: Definir Prazo                                         │
│  → Sistema valida: horario_coleta < horario_corte_ponto         │
│  → Sistema valida: data_entrega é viável                        │
│  → Alertas visuais se houver conflito                           │
│                                                                 │
│  PASSO 6: Revisar e Confirmar                                   │
│  → Todos campos preenchidos automaticamente                     │
│  → Validações passaram                                          │
│  → [CRIAR DEMANDA] (1 clique)                                   │
│                                                                 │
│  TOTAL DE CLIQUES: ~5 (vs. ~15 no fluxo atual)                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Serviços Implementados

### Backend (Python)

| Serviço | Arquivo | Responsabilidade |
|---------|---------|------------------|
| `ContextoProducaoService` | `contexto_producao_service.py` | Construir contextos unificados |
| `PriorizacaoService` | `priorizacao_service.py` | Aplicar regras de priorização |
| `SinalizacaoService` | `sinalizacao_service.py` | Gerar sinalizações visuais |
| `DemandaAutoFillService` | `demanda_autofill_service.py` | Autopreenchimento inteligente |
| `UserPreferenceService` | `user_preference_service.py` | Gerenciar preferências de UX |

### Frontend (TypeScript)

| Tipo | Arquivo | Responsabilidade |
|------|---------|------------------|
| `ContextoProducao` | `types/producao.ts` | Interface de contexto |
| `RegraPriorizacao` | `types/producao.ts` | Interface de regra |
| `SinalizacaoDemanda` | `types/producao.ts` | Interface de sinalização |
| `DemandaFormDefaults` | `types/producao.ts` | Interface de autopreenchimento |

---

## Endpoints API

### Contexto de Produção

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| GET | `/api/v2/producao-contexto/producao/contexto/ordenacao` | Lista demandas ordenadas |
| GET | `/api/v2/producao-contexto/producao/contexto/demanda/<id>` | Contexto de uma demanda |
| GET | `/api/v2/producao-contexto/producao/contexto/pedido/<id>` | Contexto de um pedido |

### Regras de Priorização

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| GET | `/api/v2/producao-contexto/producao/regras-priorizacao` | Listar regras |
| POST | `/api/v2/producao-contexto/producao/regras-priorizacao` | Criar regra |
| PUT | `/api/v2/producao-contexto/producao/regras-priorizacao/<id>` | Atualizar regra |
| DELETE | `/api/v2/producao-contexto/producao/regras-priorizacao/<id>` | Excluir regra |
| POST | `/api/v2/producao-contexto/producao/regras-priorizacao/<id>/toggle` | Alternar ativo/inativo |

### Sinalizações

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| GET | `/api/v2/producao-contexto/producao/sinalizacoes/demanda/<id>` | Listar sinalizações |
| POST | `/api/v2/producao-contexto/producao/sinalizacoes/demanda/<id>/generate` | Gerar sinalizações |
| POST | `/api/v2/producao-contexto/producao/sinalizacoes/<id>/read` | Marcar como lida |
| POST | `/api/v2/producao-contexto/producao/sinalizacoes/demanda/<id>/read-all` | Marcar todas como lidas |

### Autopreenchimento (UX)

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| GET | `/api/v2/producao-contexto/producao/autofill/canal/<canal_id>` | Defaults por canal |
| POST | `/api/v2/producao-contexto/producao/autofill/modalidade` | Defaults por modalidade |
| POST | `/api/v2/producao-contexto/producao/autofill/data-limite` | Calcular data limite |
| POST | `/api/v2/producao-contexto/producao/autofill/setores` | Obter setores envolvidos |
| POST | `/api/v2/producao-contexto/producao/autofill/validar-horario` | Validar horário coleta |
| POST | `/api/v2/producao-contexto/producao/autofill/validar-data` | Validar data entrega |
| GET | `/api/v2/producao-contexto/producao/autofill/template-obs/<canal_id>` | Template observações |

### Preferências de Usuário

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| GET | `/api/v2/producao-contexto/producao/preferencias` | Obter preferências |
| POST | `/api/v2/producao-contexto/producao/preferencias` | Salvar preferências |
| GET | `/api/v2/producao-contexto/producao/preferencias/filtros` | Filtros salvos |
| POST | `/api/v2/producao-contexto/producao/preferencias/filtros` | Salvar filtro |
| POST | `/api/v2/producao-contexto/producao/preferencias/auto-fill/toggle` | Toggle autofill |

---

## Tabela de Autopreenchimento

| Campo da Demanda | Fonte do Dado | Gatilho |
|-----------------|---------------|---------|
| `canal_venda_id` | Pedido ou último usado | Selecionar pedido / Abrir formulário |
| `horario_coleta` | `regras_logisticas_canal.horario_limite` | Selecionar canal + modalidade |
| `modalidade_logistica` | `regras_logisticas_canal.modalidade` | Selecionar canal |
| `ponto_coleta_id` | `regras_logisticas_canal.ponto_coleta_id` | Selecionar canal + tipo_envio |
| `tipo_demanda` | Inferido do canal | Selecionar canal |
| `classificacao_cliente` | Inferido do tipo_demanda | Selecionar tipo_demanda |
| `is_flex` | `modalidade_logistica == 'EXPRESS'` | Selecionar modalidade |
| `fulfillment` | `modalidade_logistica == 'FULFILLMENT'` | Selecionar modalidade |
| `setores_envolvidos` | BOM dos produtos | Adicionar produtos |
| `data_limite_execucao` | `data_entrega - tempo_producao` | Definir data_entrega |
| `observacoes` | Template do canal | Selecionar canal |

---

## Benefícios Esperados

### Técnicos
- [ ] Ordenação inteligente baseada em regras de negócio
- [ ] Sinalização visual contextual
- [ ] Visão completa do ciclo pedido→produção→entrega
- [ ] Regras de priorização configuráveis (não hard-coded)
- [ ] Arquitetura extensível para novas plataformas

### UX / Negócio
- [ ] Redução de carga cognitiva (usuário não precisa decorar informações)
- [ ] Menos cliques (~5 vs ~15 no fluxo atual)
- [ ] Menos erros (validações automáticas)
- [ ] Curva de aprendizado acelerada para novos usuários
- [ ] Produtividade aumentada com ações em massa e atalhos

---

## Próximos Passos

1. **Frontend:** Implementar componentes React para:
   - Card de demanda com sinalizações visuais
   - Formulário de demanda com autopreenchimento
   - Painel de regras de priorização
   - Gerenciador de preferências de usuário

2. **Integração:** Conectar novos serviços às rotas existentes de demandas

3. **Testes:** Criar testes unitários para os serviços implementados

4. **Migração:** Executar migration no banco de dados

5. **Documentação:** Atualizar documentação da API

---

## Referências

- Migration SQL: `supabase/migrations/20260329000004_contexto_producao_ux.sql`
- Models TypeScript: `apps/frontend/src/types/producao.ts`
- Serviços Python: `packages/shared/nistiprint_shared/services/`
- Rotas API: `apps/api/routes/producao_contexto.py`
