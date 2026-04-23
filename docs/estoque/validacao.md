# Validação e Debug

---

## ✅ Validação Rápida

```bash
# 1. Reiniciar worker
docker-compose restart worker

# 2. Logs em tempo real
docker-compose logs -f worker | grep "reconciliado"

# 3. Testar frontend
http://localhost:5173/relatorios/monitoramento-estoque
```

---

## 🐛 Debug

### Eventos não aparecem

```javascript
// Browser console
fetch('/api/v2/producao/eventos?limit=10')
  .then(r => r.json())
  .then(d => console.log(d));
```

### Worker não processa

```bash
# Verificar Celery Beat
docker-compose logs -f beat | grep "process_eventos"

# Verificar se task está registrada
docker-compose logs worker | grep "tasks.eventos_tasks"
```

### Erro de duplicação

```sql
-- Verificar eventos travados
SELECT * FROM eventos_producao_v2
WHERE processado = false
AND created_at < NOW() - INTERVAL '1 hour';

-- Liberar lock do item
UPDATE itens_demanda 
SET status_processamento = 'PENDENTE' 
WHERE status_processamento = 'PROCESSANDO';
```

### Saldos não atualizam

```sql
-- Verificar movimentações
SELECT tipo_movimentacao, quantidade, created_at 
FROM movimentacoes_estoque 
ORDER BY created_at DESC 
LIMIT 10;

-- Verificar saldos
SELECT p.nome, e.saldo_atual 
FROM estoque_atual e
JOIN produtos p ON p.id = e.produto_id
ORDER BY e.ultima_atualizacao DESC;
```

---

## 📊 Queries Úteis

```sql
-- Eventos por tipo
SELECT tipo_evento, COUNT(*) 
FROM eventos_producao_v2 
GROUP BY tipo_evento;

-- Eventos por status
SELECT processado, COUNT(*) 
FROM eventos_producao_v2 
GROUP BY processado;

### Itens travados no Dashboard (Demanda)
SELECT id, status_processamento, updated_at 
FROM itens_demanda 
WHERE status_processamento != 'PENDENTE';

### Tarefas pendentes na Fila Unificada (OP/Avulsa)
SELECT tipo_operacao, status, COUNT(*)
FROM fila_processamento_estoque
WHERE status != 'CONCLUIDO'
GROUP BY tipo_operacao, status;

```

---

## 🔧 Correções Comuns

### RPC não existe

```sql
-- Aplicar migration
-- supabase/migrations/20260325000002_create_force_fetch_tasks_rpc.sql
```

### Coluna não existe

```
eventos_producao_v2 tem apenas: processado (boolean)
NÃO tem: status
```

### Rota não encontrada

```
/relatorios/monitoramento → redirect automático
/relatorios/monitoramento-estoque → correto
```
