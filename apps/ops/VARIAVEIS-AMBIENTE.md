# Variáveis de Ambiente - Nistiprint

## Resumo Rápido

| Stack | Variáveis Necessárias |
|-------|----------------------|
| `nistiprint-infra` | 1 variável |
| `nistiprint-worker` | 3 variáveis |

---

## Stack: `nistiprint-infra` (Redis + n8n)

### Variáveis Obrigatórias

| Variável | Descrição | Onde Obter | Exemplo |
|----------|-----------|------------|---------|
| `BLING_CLENT_SECRET` | Client Secret da API Bling | [Bling Dev](https://dev.bling.com.br/) | `abc123xyz...` |

### Como Obter o `BLING_CLENT_SECRET`

1. Acesse https://dev.bling.com.br/
2. Faça login com sua conta Bling
3. Vá em **Aplicações** → **Minhas Aplicações**
4. Selecione sua aplicação ou crie uma nova
5. Copie o **Client Secret**

### Configuração no Portainer

1. Vá em **Stacks** → **Add stack**
2. Nome: `nistiprint-infra`
3. Web editor: cole o conteúdo de `docker-compose.infra.yml`
4. Clique em **Environment** (ou **Environment variables**)
5. Adicione:
   - **Name:** `BLING_CLENT_SECRET`
   - **Value:** `seu_client_secret_aqui`
6. Deploy the stack

---

## Stack: `nistiprint-worker` (Worker + Beat)

### Variáveis Obrigatórias

| Variável | Descrição | Onde Obter | Exemplo |
|----------|-----------|------------|---------|
| `SUPABASE_URL` | URL do projeto Supabase | Supabase Dashboard | `https://xxxxx.supabase.co` |
| `SUPABASE_SERVICE_KEY` | Chave de serviço do Supabase | Supabase Dashboard | `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...` |
| `FIREBASE_CREDENTIALS` | Credenciais JSON do Firebase | Firebase Console | `{ "type": "service_account", ... }` |

### Como Obter o `SUPABASE_URL`

1. Acesse https://supabase.com/dashboard
2. Selecione seu projeto
3. Vá em **Settings** → **API**
4. Copie a **Project URL**

### Como Obter o `SUPABASE_SERVICE_KEY`

1. Acesse https://supabase.com/dashboard
2. Selecione seu projeto
3. Vá em **Settings** → **API**
4. Copie a **service_role key** (⚠️ NÃO use a anon key!)

### Como Obter o `FIREBASE_CREDENTIALS`

1. Acesse https://console.firebase.google.com/
2. Selecione seu projeto
3. Vá em **Project Settings** (engrenagem)
4. Aba **Service Accounts**
5. Clique em **Generate new private key**
6. Baixe o arquivo JSON
7. Copie TODO o conteúdo do JSON (incluindo `{` e `}`)

### Formato do `FIREBASE_CREDENTIALS`

Deve ser uma string JSON válida, exemplo:

```json
{
  "type": "service_account",
  "project_id": "seu-projeto",
  "private_key_id": "abc123...",
  "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvQ...\n-----END PRIVATE KEY-----\n",
  "client_email": "firebase-adminsdk-xxxxx@seu-projeto.iam.gserviceaccount.com",
  "client_id": "123456789",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  ...
}
```

⚠️ **Importante:** No Portainer, cole o JSON inteiro em uma única linha ou use **Environment file** (.env)

### Configuração no Portainer

1. Vá em **Stacks** → **Add stack**
2. Nome: `nistiprint-worker`
3. Web editor: cole o conteúdo de `docker-compose.worker.yml`
4. Clique em **Environment** (ou **Environment variables**)
5. Adicione as 3 variáveis:

| Name | Value |
|------|-------|
| `SUPABASE_URL` | `https://xxxxx.supabase.co` |
| `SUPABASE_SERVICE_KEY` | `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...` |
| `FIREBASE_CREDENTIALS` | `{ "type": "service_account", ... }` |

6. Deploy the stack

---

## Opção Alternativa: Arquivo .env

Se preferir usar arquivo `.env` no Portainer:

### Template `.env`

```bash
# ===========================================
# NISTIPRINT - Variáveis de Ambiente
# ===========================================

# --- Infraestrutura (n8n) ---
BLING_CLENT_SECRET=seu_client_secret_aqui

# --- Worker ---
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_SERVICE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
FIREBASE_CREDENTIALS={"type":"service_account","project_id":"seu-projeto",...}
```

### Como Usar no Portainer

1. No Portainer, ao criar/editar a stack
2. Em **Environment**, selecione **File** em vez de variáveis individuais
3. Upload do arquivo `.env`
4. Deploy

---

## Verificação Pós-Deploy

### Stack Infra

```bash
# Verificar se está rodando
docker ps | findstr "nistiprint-n8n\|nistiprint-redis"

# Testar Redis
docker exec nistiprint-redis redis-cli ping
# Expected: PONG

# Testar n8n
curl https://automacao.nistiprint.neolabs.com.br/healthz
# Expected: {"status":"ok"}
```

### Stack Worker

```bash
# Verificar se está rodando
docker ps | findstr "nistiprint-app-worker\|nistiprint-app-beat"

# Testar Worker
docker exec nistiprint-app-worker celery -A worker_entrypoint inspect ping
# Expected: OK
```

---

## Troubleshooting

### n8n não inicia

1. Verifique os logs:
   ```bash
   docker logs nistiprint-n8n
   ```

2. Verifique se o Redis está saudável:
   ```bash
   docker ps | findstr redis
   ```

3. Verifique a variável `BLING_CLENT_SECRET`:
   ```bash
   docker inspect nistiprint-n8n | findstr BLING
   ```

### Worker não conecta ao Redis

1. Verifique se a rede `nistiprint-shared` existe:
   ```bash
   docker network ls | findstr nistiprint-shared
   ```

2. Se não existir, crie:
   ```bash
   docker network create nistiprint-shared
   ```

3. Verifique as variáveis do Supabase:
   ```bash
   docker inspect nistiprint-app-worker | findstr SUPABASE
   ```

### Erro de Firebase

1. Verifique se o JSON está válido:
   ```bash
   # Teste online: https://jsonlint.com/
   ```

2. Verifique se não há quebras de linha no JSON (deve ser uma linha só)

3. Verifique se o `private_key` está completo (incluindo `\n`)

---

## Checklist de Deploy

### Pré-Deploy

- [ ] Obter `BLING_CLENT_SECRET`
- [ ] Obter `SUPABASE_URL`
- [ ] Obter `SUPABASE_SERVICE_KEY`
- [ ] Obter `FIREBASE_CREDENTIALS` (JSON completo)
- [ ] Testar JSON do Firebase em https://jsonlint.com/

### Deploy Infra

- [ ] Criar stack `nistiprint-infra`
- [ ] Adicionar variável `BLING_CLENT_SECRET`
- [ ] Deploy
- [ ] Verificar: `docker ps | findstr nistiprint`
- [ ] Testar Redis: `docker exec nistiprint-redis redis-cli ping`

### Deploy Worker

- [ ] Criar stack `nistiprint-worker`
- [ ] Adicionar 3 variáveis (Supabase + Firebase)
- [ ] Deploy
- [ ] Verificar: `docker ps | findstr worker\|beat`
- [ ] Testar Worker: `docker exec nistiprint-app-worker celery -A worker_entrypoint inspect ping`

### Pós-Deploy

- [ ] Acessar n8n: https://automacao.nistiprint.neolabs.com.br/
- [ ] Verificar webhooks ativos
- [ ] Verificar filas do Celery processando
- [ ] Remover stack antiga `nistiprint-core` (opcional)

---

## Segurança

⚠️ **Nunca compartilhe estas variáveis!**

- `SUPABASE_SERVICE_KEY` tem acesso total ao banco
- `FIREBASE_CREDENTIALS` tem acesso ao Firebase
- `BLING_CLENT_SECRET` tem acesso à API Bling

**Boas práticas:**
- Use variáveis de ambiente do Portainer (não hardcode no docker-compose)
- Rotacione chaves periodicamente
- Monitore acessos não autorizados
