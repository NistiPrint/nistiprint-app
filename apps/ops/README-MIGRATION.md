# Nistiprint - Separação de Infraestrutura Crítica

## Problema

A stack atual `nistiprint-core` contém:
- Redis (broker de mensagens)
- n8n (webhooks e automações)
- Worker (processamento Celery)
- Beat (agendador de tarefas)

**Issues:**
1. Atualizar o worker reinicia toda a stack
2. n8n fica indisponível durante deploys
3. Webhooks são perdidos durante reinícios
4. Redis pode perder dados em reinícios bruscos

## Solução

Separar em **duas stacks independentes**:

### Stack 1: `nistiprint-infra` (Crítica)
- **Redis** - Broker persistente
- **n8n** - Recebimento de webhooks

**Características:**
- Máxima disponibilidade (99.9%)
- Reinícios apenas para manutenção
- Volumes persistentes obrigatórios
- Health checks rigorosos

### Stack 2: `nistiprint-worker` (Dinâmica)
- **Worker** - Processamento de filas
- **Beat** - Agendamento de tarefas

**Características:**
- Atualizações frequentes
- Pode ser reiniciado sem impacto nos webhooks
- Conecta-se ao Redis existente

## Arquitetura

```
┌──────────────────────────────────────────────────────┐
│                 TRAEFIK (Gateway)                    │
└──────────────────────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────┐
│            nistiprint-infra (CRÍTICA)                │
│  ┌─────────────┐    ┌─────────────┐                  │
│  │    n8n      │───▶│    redis    │                  │
│  │  :5678      │    │   :6379     │                  │
│  └─────────────┘    └──────┬──────┘                  │
│         │                  │                          │
│  [volumes persistentes]    │                          │
└─────────│──────────────────│──────────────────────────┘
          │                  │
          │                  ▼
          │         ┌────────────────┐
          │         │  Rede Shared   │
          │         └────────────────┘
          │                  │
          │                  ▼
          │         ┌──────────────────────────────┐
          │         │   nistiprint-worker          │
          └────────▶│  ┌────────┐    ┌────────┐    │
                    │  │ worker │    │  beat  │    │
                    │  └────────┘    └────────┘    │
                    └──────────────────────────────┘
```

## Migração

### Opção 1: Automática (Recomendada)

```batch
cd apps/ops
migrate-stack.bat
```

### Opção 2: Manual no Portainer

#### Passo 1: Criar stack `nistiprint-infra`

1. No Portainer, vá em **Stacks** → **Add stack**
2. Nome: `nistiprint-infra`
3. Web editor: cole o conteúdo de `docker-compose.infra.yml`
4. Deploy the stack

#### Passo 2: Verificar infra

```bash
# Localmente
deploy-infra.bat status

# Ou no Portainer, verifique se redis e n8n estão "Running"
```

#### Passo 3: Criar stack `nistiprint-worker`

1. No Portainer, vá em **Stacks** → **Add stack**
2. Nome: `nistiprint-worker`
3. Web editor: cole o conteúdo de `docker-compose.worker.yml`
4. Deploy the stack

#### Passo 4: Remover stack antiga (opcional)

1. Vá em **Stacks** → `nistiprint-core`
2. Remove the stack
3. **NÃO** remova os volumes!

## Operação

### Deploy de Worker (Frequente)

```batch
# 1. Build da nova imagem
build.bat push worker

# 2. Atualizar stack no Portainer
#    Stacks → nistiprint-worker → Update the stack

# 3. Ou localmente:
deploy-worker.bat restart
```

**Impacto:** Apenas worker e beat são reiniciados. n8n e Redis continuam rodando.

### Deploy de Infra (Raro)

```batch
# 1. Atualizar docker-compose.infra.yml se necessário

# 2. Localmente:
deploy-infra.bat restart

# 3. Ou no Portainer:
#    Stacks → nistiprint-infra → Update the stack
```

**Impacto:** n8n e Redis são reiniciados. Webhooks podem falhar por ~30s.

### Monitoramento

```batch
# Status da infra
deploy-infra.bat status

# Status do worker
deploy-worker.bat status

# Logs do n8n (webhooks)
deploy-infra.bat logs

# Logs do worker
deploy-worker.bat logs
```

## Health Checks

### Redis
```bash
docker exec nistiprint-redis redis-cli ping
# Expected: PONG
```

### n8n
```bash
curl https://automacao.nistiprint.neolabs.com.br/healthz
# Expected: {"status":"ok"}
```

### Worker
```bash
docker exec nistiprint-app-worker celery -A worker_entrypoint inspect ping
# Expected: OK
```

## Volumes Persistentes

| Volume | Nome | Conteúdo |
|--------|------|----------|
| Redis | `nistiprint-redis-data` | Dados AOF do Redis |
| n8n | `nistiprint-n8n-data` | Workflows, credenciais, execuções |

**Importante:** Nunca delete estes volumes a menos que queira perder todos os dados!

## Rollback

Se algo der errado:

```batch
# 1. Parar novas stacks
docker-compose -f docker-compose.worker.yml down
docker-compose -f docker-compose.infra.yml down

# 2. Restaurar stack antiga no Portainer
#    (se ainda existir)

# 3. Ou recriar volumes (perda de dados!)
docker volume rm nistiprint-redis-data nistiprint-n8n-data
```

## Benefícios

| Antes | Depois |
|-------|--------|
| Deploy do worker derruba n8n | n8n sempre disponível |
| Webhooks perdidos no deploy | Webhooks processados normalmente |
| Redis reinicia com worker | Redis sempre estável |
| Stack única (ponto único de falha) | Stacks isoladas |
| Diffícil escalar | Pode escalar worker independentemente |

## Próximos Passos (Opcional)

1. **Redis Sentinel** - High availability do Redis
2. **n8n com PostgreSQL** - Mais robusto que SQLite
3. **Worker com auto-scaling** - Mais workers sob carga
4. **Monitoring** - Prometheus + Grafana
