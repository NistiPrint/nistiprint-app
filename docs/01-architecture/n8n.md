# ===========================================
# ARQUITETURA N8N - DOCUMENTAÇÃO TÉCNICA
# ===========================================
# Status: ✅ IMPLEMENTADO
# Data: 20 de Fevereiro de 2026
# ===========================================

## Visão Geral da Nova Arquitetura

### Antes (Legado)
```
Plataformas → PHP Webhook → Supabase (direto)
```

### Agora (n8n + Celery)
```
Plataformas (Shopee/Bling)
    ↓ HTTPS
n8n (Webhook Receiver + Validação)
    ↓ Redis LPUSH (fila celery)
Celery Worker (Processamento)
    ↓
Supabase (Persistência)
```

## Componentes

### 1. n8n (Orquestrador de Webhooks)

**Função:** Receber, validar e enfileirar webhooks

**URLs dos Webhooks:**
- **Shopee:** `https://automacao.nistiprint.neolabs.com.br/webhook/shopee-webhook`
- **Bling:** `https://automacao.nistiprint.neolabs.com.br/webhook/bling-webhook`

**Fluxo:**
1. Recebe POST da plataforma
2. Valida token/assinatura
3. Formata payload para formato Celery
4. Push para Redis (lista `celery`)
5. Responde imediatamente (< 3s)

**Workflows:**
- `n8n/workflows/shopee-webhook.json`
- `n8n/workflows/bling-webhook.json`

### 2. Redis (Message Broker)

**Função:** Fila de mensagens entre n8n e Celery

**Configuração:**
```yaml
image: redis:7-alpine
command: redis-server --appendonly yes --maxmemory 256mb
volumes:
  - redis_data:/data  # Persistência
```

**Filas:**
- `celery` (índice 0): Tarefas Celery
- `n8n` (índice 1): Dados internos do n8n

**Porta:** 6379 (interna na rede `app-internal`)

### 3. Celery Worker (Processador)

**Função:** Processar webhooks da fila e atualizar Supabase

**Tasks:**
- `services.webhook_tasks.process_shopee_webhook`
- `services.webhook_tasks.process_bling_webhook`
- `services.webhook_tasks.process_pending_webhooks` (periódica)

**Configuração:**
```bash
celery -A services.celery_app worker --loglevel=info --concurrency=2
```

**Retry Automático:**
- Máximo 3 tentativas
- Backoff exponencial (60s, 120s, 240s)
- Para falhas temporárias

### 4. Celery Beat (Scheduler)

**Função:** Agendar tarefas periódicas

**Tarefas Agendadas:**
| Tarefa | Frequência | Descrição |
|--------|------------|-----------|
| `sync_all_inventory` | 6 em 6 horas | Sync de estoque |
| `process_pending_webhooks` | 5 em 5 minutos | Processar pendentes |
| `update_order_status` | 1 em 1 hora | Atualizar status |

## Redes Docker

### gateway_net
- **Propósito:** Comunicação com NPM (proxy reverso)
- **Containers:** n8n, frontend
- **Acesso:** Externo (via NPM)

### app-internal
- **Propósito:** Comunicação interna entre serviços
- **Containers:** n8n, api, worker, beat, redis
- **Acesso:** Interno (isolado)
- **Segurança:** `internal: true` (sem acesso externo)

```
┌─────────────────────────────────────────────────────────┐
│                    gateway_net                           │
│  (NPM → n8n:5678, NPM → frontend:80)                    │
│                                                          │
│  ┌──────────────┐    ┌──────────────┐                   │
│  │     n8n      │    │   frontend   │                   │
│  └──────┬───────┘    └──────────────┘                   │
│         │                                                 │
│         ▼                                                 │
│  ┌─────────────────────────────────────────────────┐    │
│  │              app-internal                        │    │
│  │  (isolada, sem acesso externo)                   │    │
│  │                                                   │    │
│  │  ┌──────┐  ┌─────┐  ┌────────┐  ┌──────┐        │    │
│  │  │ n8n  │──│ api │──│ worker │──│ redis│        │    │
│  │  └──────┘  └─────┘  └────────┘  └──────┘        │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

## Variáveis de Ambiente

### Stack app-core (Portainer)

```env
# ===========================================
# REDIS (Celery Broker)
# ===========================================
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0
REDIS_URL=redis://redis:6379/0

# ===========================================
# N8N
# ===========================================
N8N_HOST=automacao.nistiprint.neolabs.com.br
N8N_PORT=5678
N8N_PROTOCOL=https
N8N_ENCRYPTION_KEY=gerar_chave_aleatoria_aqui
N8N_DB_PASSWORD=senha_postgres_n8n

# Webhook Tokens
WEBHOOK_TOKEN=token_secreto_shopee
BLING_WEBHOOK_SECRET=token_secreto_bling

# ===========================================
# SUPABASE
# ===========================================
DATABASE_URL=postgresql://postgres.xxxxx:SENHA@aws-0-sa-east-1.pooler.supabase.com:6543/postgres?pgbouncer=true
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_SERVICE_KEY=eyJhbGci...
```

## Configuração no NPM (Proxy Reverso)

### 1. n8n (automacao.nistiprint.neolabs.com.br)

```json
{
  "domain": "automacao.nistiprint.neolabs.com.br",
  "forward_to": "n8n:5678",
  "ssl": true,
  "websockets": true,
  "hsts": true,
  "http2": true
}
```

**Importante:** Websockets devem estar **ATIVADOS** para a interface do n8n funcionar corretamente.

### 2. Frontend (app.nistiprint.neolabs.com.br)

```json
{
  "domain": "app.nistiprint.neolabs.com.br",
  "forward_to": "frontend:80",
  "ssl": true,
  "websockets": false
}
```

### 3. API (api.nistiprint.neolabs.com.br) - Opcional

```json
{
  "domain": "api.nistiprint.neolabs.com.br",
  "forward_to": "api:8080",
  "ssl": true,
  "websockets": false
}
```

## Deploy no Portainer

### 1. Criar Redes

```bash
# Rede para comunicação com NPM
docker network create gateway_net

# Rede interna para serviços
docker network create app-internal --internal
```

### 2. Criar Volumes

```bash
docker volume create nistiprint-n8n-data
docker volume create nistiprint-redis-data
```

### 3. Criar Stack

1. **Stacks** → **Add stack**
2. **Name:** `app-core`
3. **Build method:** Git Repository
4. **Repository URL:** `https://github.com/seu-usuario/nistiprint-erp.git`
5. **Repository Reference:** `main`
6. **Compose Path:** `docker-compose.prod.yml`

### 4. Configurar Variáveis

No Portainer, em **Environment Variables**:

| Variável | Valor |
|----------|-------|
| `CELERY_BROKER_URL` | `redis://redis:6379/0` |
| `N8N_HOST` | `automacao.nistiprint.neolabs.com.br` |
| `N8N_ENCRYPTION_KEY` | `(gerar aleatório)` |
| `WEBHOOK_TOKEN` | `(token Shopee)` |
| `BLING_WEBHOOK_SECRET` | `(token Bling)` |
| `DATABASE_URL` | `(Supabase com porta 6543)` |

### 5. Deploy e Validação

```bash
# Ver status dos containers
docker-compose ps

# Ver logs do n8n
docker-compose logs -f n8n

# Ver logs do worker
docker-compose logs -f worker

# Testar conexão Redis
docker-compose exec redis redis-cli ping
# Deve retornar: PONG
```

## Importar Workflows no n8n

### 1. Acessar n8n

- URL: `https://automacao.nistiprint.neolabs.com.br`
- Login: Admin (primeiro acesso)

### 2. Importar Workflows

1. **Settings** → **Import from File**
2. Selecionar `n8n/workflows/shopee-webhook.json`
3. Ativar workflow (toggle **Active**)
4. Repetir para `bling-webhook.json`

### 3. Configurar Credenciais Redis

1. **Credentials** → **Add Credential**
2. **Type:** Redis
3. **Connection:** `redis://redis:6379/0`
4. **Name:** `Redis Credentials`

### 4. Configurar Webhook URLs nas Plataformas

**Shopee:**
1. Shopee Partner Platform → Development → Webhook
2. URL: `https://automacao.nistiprint.neolabs.com.br/webhook/shopee-webhook?token=WEBHOOK_TOKEN`
3. Eventos: Order created, Order updated, Order cancelled

**Bling:**
1. Bling ERP → Configurações → Webhooks
2. URL: `https://automacao.nistiprint.neolabs.com.br/webhook/bling-webhook`
3. Eventos: Vendas, Produtos, Estoque

## Monitoramento

### 1. Dashboard Celery (Flower)

Opcional: Habilitar Flower para monitoramento Celery

```bash
# Adicionar ao docker-compose
flower:
  image: nistiprint-worker
  command: celery -A services.celery_app flower --port=5555
  ports:
    - "5555:5555"
```

Acessar: `https://flower.nistiprint.neolabs.com.br`

### 2. Logs em Tempo Real

```bash
# Worker
docker-compose logs -f worker

# n8n
docker-compose logs -f n8n

# Redis
docker-compose logs -f redis
```

### 3. Métricas Redis

```bash
# Acessar Redis CLI
docker-compose exec redis redis-cli

# Ver info
INFO

# Ver tamanho da fila
LLEN celery
```

### 4. Tarefas Ativas

```bash
# Inspecionar worker
docker-compose exec worker celery -A services.celery_app inspect active

# Ver tarefas registradas
docker-compose exec worker celery -A services.celery_app inspect registered

# Ping workers
docker-compose exec worker celery -A services.celery_app inspect ping
```

## Troubleshooting

### n8n não recebe webhooks

**Sintoma:** Webhooks não chegam no n8n

**Solução:**
1. Verificar NPM:
   ```bash
   docker logs nginx-proxy-manager
   ```
2. Testar URL externamente:
   ```bash
   curl -X POST https://automacao.nistiprint.neolabs.com.br/webhook/shopee-webhook
   ```
3. Verificar se n8n está ouvindo:
   ```bash
   docker-compose exec n8n wget -q http://localhost:5678/healthcheck
   ```

### Redis não conecta

**Sintoma:** n8n ou worker não conectam ao Redis

**Solução:**
1. Verificar rede:
   ```bash
   docker network inspect app-internal
   ```
2. Testar conexão:
   ```bash
   docker-compose exec n8n redis-cli -h redis ping
   ```
3. Verificar logs do Redis:
   ```bash
   docker-compose logs redis
   ```

### Celery não processa tarefas

**Sintoma:** Fila cresce mas tarefas não são processadas

**Solução:**
1. Verificar worker:
   ```bash
   docker-compose logs worker
   ```
2. Verificar se task está registrada:
   ```bash
   docker-compose exec worker celery -A services.celery_app inspect registered
   ```
3. Verificar broker:
   ```bash
   docker-compose exec redis redis-cli LRANGE celery 0 -1
   ```

### n8n perde conexão com Redis

**Sintoma:** Erro "Connection refused" no n8n

**Solução:**
1. Verificar se Redis está na mesma rede:
   ```bash
   docker network inspect app-internal | grep -A 10 n8n
   docker network inspect app-internal | grep -A 10 redis
   ```
2. Reiniciar n8n:
   ```bash
   docker-compose restart n8n
   ```

## Segurança

### 1. Tokens de Webhook

- **Shopee:** Usar `X-Webhook-Token` header
- **Bling:** Usar `X-Bling-Signature` header
- Armazenar em variáveis de ambiente no n8n

### 2. Isolamento de Rede

- Redis **NÃO** exposto externamente
- n8n acessível apenas via NPM (HTTPS)
- Worker e Beat em rede interna

### 3. Persistência Redis

```yaml
command: redis-server --appendonly yes
volumes:
  - redis_data:/data
```

Isso previne perda de filas em caso de restart.

### 4. Rate Limiting

Configurar no n8n para prevenir abuso:

```json
{
  "parameters": {
    "limits": {
      "maxConcurrent": 10,
      "rateLimitPeriod": "minute",
      "rateLimit": 100
    }
  }
}
```

## Migração do PHP

### Passo a Passo

1. **Parar webhook PHP:**
   ```bash
   # cPanel: Renomear arquivo
   mv shopee_webhook.php shopee_webhook.php.bak
   ```

2. **Importar workflows n8n:**
   - Seguir seção "Importar Workflows no n8n"

3. **Atualizar URLs nas plataformas:**
   - Shopee: Apontar para URL do n8n
   - Bling: Apontar para URL do n8n

4. **Validar processamento:**
   ```bash
   # Monitorar fila
   watch -n 1 'docker-compose exec redis redis-cli LLEN celery'
   
   # Monitorar worker
   docker-compose logs -f worker
   ```

5. **Remover PHP (após validação):**
   ```bash
   rm webhook_service/*.php
   ```

## Próximos Passos

- [ ] Implementar retry manual para webhooks falhos
- [ ] Dashboard de monitoramento de webhooks
- [ ] Alertas (Discord/Slack) para falhas
- [ ] Load balancing para workers (múltiplos containers)
- [ ] Flower para monitoramento Celery

---

**Arquitetura implementada com sucesso!**

Para dúvidas: `docs/DEPLOY_GUIDE.md` | `docs/VARIAVEIS_AMBIENTE.md`
