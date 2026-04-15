
# Manual de Infraestrutura: Nistiprint App

Este documento descreve a infraestrutura em produção da Nistiprint.

## 1. Visão Geral da Arquitetura

A infraestrutura é hospedada em um **servidor dedicado com Portainer**, organizada em stacks Docker:

```
┌─────────────────────────────────────────────────────────────┐
│                    SERVIDOR (Portainer)                     │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              nginx-proxy-manager                    │    │
│  │         (Proxy Reverso + SSL - Port 80/443)         │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌──────────────────┐  ┌──────────────────┐                │
│  │  nistiprint-infra│  │  nistiprint-app  │                │
│  │  ┌────────────┐  │  │  ┌────────────┐  │                │
│  │  │   redis    │  │  │  │    api     │  │                │
│  │  │    n8n     │  │  │  │  frontend  │  │                │
│  │  └────────────┘  │  │  └────────────┘  │                │
│  └──────────────────┘  └──────────────────┘                │
│                                                             │
│  ┌──────────────────┐                                       │
│  │ nistiprint-worker│                                       │
│  │  ┌────────────┐  │                                       │
│  │  │   worker   │  │                                       │
│  │  │    beat    │  │                                       │
│  │  └────────────┘  │                                       │
│  └──────────────────┘                                       │
└─────────────────────────────────────────────────────────────┘
```

## 2. Stacks Docker

### 2.1 nginx-proxy-manager
- **Função:** Proxy reverso, gerenciamento de SSL (Let's Encrypt), roteamento de domínios
- **Portas:** 80 (HTTP), 443 (HTTPS), 81 (Admin)
- **Domínios:**
  - `api.nistiprint.neolabs.com.br` → nistiprint-api
  - `app.nistiprint.neolabs.com.br` → nistiprint-frontend
  - `automacao.nistiprint.neolabs.com.br` → nistiprint-n8n

### 2.2 nistiprint-infra
- **Função:** Serviços de infraestrutura base
- **Serviços:**
  - **redis:** Fila de mensagens para Celery
  - **n8n:** Automação de webhooks (Bling, Shopee)

### 2.3 nistiprint-app
- **Função:** Aplicação principal
- **Serviços:**
  - **api:** API REST Flask/FastAPI
  - **frontend:** Aplicação React

### 2.4 nistiprint-worker
- **Função:** Processamento assíncrono de tarefas
- **Serviços:**
  - **worker:** Worker Celery para processamento de filas
  - **beat:** Agendador de tarefas periódicas Celery

## 3. Domínios e Endpoints

| Serviço | Domínio | Descrição |
|---------|---------|-----------|
| API | `https://api.nistiprint.neolabs.com.br` | API REST principal |
| Frontend | `https://app.nistiprint.neolabs.com.br` | Interface web |
| n8n | `https://automacao.nistiprint.neolabs.com.br` | Automação e webhooks |
| Portainer | `https://gestao.nistiprint.neolabs.com.br` | Gestão de containers |

## 4. Fluxo de Dados

### 4.1 Webhook Bling/Shopee
```
1. Evento na plataforma (Bling/Shopee)
   ↓
2. Webhook → n8n (automacao.nistiprint.neolabs.com.br)
   ↓
3. n8n → Redis (fila 'celery')
   ↓
4. Worker Celery processa a tarefa
   ↓
5. Resultado → Supabase/PostgreSQL
```

### 4.2 Requisição API
```
1. Frontend/Navegador
   ↓
2. nginx-proxy-manager (SSL termination)
   ↓
3. nistiprint-api
   ↓
4. Supabase/PostgreSQL
```

## 5. Aplicação Legada (Firestore)

A aplicação legada em PHP utiliza **Google Firestore** e serve como:

- **Origem para sincronização de tokens Bling**
- **Backup histórico de pedidos**

### Sincronização de Tokens
No dashboard: `configuracoes/integracoes > aba 'status' > botão 'sync legacy'`

Esta funcionalidade recupera os tokens de acesso das 3 contas Bling armazenados no Firestore e os migra para o banco de dados principal (Supabase).

## 6. Operações Comuns

### 6.1 Deploy de Nova Versão

```batch
# Build e push para Docker Hub
build.bat push worker        # Apenas worker
build.bat push api           # Apenas API
build.bat push frontend      # Apenas frontend
build.bat push               # Todos os serviços

# No Portainer:
# 1. Stacks → [stack desejada]
# 2. Update the stack
# 3. Aguardar ~60s
```

### 6.2 Verificação de Saúde

```bash
# Redis
docker exec nistiprint-redis redis-cli ping
# Expected: PONG

# Worker
docker exec nistiprint-worker celery -A worker_entrypoint inspect ping
# Expected: OK

# n8n Health Check
curl https://automacao.nistiprint.neolabs.com.br/healthz
# Expected: {"status":"ok"}

# API Health Check
curl https://api.nistiprint.neolabs.com.br/health
```

### 6.3 Logs em Tempo Real

```bash
# Worker
docker logs -f nistiprint-worker

# API
docker logs -f nistiprint-api

# n8n
docker logs -f nistiprint-n8n

# Redis
docker logs -f nistiprint-redis
```

### 6.4 Reiniciar Serviços

```bash
# No Portainer:
# 1. Stacks → [stack desejada]
# 2. Restart the stack

# Via Docker CLI:
docker restart nistiprint-worker
docker restart nistiprint-api
docker restart nistiprint-n8n
```

## 7. Troubleshooting

| Problema | Solução |
|----------|---------|
| Worker não processa filas | Verificar conexão Redis: `docker logs nistiprint-worker` |
| Webhooks não chegam | Verificar n8n: `docker logs nistiprint-n8n` |
| API indisponível | Verificar logs: `docker logs nistiprint-api` |
| SSL expirado | NPM → Certificates → Renew Let's Encrypt |
| Redis cheio | `docker exec nistiprint-redis redis-cli INFO memory` |

## 8. Backup e Recuperação

### Dados Críticos
- **Supabase:** Banco de dados principal (gerenciado externamente)
- **n8n:** Workflows e execuções (volume Docker)
- **Firestore:** Aplicação legada (gerenciado pelo Google)

### Backup n8n
```bash
# O volume do n8n contém database.sqlite com workflows
docker volume inspect nistiprint-infra_n8n_data
```

## 9. Variáveis de Ambiente

Consulte `apps/ops/VARIAVEIS-AMBIENTE.md` para lista completa.

### Principais Variáveis

#### nistiprint-infra
- `BLING_CLIENT_SECRET`: Segredo da API Bling
- `REDIS_URL`: URL de conexão Redis

#### nistiprint-app
- `SUPABASE_URL`: URL do projeto Supabase
- `SUPABASE_KEY`: Chave de serviço Supabase
- `REDIS_URL`: URL de conexão Redis

#### nistiprint-worker
- `SUPABASE_URL`: URL do projeto Supabase
- `SUPABASE_KEY`: Chave de serviço Supabase
- `REDIS_URL`: URL de conexão Redis
- `CELERY_BROKER_URL`: URL do broker Celery (Redis)
