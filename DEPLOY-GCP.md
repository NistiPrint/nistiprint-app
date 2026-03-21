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
│  │  │  porta 8080 │    │ localhost   │                   │  │
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
location /api {
    proxy_pass http://127.0.0.1:5000/api;
    ...
}

location / {
    try_files $uri $uri/ /index.html;
}
```

---

## Logs

```bash
# Ver logs do serviço
gcloud run services logs read nistiprint-app --region southamerica-east1 --limit 50

# Logs em tempo real
gcloud run services logs tail nistiprint-app --region southamerica-east1
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

### Erro: "502 Bad Gateway"

O nginx não consegue conectar no gunicorn. Verifique:
```bash
gcloud run services logs read nistiprint-app --region southamerica-east1 --format="table(textPayload)" | grep -i "supervisor\|gunicorn\|nginx"
```

### API não responde

Verifique se o gunicorn está rodando:
```bash
gcloud run services logs read nistiprint-app --region southamerica-east1 --limit 50 | grep "Starting gunicorn"
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
| Escalabilidade | Independente | Acoplada |

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
