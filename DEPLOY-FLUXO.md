# Fluxo de Deploy - Nistiprint

## Visão Geral

```
┌─────────────────────────────────────────────────────────────┐
│                    APLICAÇÕES (build.bat)                   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│  │     API     │  │   WORKER    │  │   FRONTEND  │          │
│  │   Docker    │  │   Docker    │  │   Docker    │          │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘          │
│         │                │                │                  │
│         └────────────────┼────────────────┘                  │
│                          │                                   │
│                  Docker Hub (push)                           │
└──────────────────────────┼───────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    INFRAESTRUTURA (Portainer)               │
│  ┌─────────────────────────┐                                │
│  │   nistiprint-infra      │                                │
│  │  ┌───────────────────┐  │                                │
│  │  │      redis        │  │                                │
│  │  │      n8n          │  │                                │
│  │  └───────────────────┘  │                                │
│  └─────────────────────────┘                                │
│  ┌─────────────────────────┐                                │
│  │   nistiprint-app        │                                │
│  │  ┌───────────────────┐  │                                │
│  │  │        api        │  │                                │
│  │  │     frontend      │  │                                │
│  │  └───────────────────┘  │                                │
│  └─────────────────────────┘                                │
│  ┌─────────────────────────┐                                │
│  │   nistiprint-worker     │                                │
│  │  ┌───────────────────┐  │                                │
│  │  │      worker       │  │                                │
│  │  │      beat         │  │                                │
│  │  └───────────────────┘  │                                │
│  └─────────────────────────┘                                │
└─────────────────────────────────────────────────────────────┘
```

---

## 1. Deploy de Infraestrutura (Raro)

### Quando Fazer
- Primeira instalação
- Mudança no Redis ou n8n
- Atualização de versão do Redis/n8n

### Como Fazer

```batch
cd apps/ops

# Subir infraestrutura
deploy-infra.bat up

# Verificar status
deploy-infra.bat status
```

### No Portainer
1. Criar stack `nistiprint-infra` com `docker-compose.infra.yml`
2. Adicionar variável: `BLING_CLIENT_SECRET`
3. Deploy
4. **Aguardar ~30s até Redis e n8n estarem "Running"**

---

## 2. Deploy de Aplicações (Frequente)

### Quando Fazer
- Nova versão da API
- Nova versão do Worker
- Nova versão do Frontend
- Correção de bugs

### Opção A: Build + Push Completo

```batch
# Build local para teste
build.bat local

# Testar localmente
docker-compose -f docker-compose.local.yml up -d

# Push para Docker Hub
build.bat push

# Ou com tag específica
build.bat push v1.2.3
```

### Opção B: Build + Push de Serviço Específico

```batch
# Apenas Worker (mais comum)
build.bat push worker

# Apenas API
build.bat push api

# Apenas Frontend
build.bat push frontend

# Com tag customizada
build.bat push dev worker
build.bat push v1.2.3 api worker
```

### No Portainer

#### Para Worker (mais comum):
1. Ir em **Stacks** → `nistiprint-worker`
2. Clicar em **Update the stack**
3. Aguardar ~60s para worker ficar saudável

#### Para API:
1. Ir em **Stacks** → `nistiprint-app`
2. Clicar em **Update the stack**

#### Para Frontend:
1. Ir em **Stacks** → `nistiprint-app`
2. Clicar em **Update the stack**

---

## 3. Verificação Pós-Deploy

### Infraestrutura
```bash
# Redis
docker exec nistiprint-redis redis-cli ping
# Expected: PONG

# n8n
curl https://automacao.nistiprint.neolabs.com.br/healthz
# Expected: {"status":"ok"}
```

### Worker
```bash
# Status
docker exec nistiprint-worker celery -A worker_entrypoint inspect ping
# Expected: OK

# Logs
docker logs -f nistiprint-worker
```

### API
```bash
# Health check
curl https://api.nistiprint.neolabs.com.br/health
```

### Frontend
```bash
# Acessar no navegador
https://app.nistiprint.neolabs.com.br/
```

---

## 4. Rollback (Se Necessário)

### Worker
```bash
# No Portainer:
# 1. Stacks → nistiprint-worker
# 2. Editar e mudar imagem para versão anterior
#    leandrogbreve/nistiprint-worker:v1.2.2
# 3. Update the stack
```

### Infraestrutura
```batch
cd apps/ops
deploy-infra.bat restart
```

---

## Resumo dos Comandos

### build.bat (Aplicações)
```batch
build.bat local              # Testa api, worker, frontend localmente
build.bat local worker       # Testa apenas worker
build.bat push               # Publica api, worker, frontend (latest)
build.bat push worker        # Publica apenas worker
build.bat push dev api       # Publica API com tag dev
```

### deploy-infra.bat (Infraestrutura)
```batch
deploy-infra.bat up          # Sobe redis + n8n
deploy-infra.bat status      # Verifica status
deploy-infra.bat logs        # Logs em tempo real
```

### deploy-worker.bat (Worker)
```batch
deploy-worker.bat up         # Sobe worker + beat
deploy-worker.bat status     # Verifica status
deploy-worker.bat logs       # Logs em tempo real
```

---

## Fluxo Típico de Desenvolvimento

```
1. Desenvolvimento local
   → build.bat local worker
   → docker-compose -f docker-compose.local.yml up -d
   → Testar

2. Commit e Push
   → git add .
   → git commit -m "fix: correção no worker"
   → git push

3. Deploy em Produção
   → build.bat push worker
   → Portainer: Update stack nistiprint-worker
   → Verificar logs

4. Monitoramento
   → deploy-worker.bat logs
   → Verificar webhooks no n8n
   → Verificar filas processando
```

---

## Dicas

1. **Sempre teste localmente antes de publicar**
   ```batch
   build.bat local worker
   # Teste → build.bat push worker
   ```

2. **Use tags específicas para versões**
   ```batch
   build.bat push v1.2.3 worker
   ```

3. **Worker é o serviço mais atualizado**
   - Webhooks mudam frequentemente
   - Processamento de pedidos evolui
   - Correções são comuns

4. **Infraestrutura muda pouco**
   - Redis: apenas se mudar versão ou configuração
   - n8n: apenas se mudar versão ou workflows

5. **Nunca reinicie infra para deploy de worker**
   - Isso causa indisponibilidade de webhooks
   - Use stacks separadas (já configurado)

---

## Troubleshooting Rápido

| Problema | Solução |
|----------|---------|
| Worker não conecta | `deploy-infra.bat status` (verifique Redis) |
| Webhooks falham | `deploy-infra.bat logs` (verifique n8n) |
| API não responde | `build.bat local api` (teste local) |
| Frontend não carrega | Verifique build e deploy |

---

## Arquivos de Referência

| Arquivo | Descrição |
|---------|-----------|
| `build.bat` | Build e push de aplicações |
| `apps/ops/deploy-infra.bat` | Deploy de infra |
| `apps/ops/deploy-worker.bat` | Deploy de worker |
| `apps/ops/docker-compose.infra.yml` | Infra (redis + n8n) |
| `apps/ops/docker-compose.worker.yml` | Worker + beat |
| `apps/ops/VARIAVEIS-AMBIENTE.md` | Variáveis necessárias |
| `apps/ops/TROUBLESHOOTING.md` | Solução de problemas |
