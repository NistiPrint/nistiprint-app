# Setup de Desenvolvimento Local

**Última atualização:** 2026-04-29

A produção roda nativamente via systemd (sem Docker para a aplicação). Recomendamos o mesmo padrão localmente: rodar API/Worker com Python direto e usar Docker apenas para Redis.

---

## Pré-requisitos

- Python 3.11+
- Node.js 20+
- Docker (apenas para o Redis local)
- Git

---

## 1. Clonar e preparar a venv

```bash
git clone https://github.com/NistiPrint/nistiprint-app.git
cd nistiprint-app

python -m venv .venv
# Linux/Mac
source .venv/bin/activate
# Windows (PowerShell)
.\.venv\Scripts\Activate.ps1

pip install --upgrade pip wheel
pip install -e packages/shared
pip install -r apps/api/requirements.txt
pip install -r apps/worker/requirements.txt
```

Uma única venv atende API + Worker — `packages/shared` instalado em modo editável (`-e`) faz com que qualquer alteração no código compartilhado seja refletida imediatamente nos dois.

---

## 2. Subir o Redis local

```bash
docker run -d --name nistiprint-redis-local -p 6379:6379 redis:7-alpine
```

(Opcional) também subir n8n se você precisa testar webhooks:
```bash
docker run -d --name nistiprint-n8n-local -p 5678:5678 -v n8n_data:/home/node/.n8n n8nio/n8n
```

---

## 3. Configurar `.env`

Crie um `.env` na raiz com:

```ini
FLASK_ENV=development
SECRET_KEY=algum-valor-qualquer-pra-dev

SUPABASE_URL=https://xxx.supabase.co
SUPABASE_SERVICE_KEY=eyJ...
DATABASE_URL=postgresql://user:pass@host:6543/db?pgbouncer=true

REDIS_HOST=127.0.0.1
REDIS_PORT=6379
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/0

FIREBASE_CREDENTIALS={"type":"service_account",...}
SHOPEE_PARTNER_ID=...
SHOPEE_PARTNER_KEY=...
```

> Lista completa das variáveis: [variaveis-ambiente.md](../operacoes/variaveis-ambiente.md).

---

## 4. Rodar a API

```bash
cd apps/api
python main.py        # dev server (Flask)
```

A API sobe em `http://localhost:8080`. Use o dev server em desenvolvimento — o `gunicorn` é só pra produção.

---

## 5. Rodar o Worker

Em outro terminal, com a mesma venv ativa:

```bash
cd apps/worker
celery -A worker_entrypoint worker --loglevel=info --concurrency=2
```

E o Beat (scheduler), em mais um terminal, se for testar tarefas agendadas:

```bash
cd apps/worker
celery -A worker_entrypoint beat --loglevel=info
```

---

## 6. Rodar o Frontend

```bash
cd apps/frontend
npm install
npm run dev
```

Vite sobe em `http://localhost:5173` com hot reload. Por padrão proxa `/api` para `http://localhost:8080` (ver `vite.config.js`).

---

## 7. Configuração do VS Code

Para que o autocomplete encontre `nistiprint_shared`, em `.vscode/settings.json`:

```json
{
  "python.defaultInterpreterPath": ".venv/bin/python",
  "python.analysis.extraPaths": ["packages/shared"]
}
```

(Em Windows: `.venv\\Scripts\\python.exe`.)

---

## 8. Encerrar tudo

```bash
# Ctrl+C nos terminais da API, Worker, Beat e Frontend
docker stop nistiprint-redis-local
```

---

## Dicas

- **Hot reload Python:** o Flask em modo dev recarrega sozinho ao salvar arquivos. O Celery não — você precisa reiniciar o worker após mudar código de tasks.
- **Reset Redis local:** `docker exec nistiprint-redis-local redis-cli FLUSHALL`
- **Testar uma task manualmente:**
  ```python
  from worker_entrypoint import celery_app
  celery_app.send_task('tasks.minha_task', args=[...])
  ```
