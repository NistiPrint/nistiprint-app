# Guia Rápido - Variáveis de Ambiente

## 📋 Resumo

| Stack | Variáveis | Total |
|-------|-----------|-------|
| **nistiprint-infra** | `BLING_CLENT_SECRET` | 1 |
| **nistiprint-worker** | `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `FIREBASE_CREDENTIALS` | 3 |

---

## 🔑 Onde Obter Cada Variável

### 1. BLING_CLENT_SECRET
```
📍 https://dev.bling.com.br/
   → Login → Aplicações → Minhas Aplicações → Client Secret
```

### 2. SUPABASE_URL
```
📍 https://supabase.com/dashboard
   → Selecionar projeto → Settings → API → Project URL
```

### 3. SUPABASE_SERVICE_KEY
```
📍 https://supabase.com/dashboard
   → Selecionar projeto → Settings → API → service_role key
   ⚠️ NÃO use a "anon" key!
```

### 4. FIREBASE_CREDENTIALS
```
📍 https://console.firebase.google.com/
   → Selecionar projeto → Project Settings (⚙️)
   → Service Accounts → Generate new private key
   → Baixar JSON → Copiar conteúdo completo
```

---

## 🚀 Deploy no Portainer

### ⚠️ Importante: Ordem de Deploy!

**Sempre deploy da infra PRIMEIRO!** O Redis precisa estar saudável antes do worker.

### Stack Infra (1 variável) - DEPLOY PRIMEIRO

```
1. Stacks → Add stack
2. Nome: nistiprint-infra
3. Web editor: cole docker-compose.infra.yml
4. Environment → Add variable:
   Name:  BLING_CLENT_SECRET
   Value: seu_valor_aqui
5. Deploy the stack
6. ⚠️ AGUARDE: Redis e n8n devem estar "Running" (~30s)
```

### Stack Worker (3 variáveis) - DEPLOY DEPOIS

```
1. Verifique infra rodando:
   docker ps | findstr "nistiprint-redis\|nistiprint-n8n"

2. Stacks → Add stack
3. Nome: nistiprint-worker
4. Web editor: cole docker-compose.worker.yml
5. Environment → Add variables:
   
   Name:  SUPABASE_URL
   Value: https://xxxxx.supabase.co
   
   Name:  SUPABASE_SERVICE_KEY
   Value: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
   
   Name:  FIREBASE_CREDENTIALS
   Value: {"type":"service_account",...} (JSON inteiro)
   
6. Deploy the stack
7. ⚠️ Worker pode levar 30-60s para ficar saudável
```

---

## ✅ Verificação

```bash
# Infra rodando?
docker ps | findstr "nistiprint-n8n\|nistiprint-redis"

# Worker rodando?
docker ps | findstr "nistiprint-app-worker\|nistiprint-app-beat"

# Redis saudável?
docker exec nistiprint-redis redis-cli ping
# Resposta: PONG

# Worker saudável?
docker exec nistiprint-app-worker celery -A worker_entrypoint inspect ping
# Resposta: OK
```

---

## ⚠️ Problemas Comuns

| Erro | Solução |
|------|---------|
| n8n não inicia | Verifique `BLING_CLENT_SECRET` |
| Worker não conecta | Verifique rede `nistiprint-shared` |
| Erro Firebase | JSON inválido (use https://jsonlint.com/) |
| Erro Supabase | Verifique se está usando `service_role` key |

---

## 📁 Arquivos de Referência

- `VARIAVEIS-AMBIENTE.md` - Guia completo
- `.env.template` - Template para copiar
- `docker-compose.infra.yml` - Stack de infra
- `docker-compose.worker.yml` - Stack de worker
