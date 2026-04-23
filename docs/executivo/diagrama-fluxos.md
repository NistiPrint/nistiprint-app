# 🎯 DIAGRAMAS VISUAIS - FLUXOS DA SOLUÇÃO

---

## PROBLEMA 1: Rastreamento Pedidos ↔ Demandas

### Fluxo ATUAL (Incompleto)

```
┌─────────────────────────────────────────────────────────────────┐
│                        BANCO DE DADOS                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  pedidos_bling                demandas_item_origem             │
│  ┌──────────────────┐         ┌──────────────────┐             │
│  │ id               │         │ id               │             │
│  │ numero_pedido    │    _____|> pedido_externo_ │             │
│  │ codigo_pedido_   │   /     │  id (FK) ❌ NÃO │             │
│  │ externo    ─────────┘      │  CONSULTADA!     │             │
│  │ bling_id         │         │  demanda_item_id │             │
│  │ personalizado    │         │  quantidade      │             │
│  └──────────────────┘         └────────┬─────────┘             │
│                                        │                       │
│                                        │ LEFT JOIN             │
│                                        ▼                       │
│                              itens_demanda                    │
│                              ┌──────────────────┐             │
│                              │ id               │             │
│                              │ demanda_id ─────────┐          │
│                              │ produto_id       │  │          │
│                              │ quantidade       │  │          │
│                              └──────────────────┘  │          │
│                                                    │          │
│                                    ┌───────────────┘          │
│                                    │ LEFT JOIN                │
│                                    ▼                          │
│                              demandas_producao               │
│                              ┌──────────────────┐             │
│                              │ id               │             │
│                              │ demanda_numero   │             │
│                              │ status           │             │
│                              │ data_entrega     │             │
│                              └──────────────────┘             │
│                                                              │
│  ❌ PROBLEMA:                                                │
│  - SQL join correto, mas não executado em nenhum lugar      │
│  - API não expõe dados de rastreamento                       │
│  - Frontend não mostra relacionamento                        │
│  - Usuário não consegue clicar "pedido → demanda"           │
└─────────────────────────────────────────────────────────────────┘
```

### Fluxo DESEJADO (Implementação)

```
┌──────────────────────────────────────────────────────────────────────┐
│                          USUÁRIO FRONTEND                            │
└──────────────────────────────────────────────────────────────────────┘
                   │                              │
                   │ Clica "Ver Demandas"        │ Clica "Ver Pedidos"
                   │                              │
                   ▼                              ▼
    ┌──────────────────────────────┐  ┌──────────────────────────────┐
    │ PedidosListPage              │  │ DemandaDetailPage            │
    │ • Coluna "Status Demanda"    │  │ • Aba "Pedidos Origem"       │
    │ • Link para demanda #123     │  │ • Lista de pedidos           │
    │ • Badge "PENDENTE"           │  │ • Navegação para pedido      │
    └──────────────────────────────┘  └──────────────────────────────┘
                   │                              │
                   │ GET               │ GET /api/v2/demandas/{id}/
                   │ /pedidos/{id}/    │            pedidos
                   │ demandas          │
                   │                   │
                   └───────┬───────────┘
                           │
                           ▼
    ┌──────────────────────────────────────────────────────┐
    │           API Layer (Backend)                        │
    │  ┌────────────────────────────────────────────────┐  │
    │  │ routes/demandas.py                             │  │
    │  │  GET /<demanda_id>/pedidos                     │  │
    │  │  GET /<demanda_id>/rastreamento              │  │
    │  └────────────────────────────────────────────────┘  │
    │  ┌────────────────────────────────────────────────┐  │
    │  │ routes/pedidos.py                              │  │
    │  │  GET /<pedido_id>/demandas                     │  │
    │  └────────────────────────────────────────────────┘  │
    └──────────────────────────────────────────────────────┘
                           │
                           │ SELECT via v_pedido_demanda_rastreamento
                           │
                           ▼
    ┌──────────────────────────────────────────────────────┐
    │              SQL VIEW (Novo)                         │
    │  ┌────────────────────────────────────────────────┐  │
    │  │ v_pedido_demanda_rastreamento                  │  │
    │  │                                                │  │
    │  │ SELECT                                         │  │
    │  │   pb.numero_pedido,                            │  │
    │  │   dio.quantidade_atendida,                     │  │
    │  │   dp.demanda_numero,                           │  │
    │  │   dp.status                                    │  │
    │  │ FROM pedidos_bling pb                          │  │
    │  │ LEFT JOIN demandas_item_origem dio            │  │
    │  │   ON pb.codigo_pedido_externo =                │  │
    │  │       dio.pedido_externo_id ✅ FK CORRETO     │  │
    │  │ LEFT JOIN itens_demanda id                    │  │
    │  │   ON dio.demanda_item_id = id.id              │  │
    │  │ LEFT JOIN demandas_producao dp                │  │
    │  │   ON id.demanda_id = dp.id                    │  │
    │  └────────────────────────────────────────────────┘  │
    └──────────────────────────────────────────────────────┘
```

### Exemplo de Resultado

```
ENTRADA: Pedido #2024-01-15-SHOP-001 (Shopee)

CONSULTA:
  GET /api/v2/pedidos/123/demandas

RESPOSTA:
{
  "sucesso": true,
  "numero_pedido": "2024-01-15-SHOP-001",
  "demandas": [
    {
      "demanda_id": 45,
      "demanda_numero": "DEM-2024-001",
      "demanda_status": "PENDENTE",
      "dados_entrega": "2024-02-15",
      "tipo_demanda": "PLATAFORMA",
      "quantidade_atendida": 50,
      "criado_em": "2024-01-16T10:30:00Z"
    }
  ]
}

UI RENDERIZADA:
┌─────────────────────────┐
│ Pedido #2024-01-...     │
│ DEMANDA VINCULADA:      │  ← COLUNA NOVA
│ [DEM-2024-001 PENDENTE] │  ← LINK CLICÁVEL
│ (Criado: 2024-01-16)    │
└─────────────────────────┘
```

---

## PROBLEMA 2: IA & Identificação (Redundância)

### Fluxo ATUAL (Confuso)

```
┌────────────────────────────────────────────────────────────────┐
│                       USUÁRIO                                  │
└────────────────────────────────────────────────────────────────┘
    │                  │                    │
    │ Menu 1           │ Menu 2             │ Menu 3
    ▼                  ▼                    ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ /vendas/pers │  │ /vendas/id-  │  │ /ai/logs     │
│ onalizadas   │  │ ia           │  └──────────────┘
│              │  │              │
│ ✅ FUNCIONA  │  │ ❌ VAZIA     │
│ (pedidos +   │  │ (não mostra  │
│  botão IA)   │  │  dados)      │
└──────────────┘  └──────────────┘
    │                  │
    └──────┬───────────┘ (MESMO RESULTADO ESPERADO)
           │
           ▼
    ┌──────────────────────────┐
    │ Backend (2 Serviços)     │
    │                          │
    │ ❌ ai_personalization_   │
    │    service.py (~900 L)   │ ← Monolítico
    │    • Gemini              │
    │    • Chat Shopee         │
    │    • Logs                │
    │    • Batch processing    │
    │                          │
    │ ❌ personalized_order_   │
    │    identifier.py         │ ← Duplicado
    │    (~280 L)              │
    │    • Identificação rápida│
    │    • DB lookup           │
    │                          │
    │ ❚❚ NÃO COORDENADOS      │
    └──────────────────────────┘
```

### Fluxo DESEJADO (UX Consolidada)

✅ **Serviços já funcionam OK! Apenas consolidar menus na UI.**

```
┌────────────────────────────────────────────────────────────────┐
│                       USUÁRIO                                  │
└────────────────────────────────────────────────────────────────┘
    │
    │ Menu único: "Pedidos Personalizados"
    │
    ▼
┌────────────────────────────────────────────────────────────────┐
│ /vendas/personalizadas  (TELA ÚNICA)                          │
│                                                                │
│ ┌──────────────────────────────────────────────────────────┐  │
│ │ Abas: [Pendentes] [Identificados] [Histórico] [Logs IA] │  │
│ └──────────────────────────────────────────────────────────┘  │
│                                                                │
│ 📌 Aba "Pendentes Extração"                                    │
│ ┌──────────────────────────────────────────────────────────┐  │
│ │ Pedido   │ Status          │ Ações                        │  │
│ │──────────┼─────────────────┼────────────────────────────│  │
│ │ #2024-01 │ Personalizado   │ [Extrair com IA]          │  │
│ │ #2024-02 │ ⏳ Processando  │ ⏳ Aguarde...              │  │
│ │ #2024-03 │ ✅ Extraído     │ ✅ "Agenda X" (nome)       │  │
│ └──────────────────────────────────────────────────────────┘  │
│                                                                │
│ 📌 Aba "Logs IA"                                               │
│ ┌──────────────────────────────────────────────────────────┐  │
│ │ Pedido   │ Nome Extraído │ Status       │ Tempo         │  │
│ │──────────┼───────────────┼──────────────┼───────────────│  │
│ │ #2024-01 │ "Agenda X"    │ ✅ Sucesso   │ 1.5s         │  │
│ │ #2024-02 │ "Livro Y"     │ ✅ Sucesso   │ 2.1s         │  │
│ │ #2024-03 │ (falhou)      │ ❌ Falha     │ 30s          │  │
│ └──────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────┘

NOTA: Redirecionar /ai e /vendas/identificacao-ia → /vendas/personalizadas
      Serviços Python/SQL: ZERO MUDANÇAS (já funcionam corretamente)
```

---

## PROBLEMA 3: Worker & Auto-Consolidação

### Fluxo ATUAL (Manual)

```
┌─────────────────────────────────────────────────────────────┐
│                    PLATAFORMAS                              │
│        (Shopee/ML/Amazon/Bling)                             │
└─────────────────────────────────────────────────────────────┘
                           │
                           │ Webhook POST /webhook/pedido
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ Worker (Celery)                                             │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ sync_pedidos_bling()                                    │ │
│ │  ├─ upsert_order() ✅                                   │ │
│ │  └─ ❌ NÃO CONSOLIDA (pula etapa)                       │ │
│ │                                                         │ │
│ │ sync_pedidos_shopee()                                   │ │
│ │  ├─ upsert_order() ✅                                   │ │
│ │  └─ ❌ NÃO CONSOLIDA                                    │ │
│ └─────────────────────────────────────────────────────────┘ │
│  ⚠️ PROBLEMA: Consolidação = MANUAL (usuário upload arquivo)│
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
                    ┌──────────────┐
                    │ BD: pedidos   │ ← Inserido mas
                    │              │  não agrupado
                    └──────────────┘
                           │
                    ❌ PARADO AQUI
                           │
  ┌─────────────────────────────────────────────────┐
  │ MANUAL: Usuário inicia /consolidar (upload file)│
  └─────────────────────────────────────────────────┘
                           │
                           ▼
                    ┌──────────────────┐
                    │ demandas_producao │ ← RASCUNHO
                    │ (status=RASCUNHO) │   criado
                    └──────────────────┘
                           │
                           ▼ (usuário revisa manualmente)
                    ┌──────────────────┐
                    │ Status PENDENTE   │
                    │ (vai para produção)
                    └──────────────────┘
```

### Fluxo DESEJADO (Automático)

```
┌─────────────────────────────────────────────────────────────┐
│                    PLATAFORMAS                              │
│        (Shopee/ML/Amazon/Bling)                             │
└─────────────────────────────────────────────────────────────┘
                           │
                           │ Webhook POST /webhook/pedido
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ Worker (Celery) - REFATORADO                                │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ sync_pedidos_bling()                                    │ │
│ │  ├─ upsert_order() ✅                                   │ │
│ │  ├─ auto_consolidate_pedido.delay(pedido_id)  ← NOVO   │ │
│ │  └─ [opcionalmente] process_ia_personalization()       │ │
│ │                                                         │ │
│ │ auto_consolidate_pedido(pedido_id)  ← TASK NOVA        │ │
│ │  ├─ Buscar pedido                                       │ │
│ │  ├─ Resolver modalidade                                │ │
│ │  ├─ Buscar rascunho compatível                         │ │
│ │  │   ├─ Encontrado → adicionar item + log INFO        │ │
│ │  │   └─ Não → criar novo rascunho + log INFO          │ │
│ │  └─ ✅ Salvar resultado em worker_logs                 │ │
│ │                                                         │ │
│ │ processar_lote_rascunhos()  ← AGENDADO (30 min)        │ │
│ │  ├─ Validar rascunhos <24h                             │ │
│ │  ├─ Consolidar últimos pedidos                         │ │
│ │  └─ ✅ Log saúde dos rascunhos                         │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                           │
                           │ Em tempo real
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ BD: Tabelas Novas/Atualizadas                                │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  pedidos → demandas_producao                                │
│  (pedido entra automaticamente em rascunho < 10s)            │
│                                                              │
│  worker_logs ← Correlação completa                          │
│  • task_name: "auto_consolidate_pedido"                     │
│  • level: "INFO" / "ERROR"                                  │
│  • pedido_id: 123                                           │
│  • demanda_id: 45                                           │
│  • timestamp + traceback se erro                            │
│                                                              │
│  demandas_producao                                          │
│  • status: RASCUNHO (aguardando revisão)                    │
│  • created_at: 2024-01-16 10:30:15 (logo após webhook)      │
│                                                              │
└──────────────────────────────────────────────────────────────┘
                           │
                           │ Usuário vê em tempo real
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ Frontend: Rascunhos (NOVA PÁGINA)                            │
│ /demandas/rascunhos   (ou aba em demandas)                   │
│                                                              │
│ ┌────────────────────────────────────────────────────────┐   │
│ │ Rascunhos de Consolidação                              │   │
│ │ ┌──────────────────────────────────────────────────────┤   │
│ │ │ Demanda #DEM-2024-001      Criado: há 2 minutos ✨  │   │
│ │ │ Produto: Agenda X          [Expandir v]             │   │
│ │ │ Modalidade: EXPRESS         [Confirmar] [Descartar]  │   │
│ │ │                                                      │   │
│ │ │ ┌─ Pedidos neste Rascunho                          │   │
│ │ │ │ #2024-01 (50 un) Shopee                          │   │
│ │ │ │ #2024-02 (25 un) ML                               │   │
│ │ │ │ #2024-03 (100 un) Bling                           │   │
│ │ │ └─────────────────────────────────────────────────  │   │
│ │ │ Total: 175 unidades                                 │   │
│ │ └──────────────────────────────────────────────────────┤   │
│ │                                                        │   │
│ │ │ Demanda #DEM-2024-002      Criado: há 5 minutos    │   │
│ │ │ [...]                                               │   │
│ │ └──────────────────────────────────────────────────────┤   │
│ │                                                        │   │
│ │ ⏱️ Processamento em lote: Próximo em 25 minutos       │   │
│ └────────────────────────────────────────────────────────┘   │
│                                                              │
│ ✅ Usuário revisa confortavelmente                           │
└──────────────────────────────────────────────────────────────┘
                           │
                           │ Clica "Confirmar"
                           │
                           ▼
                  ┌──────────────────┐
                  │ Status PENDENTE   │
                  │ (vai para produção)
                  └──────────────────┘
```

### Tabela worker_logs (Schema)

```
┌─────────────────────────────────────────────────────┐
│         worker_logs (NOVA TABELA)                   │
├─────────────────────────────────────────────────────┤
│ id (BIGSERIAL PK)                                   │
│ task_name (VARCHAR)        ex: "auto_consolidate"   │
│ level (VARCHAR)            ex: "INFO", "ERROR"      │
│ message (TEXT)             ex: "Pedido consolidado" │
│ pedido_id (INT FK → pedidos)                        │
│ demanda_id (INT FK → demandas_producao)             │
│ detalhes (JSONB)           ex: {produto_id: 123}    │
│ erro (TEXT)                SQL error/traceback      │
│ celery_task_id (VARCHAR)   ID da task Celery        │
│ timestamp (TIMESTAMP TZ)   Quando aconteceu         │
│ created_at (TIMESTAMP TZ)  INSERT time              │
│                                                     │
│ Índices:                                            │
│  • timestamp DESC (últimos logs)                    │
│  • level (filtro por severity)                      │
│  • task_name (filtro por operação)                  │
│  • pedido_id (rastreamento)                         │
│  • demanda_id (correlação)                          │
│                                                     │
│ Exemplo de Log:                                     │
│ {                                                   │
│   "id": 1001,                                       │
│   "task_name": "auto_consolidate_pedido",           │
│   "level": "INFO",                                  │
│   "message": "Consolidação bem-sucedida",           │
│   "pedido_id": 123,                                 │
│   "demanda_id": 45,                                 │
│   "detalhes": {                                     │
│     "modalidade": "EXPRESS",                        │
│     "canal_venda_id": 1,                            │
│     "acao": "ADICIONAR_A_RASCUNHO"                  │
│   },                                                │
│   "timestamp": "2024-01-16T10:30:15Z"               │
│ }                                                   │
└─────────────────────────────────────────────────────┘
```

---

## SEQUÊNCIA TIMELINE

```
SEMANA 1 (Bloqueadores) ┓
├─ Seg 1: View SQL rastreamento + 2 APIs + Testes  ┃
├─ Ter 1: Task worker auto-consolidação            ┃ 40h
├─ Qua 1: Refatorar serviço IA (modular)           ┃
├─ Qui 1: Frontend coluna rastreamento             ┃
└─ Sex 1: Staging + Deploy                         ┛

SEMANA 2 (Melhorias) ┓
├─ Seg 2: Aba Pedidos em Demandas                  ┃
├─ Ter 2: Consolidar IA/Personalizados na UI       ┃ 30h
├─ Qua 2: Página Rascunhos dedicada                ┃
├─ Qui 2: API debug (logs + rastreamento)          ┃
└─ Sex 2: Testes E2E + Doc                         ┛

SEMANA 3 (Otimizações) ┓
├─ Seg 3: Cache & validação                        ┃
├─ Ter 3: Log Trace UI                             ┃ 25h
├─ Qua 3: Agendamento automático lote              ┃
└─ Qui-Sex 3: Query optimization + Buffer          ┛

Total: ~95 horas → 2-3 semanas com 1 squad full-time
```

---

## VISÃO DE SUCESSO (Antes/Depois)

```
ANTES:
┌─────────────────────────────┐
│ Usuário quer saber:         │
│ "Qual pedido gerou essa     │
│  demanda?"                  │
│                             │
│ Ação: Abrir arquivo Excel   │
│ manual, buscar manualmente. │
│ Tempo: 15 min               │
│ Confiabilidade: 80%         │
│ (pode errar em dados)       │
├─────────────────────────────┤
│ UX: Menu confuso            │
│ "Personalizadas" vs "IA"    │
│ Qual usar? Mesmo resultado? │
│ Botão onde? Confuso.        │
├─────────────────────────────┤
│ Debug: "Worker não consolida│
│ rascunhos automaticamente"  │
│ Log: Nenhum arquivo (!)     │
│ Análise: Impossível         │
│ Suporte: Blind              │
└─────────────────────────────┘

DEPOIS:
┌─────────────────────────────┐
│ Usuário quer saber:         │
│ "Qual pedido gerou essa     │
│  demanda?"                  │
│                             │
│ Ação: Clica "Ver Pedidos"   │
│ na tela de Demanda          │
│ Tempo: <1 segundo           │
│ Confiabilidade: 100%        │
│ (direto do DB)              │
├─────────────────────────────┤
│ UX: Tela única "Personalizados"
│ Abas: [Pendentes] [Ident.]  │
│      [Histórico] [Logs]     │
│ Claro, intuitivo, 1-click   │
├─────────────────────────────┤
│ Debug: "Worker consolidou   │
│ rascunho em 2 seg"          │
│ Logs: Tabela worker_logs    │
│       com trace completo    │
│ Análise: Tempo real         │
│ Suporte: Dados estruturados │
└─────────────────────────────┘
```
