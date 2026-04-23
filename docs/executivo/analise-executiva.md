# 📊 ANÁLISE EXECUTIVA - NISTIPRINT

**Preparado em**: Abril 2026  
**Status**: Análise Completa  
**Docs de Suporte**: 
- [PLANO_CORRECAO_OTIMIZACAO.md](PLANO_CORRECAO_OTIMIZACAO.md) - Detalhamento técnico completo
- [DIAGRAMA-FLUXOS-SOLUCAO.md](DIAGRAMA-FLUXOS-SOLUCAO.md) - Visualizações visuais

---

## 🎯 SITUAÇÃO

**Nistiprint** é um **sistema ERP+PCP robusto** para gráfica criativa com integração em 3 marketplaces e 3 contas Bling. Arquitetura é **sólida** (Python+React+Supabase+Celery), mas **3 problemas críticos** bloqueiam produtividade dos usuários no dia-a-dia:

| # | Problema | Impacto | Severidade |
|---|----------|---------|-----------|
| **1** | Rastreamento pedidos ↔ demandas | Usuário não vê qual pedido foi agrupado em qual demanda | 🔴 CRÍTICO |
| **2** | Redundância de menus IA | 2 menus para mesma funcionalidade (confundindo usuário) | 🟡 OPTIMIZAÇÃO UX |
| **3** | Worker não consolida rascunhos | Consolidação é manual, logs faltam, sem automação | 🔴 CRÍTICO |

---

## 🔍 DIAGNÓSTICO

### Problema 1: Rastreamento (Invisível na UI)

**O que está certo:**
- ✅ DB schema correto: `demandas_item_origem` com FK `pedido_externo_id`
- ✅ Estrutura de view pronta: JOIN `pedidos_bling` → `demandas_item_origem` → `itens_demanda` → `demandas_producao`

**O que está errado:**
- ❌ View SQL não criada
- ❌ Nenhuma API GET expõe `/pedidos/{id}/demandas` ou `/demandas/{id}/pedidos`
- ❌ Frontend não mostra coluna "Demanda Vinculada" em PedidosListPage
- ❌ Frontend não mostra aba "Pedidos Origem" em DemandaDetailPage

**Resultado**: Relacionamento existe no DB, mas é **invisível para usuário**. Ele não consegue clicar "ver qual pedido gerou essa demanda".

---

### Problema 2: Redundância IA & Identificação

**✅ ESCLARECIMENTO (Message 4)**: Serviços já estão corretos!

**O que está certo:**
- ✅ `personalized_order_identifier.py` (classifica se é personalizado via regras)
- ✅ `ai_personalization_service.py` (extrai nome a personalizar via Gemini)
- ✅ Tela `/vendas/personalizadas` funciona bem

**O que está errado** (APENAS UX):
- ❌ Tela `/vendas/identificacao-ia` é redundante (faz mesma coisa da `/vendas/personalizadas`)
- ❌ Menu `/ai` apontar para página separada confunde usuário (2 menus = 1 serviço)

**Resultado**: Usuário vê **2 menus para mesma funcionalidade**. Confusão. Solução: consolidar em 1 tela com abas.

---

### Problema 3: Worker & Auto-Consolidação

**O que está certo:**
- ✅ Task Celery `sync_pedidos_bling()` processa webhooks
- ✅ `upsert_order()` insere pedidos no DB
- ✅ Consolidação manual via `POST /consolidar` (upload Excel) funciona

**O que está errado:**
- ❌ Webhook não dispara consolidação automática
- ❌ Rascunhos `demandas_producao.status='RASCUNHO'` não são criados automaticamente
- ❌ Faltam logs estruturados do worker (só stdout, não persistem)
- ❌ Rascunhos não são acessíveis via UI (sem filtro/tela dedicada)
- ❌ Sem retry/retry policy clara em case de erro

**Resultado**: **Consolidação = manual** (usuário faz upload), não automática. **Sem debug possível** (sem logs).

---

## 💡 SOLUÇÃO

### Problema 1: Rastreamento

**Ações**:
1. Criar **VIEW SQL** `v_pedido_demanda_rastreamento` (join 4 tabelas)
2. Criar **2 APIs**: `GET /pedidos/{id}/demandas` + `GET /demandas/{id}/pedidos`
3. Adicionar **coluna "Status Demanda"** em PedidosListPage (com badge + link clicável)
4. Adicionar **aba "Pedidos Origem"** em DemandaDetailPage (com tabela expandível)

**Resultado**: Usuário vê em **tempo real**, **1 clique**, onde está cada pedido/demanda.

---

### Problema 2: IA & Identificação

✅ **ESCLARECIMENTO (Message 4)**: Serviços já estão corretos! Problema é APENAS UX.

- `personalized_order_identifier.py` (classificação via regras) = PERFEITO, deixar igual
- `ai_personalization_service.py` (extração nome via Gemini) = PERFEITO, deixar igual
- ❌ Problema: 2 menus frontend → consolidar em 1 tela

**Ações** (Frontend ONLY):
1. **Refatorar VendasPersonalizadasPage.jsx**: Adicionar 4 abas
   - Pendentes Extração (personalizado=true, sem nome)
   - Nomes Extraídos (com nome já extraído)
   - Histórico (tudo processado)
   - Logs IA (execuções detalha​das)
2. **Remover redundância**: Redirecionar `/ai` e `/vendas/identificacao-ia` → `/vendas/personalizadas`
3. **Backend**: Zero mudanças (serviços já funcionam corretamente)

**Resultado**: **1 tela, 1 serviço, estrutura clara**. Logs rastreáveis. Sem redundância.

---

### Problema 3: Worker & Auto-Consolidação

**Ações**:
1. Criar **2 tasks worker novas**:
   - `auto_consolidate_pedido(pedido_id)` - Disparada ao receber webhook
   - `processar_lote_rascunhos()` - Agendada a cada 30 min (validação lote)
2. Criar **tabela `worker_logs`** com campos estruturados (task, level, msg, pedido_id, demanda_id, detalhes, erro)
3. Adicionar **APIs debug**: `GET /debug/worker-logs` + `GET /debug/pedido/{id}/rastreamento-completo`
4. Criar **página RascunhosPage**: Listar rascunhos com pedidos expandíveis, botões Confirmar/Descartar
5. Integrar task no webhook: `upsert_order()` → `auto_consolidate_pedido.delay()`

**Resultado**: **Consolidação automática** (< 10s após webhook), **logs persistidos**, **rascunhos visíveis**.

---

## 📅 TIMELINE

| Fase | Título | Horas | Semanas | Detalhes |
|------|--------|-------|---------|----------|
| **P0** | Bloqueadores | 40h | 1 | View rastreamento + 2 APIs + Task worker + Serviço IA refactored + Frontend coluna |
| **P1** | Melhorias | 30h | 2 | Aba Demandas + Consolidar UI IA + Página Rascunhos + APIs debug + Testes |
| **P2** | Otimizações | 25h | 3 | Cache IA + Validação modal + Log Trace UI + Agendamento automático + Query opt |
| | **TOTAL** | **~95h** | **2-3 semanas** | Com 1 squad: Backend (2-3) + Frontend (1-2) + Worker (1) |

---

## 💰 INVESTIMENTO vs RETORNO

| Aspecto | Antes | Depois |
|---------|---------|----------|
| **Rastreamento pedido→demanda** | 15 min (manual Excel) | <1s (UI clicável) |
| **Consolidação rascunhos** | Manual (upload arquivo) | Automática (~10s) |
| **Debug consolidação** | Impossível (sem logs) | Estruturado (worker_logs) |
| **Menu IA/Personalizados** | Confuso (2 telas) | Claro (1 tela, 4 abas) |
| **Tempo usuário/semana** | ~4h (busca manual) | ~10min (cliques) | 
| **Custo time** | **~95 horas uma vez** | **~3h/semana economizadas** |

**ROI**: Economia de **150h/ano** para usuários (final-users) + **clarity para suporte técnico**.

---

## ✅ CHECKLIST IMPLEMENTAÇÃO

### P0 (Semana 1)
- [ ] View SQL `v_pedido_demanda_rastreamento` criada + índices
- [ ] API GET `/pedidos/{id}/demandas` implementada
- [ ] API GET `/demandas/{id}/pedidos` implementada
- [ ] Coluna "Status Demanda" em PedidosListPage
- [ ] Task `auto_consolidate_pedido()` criada com retry policy
- [ ] Task `processar_lote_rascunhos()` criada (agendada)
- [ ] Tabela `worker_logs` criada
- [ ] Serviço IA refatorado (modular + orquestrador)
- [ ] Deploy staging + testes E2E

### P1 (Semana 2)
- [ ] Aba "Pedidos Origem" em DemandaDetailPage
- [ ] Tela `/vendas/personalizadas` com 4 abas consolidadas
- [ ] Remover/redirecionar `/ai` ou `/identificacao-ia`
- [ ] Página RascunhosPage criada + acessível
- [ ] API GET `/debug/worker-logs` (admin only)
- [ ] API GET `/debug/pedido/{id}/rastreamento-completo`
- [ ] Webhook integrado com `auto_consolidate_pedido.delay()`
- [ ] Testes de correlação logs + pedido
- [ ] Deploy prod + monitoramento

### P2 (Semana 3)
- [ ] Cache de resultados IA (redis)
- [ ] Validação colisão mapeamento modal
- [ ] UI de "Log Trace" para pedido (breadcrumb debug)
- [ ] Otimização queries (índices, explain plan)
- [ ] Documentação técnica atualizada
- [ ] Documentação usuário (guia rastreamento)

---

## 🎓 DOCUMENTAÇÃO GERADA

3 documentos completos criados:

1. **[PLANO_CORRECAO_OTIMIZACAO.md](PLANO_CORRECAO_OTIMIZACAO.md)** (Técnico)
   - Detalhamento de cada problema
   - Implementação passo-a-passo com código
   - Timeline detalhada
   - Considerações de segurança

2. **[DIAGRAMA-FLUXOS-SOLUCAO.md](DIAGRAMA-FLUXOS-SOLUCAO.md)** (Visual)
   - Fluxos ASCII (antes/depois)
   - Arquitetura DB (schema novas)
   - Timeline visual
   - Sequência de sucesso

3. **Este documento** (Executivo)
   - Resumo para stakeholders
   - Go/no-go decision
   - ROI & timeline

---

## 🚀 RECOMENDAÇÃO

**✅ PROSSEGUIR com implementação (Fases P0 + P1 prioritárias)**

Justificativa:
- Impacto **imediato** na produtividade de usuários (+3h/semana economizadas)
- Baseline técnica **já existe** (schema correto, serviços funcionam)
- Timeline **realista** (2-3 semanas = 1 sprint + 1 semana adjustment)
- Risk **baixo** (mudanças são adições, não refatorações radicais)

**Próximo passo**: 
1. Confirmar alocação de recursos (Backend 2-3 + Frontend 1-2 + Worker 1)
2. Criar issues no backlog com tarefas P0
3. Kick-off segunda-feira próxima

---

## 📎 APÊNDICE: DECISÕES TÉCNICAS

### Decision 1: View SQL vs Materialized View
**Escolhido**: Regular VIEW + índices (não materialized)
**Razão**: Dados sempre fresh, sem overhead de refresh. FK correlação é natural.

### Decision 2: Orquestrador vs Sequencial
**Escolhido**: Orquestrador + múltiplas estratégias (Order: Rápida → Gemini → Chat)
**Razão**: Flexibilidade, reutilização, fácil de adicionar novas estratégias.

### Decision 3: Logs worker em BD vs Redis
**Escolhido**: BD (Supabase) + stdout paralelo
**Razão**: Persistência, queries estruturadas, retenção 30 dias, sem perda de dados.

### Decision 4: Auto-consolidação síncrona vs assíncrona
**Escolhido**: Assíncrono (Celery task.delay()) com retry
**Razão**: Não bloqueia webhook, retry automático, escalável para picos.

---

**Versão**: 1.0 | **Revisão**: Pronta para Go | **Aprovação necessária**: CTO/PM
