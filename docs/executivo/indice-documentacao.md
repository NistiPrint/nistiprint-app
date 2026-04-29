# 📑 MAPA COMPLETO - DOCUMENTAÇÃO NISTIPRINT

**Versão**: 1.0  
**Data**: 11 de abril de 2026  
**Total de documentos**: 11

---

## 🗺️ NAVEGAÇÃO POR PERFIL

### 👔 CTO / PM (Decisor)
**Tempo total**: 12 minutos

```
1. Ler: ANALISE_EXECUTIVA.md (10 min)
   ↓
2. Ler: PLANO-IMPLEMENTACAO-RESUMO.md (2 min)
   ↓
3. Decisão: GO ou NO-GO?
```

**Se GO**:
- Passar [PLANO-IMPLEMENTACAO.md](PLANO-IMPLEMENTACAO.md) para Tech Lead
- Alocar recursos (5 pessoas, 2-3 semanas)

---

### 🏗️ Tech Lead / Arquiteto
**Tempo total**: 40 minutos

```
1. Ler: ANALISE_EXECUTIVA.md (10 min)
   ↓
2. Ler: PLANO_CORRECAO_OTIMIZACAO.md (Problema 1/2/3) (20 min)
   ↓
3. Ler: PLANO-IMPLEMENTACAO.md (Fases 0-4) (10 min)
   ↓
4. Criar Jira tickets + briefing com team
```

---

### 💻 Dev Backend
**Tempo total**: 60 minutos

```
1. Ler: QUICK-REFERENCE.md (10 min) - pegar overview
   ↓
2. Ler: PLANO-IMPLEMENTACAO.md - Subtarefas backend (10 min)
   ↓
3. Ler: PLANO_CORRECAO_OTIMIZACAO.md - Seções relevantes (30 min)
   ↓
4. Começar subtarefa (copiar código SQL/Python)
```

**Arquivos envolvidos**:
- `supabase/migrations/xxx_create_view_rastreamento.sql`
- `supabase/migrations/xxx_create_worker_logs_table.sql`
- `apps/api/routes/demandas.py`
- `apps/api/routes/pedidos.py`
- `apps/api/routes/debug.py`
- `apps/worker/tasks/auto_consolidation_tasks.py`
- `apps/worker/tasks/pedidos_fetch_tasks.py`

---

### 🎨 Dev Frontend
**Tempo total**: 45 minutos

```
1. Ler: QUICK-REFERENCE.md (10 min)
   ↓
2. Ler: PLANO-IMPLEMENTACAO.md - Subtarefas frontend (10 min)
   ↓
3. Ler: PLANO_CORRECAO_OTIMIZACAO.md - Seção "Passo 3: Frontend" (15 min)
   ↓
4. Começar subtarefa (copiar código JSX)
```

**Arquivos envolvidos**:
- `apps/frontend/src/pages/pedidos/PedidosListPage.jsx`
- `apps/frontend/src/pages/demandas/DemandaDetailPage.jsx`
- `apps/frontend/src/pages/vendas/VendasPersonalizadasPage.jsx`
- `apps/frontend/src/pages/demandas/RascunhosPage.jsx` (novo)
- `apps/frontend/src/router/` (redir URLs)

---

### 🧪 QA / Tester
**Tempo total**: 30 minutos

```
1. Ler: DIAGRAMA-FLUXOS-SOLUCAO.md (10 min) - ver fluxos antes/depois
   ↓
2. Ler: PLANO-IMPLEMENTACAO.md - FASE 2 (Testes) (10 min)
   ↓
3. Criar test cases (E2E, regressão, performance)
   ↓
4. Executar testes em staging
```

**Debug helper**: Use APIs em `/debug/worker-logs` e `/debug/pedido/{id}/rastreamento-completo`

---

### 📚 DevOps / Infra
**Tempo total**: 20 minutos

```
1. Ler: PLANO-IMPLEMENTACAO.md - FASE 4 (Deploy) (20 min)
   ↓
2. Setup CI/CD para migrations
   ↓
3. Prepare staging + prod deployment
```

---

## 📄 LISTA DE DOCUMENTOS

| # | Arquivo | Público | Tempo | Propósito |
|---|---------|---------|-------|-----------|
| 1 | **README-ANALISE.md** | All | 5 min | Índice + ponto de entrada |
| 2 | **ANALISE_EXECUTIVA.md** | CTO/PM | 10 min | Diagnóstico + ROI + recomendação |
| 3 | **PLANO-IMPLEMENTACAO.md** | Tech Lead/Devs | 20 min | Subtarefas detalhadas + templates |
| 4 | **PLANO-IMPLEMENTACAO-RESUMO.md** | CTO/PM | 2 min | Versão ultra-resumida |
| 5 | **PLANO_CORRECAO_OTIMIZACAO.md** | Devs | 60 min | Código SQL/Python/JSX completo |
| 6 | **QUICK-REFERENCE.md** | Devs | 10 min | 10 passos + checklist |
| 7 | **DIAGRAMA-FLUXOS-SOLUCAO.md** | All | 15 min | ASCII diagrams antes/depois |
| 8 | **SUMARIO-EXECUTIVO-PT.md** | CTO/PM (PT) | 10 min | Resumo 100% português |
| 9 | **ENTREGA-ANALISE-COMPLETA.md** | PM/CTO | 5 min | Delivery summary + next steps |
| 10 | **MANIFESTO.md** | All | 5 min | Visão gráfica do problema |
| 11 | **INDICE-DOCUMENTACAO.md** | All | 5 min | Este documento! |

---

## 🔍 PROCURANDO POR...

### "Preciso de código SQL pronto"
→ [PLANO_CORRECAO_OTIMIZACAO.md](PLANO_CORRECAO_OTIMIZACAO.md#passo-1-view-sql-v_pedido_demanda_rastreamento) - Problema 1, Passo 1

### "Preciso de código Python para task"
→ [PLANO_CORRECAO_OTIMIZACAO.md](PLANO_CORRECAO_OTIMIZACAO.md#passo-2-task-celery-auto_consolidate_pedido) - Problema 3, Passo 2

### "Preciso de componente JSX"
→ [PLANO_CORRECAO_OTIMIZACAO.md](PLANO_CORRECAO_OTIMIZACAO.md#passo-3-frontend-ui) - Problema 1/2/3, Passo 3

### "Qual é a timeline?"
→ [PLANO-IMPLEMENTACAO.md](PLANO-IMPLEMENTACAO.md#-timeline-consolidada) - Tabela com semanas

### "Quantas horas vai levar?"
→ [PLANO-IMPLEMENTACAO-RESUMO.md](PLANO-IMPLEMENTACAO-RESUMO.md#-time--timeline) - Tabela resumida

### "Como começo?"
→ [PLANO-IMPLEMENTACAO.md](PLANO-IMPLEMENTACAO.md#-fase-0-decisão--alinhamento--1-hora) - Fase 0

### "E se der erro?"
→ [PLANO-IMPLEMENTACAO.md](PLANO-IMPLEMENTACAO.md#-troubleshooting) - Seção troubleshooting

### "Qual é o ROI?"
→ [ANALISE_EXECUTIVA.md](ANALISE_EXECUTIVA.md#-análise-de-impacto) - BizCase completo

### "Preciso convencer o CTO"
→ [ANALISE_EXECUTIVA.md](ANALISE_EXECUTIVA.md) - 1 página com tudo

### "Preciso entender a arquitetura"
→ [PLANO_CORRECAO_OTIMIZACAO.md](PLANO_CORRECAO_OTIMIZACAO.md#arquitetura-da-solução) - Diagramas + explicação

### "Gostaria de ver visuais/diagramas"
→ [DIAGRAMA-FLUXOS-SOLUCAO.md](DIAGRAMA-FLUXOS-SOLUCAO.md) - ASCII art antes/depois

### "Em português (sem inglês)"
→ [SUMARIO-EXECUTIVO-PT.md](SUMARIO-EXECUTIVO-PT.md) - Tudo 100% PT-BR

---

## 🚀 FLUXO RECOMENDADO POR SEMANA

### Semana 1: Decisão
- **Dia 1-2**: CTO/PM lê ANALISE_EXECUTIVA + PLANO-RESUMO
- **Dia 3**: Go/No-Go decision
- **Se GO**: 
  - Tech Lead lê PLANO-IMPLEMENTACAO completo
  - Tech Lead faz briefing (20 min) com time
  - Criar Jira tickets baseados no PLANO

### Semana 2: Implementação P1 & P2
- **Dia 1-2**: Backend faz Problema 1 (View + APIs)
- **Dia 2-3**: Frontend faz Problema 1 (Coluna + Aba)
- **Dia 3-4**: Frontend faz Problema 2 (Refactor page + redir)
- **Dia 4**: QA começa testes E2E

### Semana 3: Implementação P3 & Testes
- **Dia 1-2**: Backend faz Problema 3 (Migration + Task + API)
- **Dia 2-3**: Frontend faz Problema 3 (RascunhosPage)
- **Dia 3-5**: QA testes integração + regressão
- **Dia 5**: Deploy staging + smoke tests

### Semana 4: Deploy & Go-live (se timing permitir)
- **Dia 1-2**: Últimas correções
- **Dia 3-4**: Deploy production
- **Dia 5**: User training + monitoring

---

## ✅ CHECKLIST PRÉ-LEITURA

Antes de começar, preparar:

- [ ] Slack ou Teams aberto (comunicar progresso)
- [ ] Jira access (criar tickets)
- [ ] Git clonado e branches setup
- [ ] Ambiente local pronto (venv + Redis local) — ver [setup-local.md](../guias/setup-local.md)
- [ ] BD staging (ou backup de prod) disponível
- [ ] Slack #dev-nistiprint channel criado

---

## 📞 QUESTÕES FREQUENTES

**P: Posso começar Problema 3 antes de Problema 1?**  
R: Sim, são independentes. Mas Problema 1 é mais simples (comece por ele para ganhar momentum).

**P: Backend pode começar antes de QA estar pronto?**  
R: Sim, trabalhe em paralelo. QA escreve testes enquanto backend codifica.

**P: E se um documento estiver confuso?**  
R: Ler o doc anterior na hierarquia (mais simples). Se continuar confuso, escalate para tech-lead.

**P: Quanto tempo demora a ler tudo?**  
R: 2-3 horas se ler todos. Começar com seu próprio perfil (10-60 min).

**P: Posso pular alguns docs?**  
R: **Não recomendado**. Cada doc tem informações únicas (código vs. timeline vs. visão).

**P: Os templates de código estão prontos para copiar-colar?**  
R: Sim, mas você precisa adaptar para seu codebase (imports, path, etc.).

---

## 🎯 OBJETIVO FINAL

Após ler esses documentos e implementar, você terá:

✅ Rastreamento 1-clique entre pedidos ↔ demandas  
✅ Menu IA consolidado (sem confusão)  
✅ Consolidação automática + logs estruturados  
✅ ROI de €27k/ano  
✅ Time mais produtivo  
✅ Usuários felizes  

**Começa agora?** → Abra [README-ANALISE.md](README-ANALISE.md) ou [ANALISE_EXECUTIVA.md](ANALISE_EXECUTIVA.md)

---

**Última atualização**: 11 de abril de 2026  
**Criado por**: Análise técnica automática do Nistiprint ERP+PCP
