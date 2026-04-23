# Guia de Deploy — Nistiprint

**Última atualização:** 2026-04-13

---

## 1. Visão Geral das Gerações

| Geração | Status | Pastas | Stack Portainer |
|---------|--------|--------|----------------|
| G1 (Legado PHP) | Manutenção mínima | `/app` | Google Cloud Run |
| G2 (v2 estável) | Produção | `nistiprint-core`, `nistiprint-frontend` | `nistiprint-v2-prod` |
| G3 (v3 nova) | Desenvolvimento ativo | `nistiprint-api`, `nistiprint-worker`, `nistiprint-shared` | `nistiprint-v3-dev` |

---

## 2. Arquitetura de Deploy

```
┌─────────────────────────────────────────────────────────┐
│              APLICAÇÕES (build.bat)                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐               │
│  │   API    │  │  WORKER  │  │ FRONTEND │               │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘               │
│       └──────────────┼──────────────┘                    │
│              Docker Hub (push)                           │
└──────────────────────┼───────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────┐
│              INFRAESTRUTURA (Portainer)                  │
│  ┌────────────────────┐  ┌────────────────────┐         │
│  │  nistiprint-infra  │  │   nistiprint-app   │         │
│  │  redis + n8n       │  │   api + frontend   │         │
│  └────────────────────┘  └────────────────────┘         │
│  ┌────────────────────┐                                 │
│  │  nistiprint-worker │                                 │
│  │  worker + beat     │                                 │
│  └────────────────────┘                                 │
└─────────────────────────────────────────────────────────┘
```

---

## 3. Deploy de Infraestrutura (Raro)

### Quando
- Primeira instalação
- Mudança no Redis ou n8n

### Como
```batch
cd apps/ops
deploy-infra.bat up
deploy-infra.bat status
```

### Verificação
```bash
docker exec nistiprint-redis redis-cli ping   # PONG
curl https://automacao.nistiprint.neolabs.com.br/healthz  # {"status":"ok"}
```

---

## 4. Deploy de Aplicações (Frequente)

### Build + Push
```batch
# Teste local
build.bat local
build.bat local worker

# Push completo
build.bat push

# Push de serviço específico
build.bat push worker
build.bat push api
build.bat push frontend
build.bat push v1.2.3 worker
```

### Portainer
1. **Worker** → Stacks → `nistiprint-worker` → Update the stack
2. **API** → Stacks → `nistiprint-app` → Update the stack
3. **Frontend** → Stacks → `nistiprint-app` → Update the stack

### Verificação Pós-Deploy
```bash
# Worker
docker exec nistiprint-worker celery -A worker_entrypoint inspect ping

# API
curl https://api.nistiprint.neolabs.com.br/health

# Frontend
# Acessar https://app.nistiprint.neolabs.com.br/
```

---

## 5. Deploy GCP (Cloud Run Unificado)

Para deploy do Frontend + API juntos no Google Cloud Run usando supervisord (nginx + gunicorn no mesmo container), consulte: [deploy-gcp.md](./deploy-gcp.md)

---

## 6. Rollback

### Worker
1. Portainer → Stacks → `nistiprint-worker`
2. Editar → mudar imagem para versão anterior
3. Update the stack

### Infraestrutura
```batch
cd apps/ops
deploy-infra.bat restart
```

---

## 7. Fluxo Típico de Desenvolvimento

```
1. Desenvolvimento local
   → build.bat local worker
   → docker-compose -f docker-compose.local.yml up -d

2. Commit e Push
   → git add . && git commit -m "fix: correção" && git push

3. Deploy em Produção
   → build.bat push worker
   → Portainer: Update stack nistiprint-worker
   → Verificar logs

4. Monitoramento
   → deploy-worker.bat logs
   → Verificar webhooks no n8n
```

---

## 8. Dicas

1. **Sempre teste localmente antes de publicar**
2. **Use tags semânticas** (`v1.2.3`, `dev`, `beta`)
3. **Nunca reinicie infra para deploy de worker** — stacks são independentes
4. **Shared package**: ao alterar `nistiprint-shared`, re-buildar API e Worker

---

## 9. Comandos Rápidos

| Comando | Função |
|---------|--------|
| `build.bat local` | Testa api + worker + frontend localmente |
| `build.bat push worker` | Publica apenas worker |
| `deploy-infra.bat up` | Sobe redis + n8n |
| `deploy-worker.bat logs` | Logs do worker em tempo real |

---

## 10. Arquivos de Referência

| Arquivo | Descrição |
|---------|-----------|
| `build.bat` | Build e push de aplicações |
| `apps/ops/deploy-infra.bat` | Deploy de infra |
| `apps/ops/deploy-worker.bat` | Deploy de worker |
| [variaveis-ambiente.md](./variaveis-ambiente.md) | Variáveis de ambiente |
| [infraestrutura.md](./infraestrutura.md) | Setup detalhado de infra |
| [troubleshooting.md](./troubleshooting.md) | Solução de problemas |
| [logging.md](./logging.md) | Configuração de logs com rotação |
