# ===========================================
# CORREÇÃO - TypeError: create_app()
# ===========================================
# Erro: "create_app() takes 0 positional arguments but 2 were given"
# ===========================================

## Erro

```
TypeError: create_app() takes 0 positional arguments but 2 were given
```

## Causa

O Gunicorn estava configurado para usar `passenger_wsgi:create_app`, mas o `create_app` é uma factory function que precisa ser **chamada** para retornar a aplicação Flask.

**Incorreto:**
```python
# passenger_wsgi.py
from main import create_app
# Gunicorn chama: create_app(environ, start_response) ❌
```

**Correto:**
```python
# passenger_wsgi.py
from main import create_app
app = create_app()  # Cria a instância do app

# Gunicorn chama: app(environ, start_response) ✓
```

## Solução Aplicada

### 1. passenger_wsgi.py (já estava correto)

```python
from main import create_app
app = create_app()  # ✓ Já estava assim
```

### 2. Dockerfile.api.dev

**Antes:**
```dockerfile
CMD ["gunicorn", ..., "passenger_wsgi:create_app", ...]
```

**Depois:**
```dockerfile
CMD ["gunicorn", ..., "passenger_wsgi:app", ...]
```

### 3. docker-compose.yml

**Antes:**
```yaml
command: >
  gunicorn ... passenger_wsgi:create_app --reload
```

**Depois:**
```yaml
command: >
  gunicorn ... passenger_wsgi:app --reload
```

---

## Como Aplicar a Correção

### Desenvolvimento Local

```bash
# Parar containers
docker-compose down

# Rebuild da API (importante!)
docker-compose build --no-cache api

# Subir novamente
docker-compose up -d

# Ver logs
docker-compose logs -f api
```

### Validação

```bash
# Testar login
curl -X POST http://localhost:8080/api/v2/login \
  -H "Content-Type: application/json" \
  -d '{"username":"test","password":"test"}'

# Deve retornar resposta da API (não erro 500)
```

---

## Entendendo o Erro

### WSGI Interface

O Gunicorn segue o padrão WSGI:

```python
# Assinatura WSGI
def application(environ, start_response):
    # environ: dados da requisição
    # start_response: callback para iniciar resposta
    pass
```

### Flask Application Factory

```python
# main.py
def create_app():
    app = Flask(__name__)
    # ... configurações ...
    return app  # Retorna uma instância Flask

# passenger_wsgi.py
from main import create_app
app = create_app()  # ← Cria a instância
```

### O Que Aconteceu

**Com o erro:**
```
Gunicorn → passenger_wsgi:create_app(environ, start_response)
                    ❌ create_app não aceita argumentos!
```

**Correto:**
```
Gunicorn → passenger_wsgi:app(environ, start_response)
                   ✓ app é um objeto Flask callable
```

---

## Lições Aprendidas

1. **Sempre usar `:app`** no Gunicorn, não `:create_app`
2. **Factory functions** devem ser chamadas no módulo de entrada
3. **Testar após mudanças** no comando do Gunicorn

---

## Checklist de Validação

- [x] `passenger_wsgi.py` exporta `app` (não `create_app`)
- [x] `Dockerfile.api.dev` usa `passenger_wsgi:app`
- [x] `docker-compose.yml` usa `passenger_wsgi:app`
- [ ] Rebuild realizado (`docker-compose build api`)
- [ ] Teste de login funciona
- [ ] Logs não mostram TypeError

---

**Status:** ✅ Corrigido

Próximo passo: `docker-compose build --no-cache api && docker-compose up -d`
# ===========================================
# CORREÇÃO - ECONNREFUSED API
# ===========================================
# Erro: Frontend não consegue conectar na API
# ===========================================

## Erro
```
proxy error AggregateError [ECONNREFUSED]: connect ECONNREFUSED ::1:8080
```

## Causa

O container do frontend (Nginx) estava apenas na rede `gateway_net`, mas precisa estar também na rede `app-internal` para comunicar com o container da API.

## Solução Aplicada

Adicionado `app-internal` às redes do frontend no `docker-compose.prod.yml`:

```yaml
frontend:
  networks:
    - gateway_net
    - app-internal  # Adicionado
```

---

## Como Corrigir (Deploy)

### 1. Produção (Portainer)

```bash
# Parar stack
docker-compose -f docker-compose.prod.yml down

# Subir novamente
docker-compose -f docker-compose.prod.yml up -d

# Verificar redes
docker network inspect app-internal | grep frontend
```

### 2. Validação

```bash
# Verificar se frontend está em ambas redes
docker network inspect gateway_net | grep frontend
docker network inspect app-internal | grep frontend

# Testar conexão do frontend para API
docker-compose exec frontend wget -q -O- http://api:8080/test_route

# Deve retornar: "Test route works!"
```

### 3. Testar API pelo browser

Acessar: `http://seu-ip/api/v2/current-user`

Deve funcionar sem erro de conexão.

---

## Arquitetura de Redes

```
┌─────────────────────────────────────────────────────┐
│                  gateway_net                         │
│  (Internet → NPM → frontend:80)                     │
│                       ↓                              │
│  ┌─────────────────────────────────────────────┐   │
│  │              app-internal                    │   │
│  │  (frontend → api:8080 → redis:6379)         │   │
│  │                                              │   │
│  │  ┌──────────┐  ┌─────┐  ┌────────┐         │   │
│  │  │ frontend │──│ api │──│ redis  │         │   │
│  │  └──────────┘  └─────┘  └────────┘         │   │
│  └─────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

---

## Se o erro persistir

### 1. Verificar se API está rodando

```bash
docker-compose ps api
# Deve mostrar: Up (healthy)
```

### 2. Testar API diretamente

```bash
curl http://localhost:8080/test_route
# Ou em produção:
curl http://api:8080/test_route
```

### 3. Verificar logs da API

```bash
docker-compose logs api
```

### 4. Verificar logs do frontend

```bash
docker-compose logs frontend
```

### 5. Reiniciar redes

```bash
# Parar tudo
docker-compose down

# Remover redes (se necessário)
docker network rm app-internal gateway_net

# Recriar redes
docker network create gateway_net
docker network create app-internal --internal

# Subir stack
docker-compose up -d
```

---

## Configuração Correta do Nginx

O `nginx.conf` já está configurado corretamente:

```nginx
location /api/ {
    proxy_pass http://api:8080;  # Nome do serviço Docker
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

**Importante:** O `proxy_pass` usa `api:8080` (nome do serviço na rede Docker), não `localhost:8080`.

---

## Checklist de Validação

- [ ] Frontend está em `gateway_net`
- [ ] Frontend está em `app-internal`
- [ ] API está em `app-internal`
- [ ] Teste `wget` do frontend para API funciona
- [ ] Requisição `/api/v2/current-user` funciona no browser
- [ ] Logs não mostram ECONNREFUSED

---

**Status:** ✅ Corrigido no docker-compose.prod.yml
# ===========================================
# CORREÇÃO DE ERROS - BUILD E IMPORT
# ===========================================
# Data: 20 de Fevereiro de 2026
# ===========================================

## Erro 1: ImportError - secretmanager

**Erro:**
```
ImportError: cannot import name 'secretmanager' from 'google.cloud'
```

**Causa:**
Biblioteca `google-cloud-secretmanager` faltando no requirements.txt

**Solução:**
Adicionado ao `core/backend/requirements.txt` (linha 24):
```txt
google-cloud-secretmanager
```

**Rebuild necessário:**
```bash
docker-compose build --no-cache api
docker-compose up -d
```

---

## Erro 2: ImportError - get_db_connection

**Erro:**
```
ImportError: cannot import name 'get_db_connection' from 'services.database.supabase_db_service'
```

**Causa:**
Função `get_db_connection` não existe no módulo `supabase_db_service.py`

**Solução:**
Arquivo `services/webhook_tasks.py` atualizado para usar `SupabaseDBService` diretamente:

**Antes:**
```python
from services.database.supabase_db_service import get_db_connection

supabase = get_db_connection()
```

**Depois:**
```python
from services.database.v2.supabase_db_service import SupabaseDBService

def get_supabase_client():
    return SupabaseDBService()

supabase = get_supabase_client()
```

**Rebuild necessário:**
```bash
docker-compose build --no-cache worker
docker-compose up -d
```

---

## Validação

### Testar imports
```bash
# Testar secretmanager
docker-compose exec api python -c "from google.cloud import secretmanager; print('OK')"

# Testar Supabase
docker-compose exec worker python -c "from services.webhook_tasks import process_shopee_webhook; print('OK')"
```

### Verificar logs
```bash
# API
docker-compose logs api

# Worker
docker-compose logs worker
```

### Esperado
- API: "✓ Successfully connected to Supabase database"
- Worker: Sem erros de import
- Ambos: Containers estáveis (sem restarts)

---

## Comandos de Rebuild Completo

```bash
# Parar tudo
docker-compose down

# Limpar cache
docker builder prune -a

# Rebuild API
docker-compose build --no-cache api

# Rebuild Worker
docker-compose build --no-cache worker

# Subir tudo
docker-compose up -d

# Ver logs
docker-compose logs -f
```

---

## Se os erros persistirem

1. Verificar requirements.txt:
```bash
docker-compose exec api pip list | grep secretmanager
# Deve mostrar: google-cloud-secretmanager
```

2. Verificar imports:
```bash
docker-compose exec worker python -c "
from services.database.v2.supabase_db_service import SupabaseDBService
print('SupabaseDBService:', SupabaseDBService)

from services.webhook_tasks import process_shopee_webhook
print('process_shopee_webhook:', process_shopee_webhook)
"
```

3. Forçar rebuild limpo:
```bash
docker-compose down -v
docker builder prune -a
docker-compose build --no-cache
docker-compose up -d
```

---

## Status das Correções

- [x] `google-cloud-secretmanager` adicionada ao requirements.txt
- [x] `webhook_tasks.py` atualizado para usar `SupabaseDBService`
- [x] Imports corrigidos
- [ ] Aguardando rebuild e validação

---

**Próximo passo:** Fazer rebuild dos containers e validar
