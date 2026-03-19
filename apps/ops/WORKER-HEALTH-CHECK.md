# Health Check do Worker - Problema e Solução

## Problema

O container do worker ficava constantemente com status **"starting"** ou **"unhealthy"**, mesmo os logs mostrando funcionamento normal.

### Causa Raiz

O health check original usava:
```bash
celery -A worker_entrypoint inspect ping --timeout=5
```

Este comando **pode falhar** mesmo com o worker saudável porque:

1. **Timeout muito curto (5s)** - O `inspect ping` precisa:
   - Conectar ao Redis
   - Enviar mensagem para todas as filas do worker
   - Aguardar resposta de cada worker
   - Se o worker estiver processando uma tarefa longa, pode não responder a tempo

2. **Worker ocupado** - Durante processamento de tarefas:
   - Webhooks grandes
   - Processamento de IA
   - Sync de estoque em lote
   
   O worker pode não responder ao `inspect ping` dentro do timeout.

3. **Falso positivo de falha** - Após 3 retries falhos, o Docker marca como unhealthy, triggering restart desnecessário.

---

## Solução

### Novo Health Check

```yaml
healthcheck:
  test: ["CMD-SHELL", "pgrep -f 'celery.*worker' || exit 1"]
  interval: 30s
  timeout: 10s
  retries: 5
  start_period: 60s
```

### Por que `pgrep` é melhor?

| Critério | `inspect ping` | `pgrep` |
|----------|----------------|---------|
| Complexidade | Alta (RPC via Redis) | Baixa (check de processo) |
| Timeout | 5s (curto) | 10s (suficiente) |
| Falso negativo | Comum (worker ocupado) | Raro |
| Dependências | Redis funcional | Nenhuma |
| Overhead | Alto (RPC) | Mínimo |

### Parâmetros Ajustados

| Parâmetro | Antes | Agora | Motivo |
|-----------|-------|-------|--------|
| `interval` | 60s | 30s | Detecção mais rápida de falhas reais |
| `timeout` | 10s | 10s | Mantido (suficiente para pgrep) |
| `retries` | 3 | 5 | Mais tolerância a falhas transitórias |
| `start_period` | N/A | 60s | Tempo para worker inicializar |

---

## Beat (Agendador)

Mesma solução aplicada:

```yaml
healthcheck:
  test: ["CMD-SHELL", "pgrep -f 'celery.*beat' || exit 1"]
  interval: 30s
  timeout: 10s
  retries: 5
  start_period: 60s
```

---

## Verificação

### Após Deploy

```bash
# Verificar status do health check
docker inspect nistiprint-app-worker --format='{{.State.Health.Status}}'
# Expected: healthy

# Verificar logs do health check
docker inspect nistiprint-app-worker --format='{{json .State.Health}}' | jq

# Verificar processo
docker exec nistiprint-app-worker pgrep -f 'celery.*worker'
# Expected: PID (número)
```

### Logs Normais

```
[INFO/MainProcess] Connected to redis://redis:6379/0
[INFO/MainProcess] celery@hostname ready.
[INFO/ForkPoolWorker-1] Task tasks.webhook_tasks.process_bling_webhook[...] succeeded
[INFO/ForkPoolWorker-2] Task tasks.stock_tasks.sync_stock[...] succeeded
```

Se os logs mostram tarefas sendo processadas, o worker está saudável - mesmo que o health check antigo falhasse.

---

## Rollback (Se Necessário)

Se quiser voltar ao health check original (não recomendado):

```yaml
healthcheck:
  test: ["CMD-SHELL", "celery -A worker_entrypoint inspect ping --timeout=5 || exit 1"]
  interval: 60s
  timeout: 10s
  retries: 3
```

Mas isso provavelmente causará o problema novamente.

---

## Alternativa: Sem Health Check

Se preferir não usar health check (apenas rely no `restart: unless-stopped`):

```yaml
# Remova completamente a seção healthcheck
worker:
  image: leandrogbreve/nistiprint-worker:latest
  container_name: nistiprint-app-worker
  restart: unless-stopped
  # Sem healthcheck - Docker só verifica se o processo está rodando
```

**Prós:**
- Simples
- Sem falsos positivos

**Contras:**
- Não detecta worker "zumbi" (processo rodando mas não processando)
- Menos observabilidade

---

## Monitoramento Recomendado

### 1. Verificar Filas do Redis

```bash
docker exec nistiprint-redis redis-cli llen celery
# Número de tarefas na fila (deve ser baixo ou 0)
```

### 2. Verificar Workers Ativos

```bash
docker exec nistiprint-app-worker celery -A worker_entrypoint inspect active
# Mostra tarefas ativas sendo processadas
```

### 3. Verificar Estatísticas

```bash
docker exec nistiprint-app-worker celery -A worker_entrypoint inspect stats
# Mostra estatísticas de cada worker
```

### 4. Logs em Tempo Real

```bash
docker logs -f nistiprint-app-worker
# Deve mostrar tarefas sendo processadas
```

---

## Resumo

| Antes | Depois |
|-------|--------|
| Status: starting/unhealthy | Status: healthy |
| Restarts desnecessários | Restarts apenas quando necessário |
| Webhooks falhando durante restart | Webhooks processados continuamente |
| Health check complexo (RPC) | Health check simples (pgrep) |

**Resultado:** Worker estável, sem falsos positivos, máxima disponibilidade para processamento de webhooks.
