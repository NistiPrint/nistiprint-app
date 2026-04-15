# Avaliação Técnica - Sistema de Tarefas Assíncronas

**Data:** 2026-04-12  
**Objetivo:** Avaliar consistência, integridade e rastreabilidade do sistema de processamento assíncrono (Celery Worker)

---

## 1. Arquitetura Atual

### 1.1 Infraestrutura
- **Broker:** Redis (`redis://redis:6379/0`)
- **Backend:** Redis (para resultados)
- **Framework:** Celery 5.x
- **Container:** `apps/worker`

### 1.2 Tarefas Configuradas

#### Tarefas Periódicas (Beat Schedule)
| Task Name | Frequência | Descrição |
|-----------|------------|-----------|
| `sync-firestore-tokens` | 30 min | Sincroniza tokens Bling do Firestore para Supabase |
| `consumir-fila-bling` | 30 seg | Consome fila de webhooks do Bling no Redis |
| `processar-eventos-producao-periodic` | 10 seg | Processa eventos de estoque (Event Sourcing) |

#### Tarefas On-Demand (Worker)
| Task Name | Arquivo | Descrição |
|-----------|---------|-----------|
| `process_eventos_producao` | `eventos_tasks.py` | Processa eventos de produção e fila de estoque |
| `process_consolidacao` | `consolidation_tasks.py` | Consolida pedidos de plataformas (ML, Shopee, Amazon, Shein) |
| `sync_orders_with_bling` | `consolidation_tasks.py` | Sincroniza números de pedidos com Bling |
| `persist_orders_batch` | `consolidation_tasks.py` | Persiste pedidos em lote (assíncrono) |
| `fetch_pedidos_em_andamento` | `pedidos_fetch_tasks.py` | Busca pedidos "Em Andamento" do Bling |
| `classificar_e_consolidar_pedido` | `auto_consolidation_tasks.py` | Auto-consolidação de pedidos webhooks |
| `consumir_fila_bling` | `redis_queue_tasks.py` (shared) | Consome fila de webhooks |
| `sync_firestore_tokens` | `redis_queue_tasks.py` (shared) | Sincroniza tokens |
| `personalizados_tasks` | `personalizados_tasks.py` (shared) | Processamento de personalização IA |

---

## 2. Schema de Banco de Dados

### 2.1 Tabela `task_execution_logs`

**Migration:** `20260319000002_task_execution_logs.sql`  
**Enhancement:** `20260411000004_enhance_task_execution_logs.sql`

#### Colunas
| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | UUID | PK |
| `task_name` | VARCHAR(100) | Nome da tarefa |
| `status` | VARCHAR(50) | PENDING, PROCESSING, COMPLETED, FAILED, CANCELLED |
| `task_type` | VARCHAR(100) | Tipo/categoria da tarefa (enhancement) |
| `correlation_id` | VARCHAR(100) | ID para rastrear operações relacionadas (enhancement) |
| `metadata` | JSONB | Dados adicionais da execução |
| `retry_count` | INTEGER | Contador de retries (enhancement) |
| `last_retry_at` | TIMESTAMPTZ | Timestamp do último retry (enhancement) |
| `next_retry_at` | TIMESTAMPTZ | Timestamp do próximo retry (enhancement) |
| `created_at` | TIMESTAMPTZ | Quando o log foi criado |
| `started_at` | TIMESTAMPTZ | Quando a execução iniciou |
| `finished_at` | TIMESTAMPTZ | Quando a execução terminou |
| `error_message` | TEXT | Mensagem de erro (se houve) |

#### Índices
- `idx_task_execution_logs_status` (status)
- `idx_task_execution_logs_created_at` (created_at DESC)
- `idx_task_execution_logs_correlation_id` (correlation_id)
- `idx_task_execution_logs_task_type` (task_type)

---

## 3. API Endpoints

**Arquivo:** `apps/api/routes/tasks_api.py`

| Endpoint | Método | Descrição |
|----------|--------|-----------|
| `/api/v2/tasks/execution-logs` | GET | Lista logs com filtros (status, task_name, task_type, limit, offset) |
| `/api/v2/tasks/execution-logs/<id>` | GET | Detalhes de um log específico |
| `/api/v2/tasks/execution-logs/<id>/retry` | POST | Reenvia tarefa falha para processamento |
| `/api/v2/tasks/execution-logs/<id>/cancel` | POST | Cancela tarefa pendente/processing |
| `/api/v2/tasks/stats` | GET | Estatísticas (total, pending, processing, completed, failed, cancelled) |
| `/api/v2/tasks/stock/reprocess-events` | POST | Reprocessa eventos não processados |
| `/api/v2/tasks/stock/reprocess-fila` | POST | Reprocessa fila de estoque |
| `/api/v2/tasks/stock/reconcile-item/<item_id>` | POST | Reconcilia item específico |

---

## 4. UI de Monitoramento

**Arquivo:** `apps/frontend/src/pages/admin/utilitarios/TasksMonitorPage.jsx`

### Funcionalidades
- Dashboard com cards de estatísticas
- Tabela de execuções com filtros (status, task_name, task_type)
- Auto-refresh a cada 15 segundos
- Ações: Retry (falhas), Cancel (pending/processing), Ver erro
- Botões de reprocessamento (eventos, fila)
- Badge de status com ícones

### Estado Atual
**PROBLEMA:** A UI não está sendo populada porque as tarefas não registram logs em `task_execution_logs`.

---

## 5. Inconsistências Críticas Identificadas

### 5.1 Ausência de Registro de Logs

**SEVERIDADE:** CRÍTICA

Apenas **2 de 9 tarefas** registram execução em `task_execution_logs`:

| Tarefa | Registra Log? | Local |
|--------|---------------|-------|
| `process_eventos_producao` | ❌ NÃO | `eventos_tasks.py` |
| `process_consolidacao` | ❌ NÃO | `consolidation_tasks.py` |
| `sync_orders_with_bling` | ✅ SIM | `consolidation_tasks.py:332-418` |
| `persist_orders_batch` | ❌ NÃO | `consolidation_tasks.py` |
| `fetch_pedidos_em_andamento` | ❌ NÃO | `pedidos_fetch_tasks.py` |
| `classificar_e_consolidar_pedido` | ❌ NÃO | `auto_consolidation_tasks.py` |
| `consumir_fila_bling` | ❌ NÃO | `redis_queue_tasks.py` |
| `sync_firestore_tokens` | ❌ NÃO | `redis_queue_tasks.py` |
| `personalizados_tasks` | ❌ DESCONHECIDO | shared package |

**Consequências:**
- UI de monitoramento aparece vazia
- Impossível rastrear execuções
- Sem histórico para auditoria
- Impossível reprocessar com contexto

---

### 5.2 Falta de Padrão Centralizado

**SEVERIDADE:** ALTA

Não existe decorator ou classe base para padronizar o registro de logs. Cada tarefa implementa logging manualmente (ou não implementa).

**Problema:**
- Código duplicado em cada tarefa
- Inconsistência nos dados registrados
- Esquecimento de implementar logging
- Dificuldade de manutenção

---

### 5.3 Ausência de Correlation ID

**SEVERIDADE:** ALTA

O campo `correlation_id` existe no schema mas **NÃO é utilizado** nas tarefas.

**Uso atual de correlation_id:**
- Usado em operações de estoque (`motor_reconciliacao_estoque.py`, `estoque_service.py`)
- Usado em alocação de demanda (`demanda_producao_service.py`)
- **NÃO propagado para `task_execution_logs`**

**Consequências:**
- Impossível rastrear cadeia de operações
- Dificuldade em debugar problemas complexos
- Sem visibilidade end-to-end

---

### 5.4 Retry Management Inconsistente

**SEVERIDADE:** MÉDIA

As tarefas usam `max_retries=3` e `default_retry_delay=60` mas:
- `retry_count` em `task_execution_logs` NÃO é incrementado automaticamente
- `last_retry_at` e `next_retry_at` NÃO são preenchidos
- O retry do Celery é invisível na UI

**Exemplo:**
```python
@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_consolidacao(self, consolidacao_id):
    # ...
    self.retry(exc=e)  # Retry do Celery, mas não registrado no banco
```

---

### 5.5 Mecanismo de Reprocessamento Limitado

**SEVERIDADE:** MÉDIA

Os endpoints de reprocessamento (`/stock/reprocess-events`, `/stock/reprocess-fila`) executam processamento síncrono na API, não via worker.

**Problema:**
- Timeout em grandes volumes
- Sem registro em `task_execution_logs`
- Sem rastreabilidade
- Bloqueia a thread da API

---

### 5.6 Falta de Task Type

**SEVERIDADE:** BAIXA

O campo `task_type` existe mas não é preenchido, impossibilitando categorização:
- Por tipo de operação (ESTOQUE, PEDIDO, INTEGRAÇÃO, etc.)
- Por criticidade (CRÍTICA, NORMAL, BAIXA)
- Por origem (WEBHOOK, MANUAL, AGENDADA)

---

## 6. Recomendações

### 6.1 Criar Decorator de Task Logging (PRIORIDADE ALTA)

**Objetivo:** Padronizar registro automático de execuções

**Implementação sugerida:**
```python
# apps/worker/task_logger.py
from functools import wraps
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.utils.date_utils import get_now_iso
import uuid

def log_task_execution(task_type: str = None):
    """
    Decorator para registrar automaticamente execução de tarefas em task_execution_logs.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Gerar correlation_id se não fornecido
            correlation_id = kwargs.get('correlation_id') or str(uuid.uuid4())
            
            # Registrar início
            log_res = supabase_db.table('task_execution_logs').insert({
                'task_name': func.__name__,
                'task_type': task_type,
                'status': 'PROCESSING',
                'correlation_id': correlation_id,
                'started_at': get_now_iso(),
                'metadata': {'args': str(args), 'kwargs': str(kwargs)}
            }).execute()
            
            task_log_id = log_res.data[0]['id'] if log_res.data else None
            
            try:
                # Executar tarefa
                result = func(*args, **kwargs)
                
                # Registrar sucesso
                if task_log_id:
                    supabase_db.table('task_execution_logs').update({
                        'status': 'COMPLETED',
                        'finished_at': get_now_iso(),
                        'metadata': {'result': str(result)}
                    }).eq('id', task_log_id).execute()
                
                return result
                
            except Exception as e:
                # Registrar falha
                if task_log_id:
                    supabase_db.table('task_execution_logs').update({
                        'status': 'FAILED',
                        'finished_at': get_now_iso(),
                        'error_message': str(e)
                    }).eq('id', task_log_id).execute()
                raise
                
        return wrapper
    return decorator
```

**Uso:**
```python
@celery_app.task(bind=True, max_retries=3)
@log_task_execution(task_type='ESTOQUE')
def process_eventos_producao_task():
    # ...
```

---

### 6.2 Adicionar Correlation ID em Toda Cadeia (PRIORIDADE ALTA)

**Objetivo:** Rastrear operações end-to-end

**Implementação:**
1. Tarefas aceitam `correlation_id` como parâmetro opcional
2. Se não fornecido, gerar UUID
3. Propagar para serviços chamados
4. Registrar em `task_execution_logs`

**Exemplo:**
```python
@celery_app.task(bind=True)
@log_task_execution(task_type='PEDIDO')
def process_consolidacao(self, consolidacao_id, correlation_id=None):
    if not correlation_id:
        correlation_id = str(uuid.uuid4())
    
    # Propagar para serviços
    result = bling_client.process(..., correlation_id=correlation_id)
    # ...
```

---

### 6.3 Implementar Hook de Retry do Celery (PRIORIDADE MÉDIA)

**Objetivo:** Registrar retries automaticamente

**Implementação:**
```python
# celery_config.py
from celery.signals import task_prerun, task_postrun, task_failure

@task_prerun.connect
def task_prerun_handler(sender=None, task_id=None, task=None, **kwargs):
    # Atualizar retry_count se for retry
    # ...

@task_postrun.connect
def task_postrun_handler(sender=None, task_id=None, task=None, retval=None, **kwargs):
    # Registrar completion
    # ...

@task_failure.connect
def task_failure_handler(sender=None, task_id=None, exception=None, **kwargs):
    # Registrar falha e incrementar retry_count
    # ...
```

---

### 6.4 Converter Reprocessamento para Tarefas Assíncronas (PRIORIDADE MÉDIA)

**Objetivo:** Evitar timeout e garantir rastreabilidade

**Implementação:**
```python
@celery_app.task(bind=True)
@log_task_execution(task_type='REPROCESSAMENTO')
def reprocess_events_task(limit=50):
    # Lógica atual de reprocessamento
    # ...

# Endpoint API apenas dispara a tarefa
@tasks_api_bp.route('/stock/reprocess-events', methods=['POST'])
@login_required
def reprocess_events():
    celery_app.send_task('tasks.reprocess_events_task', args=[50])
    return jsonify({'success': True, 'message': 'Reprocessamento enfileirado'})
```

---

### 6.5 Adicionar Task Types (PRIORIDADE BAIXA)

**Categorias sugeridas:**
- `ESTOQUE` - Operações de estoque
- `PEDIDO` - Importação/consolidação de pedidos
- `INTEGRACAO` - Sincronização com APIs externas
- `REPROCESSAMENTO` - Reprocessamento de dados
- `MANUTENCAO` - Tarefas de manutenção
- `IA` - Processamento de IA

---

### 6.6 Adicionar Métricas e Alertas (PRIORIDADE BAIXA)

**Implementação:**
- Tempo médio de execução por tipo de tarefa
- Taxa de falhas por tarefa
- Alerta para tarefas com alta taxa de falha
- Dashboard de SLA

---

## 7. Plano de Implementação

### Fase 1: Correção Crítica (1-2 dias)
1. Criar decorator `@log_task_execution`
2. Aplicar decorator em todas as tarefas existentes
3. Testar população da UI

### Fase 2: Rastreabilidade (2-3 dias)
1. Adicionar `correlation_id` em todas as tarefas
2. Propagar correlation_id para serviços chamados
3. Testar rastreamento end-to-end

### Fase 3: Retry Management (1-2 dias)
1. Implementar hooks do Celery
2. Atualizar `retry_count`, `last_retry_at`, `next_retry_at`
3. Testar retry na UI

### Fase 4: Refinamento (1-2 dias)
1. Converter reprocessamento para assíncrono
2. Adicionar task types
3. Adicionar métricas básicas

**Total estimado:** 5-9 dias

---

## 8. Conclusão

O sistema possui infraestrutura adequada (Celery, Redis, schema de banco) mas **falta implementação consistente** de logging e rastreabilidade. A UI de monitoramento existe mas é inútil sem dados.

**Principais problemas:**
1. Apenas 22% das tarefas registram logs
2. Sem padrão centralizado
3. Sem correlation ID
4. Retry invisível
5. Reprocessamento síncrono

**Recomendação:** Implementar decorator de logging e aplicar em todas as tarefas imediatamente para habilitar monitoramento básico. Em seguida, adicionar correlation ID para rastreabilidade avançada.
