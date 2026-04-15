# ===========================================
# SETUP DESENVOLVIMENTO LOCAL (NISTIPRINT V3)
# ===========================================
# Guia para rodar a API, Worker e Shared Package
# tanto com Docker quanto localmente (Bare Metal)
# ===========================================

## Pré-requisitos
- Docker & Docker Compose
- Python 3.10+
- Node.js 18+ (para o frontend)

---

## Opção A: Rodar TUDO via Docker (Recomendado)

Esta opção garante que todo o ambiente (API, Worker, Redis, n8n) esteja isolado e configurado corretamente.

### 1. Iniciar Infraestrutura Base
O Redis e o n8n são compartilhados entre todas as versões.
```powershell
docker-compose -f nistiprint-ops/docker-compose.infra.yml up -d
```

### 2. Iniciar Aplicação V3 (API + Worker)
```powershell
# Na raiz do projeto
docker-compose up -d --build
```

### 3. Verificar Status
```powershell
docker-compose ps
# nistiprint-api      Up
# nistiprint-worker   Up
# nistiprint-redis    Up (via infra)
```

---

## Opção B: Rodar Localmente SEM Docker (Bare Metal)

Ideal para desenvolvimento rápido e debug com VS Code/PyCharm.

### 1. Iniciar apenas a Infraestrutura (Docker)
A API e o Worker precisam do Redis rodando.
```powershell
docker-compose -f nistiprint-ops/docker-compose.infra.yml up -d redis
```

### 2. Configurar o Pacote Compartilhado (Shared)
Este passo é **obrigatório** para que o Python encontre o módulo `nistiprint_shared`.

```powershell
# Crie e ative seu ambiente virtual na raiz ou em cada módulo
cd nistiprint-api
python -m venv venv
.\venv\Scripts\activate  # Windows

# Instale o shared em modo editável
pip install -e ..\nistiprint-shared
```

### 3. Instalar Dependências e Rodar a API
```powershell
# Dentro de nistiprint-api (com venv ativo)
pip install -r requirements.txt
python main.py
```
A API estará em `http://localhost:8080`.

### 4. Rodar o Worker (Celery)
```powershell
# Em um novo terminal (com o mesmo venv ativo)
cd nistiprint-worker
pip install -r requirements.txt
celery -A worker_entrypoint worker --loglevel=info
```

---

## Configuração de Ambiente (.env)

Cada módulo (`nistiprint-api`, `nistiprint-worker`, `nistiprint-legacy`) possui seu próprio arquivo `.env`.

**Exemplo para API Local (.env):**
```env
FLASK_ENV=development
DATABASE_URL=postgresql://user:pass@localhost:6543/db?pgbouncer=true
REDIS_HOST=localhost
REDIS_PORT=6379
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_SERVICE_KEY=xxx
```

*Nota: Ao rodar FORA do Docker, use `localhost` para o Redis. Ao rodar DENTRO do Docker, use `redis`.*

---

## Dicas de Desenvolvimento

### VS Code Settings
Para que o VS Code não acuse erros de import no `nistiprint_shared`, adicione o caminho ao `extraPaths`:

```json
{
  "python.analysis.extraPaths": [
    "./nistiprint-shared"
  ]
}
```

### Hot Reload
- **Docker**: O `docker-compose.yml` da raiz está configurado para refletir mudanças nos arquivos da API/Worker instantaneamente (via volumes).
- **Local**: O Flask e o Celery (com `--autoreload` se configurado) detectam mudanças automaticamente.

---

**Dúvidas frequentes?** Consulte `docs/troubleshooting/general.md`
