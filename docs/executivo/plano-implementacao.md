# 📋 PLANO DE IMPLEMENTAÇÃO - NISTIPRINT

**Data**: 11 de abril de 2026  
**Status**: Pronto para Execução  
**Documentação de Referência**:
- [README-ANALISE.md](README-ANALISE.md) - Índice geral
- [ANALISE_EXECUTIVA.md](ANALISE_EXECUTIVA.md) - Para CTO/PM (10 min)
- [PLANO_CORRECAO_OTIMIZACAO.md](PLANO_CORRECAO_OTIMIZACAO.md) - Detalhamento técnico (50+ páginas)
- [QUICK-REFERENCE.md](QUICK-REFERENCE.md) - Cheat sheet para devs

---

## 🎯 FASE 0: DECISÃO & ALINHAMENTO (< 1 hora)

### Etapa 0.1: Leitura Executiva
**Para**: CTO, PM, Tech Lead  
**Tempo**: 10 minutos  
**Ação**: Ler [ANALISE_EXECUTIVA.md](ANALISE_EXECUTIVA.md)

**Checklist**:
- [ ] Entender os 3 problemas
- [ ] Revisar tabela de severidade (CRÍTICO = Problema 1 e 3)
- [ ] Visualizar timelineestimada (95 horas = 6-7 pessoa·semanas)
- [ ] Revisar ROI (€27k/ano para €11k investimento)

**Decisão**: GO ou NO-GO?  
**Se NO-GO**: Encerre aqui.  
**Se GO**: Prossiga para 0.2.

---

### Etapa 0.2: Briefing Técnico com Time
**Para**: CTO, Backend Lead, Frontend Lead, Arquiteto  
**Tempo**: 20 minutos  
**Ação**: Discutir pontos-chaves

**Topics a cobrir** (com seções do PLANO_CORRECAO_OTIMIZACAO):
1. ✅ FK chain funciona (demandas_item_origem já existe)
2. ✅ Serviços IA já estão OK (nenhuma refactoring necessária)
3. ❌ Rastreamento não exposto via API/UI (Problema 1)
4. ❌ Worker não auto-consolida (Problema 3)

**Checklist**:
- [ ] Tech Lead concorda com arquitetura proposta
- [ ] Nenhuma dependência externa não-listada
- [ ] Recursos (devs, tester) confirmados para Timeline

---

### Etapa 0.3: Alocar Recursos
**Para**: PM, Tech Lead  
**Tempo**: 5 minutos

**Time necessário**:
- **Backend**: 1-2 devs (40 horas Problema 1+3)
- **Frontend**: 1-2 devs (20 horas Problema 2+melhorias)
- **Worker**: 1 dev (10 horas Problema 3)
- **QA**: 1 tester (20 horas integração+e2e)

**Timeline esperada**: 2-3 semanas (dependendo de paralelização)

---

## 🔧 FASE 1: PROBLEMAS BLOQUEADORES (40 horas)

**Objetivo**: Corrigir CRÍTICO e libertar usuários em produção

### Problema 1️⃣: Rastreamento Pedidos ↔ Demandas

**Documentação**: [PLANO_CORRECAO_OTIMIZACAO.md - Problema 1](PLANO_CORRECAO_OTIMIZACAO.md#problema-1-rastreamento-invisível-entre-pedidos-e-demandas)

#### Subtarefa 1.1: CREATE VIEW SQL  
**Responsável**: Backend SQL  
**Tempo**: 1 hora  
**Arquivo**: `supabase/migrations/xxx_create_view_rastreamento.sql`

**O que fazer**:
1. Ler seção "Passo 1: View SQL" em [PLANO_CORRECAO_OTIMIZACAO.md](PLANO_CORRECAO_OTIMIZACAO.md)
2. Copiar código SQL `v_pedido_demanda_rastreamento`
3. Criar migration file novo (timestamp + nome descritivo)
4. Testar: `SELECT * FROM v_pedido_demanda_rastreamento LIMIT 10;`

**Validação**:
```sql
-- Deve retornar colunas:
-- pedido_id, codigo_pedido_externo, demanda_id, status_demanda, item_count
SELECT COUNT(*) FROM v_pedido_demanda_rastreamento;  -- > 0
```

---

#### Subtarefa 1.2: CREATE 2 APIs (GET endpoints)  
**Responsável**: Backend API  
**Tempo**: 2 horas  
**Arquivo**: [apps/api/routes/demandas.py](apps/api/routes/demandas.py) + [apps/api/routes/pedidos.py](apps/api/routes/pedidos.py)

**O que fazer**:
1. Ler seção "Passo 2: APIs Backend" em [PLANO_CORRECAO_OTIMIZACAO.md](PLANO_CORRECAO_OTIMIZACAO.md)
2. Adicionar em `demandas.py`:
   ```python
   @demandas_bp.route('/<int:demanda_id>/pedidos', methods=['GET'])
   def get_pedidos_demanda(demanda_id):
       # Retorna lista de pedidos origem dessa demanda
       # Query: SELECT FROM v_pedido_demanda_rastreamento WHERE demanda_id = ?
   ```

3. Adicionar em `pedidos.py`:
   ```python
   @pedidos_bp.route('/<int:pedido_id>/demandas', methods=['GET'])
   def get_demandas_pedido(pedido_id):
       # Retorna lista de demandas onde esse pedido foi agrupado
       # Query: SELECT FROM v_pedido_demanda_rastreamento WHERE pedido_id = ?
   ```

**Testes**:
```bash
# Terminal em /apps/api
curl http://localhost:5000/api/demandas/123/pedidos
curl http://localhost:5000/api/pedidos/456/demandas
```

---

#### Subtarefa 1.3: CREATE Frontend Column (PedidosListPage)  
**Responsável**: Frontend  
**Tempo**: 1.5 hora  
**Arquivo**: [apps/frontend/src/pages/pedidos/PedidosListPage.jsx](apps/frontend/src/pages/pedidos/PedidosListPage.jsx)

**O que fazer**:
1. Ler seção "Passo 3: Frontend - UI" em [PLANO_CORRECAO_OTIMIZACAO.md](PLANO_CORRECAO_OTIMIZACAO.md)
2. Em PedidosListPage, adicionar coluna "Demanda"
3. Chamar API GET `/pedidos/{id}/demandas`
4. Exibir como badge com link

**Template** (usar como base):
```jsx
// Em columns array de <Table>
{
  field: 'demanda_id',
  headerName: 'Demanda',
  width: 120,
  renderCell: (params) => {
    const demandaId = params.row.demanda_id;
    return demandaId ? (
      <Link to={`/demandas/${demandaId}`}>
        <Chip label={`#${demandaId}`} />
      </Link>
    ) : (
      <span>-</span>
    );
  }
}
```

**Testes** (manualmente no navegador):
- [ ] PedidosListPage carrega sem erro
- [ ] Coluna "Demanda" aparece
- [ ] Clique em demanda leva para DemandaDetailPage

---

#### Subtarefa 1.4: CREATE Frontend Tab (DemandaDetailPage)  
**Responsável**: Frontend  
**Tempo**: 1.5 hora  
**Arquivo**: [apps/frontend/src/pages/demandas/DemandaDetailPage.jsx](apps/frontend/src/pages/demandas/DemandaDetailPage.jsx)

**O que fazer**:
1. Ler seção "Passo 3: Frontend - UI" novamente
2. Em DemandaDetailPage, adicionar nova aba "Pedidos Origem"
3. Chamar API GET `/demandas/{id}/pedidos`
4. Exibir em tabela expansível

**Template**:
```jsx
// Nova aba em <Tabs>
<Tab label="Pedidos Origem" value="pedidos" />

// Conteúdo da aba
{tabValue === 'pedidos' && (
  <PedidosOrigemTable demandaId={demandaId} />
)}

// Componente helper
function PedidosOrigemTable({ demandaId }) {
  const [pedidos, setPedidos] = useState([]);
  useEffect(() => {
    fetch(`/api/demandas/${demandaId}/pedidos`)
      .then(r => r.json())
      .then(data => setPedidos(data.pedidos));
  }, [demandaId]);
  
  return <Table data={pedidos} columns={[...]} />;
}
```

**Testes**:
- [ ] DemandaDetailPage carrega sem erro
- [ ] Aba "Pedidos Origem" aparece
- [ ] Tabela popula com dados da API

---

#### **Resumo Problema 1**:
- ✅ View SQL created + tested
- ✅ 2 GET APIs implementadas + testadas
- ✅ Frontend: 2 UI components (column + tab) implementados + testados
- ⏱️ **Total**: ~5-6 horas (1 dev backend + 1 dev frontend)

---

### Problema 2️⃣: Redundância de Menus IA

**Documentação**: [PLANO_CORRECAO_OTIMIZACAO.md - Problema 2](PLANO_CORRECAO_OTIMIZACAO.md#problema-2-redundância-ia--identificação)

#### Subtarefa 2.1: Refatorar VendasPersonalizadasPage.jsx  
**Responsável**: Frontend  
**Tempo**: 1.5 horas  
**Arquivo**: [apps/frontend/src/pages/vendas/VendasPersonalizadasPage.jsx](apps/frontend/src/pages/vendas/VendasPersonalizadasPage.jsx)

**O que fazer**:
1. Ler seção "Passo 1: Consolidar UX" em [PLANO_CORRECAO_OTIMIZACAO.md](PLANO_CORRECAO_OTIMIZACAO.md)
2. Adicionar 4 abas ao componente:
   - "Pendentes Extração" → Filtro `personalizado=true AND nome IS NULL`
   - "Nomes Extraídos" → Filtro `personalizado=true AND nome IS NOT NULL`
   - "Histórico" → Filtro `archived=true`
   - "Logs IA" → Dados de `logs_execucao_ia`

**Template**:
```jsx
const [tabValue, setTabValue] = useState('pendentes');

<Tabs value={tabValue} onChange={(e, v) => setTabValue(v)}>
  <Tab label="Pendentes Extração" value="pendentes" />
  <Tab label="Nomes Extraídos" value="identificados" />
  <Tab label="Histórico" value="historico" />
  <Tab label="Logs IA" value="logs" />
</Tabs>

{tabValue === 'pendentes' && <PedentesTab />}
{tabValue === 'identificados' && <IdentificadosTab />}
...
```

**Testes**:
- [ ] VendasPersonalizadasPage carrega
- [ ] 4 abas aparecem e funcionam
- [ ] Filtros funcionam (dados corretos em cada aba)

---

#### Subtarefa 2.2: Redirecionar URLs redundantes  
**Responsável**: Frontend  
**Tempo**: 30 minutos  
**Arquivo**: Router config (ex: [apps/frontend/src/router/index.jsx](apps/frontend/src/router/index.jsx) ou App.jsx)

**O que fazer**:
1. Encontrar onde `/ai` e `/vendas/identificacao-ia` são definidas
2. Substituir por `<Navigate to="/vendas/personalizadas" replace />`

**Template**:
```jsx
// ANTES
<Route path="/ai" element={<AIDashboardPage />} />
<Route path="/vendas/identificacao-ia" element={<IdentificacaoIAPage />} />

// DEPOIS
<Route path="/ai" element={<Navigate to="/vendas/personalizadas" replace />} />
<Route path="/vendas/identificacao-ia" element={<Navigate to="/vendas/personalizadas" replace />} />
```

**Testes**:
- [ ] Acessar `/ai` redireciona para `/vendas/personalizadas`
- [ ] Acessar `/vendas/identificacao-ia` redireciona também
- [ ] Sem erros de console

---

#### Subtarefa 2.3: Backend = ZERO (Não fazer nada!)  
**Status**: ✅ Serviços já funcionam

Nenhuma mudança em:
- ✅ `personalized_order_identifier.py` 
- ✅ `ai_personalization_service.py`
- ✅ Rotas de API (`/api/personalizados/*`)

---

#### **Resumo Problema 2**:
- ✅ 4 abas em VendasPersonalizadasPage
- ✅ Redir URLs redundantes
- ❌ Backend: zero mudanças
- ⏱️ **Total**: 1-2 horas (1 dev frontend apenas)

---

### Problema 3️⃣: Worker & Auto-Consolidação

**Documentação**: [PLANO_CORRECAO_OTIMIZACAO.md - Problema 3](PLANO_CORRECAO_OTIMIZACAO.md#problema-3-worker--auto-consolidação)

#### Subtarefa 3.1: CREATE Migration - worker_logs table  
**Responsável**: Backend SQL  
**Tempo**: 1 hora  
**Arquivo**: `supabase/migrations/xxx_create_worker_logs_table.sql`

**O que fazer**:
1. Ler seção "Passo 1: Tabela worker_logs" em [PLANO_CORRECAO_OTIMIZACAO.md](PLANO_CORRECAO_OTIMIZACAO.md)
2. Criar migration com CREATE TABLE

**Schema** (do PLANO):
```sql
CREATE TABLE worker_logs (
  id SERIAL PRIMARY KEY,
  task_name VARCHAR(255) NOT NULL,
  log_level VARCHAR(20) DEFAULT 'INFO',  -- DEBUG, INFO, WARNING, ERROR
  message TEXT NOT NULL,
  pedido_id INTEGER REFERENCES pedidos(id),
  demanda_id INTEGER REFERENCES demandas_producao(id),
  detalhes JSONB,
  erro TEXT,
  celery_task_id VARCHAR(255),
  created_at TIMESTAMP DEFAULT NOW(),
  
  -- Índices
  CONSTRAINT fk_pedido FOREIGN KEY (pedido_id) REFERENCES pedidos(id),
  CONSTRAINT fk_demanda FOREIGN KEY (demanda_id) REFERENCES demandas_producao(id)
);

CREATE INDEX idx_worker_logs_pedido_id ON worker_logs(pedido_id);
CREATE INDEX idx_worker_logs_demanda_id ON worker_logs(demanda_id);
CREATE INDEX idx_worker_logs_task_name ON worker_logs(task_name);
CREATE INDEX idx_worker_logs_created_at ON worker_logs(created_at);
```

**Validação**:
```sql
SELECT COUNT(*) FROM worker_logs;  -- Deve retornar 0
\d worker_logs  -- Checar estrutura
```

---

#### Subtarefa 3.2: CREATE Task - auto_consolidate_pedido  
**Responsável**: Backend Worker  
**Tempo**: 2 horas  
**Arquivo**: [apps/worker/tasks/auto_consolidation_tasks.py](apps/worker/tasks/auto_consolidation_tasks.py) (NOVO)

**O que fazer**:
1. Ler seção "Passo 2: Task auto_consolidation_tasks.py" em [PLANO_CORRECAO_OTIMIZACAO.md](PLANO_CORRECAO_OTIMIZACAO.md)
2. Criar novo arquivo com 2 tasks:

**Task 1: `auto_consolidate_pedido`**
```python
from celery import shared_task
import logging
from ..models import Pedido, DemandaProducao
from ..services import consolidation_service
from ..utils import log_worker_event

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3)
def auto_consolidate_pedido(self, pedido_id):
    """Consolida automaticamente pedido em demanda rascunho."""
    try:
        pedido = Pedido.query.get(pedido_id)
        if not pedido:
            log_worker_event('auto_consolidate_pedido', 'ERROR', 
                            f'Pedido {pedido_id} não encontrado')
            return False
        
        # Chamar consolidation_service (já existe)
        demanda = consolidation_service.consolidate_pedido(pedido)
        
        log_worker_event('auto_consolidate_pedido', 'INFO',
                        f'Pedido {pedido_id} consolidado em demanda {demanda.id}',
                        pedido_id=pedido_id, demanda_id=demanda.id)
        
        return True
        
    except Exception as e:
        log_worker_event('auto_consolidate_pedido', 'ERROR',
                        f'Erro ao consolidar: {str(e)}',
                        pedido_id=pedido_id, erro=str(e))
        # Retry com backoff
        raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
```

**Task 2: `processar_lote_rascunhos`**
```python
@shared_task
def processar_lote_rascunhos():
    """Processa lote de rascunhos aguardando revisão (scheduler)."""
    rascunhos = DemandaProducao.query.filter_by(status='RASCUNHO').\
                 filter(created_at > datetime.now() - timedelta(hours=1)).all()
    
    for rascunho in rascunhos:
        # Validações, agregações, etc.
        log_worker_event('processar_lote_rascunhos', 'INFO',
                        f'Lote {len(rascunhos)} rascunhos processados')
```

**Testes**:
```bash
# Terminal worker
celery -A nistiprint_worker worker --loglevel=info

# Broadcasting da task
python -c "from apps.worker.tasks import auto_consolidate_pedido; \
           auto_consolidate_pedido.delay(123)"
```

---

#### Subtarefa 3.3: MODIFY webhook handler - trigger task  
**Responsável**: Backend Worker  
**Tempo**: 1 hora  
**Arquivo**: [apps/worker/tasks/pedidos_fetch_tasks.py](apps/worker/tasks/pedidos_fetch_tasks.py)

**O que fazer**:
1. Ler seção "Passo 3: Webhook integration" em [PLANO_CORRECAO_OTIMIZACAO.md](PLANO_CORRECAO_OTIMIZACAO.md)
2. Em `sync_pedidos_bling()` ou similar, após `upsert_order()`, adicionar:

**Antes**:
```python
@shared_task
def sync_pedidos_bling():
    # ... fetch de API ...
    for order in orders:
        upsert_order(order)  # Insere mas não consolida
    # Fim
```

**Depois**:
```python
@shared_task
def sync_pedidos_bling():
    # ... fetch de API ...
    for order in orders:
        pedido_id = upsert_order(order)
        # ← NOVA LINHA
        auto_consolidate_pedido.delay(pedido_id)  # Dispara consolidação automática
    # Fim
```

**Validação**:
- [ ] Webhook recebido
- [ ] Pedido inserido em BD
- [ ] Task `auto_consolidate_pedido` enfileirada (visible no Flower/Redis)
- [ ] Demanda RASCUNHO criada automaticamente

---

#### Subtarefa 3.4: CREATE 2 DEBUG APIs  
**Responsável**: Backend API  
**Tempo**: 1.5 horas  
**Arquivo**: [apps/api/routes/debug.py](apps/api/routes/debug.py) (NOVO)

**O que fazer**:

**API 1**: `GET /debug/worker-logs`
```python
from flask import Blueprint, request, jsonify

debug_bp = Blueprint('debug', __name__, url_prefix='/debug')

@debug_bp.route('/worker-logs', methods=['GET'])
def get_worker_logs():
    """Retorna últimos worker logs (últimas 24h por padrão)."""
    hours = request.args.get('hours', 24, type=int)
    limit = request.args.get('limit', 100, type=int)
    
    logs = WorkerLog.query.\
           filter(created_at >= datetime.now() - timedelta(hours=hours)).\
           order_by(WorkerLog.created_at.desc()).\
           limit(limit).all()
    
    return jsonify({'logs': [l.to_dict() for l in logs]})
```

**API 2**: `GET /debug/pedido/<id>/rastreamento-completo`
```python
@debug_bp.route('/pedido/<int:pedido_id>/rastreamento-completo', methods=['GET'])
def get_pedido_rastreamento(pedido_id):
    """Retorna rastreamento completo: pedido → demanda → logs worker."""
    pedido = Pedido.query.get(pedido_id)
    demandas = Demanda.query.filter_by(pedido_id=pedido_id).all()
    logs = WorkerLog.query.filter_by(pedido_id=pedido_id).all()
    
    return jsonify({
        'pedido': pedido.to_dict(),
        'demandas': [d.to_dict() for d in demandas],
        'worker_logs': [l.to_dict() for l in logs]
    })
```

**Testes**:
```bash
curl http://localhost:5000/api/debug/worker-logs?hours=24&limit=50
curl http://localhost:5000/api/debug/pedido/123/rastreamento-completo
```

---

#### Subtarefa 3.5: CREATE Frontend page - RascunhosPage  
**Responsável**: Frontend  
**Tempo**: 2 horas  
**Arquivo**: [apps/frontend/src/pages/demandas/RascunhosPage.jsx](apps/frontend/src/pages/demandas/RascunhosPage.jsx) (NOVO)

**O que fazer**:
1. Ler seção "Passo 4: Frontend - UI" em [PLANO_CORRECAO_OTIMIZACAO.md](PLANO_CORRECAO_OTIMIZACAO.md)
2. Criar nova página para gerenciar rascunhos

**Features**:
- Lista rascunhos criados automaticamente
- Botão "Liberar para Produção" → status PENDENTE
- Filtro por data/hora
- Card com detalhes: pedidos origem, itens, estoque

**Template**:
```jsx
export default function RascunhosPage() {
  const [rascunhos, setRascunhos] = useState([]);
  
  useEffect(() => {
    fetch('/api/demandas?status=RASCUNHO')
      .then(r => r.json())
      .then(data => setRascunhos(data.demandas));
  }, []);
  
  const liberarParaProducao = (demandaId) => {
    fetch(`/api/demandas/${demandaId}`, {
      method: 'PATCH',
      body: JSON.stringify({ status: 'PENDENTE' })
    }).then(/* refresh */)
  };
  
  return (
    <Container>
      <h1>Rascunhos de Demandas</h1>
      <Grid>
        {rascunhos.map(r => (
          <RascunhoCard 
            key={r.id} 
            rascunho={r}
            onLiberar={() => liberarParaProducao(r.id)}
          />
        ))}
      </Grid>
    </Container>
  );
}
```

**Testes**:
- [ ] Página carrega
- [ ] Rascunhos aparecem
- [ ] Botão "Liberar" funciona
- [ ] Status muda para PENDENTE em tempo real

---

#### **Resumo Problema 3**:
- ✅ Migration `worker_logs` table criada
- ✅ Task `auto_consolidate_pedido` criada + integrada ao webhook
- ✅ Task `processar_lote_rascunhos` criada (scheduler)
- ✅ 2 DEBUG APIs criadas (`/worker-logs`, `/pedido/.../rastreamento`)
- ✅ Frontend `RascunhosPage` criada
- ⏱️ **Total**: ~8-10 horas (1-2 devs backend + 1 dev frontend)

---

## 🧪 FASE 2: INTEGRAÇÃO & TESTES (15-20 horas)

### Etapa 2.1: Testes E2E (Problema 1)

**Cenário**: Rastrear pedido → demanda

```
1. Simular webhook com novo pedido (Bling)
2. Verificar: pedido criado em BD
3. Verificar: demanda RASCUNHO criada (auto-consolidação)
4. Verificar: FK em demandas_item_origem populado
5. Acessar /pedidos/{id} → coluna "Demanda" mostra link
6. Clicar na demanda → /demandas/{id}/pedidos mostra pedido origem
7. Dados coincidem com BD (via /debug/pedido/{id}/rastreamento-completo)
```

**Responsável**: QA + Backend  
**Tempo**: 2 horas

---

### Etapa 2.2: Testes E2E (Problema 2)

**Cenário**: Consolidar menus IA

```
1. Acessar /ai → redireciona para /vendas/personalizadas
2. Acessar /vendas/identificacao-ia → redireciona também
3. Em /vendas/personalizadas:
   - Aba "Pendentes Extração" mostra pedidos personalizado=true, nome=null
   - Aba "Nomes Extraídos" mostra pedidos com nome preenchido
   - Aba "Logs IA" mostra execuções
   - Histórico mostra tudo (archive=true)
4. Botão "Extrair com IA" funciona
5. Nome atualizado em tempo real na aba "Identificados"
```

**Responsável**: QA + Frontend  
**Tempo**: 1.5 horas

---

### Etapa 2.3: Testes E2E (Problema 3)

**Cenário**: Auto-consolidação + logs

```
1. Simular webhook com novo pedido
2. Verificar em Redis/Flower: task enfileirada
3. Aguardar task executar
4. Verificar:
   - Demanda RASCUNHO criada
   - Pedido linkado na demandas_item_origem
   - Log em worker_logs (INFO)
5. Acessar /demandas/rascunhos → novo rascunho aparece
6. Clicar "Liberar para Produção" → status muda para PENDENTE
7. Acessar /debug/worker-logs → histórico de tarefas
8. Acessar /debug/pedido/{id}/rastreamento-completo → fluxo completo visível
```

**Responsável**: QA + Backend  
**Tempo**: 2.5 horas

---

### Etapa 2.4: Testes de Integração (Todos os 3)

**Cenário**: E2E completo (pedido → demanda → extração IA → produção)

```
1. Criar pedido em marketplace (Shopee test)
2. Webhook atualiza Nistiprint
3. Auto-consolidação dispara
4. Demanda RASCUNHO criada
5. Sistema detecta personalizado + dispara extração IA
6. Nome extraído salvo
7. Usuário vê em /vendas/personalizadas (aba "Identificados")
8. Usuário vai a /demandas/rascunhos
9. Clica "Liberar para Produção"
10. Demanda agora em /demandas com status PENDENTE
11. Pode rastrear pedido origem clicando coluna "Demanda" em /pedidos
12. Logs visíveis em /debug/pedido/{id}/rastreamento-completo
```

**Responsável**: QA  
**Tempo**: 3 horas  
**Checklist**:
- [ ] Fluxo inteiro do pedido ao lançamento funcionando
- [ ] UI responsiva
- [ ] Sem erros de console
- [ ] Performance aceitável (< 2s carregamento)

---

### Etapa 2.5: Testes de Regressão

**Responsável**: QA  
**Tempo**: 3 horas

Testar que as mudanças NÃO quebraram:
- [ ] Consolidação manual via `/consolidar` (POST upload) continua funcionando
- [ ] Estoque (7 níveis) ainda calcula corretamente
- [ ] Pedidos não-personalizados não afetados
- [ ] Filtros/search em todas as páginas
- [ ] Relatórios existentes

---

### Etapa 2.6: Testes de Performance (opcional, mas recomendado)

**Responsável**: Backend  
**Tempo**: 2 horas

```sql
-- Verificar view performance
EXPLAIN ANALYZE SELECT * FROM v_pedido_demanda_rastreamento WHERE demanda_id = 123;
-- Deve usar índices (não Sequential Scan)

-- Verificar índices estão sendo usados
SELECT * FROM pg_stat_user_indexes WHERE tablename LIKE '%demanda%';
```

---

## 📦 FASE 3: MELHORIAS (30 horas - OPCIONAL)

### Melhorias Listadas em [PLANO_CORRECAO_OTIMIZACAO.md](PLANO_CORRECAO_OTIMIZACAO.md#fase-3-melhorias-otimizações)

Se timeline permitir (< 2 semanas ocupação):

1. **Frontend enhancements** (5h)
   - Nova página `/demandas/analytics` com gráficos
   - Dashboard de logs worker com filtros
   - Bulk actions em rascunhos

2. **Backend enhancements** (8h)
   - Webhook retry policy (não-idempotentes)
   - Scheduler para `processar_lote_rascunhos()` (processa a cada 6h)
   - Alert system (demanda sem consolidação > 24h)

3. **DB Otimizações** (5h)
   - Particionamento de `worker_logs` por data
   - Archive de logs > 90 dias
   - Cache Redis de rastreamento (invalidate on update)

4. **Documentação** (5h)
   - Runbook de deploy
   - Guia de troubleshooting
   - API documentation (Swagger/OpenAPI)

5. **Testes** (7h)
   - Unit tests para tasks worker
   - Integration tests para APIs
   - E2E tests com Cypress/Playwright

---

## 🚀 FASE 4: DEPLOY & GO-LIVE

### Etapa 4.1: Staging Deployment

**Responsável**: DevOps + Tech Lead  
**Tempo**: 2 horas

```bash
# Build
docker build -t nistiprint:staging-0.2.0 -f apps/api/Dockerfile .

# Deploy (GCP / seu ambiente)
gcloud run deploy nistiprint-api-staging --image nistiprint:staging-0.2.0

# Smoke tests
curl https://nistiprint-staging.run.app/api/health
```

**Checklist**:
- [ ] Build passa (zero dockerfile errors)
- [ ] Migrations aplicadas (`/supabase/migrations`)
- [ ] API health check OK
- [ ] Frontend carrega
- [ ] Worker conecta a Redis

---

### Etapa 4.2: Smoke Tests em Staging

**Responsável**: QA  
**Tempo**: 1 hora

```
1. Simular webhook (usar curl ou Postman)
2. Verificar pedido criado
3. Verificar demanda RASCUNHO criada
4. Acessar UI → nenhum erro de console
5. Rastrear pedido (coluna demanda)
6. Consolidar personalizado (aba IA)
7. Logs visíveis em /debug/
```

---

### Etapa 4.3: Production Deployment

**Responsável**: DevOps + Tech Lead + CTO (aprovação)  
**Tempo**: 1 hora (deploy) + 30 min (monitoramento)

**Pre-deploy**:
- [ ] CTO aprovado
- [ ] Backup de BD feito
- [ ] Rollback plan documentado
- [ ] Monitoring setup (logs, metrics, alertas)

**Deploy**:
```bash
# Tag e push
git tag v0.2.0
docker build -t nistiprint:v0.2.0 ...
docker push ...

# Deploy prod (zero-downtime blue-green se possível)
# OR: Scheduled maintenance window (20:00-21:30 UTC)

# Aplicar migrations em BD
psql -h supabase.co -d nistiprint -f supabase/migrations/xxx*.sql
```

**Post-deploy**:
- [ ] Health check OK
- [ ] Logs monitorados por 1h
- [ ] Usuários notificados de features novas
- [ ] Team on-call

---

### Etapa 4.4: User Training & Go-Live

**Responsável**: PM + Suporte  
**Tempo**: 2 horas

- [ ] Demo para usuários (novo rastreamento, menus consolidados, rascunhos automáticos)
- [ ] FAQ atualizada
- [ ] Suporte treinado em erros comuns
- [ ] Canais comunicação abertos (Slack, email)

---

## 📊 TIMELINE CONSOLIDADA

| Fase | Tarefas | Horas | Semana 1 | Semana 2 | Semana 3 |
|------|---------|-------|---------|---------|---------|
| **0** | Decisão + Alinhamento | 1h | ✅ 1h | | |
| **1a** | Problema 1 (rastreamento) | 5-6h | ✅ 5-6h | | |
| **1b** | Problema 2 (menus IA) | 1-2h | ✅ 1-2h | | |
| **1c** | Problema 3 (worker) | 8-10h | | ✅ 4h | ✅ 4-6h |
| **2** | Integração & Testes | 15-20h | | ✅ 10h | ✅ 5-10h |
| **3** | Melhorias (opcional) | 30h | | | ✅ 20-30h |
| **4** | Deploy & Go-Live | 4-5h | | | ✅ 4-5h |
| **TOTAL** | | **94-98h** | **7-9h** | **14-20h** | **29-40h** |

---

## 👥 RECURSOS NECESSÁRIOS

| Role | Tasks | Semana 1 | Semana 2 | Semana 3 | Total |
|------|-------|---------|---------|---------|-------|
| **Backend (SQL)** | Problem 1: View, Migrations | 6h | - | - | 6h |
| **Backend (API)** | Problem 1: 2 APIs, Problem 3: Tasks, APIs | 3h | 4h | 2h | 9h |
| **Backend (Worker)** | Problem 3: Celery tasks | - | 4h | 2h | 6h |
| **Frontend** | Problem 2: UX, Problem 1: UI, Problem 3: Page | 2h | 2h | 2h | 6h |
| **QA** | E2E, Regressão, Smoke | 2h | 8h | 5h | 15h |
| **DevOps** | Staging, Prod Deploy | - | - | 3h | 3h |
| **CTO/Tech Lead** | Reviews, Approvals | 1h | 2h | 1h | 4h |
| **TOTAL** | | **14-15h/semana** | **20-30h/semana** | **15-25h/semana** | **98h** |

---

## ✅ CHECKLIST PRÉ-INÍCIO

Antes de começar Fase 1, verificar:

- [ ] 3 docs lidos (executiva, plan, quick-ref)
- [ ] GO/NO-GO decision feito
- [ ] Recursos alocados (devs, tester, DevOps)
- [ ] CI/CD pipeline testado (docker, migrations)
- [ ] BD staging (ou backup de prod) disponível
- [ ] Slack/comms channels criados
- [ ] Jira/Issues criados e linkeados aos doc sections
- [ ] Sprint planning feito

---

## 🆘 TROUBLESHOOTING

### "Minha view não retorna dados"
→ Verificar: FK em `demandas_item_origem` está populado?  
→ SQL: `SELECT COUNT(*) FROM demandas_item_origem WHERE pedido_externo_id IS NOT NULL;`  
→ Se 0 → consolidação ainda não rodou para esse pedido

### "Task não está sendo executada"
→ Verificar: Redis rodando? `redis-cli ping`  
→ Verificar: Worker conectado? `celery -A nistiprint_worker inspect active`  
→ Verificar: Task enfileirada? `redis-cli LLEN celery` (deve > 0)

### "API retorna 404"
→ Verificar: Rota registrada em blueprint?  
→ Verificar: `app.register_blueprint(demandas_bp)` feito?  
→ Verificar: Prefix correto? (ex: `/api/demandas`)

### "Frontend carrega, mas dados vazios"
→ Verificar: Network tab (XHR requests)  
→ Verificar: API retorna dados? (`curl http://...`)  
→ Verificar: useEffect() triggered corretamente?  
→ Verificar: CORS habilitado?

---

## 📞 CONTATO & ESCALAÇÃO

- **Dúvidas técnicas**: Postar em #dev-nistiprint (Slack), tag `@tech-lead`
- **Bloqueadores**: Escalate para CTO
- **Suporte em produção**: On-call rotation

---

## 📝 NOTAS IMPORTANTES

1. **Não faça refactoring desnecessário**: Serviços IA já estão OK
2. **Teste early, test often**: Não deixe tudo pra Fase 2
3. **Backup antes de migrations**: `pg_dump` antes de aplicar mudanças
4. **Logs são seus amigos**: Use `/debug` APIs para troubleshooting
5. **Comunique progresso**: Daily standup, status updates em Slack

---

**Documento elaborado em**: 11 de abril de 2026  
**Próximas revisões**: Após Phase 1 (Semana 2)
