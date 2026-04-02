# Nistiprint - Arquitetura de Microsserviços

## Visão Geral

Esta é a nova arquitetura baseada em microsserviços do Nistiprint, separando a API (leve) do Worker (processamento pesado).

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Frontend   │────▶│     API     │────▶│    Redis    │
│   (React)   │     │   (Flask)   │     │   (Broker)  │
└─────────────┘     └─────────────┘     └──────┬──────┘
                                               │
                                               ▼
┌─────────────┐                         ┌─────────────┐
│   Banco     │◀────────────────────────│   Worker    │
│  (Supabase) │                         │  (Celery)   │
└─────────────┘                         └─────────────┘
```

## Serviços

### 1. Frontend (`nistiprint-frontend`)
- **Tecnologia:** React + Vite
- **Função:** Interface do usuário
- **Comunicação:** HTTP → API

### 2. API (`nistiprint-api`)
- **Tecnologia:** Flask
- **Função:** 
  - Autenticação
  - CRUD simples
  - Validação de requests
  - Producer de mensagens (Redis)
- **NUNCA faz:** Processamento pesado, geração de PDF, integrações demoradas

### 3. Worker (`nistiprint-worker`)
- **Tecnologia:** Celery + Python
- **Função:**
  - Processamento pesado
  - Integrações com terceiros (Bling, Shopee)
  - Geração de relatórios/PDF
  - Processamento de imagens
- **Headless:** Sem rotas HTTP, apenas consome Redis

### 4. Redis
- **Função:** Message Broker entre API e Worker
- **Filas:** 
  - `celery` (padrão)
  - `bling:webhooks:pendentes` (webhooks)

### 5. Shared (`nistiprint-shared`)
- **Função:** Biblioteca compartilhada
- **Conteúdo:**
  - Models (SQLAlchemy)
  - Configuração de database
  - Utilitários comuns

---

## Estrutura de Diretórios

```
nistiprint/
├── docker-compose.yml
├── nistiprint-shared/
│   ├── __init__.py
│   ├── models/
│   │   └── *.py (todos os models)
│   └── database/
│       └── supabase_db_service.py
├── nistiprint-api/
│   ├── Dockerfile
│   ├── main.py
│   ├── routes/
│   └── requirements.txt
├── nistiprint-worker/
│   ├── Dockerfile
│   ├── worker_entrypoint.py
│   ├── celery_config.py
│   ├── services/
│   │   ├── redis_queue_tasks.py
│   │   └── webhook_tasks.py
│   └── requirements.txt
└── nistiprint-frontend/
    └── ... (já existente)
```

---

## Manutenção e Boas Práticas (V3)

### 1. Inicialização de Ambiente e Infraestrutura
Sempre que criar um novo ponto de entrada (CLI, Script ou Microsserviço) que utilize o `nistiprint-shared`, a inicialização deve seguir esta ordem:
```python
from nistiprint_shared.utils.env_loader import load_nistiprint_env
from nistiprint_shared.database.initializer import setup_mock_query_interface

# Carrega o .env localizando-o recursivamente
load_nistiprint_env()

# Inicializa a compatibilidade Mock SQLAlchemy -> Supabase
setup_mock_query_interface()
```

### 2. Acesso ao Banco de Dados (Lazy Loading)
**NUNCA** acesse `supabase_db.client.table()` diretamente em construtores (`__init__`) ou escopo global de módulos. Isso causa erros de inicialização (`NoneType`) devido à ordem de importação.
- **Incorreto:** `self.table = supabase_db.client.table('tags')`
- **Correto:** `self.table = supabase_db.table('tags')` (Utiliza o método wrapper que garante a inicialização do cliente).

### 3. Registro de Novos Modelos
Ao adicionar um novo arquivo em `nistiprint_shared/models/`, ele deve ser registrado no dicionário `models_to_init` dentro de `nistiprint_shared/database/initializer.py` para que o atributo `.query` seja injetado corretamente.

### 4. Localização de Recursos (Templates/Static)
Evite caminhos relativos fixos (ex: `../../templates`). Utilize o `resource_helper`:
```python
from nistiprint_shared.utils.resource_helper import get_shared_resource_path
path = get_shared_resource_path('templates/prompts/prompt_template.txt')
```

### 5. Padrão de Imports
A V3 utiliza apenas imports absolutos do pacote compartilhado:
- `from nistiprint_shared.models.pedido import Pedido`
- `from nistiprint_shared.services.order_service import order_service`

---

## Regras de Ouro

### 1. Dependência Unilateral
- **Worker NUNCA importa da API**
- **API NUNCA importa do Worker**
- **Ambos importam apenas do shared**

### 2. Comunicação Cega
- API não sabe se worker está rodando
- API apenas enqueue no Redis e retorna 200 OK
- Worker consome Redis e processa

### 3. Task Discovery
- Nome da task no `send_task()` da API deve ser **idêntico** ao `name='...'` no `@shared_task` do Worker

### 4. Shared Kernel
- Tudo que é comum (models, db config) vai em `nistiprint-shared`
- Ambos serviços instalam shared como dependência

---

## Desenvolvimento

### Subir todos os serviços

```bash
docker-compose up -d
```

### Ver logs

```bash
# Todos
docker-compose logs -f

# Apenas worker
docker-compose logs -f worker

# Apenas API
docker-compose logs -f api
```

### Reiniciar serviço

```bash
docker-compose restart worker
```

### Escalar worker

```bash
docker-compose up -d --scale worker=3
```

---

## Deploy

### 1. Build

```bash
docker-compose build
```

### 2. Subir

```bash
docker-compose up -d
```

### 3. Health Check

```bash
# API
curl http://localhost:8080/test_route

# Worker (via logs)
docker-compose logs worker | grep "Celery worker is running"

# Redis
docker-compose exec redis redis-cli ping
```

---

## Adicionando Nova Task

### No Worker (`nistiprint-worker/services/minha_task.py`)

```python
from celery import shared_task

@shared_task(name='services.minha_task.processar_algo')
def processar_algo(dados: dict):
    # Processamento pesado aqui
    return {'status': 'success'}
```

### Registrar no `worker_entrypoint.py`

```python
celery_app = Celery(
    'nistiprint_worker',
    include=[
        'services.redis_queue_tasks',
        'services.webhook_tasks',
        'services.minha_task',  # ← Adicionar aqui
    ]
)
```

### Na API (`nistiprint-api/routes/algo.py`)

```python
from celery import Celery

celery = Celery(broker='redis://redis:6379/0')

@app.route('/api/processar', methods=['POST'])
def processar():
    # Apenas enfileira
    celery.send_task(
        'services.minha_task.processar_algo',
        args=[request.json]
    )
    return {'status': 'queued'}, 202
```

---

## Troubleshooting

### Worker não processa tarefas

1. Verificar se está na mesma rede que Redis:
   ```bash
   docker network inspect app-internal
   ```

2. Verificar tasks registradas:
   ```bash
   docker-compose exec worker celery -A worker_entrypoint inspect registered
   ```

3. Verificar logs:
   ```bash
   docker-compose logs worker
   ```

### API não conecta no Redis

1. Verificar variável de ambiente:
   ```bash
   docker-compose exec api env | grep REDIS
   ```

2. Testar conexão:
   ```bash
   docker-compose exec api python -c "import redis; r = redis.Redis(host='redis'); print(r.ping())"
   ```

---

**Última atualização:** Fevereiro de 2026  
**Status:** ✅ Em implementação
