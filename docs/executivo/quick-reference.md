# 🚀 QUICK REFERENCE - NISTIPRINT FIXES

**Use este documento para implementação rápida durante sprints**

---

## P0 SPRINT (Semana 1) - BLOQUEADORES

### 1️⃣ View SQL Rastreamento

**Arquivo**: `supabase/migrations/xxx_create_v_pedido_demanda_rastreamento.sql`

```sql
CREATE OR REPLACE VIEW v_pedido_demanda_rastreamento AS
SELECT 
    pb.id AS pedido_id,
    pb.numero_pedido,
    pb.codigo_pedido_externo,
    dio.quantidade_atendida,
    id_demanda.id AS item_demanda_id,
    dp.id AS demanda_id,
    dp.demanda_id AS demanda_numero,
    dp.status AS demanda_status
FROM pedidos_bling pb
LEFT JOIN demandas_item_origem dio ON pb.codigo_pedido_externo = dio.pedido_externo_id
LEFT JOIN itens_demanda id_demanda ON dio.demanda_item_id = id_demanda.id
LEFT JOIN demandas_producao dp ON id_demanda.demanda_id = dp.id;

-- Índices
CREATE INDEX idx_v_pedido_demanda_pedido ON demandas_item_origem(pedido_externo_id);
CREATE INDEX idx_v_pedido_demanda_demanda ON itens_demanda(demanda_id);
```

**Status**: ⏳ TODO | **Tempo**: 1h | **Responsável**: Backend SQL

---

### 2️⃣ API GET /pedidos/{id}/demandas

**Arquivo**: `apps/api/routes/pedidos.py` (adicionar ao final)

```python
@pedidos_bp.route('/<int:pedido_id>/demandas', methods=['GET'])
@login_required
def get_pedido_demandas(pedido_id):
    """GET /api/v2/pedidos/{pedido_id}/demandas"""
    try:
        pedido = supabase_db.table('pedidos').select('*').eq('id', pedido_id).single()
        if not pedido:
            return jsonify({'success': False}), 404
        
        demandas = supabase_db.execute(
            "SELECT demanda_id, demanda_numero, demanda_status, data_entrega, quantidade_atendida "
            "FROM v_pedido_demanda_rastreamento WHERE pedido_id = :id ORDER BY demanda_id DESC",
            {'id': pedido_id}
        )
        
        return jsonify({
            'success': True,
            'demandas': demandas or [],
            'incluido': len(demandas or []) > 0
        })
    except Exception as e:
        logger.error(f"Erro: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
```

**Status**: ⏳ TODO | **Tempo**: 30min | **Responsável**: Backend API

---

### 3️⃣ API GET /demandas/{id}/pedidos

**Arquivo**: `apps/api/routes/demandas.py` (adicionar ao final)

```python
@demandas_bp.route('/<int:demanda_id>/pedidos', methods=['GET'])
@login_required
def get_demanda_pedidos(demanda_id):
    """GET /api/v2/demandas/{demanda_id}/pedidos"""
    try:
        demanda = supabase_db.table('demandas_producao').select('*').eq('id', demanda_id).single()
        if not demanda:
            return jsonify({'success': False}), 404
        
        pedidos = supabase_db.execute(
            "SELECT DISTINCT numero_pedido, codigo_pedido_externo, plataforma, quantidade_atendida "
            "FROM v_pedido_demanda_rastreamento WHERE demanda_id = :id ORDER BY pedido_data DESC",
            {'id': demanda_id}
        )
        
        return jsonify({
            'success': True,
            'pedidos': pedidos or [],
            'total': len(pedidos or [])
        })
    except Exception as e:
        logger.error(f"Erro: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
```

**Status**: ⏳ TODO | **Tempo**: 30min | **Responsável**: Backend API

---

### 4️⃣ Coluna Frontend: Pedidos List

**Arquivo**: `apps/frontend/src/pages/pedidos/PedidosListPage.jsx`

**Adicionar antes do `return` da função (state):**
```jsx
const [demandaMap, setDemandaMap] = useState(new Map());

// Effect para carregar demandas
useEffect(() => {
  const load = async () => {
    const map = new Map();
    for (const p of pedidos.slice(0, 100)) {
      const res = await fetch(`/api/v2/pedidos/${p.id}/demandas`);
      const d = await res.json();
      if (d.demandas?.length) map.set(p.id, d.demandas[0]);
    }
    setDemandaMap(map);
  };
  pedidos.length && load();
}, [pedidos]);
```

**Adicionar coluna na tabela:**
```jsx
{
  id: 'demanda',
  header: 'Demanda',
  cell: ({ row }) => {
    const dem = demandaMap.get(row.original.id);
    return dem ? (
      <Badge variant="outline" className="cursor-pointer hover:opacity-75"
        onClick={() => navigate(`/demandas/${dem.demanda_id}`)}>
        {dem.demanda_numero} #{dem.demanda_status}
      </Badge>
    ) : <span className="text-gray-400">-</span>;
  }
}
```

**Status**: ⏳ TODO | **Tempo**: 45min | **Responsável**: Frontend

---

### 5️⃣ Tabela worker_logs

**Arquivo**: `supabase/migrations/xxx_create_worker_logs.sql`

```sql
CREATE TABLE worker_logs (
    id BIGSERIAL PRIMARY KEY,
    task_name VARCHAR(100),
    level VARCHAR(20),
    message TEXT,
    pedido_id INTEGER REFERENCES pedidos(id),
    demanda_id INTEGER REFERENCES demandas_producao(id),
    detalhes JSONB DEFAULT '{}',
    erro TEXT,
    celery_task_id VARCHAR(255),
    timestamp TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_worker_logs_timestamp ON worker_logs(timestamp DESC);
CREATE INDEX idx_worker_logs_level ON worker_logs(level);
CREATE INDEX idx_worker_logs_pedido ON worker_logs(pedido_id);
```

**Status**: ⏳ TODO | **Tempo**: 30min | **Responsável**: Backend SQL

---

### 6️⃣ Task Worker: auto_consolidate_pedido

**Arquivo**: `apps/worker/tasks/auto_consolidation_tasks.py` (novo)

```python
from celery import shared_task
from nistiprint_shared.services.consolidation_service import ConsolidationService
from nistiprint_shared.database.supabase_db_service import supabase_db
import logging, traceback

logger = logging.getLogger(__name__)
LOGS_TABLE = 'worker_logs'

def log_worker(task_name, level, msg, pedido_id=None, demanda_id=None, erro=None):
    """Salva log estruturado"""
    try:
        supabase_db.table(LOGS_TABLE).insert({
            'task_name': task_name, 'level': level, 'message': msg,
            'pedido_id': pedido_id, 'demanda_id': demanda_id,
            'erro': erro, 'timestamp': 'now()'
        }).execute()
    except: pass

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def auto_consolidate_pedido(self, pedido_id: int):
    """Auto-consolida pedido em rascunho"""
    log_worker('auto_consolidate', 'INFO', f'Iniciando {pedido_id}', pedido_id=pedido_id)
    
    try:
        consolidation = ConsolidationService()
        pedido = supabase_db.table('pedidos').select('*').eq('id', pedido_id).single()
        
        if not pedido:
            log_worker('auto_consolidate', 'ERROR', 'Pedido não encontrado', pedido_id=pedido_id, 
                      erro=f'ID {pedido_id} not exist')
            return {'sucesso': False}
        
        resultado = consolidation.consolidar_pedido(pedido_id)
        
        log_worker('auto_consolidate', 'INFO', 'Sucesso',
                  pedido_id=pedido_id, demanda_id=resultado.get('demanda_id') if resultado else None)
        
        return {'sucesso': True, 'demanda': resultado}
    
    except Exception as e:
        erro_trace = traceback.format_exc()
        log_worker('auto_consolidate', 'ERROR', 'Erro ao consolidar',
                  pedido_id=pedido_id, erro=erro_trace)
        
        try:
            raise self.retry(exc=e, countdown=60)
        except:
            return {'sucesso': False, 'erro': str(e)}
```

**Status**: ⏳ TODO | **Tempo**: 1h | **Responsável**: Worker

---

### 7️⃣ Integrar Task no Webhook

**Arquivo**: `apps/worker/tasks/pedidos_fetch_tasks.py`

**Encontrar**: `sync_pedidos_bling()` ou similar  
**Adicionar após `upsert_order()`**:

```python
# Após cada pedido inserido
pedido_id = upsert_order(account_id, pedido_data)

# NOVO: Disparar consolidação automática
from tasks.auto_consolidation_tasks import auto_consolidate_pedido
auto_consolidate_pedido.delay(pedido_id)
```

**Status**: ⏳ TODO | **Tempo**: 15min | **Responsável**: Worker

---

## P1 SPRINT (Semana 2) - MELHORIAS

### 8️⃣ Aba "Pedidos Origem" em DemandaDetailPage

**Arquivo**: `apps/frontend/src/pages/demandas/DemandaDetailPage.jsx`

```jsx
// Adicionar aba
const tabs = [
  { id: 'info', label: 'Info' },
  { id: 'pedidos', label: `Pedidos (${pedidosOrigens.length})` }, // NOVO
  { id: 'timeline', label: 'Timeline' }
];

// Effect para carregar
useEffect(() => {
  fetch(`/api/v2/demandas/${demandaId}/pedidos`)
    .then(r => r.json())
    .then(d => setPedidosOrigens(d.pedidos || []))
    .catch(e => console.error(e));
}, [demandaId]);

// Render pedidos
{abaSelecionada === 'pedidos' && (
  <table className="w-full">
    <thead>
      <tr><th>Número</th><th>Plataforma</th><th>Qtd</th></tr>
    </thead>
    <tbody>
      {pedidosOrigens.map(p => (
        <tr key={p.pedido_id}>
          <td><a href={`/pedidos/${p.pedido_id}`}>{p.numero_pedido}</a></td>
          <td>{p.plataforma}</td>
          <td>{p.quantidade_atendida}</td>
        </tr>
      ))}
    </tbody>
  </table>
)}
```

**Status**: ⏳ TODO | **Tempo**: 45min | **Responsável**: Frontend

---

### 9️⃣ Consolidar Menus IA (Frontend ONLY)

✅ **Mudança**: Serviços Python já funcionam OK! Problema é só UX (2 menus redundantes).

**Arquivo**: `apps/frontend/src/pages/vendas/VendasPersonalizadasPage.jsx` (refatorar)

**Mudança 1** - Adicionar 4 abas no componente:
```jsx
const abas = [
  { id: 'pendentes', label: 'Pendentes Extração' },
  { id: 'identificados', label: 'Nomes Extraídos' },
  { id: 'historico', label: 'Histórico' },
  { id: 'logs', label: 'Logs IA' }
];
```

**Mudança 2** - Redirecionar menus redundantes em router:
```jsx
// Em apps/frontend/src/router/ ou App.jsx
<Route path="/ai" element={<Navigate to="/vendas/personalizadas" replace />} />
<Route path="/vendas/identificacao-ia" element={<Navigate to="/vendas/personalizadas" replace />} />
```

**Mudança 3** - Backend: ZERO mudanças (serviços já funcionam corretamente)

**Status**: ⏳ TODO | **Tempo**: 1-2h | **Responsável**: Frontend

---

### 🔟 Página RascunhosPage

**Arquivo**: `apps/frontend/src/pages/demandas/RascunhosPage.jsx`

**Template básico**:
```jsx
export default function RascunhosPage() {
  const [rascunhos, setRascunhos] = useState([]);
  
  useEffect(() => {
    fetch('/api/v2/demandas?status=RASCUNHO')
      .then(r => r.json())
      .then(d => setRascunhos(d.demandas || []))
      .catch(e => console.error(e));
  }, []);
  
  const confirmar = async (id) => {
    await fetch(`/api/v2/demandas/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'PENDENTE' })
    });
    setRascunhos(rascunhos.filter(r => r.id !== id));
  };
  
  return (
    <div className="p-6">
      <h1>Rascunhos ({rascunhos.length})</h1>
      {rascunhos.map(r => (
        <div key={r.id} className="border p-4 mb-3">
          <div className="flex justify-between">
            <h3>#{r.demanda_numero} - {r.produto_id}</h3>
            <div className="gap-2">
              <button onClick={() => confirmar(r.id)} className="btn-success">Confirmar</button>
              <button onClick={() => descartar(r.id)} className="btn-danger">Descartar</button>
            </div>
          </div>
          {/* Pedidos expandíveis */}
        </div>
      ))}
    </div>
  );
}
```

**Status**: ⏳ TODO | **Tempo**: 1.5h | **Responsável**: Frontend

---

## P2 SPRINT (Semana 3) - OTIMIZAÇÕES

### 1️⃣1️⃣ API Debug: worker-logs

**Arquivo**: `apps/api/routes/debug.py` (novo)

```python
from flask import Blueprint, jsonify, request
from routes.auth import login_required
from nistiprint_shared.database.supabase_db_service import supabase_db

debug_bp = Blueprint('debug', __name__, url_prefix='/api/v2/debug')

@debug_bp.route('/worker-logs', methods=['GET'])
@login_required
def get_worker_logs():
    limit = request.args.get('limit', 100, type=int)
    level = request.args.get('level')
    
    q = supabase_db.table('worker_logs').select('*').order('timestamp', desc=True).limit(limit)
    if level:
        q = q.eq('level', level)
    
    logs = q.execute().data
    return jsonify({'success': True, 'logs': logs})
```

**Status**: ⏳ TODO | **Tempo**: 30min | **Responsável**: Backend API

---

### 1️⃣2️⃣ Cache IA (Redis)

**Arquivo**: `packages/shared/nistiprint_shared/services/ai_personalization/cache.py` (novo)

```python
from redis import Redis
import json

class CacheIdentificacao:
    def __init__(self, redis_client: Redis):
        self.redis = redis_client
    
    def get(self, pedido_id: str):
        """Retorna resultado em cache ou None"""
        data = self.redis.get(f'ident:{pedido_id}')
        return json.loads(data) if data else None
    
    def set(self, pedido_id: str, resultado: dict, ttl: int = 86400):
        """Salva resultado com TTL 24h"""
        self.redis.setex(f'ident:{pedido_id}', ttl, json.dumps(resultado))
    
    def clear(self, pedido_id: str):
        """Limpa cache manual"""
        self.redis.delete(f'ident:{pedido_id}')
```

**Status**: ⏳ TODO | **Tempo**: 45min | **Responsável**: Backend Cache

---

## 🧪 TESTES (Verificar depois de cada passo)

**Teste P0 - Rastreamento**
```curl
# View existe?
curl "http://{db}/v1/graphql" -H "Authorization: Bearer {token}" \
  -d '{"query":"SELECT pedido_id, demanda_id FROM v_pedido_demanda_rastreamento LIMIT 1"}'

# API funciona?
curl "http://localhost:5000/api/v2/pedidos/123/demandas"

# Frontend renderiza coluna?
Visit /pedidos → verificar coluna "Demanda"
```

**Teste P0 - Worker**
```bash
# Task Celery está registrada?
celery -A apps.worker.worker_entrypoint inspect active_queues

# Webhook dispara auto_consolidate?
# (enviara pedido teste via Bling webhook + verificar worker_logs)

tail -f /var/log/worker.log
# Procurar por "auto_consolidate_pedido"
```

**Teste P1 - Aba em Demandas**
```
Visit /demandas/1 → clicar aba "Pedidos"
Verificar lista de pedidos aparece corretamente
```

---

## 🚀 DEPLOY CHECKLIST

- [ ] Todos os migrations rodaram (`supabase migration up`)
- [ ] Views estão visíveis (`SELECT * FROM v_pedido_demanda_rastreamento`)
- [ ] APIs testadas com curl/Postman
- [ ] Frontend rebuild sem warnings
- [ ] Worker task registrada (`celery inspect active_queues`)
- [ ] Logs sendo salvo em `worker_logs`
- [ ] Staging testado end-to-end
- [ ] Pronto para prod

---

## 📞 DEBUG RÁPIDO

**"API retorna 404"**
```bash
# Verificar se view foi criada
SELECT EXISTS(SELECT 1 FROM information_schema.views WHERE table_name = 'v_pedido_demanda_rastreamento');

# Verificar dados
SELECT COUNT(*) FROM v_pedido_demanda_rastreamento WHERE demanda_id IS NOT NULL;
```

**"Worker não consolida"**
```bash
# Verificar task está registrada
celery -A apps.worker.worker_entrypoint inspect registered

# Ver logs
SELECT * FROM worker_logs WHERE task_name = 'auto_consolidate' ORDER BY timestamp DESC LIMIT 10;

# Verificar retry
SELECT COUNT(*) FROM worker_logs WHERE level = 'ERROR' AND timestamp > NOW() - INTERVAL '1 hour';
```

**"Frontend coluna vazia"**
```javascript
// Console browser
fetch('/api/v2/pedidos/123/demandas').then(r => r.json()).then(console.log)
// Você vê demandas? Se não, API não retorna dados
```

---

**Status**: Pronto para Implementação | **Versão**: 1.0 | **Atualizado**: Abril 2026
