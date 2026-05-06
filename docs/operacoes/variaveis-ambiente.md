# ===========================================
# VARIÁVEIS DE AMBIENTE - GUIA COMPLETO
# ===========================================

## Visão Geral

Este documento descreve todas as variáveis de ambiente necessárias para operar o Nistiprint ERP.

## 📋 Índice

1. [Variáveis Obrigatórias](#variáveis-obrigatórias)
2. [Variáveis Opcionais](#variáveis-opcionais)
3. [Exemplos por Ambiente](#exemplos-por-ambiente)
4. [Como Configurar](#como-configurar)

---

## Variáveis Obrigatórias

### Supabase (Database)

| Variável | Descrição | Exemplo |
|----------|-----------|---------|
| `SUPABASE_URL` | URL do projeto Supabase | `https://xxxxxxxxxxxxx.supabase.co` |
| `SUPABASE_SERVICE_KEY` | Service Role Key (backend) | `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...` |
| `SUPABASE_ANON_KEY` | Anon Key (frontend) | `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...` |
| `DATABASE_URL` | Connection string com PGBouncer | `postgresql://postgres.xxxxx:SENHA@aws-0-sa-east-1.pooler.supabase.com:6543/postgres?pgbouncer=true` |

**⚠️ Importante:** O `DATABASE_URL` deve usar:
- Porta **6543** (PGBouncer)
- Parâmetro `?pgbouncer=true`
- Formato: `postgresql://` (não `https://`)

### Flask (API)

| Variável | Descrição | Exemplo |
|----------|-----------|---------|
| `SECRET_KEY` | Chave para sessões e tokens | `a1b2c3d4e5f6...` (32+ caracteres) |
| `FLASK_ENV` | Ambiente | `development` ou `production` |

### Frontend (Vite)

| Variável | Descrição | Exemplo |
|----------|-----------|---------|
| `VITE_API_URL` | URL da API backend | `http://localhost:8080` |
| `VITE_SUPABASE_URL` | URL do Supabase (frontend) | `https://xxxxx.supabase.co` |
| `VITE_SUPABASE_ANON_KEY` | Anon Key (frontend) | `eyJhbGci...` |

---

## Variáveis Opcionais

### Webhooks

| Variável | Descrição | Exemplo |
|----------|-----------|---------|
| `WEBHOOK_TOKEN` | Token para validar webhooks | `meu_token_secreto_123` |
| `BLING_ID_LOJA` | ID da loja no Bling | `12345` |

### Integrações - Shopee

| Variável | Descrição | Exemplo |
|----------|-----------|---------|
| `SHOPEE_APP_ID` | App ID da Shopee | `123456` |
| `SHOPEE_APP_SECRET` | App Secret | `abcdef123456` |
| `SHOPEE_SHOP_ID` | ID da loja | `987654` |

### Integrações - Bling

| Variável | Descrição | Exemplo |
|----------|-----------|---------|
| `BLING_CLIENT_ID` | Client ID | `abc123` |
| `BLING_CLIENT_SECRET` | Client Secret | `xyz789` |
| `BLING_REDIRECT_URI` | Redirect URI OAuth | `https://seudominio.com/callback` |

### Google Cloud (Vertex AI)

| Variável | Descrição | Exemplo |
|----------|-----------|---------|
| `GOOGLE_CLOUD_PROJECT_ID` | ID do projeto GCP | `my-project-123` |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path para credentials JSON | `/app/credentials.json` |

### Logs

| Variável | Descrição | Exemplo | Padrão |
|----------|-----------|---------|--------|
| `LOG_LEVEL` | Nível de log | `INFO`, `DEBUG`, `ERROR` | `INFO` |
| `WORKER_LOG_LEVEL` | Nível do logger do worker Celery | `INFO`, `DEBUG`, `WARNING` | `INFO` |
| `WORKER_LOG_FILE` | Caminho do arquivo de log rotacionado do worker | `/var/log/nistiprint/worker.log` | `/var/log/nistiprint/worker.log` |
| `WORKER_LOG_BACKUP_COUNT` | Quantidade de arquivos diários mantidos | `30` | `30` |

---

## Exemplos por Ambiente

### Desenvolvimento Local (.env)

```env
# ===========================================
# SUPABASE
# ===========================================
SUPABASE_URL=https://abcdefghij.supabase.co
SUPABASE_SERVICE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFiY2RlZmdoaWoiLCJyb2xlIjoic2VydmljZV9yb2xlIiwiaWF0IjoxNjg...
SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFiY2RlZmdoaWoiLCJyb2xlIjoiYW5vbiIsImlhdCI6MTY4...
DATABASE_URL=postgresql://postgres.abcdefghij:MinhaSenha123@aws-0-sa-east-1.pooler.supabase.com:6543/postgres?pgbouncer=true

# ===========================================
# FLASK
# ===========================================
SECRET_KEY=dev_secret_key_for_local_development_only_12345
FLASK_ENV=development
FLASK_DEBUG=1

# ===========================================
# FRONTEND
# ===========================================
VITE_API_URL=http://localhost:8080
VITE_SUPABASE_URL=https://abcdefghij.supabase.co
VITE_SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

# ===========================================
# WEBHOOKS (opcional para testes)
# ===========================================
WEBHOOK_TOKEN=test_token_123
BLING_ID_LOJA=12345
```

### Produção - Portainer (.env)

```env
# ===========================================
# SUPABASE
# ===========================================
SUPABASE_URL=https://abcdefghij.supabase.co
SUPABASE_SERVICE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
DATABASE_URL=postgresql://postgres.abcdefghij:SenhaForte456@aws-0-sa-east-1.pooler.supabase.com:6543/postgres?pgbouncer=true

# ===========================================
# FLASK
# ===========================================
SECRET_KEY=8f7a9b2c1d3e4f5g6h7i8j9k0l1m2n3o4p5q6r7s8t9u0v1w2x3y4z
FLASK_ENV=production
FLASK_DEBUG=0

# ===========================================
# FRONTEND
# ===========================================
VITE_API_URL=http://localhost:8080
VITE_SUPABASE_URL=https://abcdefghij.supabase.co
VITE_SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

# ===========================================
# WEBHOOKS
# ===========================================
WEBHOOK_TOKEN=producao_token_super_secreto_789
BLING_ID_LOJA=12345

# ===========================================
# INTEGRAÇÕES
# ===========================================
SHOPEE_APP_ID=123456
SHOPEE_APP_SECRET=abcdef123456
SHOPEE_SHOP_ID=987654
```

### Produção - Webhook PHP no cPanel

```env
# ===========================================
# SUPABASE
# ===========================================
DATABASE_URL=postgresql://postgres.abcdefghij:SenhaForte456@aws-0-sa-east-1.pooler.supabase.com:6543/postgres?pgbouncer=true
SUPABASE_URL=https://abcdefghij.supabase.co
SUPABASE_SERVICE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

# ===========================================
# WEBHOOKS
# ===========================================
WEBHOOK_TOKEN=producao_token_super_secreto_789
BLING_ID_LOJA=12345

# ===========================================
# LOGS
# ===========================================
LOG_LEVEL=INFO
LOG_FILE=/var/log/webhooks.log
WORKER_LOG_LEVEL=INFO
WORKER_LOG_FILE=/var/log/nistiprint/worker.log
WORKER_LOG_BACKUP_COUNT=30
```

---

## Como Configurar

### 1. Obter credenciais do Supabase

1. Acesse https://supabase.com
2. Selecione seu projeto
3. Vá em **Settings** → **API**
4. Copie:
   - **Project URL** → `SUPABASE_URL`
   - **service_role secret** → `SUPABASE_SERVICE_KEY`
   - **anon public secret** → `SUPABASE_ANON_KEY`

5. Para `DATABASE_URL`:
   - Vá em **Settings** → **Database**
   - Copie **Connection string** (URI)
   - Modifique para usar PGBouncer:
     - Troque a porta para **6543**
     - Adicione `?pgbouncer=true` no final

### 2. Gerar SECRET_KEY

```bash
# Python
python -c "import secrets; print(secrets.token_hex(32))"

# OpenSSL
openssl rand -hex 32

# PowerShell
-join ((48..57) + (65..90) + (97..122) | Get-Random -Count 64 | ForEach-Object {[char]$_})
```

### 3. Configurar no Portainer

1. Acesse o Portainer
2. Vá em **Stacks** → Selecione sua stack
3. Clique em **Editor** ou **Environment Variables**
4. Adicione cada variável manualmente
5. Clique em **Update the stack**

### 4. Configurar no GitHub (Secrets)

1. GitHub → Repositório → **Settings**
2. **Secrets and variables** → **Actions**
3. **New repository secret**
4. Adicione:
   - `PORTAINER_WEBHOOK_URL` (URL do webhook do Portainer)
   - `DISCORD_WEBHOOK_URL` (opcional, para notificações)

### 5. Configurar no cPanel

**Via File Manager:**
1. cPanel → File Manager
2. Navegue até `public_html/webhooks`
3. Create New File → `.env`
4. Edit → Cole o conteúdo
5. Save

**Via FTP:**
1. Conecte via FTP
2. Upload do arquivo `.env` para `public_html/webhooks`

**Permissões:**
```bash
chmod 644 public_html/webhooks/.env
chown usuario:usuario public_html/webhooks/.env
```

---

## Validação

### Testar conexão com Supabase

```bash
# Do container da API
docker-compose run api python -c "
import os
from dotenv import load_dotenv
load_dotenv()
print('DATABASE_URL:', os.environ.get('DATABASE_URL')[:50] + '...')
print('SUPABASE_URL:', os.environ.get('SUPABASE_URL'))
"
```

### Testar variáveis do Frontend

```bash
# Do container do frontend
docker-compose run frontend sh -c "
echo 'VITE_API_URL:' \$VITE_API_URL
echo 'VITE_SUPABASE_URL:' \$VITE_SUPABASE_URL
"
```

### Verificar se todas variáveis estão setadas

```bash
# Script de validação
docker-compose run api python -c "
import os
required = ['SUPABASE_URL', 'SUPABASE_SERVICE_KEY', 'DATABASE_URL', 'SECRET_KEY']
missing = [var for var in required if not os.environ.get(var)]
if missing:
    print('❌ Variáveis faltando:', missing)
    exit(1)
else:
    print('✅ Todas variáveis configuradas')
"
```

---

## Troubleshooting

### Erro: "Connection refused" no banco

**Causa:** DATABASE_URL incorreta ou porta errada

**Solução:**
```env
# Errado (porta 5432 - conexão direta)
DATABASE_URL=postgresql://user:pass@host:5432/postgres

# Correto (porta 6543 - PGBouncer)
DATABASE_URL=postgresql://user:pass@host:6543/postgres?pgbouncer=true
```

### Erro: "Invalid API key" no Supabase

**Causa:** Chave errada ou expirada

**Solução:**
- Verificar se está usando `SERVICE_ROLE_KEY` (não `ANON_KEY`) no backend
- Renovar chaves em Supabase Dashboard → Settings → API

### Frontend não conecta na API

**Causa:** `VITE_API_URL` incorreta

**Solução:**
- Desenvolvimento: `http://localhost:8080`
- Produção: URL do backend ou proxy (ex: `/api`)

### Variáveis não carregam no cPanel

**Causa:** Arquivo `.env` não encontrado

**Solução:**
```php
// No PHP, carregar manualmente
$envFile = __DIR__ . '/.env';
if (file_exists($envFile)) {
    $envVars = parse_ini_file($envFile);
    foreach ($envVars as $key => $value) {
        putenv("$key=$value");
    }
}
```

---

## Segurança

### ✅ Boas Práticas

- [ ] Nunca commit `.env` no Git
- [ ] Usar `.env.example` como modelo
- [ ] Gerar chaves fortes (32+ caracteres)
- [ ] Rotacionar chaves periodicamente
- [ ] Usar secrets do Portainer/GitHub em produção
- [ ] Restringir IP no Supabase

### ❌ O que NÃO fazer

- [ ] Usar chaves de produção em desenvolvimento
- [ ] Compartilhar `.env` por email/chat
- [ ] Usar `SECRET_KEY` padrão
- [ ] Logar variáveis sensíveis
- [ ] Commitar acidentalmente (use `.gitignore`)

---

## Próximos Passos

- [ ] Implementar rotação automática de chaves
- [ ] Usar AWS Secrets Manager ou similar
- [ ] Auditoria de acesso às variáveis
- [ ] Criptografia de variáveis em repouso
