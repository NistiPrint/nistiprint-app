# Troubleshooting - Separação de Stacks

## Problema: Worker fica em "starting" constantemente

### Sintoma
- Container mostra status **"starting"** ou **"unhealthy"**
- Logs mostram funcionamento normal (tarefas sendo processadas)
- Worker não estabiliza

### Causa
Health check original (`celery inspect ping`) falha mesmo com worker saudável porque:
- Timeout de 5s é muito curto
- Worker ocupado processando tarefas não responde a tempo
- RPC via Redis pode falhar temporariamente

### Solução
Health check foi alterado para usar `pgrep`:

```yaml
healthcheck:
  test: ["CMD-SHELL", "pgrep -f 'celery.*worker' || exit 1"]
  interval: 30s
  timeout: 10s
  retries: 5
  start_period: 60s
```

**Deploy da correção:**
```batch
# No Portainer:
# 1. Stacks → nistiprint-worker
# 2. Editar com novo docker-compose.worker.yml
# 3. Update the stack

# Ou localmente:
deploy-worker.bat restart
```

**Verificação:**
```bash
docker inspect nistiprint-app-worker --format='{{.State.Health.Status}}'
# Expected: healthy
```

Veja: `WORKER-HEALTH-CHECK.md` para detalhes completos.

---

## Problema: "Service 'redis' not found"

### Causa
O `depends_on` não funciona entre stacks diferentes no Docker Swarm/Portainer.

### Solução Aplicada
- Removido `depends_on` do `docker-compose.worker.yml`
- Worker agora usa política de retry para reconectar ao Redis
- Scripts verificam se Redis está rodando antes de subir worker

---

## Ordem Correta de Deploy

### ✅ Correto
```
1. Deploy nistiprint-infra (redis + n8n)
2. Aguardar Redis estar "Running" (~10-30s)
3. Deploy nistiprint-worker (worker + beat)
```

### ❌ Errado
```
1. Deploy ambas stacks simultaneamente
2. Deploy worker antes da infra
```

---

## Verificação Passo a Passo

### 1. Verificar Redis
```bash
# No Portainer: Stacks → nistiprint-infra → Ver status
# Ou localmente:
docker ps | findstr "nistiprint-redis"
```

**Esperado:** Container com status "Up"

### 2. Testar Conexão Redis
```bash
docker exec nistiprint-redis redis-cli ping
```

**Esperado:** `PONG`

### 3. Verificar Rede Compartilhada
```bash
docker network ls | findstr "nistiprint-shared"
```

**Esperado:** Rede listada

### 4. Deploy Worker
```bash
# Só após Redis estar saudável:
deploy-worker.bat up
# Ou no Portainer: Deploy stack nistiprint-worker
```

### 5. Verificar Worker
```bash
docker ps | findstr "nistiprint-app-worker"
```

**Esperado:** Container com status "Up"

### 6. Testar Worker
```bash
docker exec nistiprint-app-worker celery -A worker_entrypoint inspect ping
```

**Esperado:** `OK`

---

## Problemas Comuns

### Worker fica em "Restarting"

**Causa:** Redis ainda não está disponível

**Solução:**
```bash
# 1. Verifique se Redis está rodando
docker ps | findstr nistiprint-redis

# 2. Se não estiver, suba a infra primeiro
deploy-infra.bat up

# 3. Aguarde 30 segundos

# 4. Teste Redis
docker exec nistiprint-redis redis-cli ping

# 5. Só então suba o worker
deploy-worker.bat up
```

### Worker não conecta ao Redis

**Causa:** Rede `nistiprint-shared` não existe ou worker não está nela

**Solução:**
```bash
# 1. Verifique redes
docker network ls | findstr nistiprint-shared

# 2. Se não existir, crie
docker network create nistiprint-shared

# 3. Recrie worker
docker-compose -f docker-compose.worker.yml down
docker-compose -f docker-compose.worker.yml up -d
```

### n8n não conecta ao Redis

**Causa:** Mesmo problema - rede ou Redis indisponível

**Solução:**
```bash
# 1. Verifique se Redis está saudável
docker exec nistiprint-redis redis-cli ping

# 2. Verifique logs do n8n
docker logs nistiprint-n8n

# 3. Recrie n8n se necessário
docker-compose -f docker-compose.infra.yml restart n8n
```

---

## Rollback

Se algo der errado:

### Opção 1: Recriar Stacks
```bash
# 1. Derrubar tudo
docker-compose -f docker-compose.worker.yml down
docker-compose -f docker-compose.infra.yml down

# 2. Recriar infra
deploy-infra.bat up

# 3. Aguardar Redis saudável

# 4. Recriar worker
deploy-worker.bat up
```

### Opção 2: Voltar para Stack Única
```bash
# 1. Derrubar novas stacks
docker-compose -f docker-compose.worker.yml down
docker-compose -f docker-compose.infra.yml down

# 2. Recriar stack core antiga
docker-compose -f docker-compose.core.yml up -d
```

---

## Checklist de Deploy

### Pré-Deploy
- [ ] Rede `nistiprint-shared` existe
- [ ] Volumes `nistiprint-redis-data` e `nistiprint-n8n-data` existem (se migrando)

### Deploy Infra
- [ ] Stack `nistiprint-infra` criada
- [ ] Redis está "Running"
- [ ] n8n está "Running"
- [ ] `docker exec nistiprint-redis redis-cli ping` retorna `PONG`

### Deploy Worker
- [ ] Stack `nistiprint-worker` criada
- [ ] Worker está "Running" (pode levar 30-60s)
- [ ] Beat está "Running"
- [ ] `docker exec nistiprint-app-worker celery -A worker_entrypoint inspect ping` retorna `OK`

### Pós-Deploy
- [ ] n8n acessível em https://automacao.nistiprint.neolabs.com.br/
- [ ] Webhooks estão sendo recebidos
- [ ] Filas do Celery estão sendo processadas

---

## Logs Úteis

```bash
# Redis
docker logs nistiprint-redis

# n8n
docker logs nistiprint-n8n

# Worker
docker logs nistiprint-app-worker

# Beat
docker logs nistiprint-app-beat

# Todos em tempo real
docker logs -f nistiprint-app-worker
```

---

## Dicas

1. **Sempre deploy infra primeiro** - Redis precisa estar saudável antes do worker
2. **Aguarde 30-60s** - Worker pode levar tempo para conectar e ficar saudável
3. **Verifique logs** - A maioria dos problemas aparece nos logs
4. **Use os scripts** - `deploy-infra.bat` e `deploy-worker.bat` já fazem verificações
5. **Não delete volumes** - Dados do Redis e n8n estão em volumes persistentes
