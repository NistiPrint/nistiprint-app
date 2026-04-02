# Controle de Estoque - Event Sourcing

**Status:** ✅ Pronto | **Data:** 2026-03-26

---

## 🎯 Resumo

Sistema de estoque unificado com arquitetura **Event Sourcing**:
- Eventos imutáveis como fonte da verdade
- Processamento assíncrono via Celery (10s)
- Reconciliação automática de BOM
- Intermediários nunca ficam negativos

---

## 🏗️ Arquitetura Unificada

```
Dashboard → eventos_producao_v2 ┐
                                ├─→ Celery (10s) ──→ Motor (MRE) ──→ Estoque
OP/Avulsa → fila_processamento  ┘
```

| Tabela | Função |
|--------|--------|
| `eventos_producao_v2` | Eventos imutáveis do Dashboard (SINAL, LIQUIDACAO) |
| `fila_processamento_estoque` | Fila para Ordens de Produção e Produção Avulsa |
| `estoque_consolidado` | Cache de leitura (Cache Aside) |
| `estoque_atual` | Saldos físicos e disponíveis |
| `movimentacoes_estoque` | Ledger/Histórico imutável de movimentações |

---

## 🚀 Como Funciona

### 1. Finalizar Item
```python
eventos_producao_v2.insert({
    'item_demanda_id': item_id,
    'tipo_evento': 'LIQUIDACAO',
    'processado': False
})
```

### 2. Processamento Automático
- Celery Beat roda a cada 10s
- Consolidador processa eventos pendentes
- Motor reconcilia estoque (BOM, JIT)
- Marca `processado = True`

---

## 📁 Arquivos

| Backend | Frontend |
|---------|----------|
| `consolidador_estoque.py` | `MonitoramentoEstoquePage.jsx` |
| `motor_reconciliacao_estoque.py` | Rotas: `/fila-estoque`, `/monitoramento-estoque` |
| `eventos_tasks.py` | |

---

## ✅ Validação

```bash
# Reiniciar worker
docker-compose restart worker

# Logs
docker-compose logs -f worker | grep "reconciliado"

# Frontend
http://localhost:5173/relatorios/monitoramento-estoque
```

---

## 📚 Docs

- `ARQUITETURA_EVENT_SOURCING.md` - Detalhes técnicos
- `UX_MONITORAMENTO_ESTOQUE.md` - Frontend
- `VALIDACAO-FINAL.md` - Debug
