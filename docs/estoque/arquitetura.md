# Arquitetura Event Sourcing - Estoque

**Status:** ✅ Implementado

---

## Fluxo unificado

```
Dashboard → eventos_producao_v2 ┐
                                ├─→ Celery Worker ──→ Motor de Reconciliação ──→ Estoque
OP/Avulsa → fila_processamento  ┘
```

---

## Componentes

### 1. Eventos (`eventos_producao_v2`)
Fonte da verdade para o dashboard de demandas.

### 2. Fila Unificada (`fila_processamento_estoque`)
Fonte da verdade para Ordens de Produção e Produção Avulsa.

### 3. Consolidador (`consolidador_estoque.py`)
Agrupa eventos imutáveis do dashboard e chama o Motor.

### 4. Motor (`motor_reconciliacao_estoque.py`)
Núcleo determinístico que processa:
- Reconciliação por item (Dashboard)
- Explosão de BOM avulsa (OP/Avulsa)
- Produção compensatória (JIT)

**Responsabilidades:**
- Explosão de BOM recursiva
- Cálculo de deltas (efetivo - realizado)
- Produção compensatória (JIT)
- Idempotência (correlation_id)

**Regras de Negócio:**
| Tipo | Regra |
|------|-------|
| Intermediários | NUNCA negativos → PROD_INT |
| Matérias-primas | PODEM negativas → CONS_MP |
| Finalização | Liquidação completa do BOM |

---

### 4. Worker (`eventos_tasks.py`)

```python
@celery_app.task
def process_eventos_producao():
    consolidador_estoque.processar_lote()
```

**Agendamento:** Celery Beat a cada 10 segundos

---

## API

### GET `/api/v2/producao/eventos`

**Query Params:**
- `limit` (default: 100)
- `tipo` (SINAL | LIQUIDACAO)
- `processado` (true | false)

**Response:**
```json
{
  "success": true,
  "eventos": [...],
  "total": 10
}
```

---

## Validação

```sql
-- Eventos pendentes
SELECT COUNT(*) FROM eventos_producao_v2 
WHERE processado = false;

-- Movimentações recentes
SELECT tipo_movimentacao, quantidade, created_at 
FROM movimentacoes_estoque 
ORDER BY created_at DESC 
LIMIT 10;
```
