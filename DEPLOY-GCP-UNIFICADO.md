# Deploy Unificado - Nistiprint no Google Cloud Run

## Visão Geral

Esta abordagem coloca **Frontend + API no mesmo container** Cloud Run, eliminando problemas de proxy e latência entre serviços.

### Arquitetura

```
┌─────────────────────────────────────────────────────────────┐
│  Cloud Run: nistiprint-app                                  │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Container Único (supervisord)                        │  │
│  │  ┌─────────────┐    ┌─────────────┐                   │  │
│  │  │   nginx     │───▶│  gunicorn   │                   │  │
│  │  │  porta 8080 │    │  localhost  │                   │  │
│  │  │             │    │  porta 5000 │                   │  │
│  │  └─────────────┘    └─────────────┘                   │  │
│  │         │                   │                         │  │
│  │    /api/* → proxy      Flask API                      │  │
│  │    /* → frontend                                      │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### Vantagens

- ✅ **Sem latência** entre frontend e API (localhost)
- ✅ **Sem problemas de proxy** externo
- ✅ **Mesma arquitetura** do ambiente atual (Docker Compose)
- ✅ **Mais simples** - apenas 1 serviço para gerenciar
- ✅ **Mais barato** - 1 instância ao invés de 2

---

## Deploy

### Comando Único

```bash
# Build + Push + Deploy
.\build-gcp-unified.bat
```

### Comandos Individuais

```bash
# Apenas build
.\build-gcp-unified.bat build

# Apenas push
.\build-gcp-unified.bat push

# Apenas deploy
.\build-gcp-unified.bat deploy
```

---

## Configuração

### Recursos do Cloud Run

| Recurso | Valor |
|---------|-------|
| Memória | 2 Gi |
| CPU | 1 |
| Min Instances | 1 |
| Timeout | 300s |
| Concurrency | 80 |

### Secrets Necessários

| Secret | Variável |
|--------|----------|
| `neolabs-nistiprint-firebase-adminsdk` | FIREBASE_CREDENTIALS |
| `DATABASE_URL_RIOMIDC` | DATABASE_URL |
| `GENAI_API_KEY_LEANDROGBREVE` | GEMINI_API_KEY |
| `AISTUDIO_APIKEY` | AISTUDIO_APIKEY |
| `SUPABASE_URL` | SUPABASE_URL |
| `SUPABASE_SERVICE_KEY` | SUPABASE_SERVICE_KEY |
| `SECRET_KEY` | SECRET_KEY |

---

## URLs

**App Unificado:** `https://nistiprint-app-992903106218.southamerica-east1.run.app`

---

## Segurança

### Proteção da API

A API está protegida por:

1. **CORS Restrito:** Aceita requisições apenas de:
   - `localhost:*` (desenvolvimento)
   - `127.0.0.1:*` (desenvolvimento)
   - `nistiprint-app-*.southamerica-east1.run.app` (Cloud Run)
   - `app.nistiprint.neolabs.com.br` (domínio customizado)

2. **Rate Limiting:** 10 requisições/segundo por IP (com burst de 20)

3. **Acesso Público:** Frontend é acessível de qualquer lugar

### Como Funciona a Proteção

```
┌─────────────────────────────────────────────────────────────┐
│  Requisição Recebida                                        │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  nginx verifica Origin header                               │
├─────────────────────────────────────────────────────────────┤
│  ✓ localhost:3000              → PERMITIDO                  │
│  ✓ nistiprint-app-xxx.run.app  → PERMITIDO                  │
│  ✓ app.nistiprint.neolabs.com  → PERMITIDO                  │
│  ✗ evil-site.com               → BLOQUEADO (403)            │
│  ✗ curl direto                 → BLOQUEADO (403)            │
└─────────────────────────────────────────────────────────────┘
```

### Configurar Domínio Customizado (Opcional)

```bash
# Mapear domínio próprio
gcloud run domain-mappings create \
    --service nistiprint-app \
    --domain app.nistiprint.neolabs.com.br \
    --region southamerica-east1
```

### Cloud Armor (Opcional - Proteção DDoS)

Para proteção adicional contra DDoS e ataques:

```bash
# Criar política de segurança
gcloud compute security-policies create nistiprint-policy \
    --description="Proteção Nistiprint"

# Adicionar rate limiting global
gcloud compute security-policies rules create 1000 \
    --security-policy nistiprint-policy \
    --expression "evaluatePreconfiguredExpr('rate-based-ban')" \
    --action "rate_based_ban"

# Associar ao Cloud Run
gcloud run services update nistiprint-app \
    --region southamerica-east1 \
    --security-policy nistiprint-policy
```

**Custo:** ~$3/mês + $1 por milhão de requisições

---

## Como Funciona

### 1. Build da Imagem

O Dockerfile unificado:
- **Stage 1:** Build da API (Python + dependências)
- **Stage 2:** Build do Frontend (Node + Vite)
- **Stage 3:** Production (nginx + supervisor + API)

### 2. Supervisor

O `supervisord` gerencia dois processos:
- **nginx** (porta 8080) - serve frontend + proxy
- **gunicorn** (porta 5000) - API Flask

### 3. Proxy nginx

```nginx
# Frontend: público
location / {
    try_files $uri $uri/ /index.html;
}

# API: protegido por CORS + Rate Limiting
location /api {
    # Verifica Origin header
    if ($http_origin !~* "^https?://(localhost|nistiprint-app-*.run.app)") {
        return 403;
    }
    
    # Rate limiting: 10 req/s por IP
    limit_req zone=api_limit burst=20 nodelay;
    
    proxy_pass http://127.0.0.1:5000/api;
}
```

---

## Logs

```bash
# Ver logs do serviço
gcloud run services logs read nistiprint-app --region southamerica-east1 --limit 50

# Logs em tempo real
gcloud run services logs tail nistiprint-app --region southamerica-east1

# Filtrar erros
gcloud run services logs read nistiprint-app --region southamerica-east1 --filter "severity>=ERROR"
```

---

## Custo Estimado

| Recurso | Quantidade | Custo/mês |
|---------|------------|-----------|
| Cloud Run (2Gi CPU 1) | 1 instância | ~$15-25 |
| Request (2M free) | Variável | Grátis* |

*Free tier: 2M requisições/mês

---

## Troubleshooting

### Erro: "Build failed"

Verifique se o contexto de build é a raiz do projeto:
```bash
docker build -f apps/api/Dockerfile.gcp-unified -t ... .
```

### Erro: "Container failed to start"

Verifique os logs:
```bash
gcloud run services logs read nistiprint-app --region southamerica-east1 --limit 100
```

### Erro: "403 CORS not allowed"

A origem da requisição não está na lista permitida. Verifique:
- Frontend está acessando de `localhost`, `run.app`, ou domínio configurado?
- Header `Origin` está sendo enviado?

### Erro: "429 Too Many Requests"

Rate limiting ativado. Aguarde ou aumente o limite no `nginx.conf.gcp`:
```nginx
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=20r/s;
```

---

## Comparação: Separado vs Unificado

| Aspecto | Separado | Unificado |
|---------|----------|-----------|
| Serviços Cloud Run | 2 | 1 |
| Latência frontend→API | ~5-10ms | ~1ms |
| Problemas de proxy | Possíveis | Nenhum |
| Custo base | ~$20-40/mês | ~$15-25/mês |
| Complexidade | Média | Baixa |
| Segurança | CORS complexo | CORS simplificado |

---

## Próximos Passos

1. ✅ Executar `.\build-gcp-unified.bat`
2. ✅ Aguardar deploy concluir (~3-5 minutos)
3. ✅ Acessar `https://nistiprint-app-992903106218.southamerica-east1.run.app`
4. ✅ Testar login
5. ✅ Monitorar logs

---

## Links Úteis

- [Console Cloud Run](https://console.cloud.google.com/run?project=neolabs-nistiprint&region=southamerica-east1)
- [Cloud Run Pricing](https://cloud.google.com/run/pricing)
- [Supervisor Documentation](http://supervisord.org/)
- [NGINX CORS Configuration](https://www.nginx.com/resources/wiki/start/topics/examples/cors/)
