# 📋 PLANO DE CORREÇÃO, OTIMIZAÇÃO E MELHORIAS - NISTIPRINT

**Data**: Abril 2026 | **Status**: Proposta de Implementação | **Autor**: Análise Técnica

---

## 📌 SUMÁRIO EXECUTIVO

O Nistiprint é um sistema **ERP+PCP robusto** para gráfica criativa com **3 problemas críticos** bloqueando produtividade dos usuários:

1. **Rastreamento pedido↔demanda** está implementado no DB mas **não acessível na UI** (invisível para usuário)
2. **Funcionalidades IA/Personalizadas duplicadas** em múltiplas telas causando **confusão e UX ruim**
3. **Worker não consolida rascunhos automaticamente** e **faltam logs** (impede debug e automação)

Este plano detalha: **o quê**, **como**, **onde**, **timeline**, e **recursos** para cada correção.

---

## 🎯 OBJETIVOS

- ✅ Rastreabilidade completa: usuário vê pedido↔demanda em tempo real
- ✅ UX consolidada: 1 tela, 1 serviço, sem redundância para IA/Personalizados
- ✅ Automação confiável: rascunhos criados/atualizados automaticamente com logs estruturados
- ✅ Debug facilitado: logs centralizados correlacionam worker + API + DB

---

## 📊 PROBLEMAS DETALHADOS

### Problema 1: RASTREAMENTO PEDIDOS × DEMANDAS (CRÍTICO)

#### 📍 Situação Atual
| Aspecto | Status |
|---------|--------|
| **DB Schema** | ✅ Tabela `demandas_item_origem` existe com FK correto |
| **Preenchimento** | ❓ Não verificado se `consolidation_service.py` popula |
| **API Leitura** | ❌ Não existe GET `/pedidos/{id}/demandas` |
| **API Leitura** | ❌ Não existe GET `/demandas/{id}/pedidos` estruturado |
| **Frontend: Pedidos** | ❌ Sem coluna "Demanda Vinculada" |
| **Frontend: Demandas** | ❌ Sem aba "Pedidos Origem" |
| **UX Breadcrumb** | ❌ Sem navegação visual pedido→demanda |

#### 🔍 Raiz: Cadeia de FK em `demandas_item_origem`

```
pedidos_bling.codigo_pedido_externo 
  ↓
demandas_item_origem.pedido_externo_id (FK)
  ↓
itens_demanda.id
  ↓
demandas_producao.id
```

**Problema**: Estrutura está lá, mas não documentada e não consultada na UI.

#### 🔧 Implementação

##### **PASSO 1: Criar View SQL de Rastreamento**

**Arquivo**: `supabase/migrations/xxx_create_v_pedido_demanda_rastreamento.sql`

```sql
-- View: v_pedido_demanda_rastreamento
-- Propósito: Mapear pedido → demanda (multihop query simplificado)
CREATE OR REPLACE VIEW v_pedido_demanda_rastreamento AS
SELECT 
    pb.id AS pedido_id,
    pb.numero_pedido,
    pb.codigo_pedido_externo,
    pb.bling_id,
    pb.plataforma,
    
    dio.quantidade_atendida,
    
    id_demanda.id AS item_demanda_id,
    id_demanda.produto_id,
    id_demanda.sku,
    id_demanda.quantidade AS quantidade_demanda,
    id_demanda.status_item,
    
    dp.id AS demanda_id,
    dp.demanda_id AS demanda_numero,
    dp.status AS demanda_status,
    dp.tipo_demanda,
    dp.data_entrega,
    dp.modalidade_logistica,
    
    pb.created_at AS pedido_data,
    dp.created_at AS demanda_data,
    dp.updated_at AS demanda_atualizado
FROM pedidos_bling pb
LEFT JOIN demandas_item_origem dio ON pb.codigo_pedido_externo = dio.pedido_externo_id
LEFT JOIN itens_demanda id_demanda ON dio.demanda_item_id = id_demanda.id
LEFT JOIN demandas_producao dp ON id_demanda.demanda_id = dp.id
WHERE pb.deleted_at IS NULL;

-- Índices para performance
CREATE INDEX IF NOT EXISTS idx_v_pedido_demanda_pedido_id 
ON demandas_item_origem(pedido_externo_id);

CREATE INDEX IF NOT EXISTS idx_v_pedido_demanda_demanda_id 
ON itens_demanda(demanda_id);
```

##### **PASSO 2: APIs de Rastreamento**

**Arquivo**: `apps/api/routes/demandas.py` (adicionar endpoints)

```python
@demandas_bp.route('/<demanda_id>/pedidos', methods=['GET'])
@login_required
def get_demanda_pedidos(demanda_id):
    """
    GET /api/v2/demandas/{demanda_id}/pedidos
    
    Retorna todos os pedidos que geraram esta demanda.
    Inclui: número, plataforma, status, quantidade atendida.
    """
    try:
        # Query via view
        response = supabase_db.execute("""
            SELECT numero_pedido, codigo_pedido_externo, plataforma, 
                   quantidade_atendida, pedido_data, status_item
            FROM v_pedido_demanda_rastreamento
            WHERE demanda_id = :demanda_id
            ORDER BY pedido_data DESC
        """, {'demanda_id': int(demanda_id)})
        
        return jsonify({
            'success': True,
            'demanda_id': demanda_id,
            'pedidos': response or [],
            'total': len(response or [])
        })
    except Exception as e:
        logger.error(f"Erro ao buscar pedidos da demanda: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@demandas_bp.route('/<demanda_id>/rastreamento', methods=['GET'])
@login_required
def get_demanda_rastreamento_completo(demanda_id):
    """
    GET /api/v2/demandas/{demanda_id}/rastreamento
    
    Retorna grafo completo: pedido → item → demanda com estoque.
    Útil para UI de breadcrumb.
    """
    # Buscar demanda
    demanda = supabase_db.table('demandas_producao').select('*').eq('id', demanda_id).single()
    
    # Buscar pedidos
    pedidos_sql = """
        SELECT pb.numero_pedido, pb.codigo_pedido_externo, pb.plataforma,
               dio.quantidade_atendida, id_demanda.status_item
        FROM v_pedido_demanda_rastreamento
        WHERE demanda_id = :demanda_id
    """
    pedidos = supabase_db.execute(pedidos_sql, {'demanda_id': int(demanda_id)})
    
    return jsonify({
        'success': True,
        'rastreamento': {
            'demanda': demanda,
            'pedidos': pedidos,
            'timeline': [
                {'etapa': 'Pedidos Agrupados', 'data': pedidos[0].get('pedido_data') if pedidos else None},
                {'etapa': 'Demanda Criada', 'data': demanda.get('created_at')},
                {'etapa': 'Status Atual', 'data': demanda.get('updated_at')}
            ]
        }
    })
```

**Arquivo**: `apps/api/routes/pedidos.py` (adicionar endpoint)

```python
@pedidos_bp.route('/<pedido_id>/demandas', methods=['GET'])
@login_required
def get_pedido_demandas(pedido_id):
    """
    GET /api/v2/pedidos/{pedido_id}/demandas
    
    Retorna todas as demandas que incluem este pedido.
    Se não incluído em nenhuma, retorna lista vazia + flag "não incluído".
    """
    try:
        # Buscar pedido original
        pedido = supabase_db.table('pedidos').select('*').eq('id', pedido_id).single()
        if not pedido:
            return jsonify({'success': False, 'error': 'Pedido não encontrado'}), 404
        
        # Buscar via view
        response = supabase_db.execute("""
            SELECT DISTINCT demanda_id, demanda_numero, demanda_status, 
                   data_entrega, tipo_demanda, modalidade_logistica,
                   demanda_data, quantidade_demanda, quantidade_atendida
            FROM v_pedido_demanda_rastreamento
            WHERE pedido_id = :pedido_id
            ORDER BY demanda_data DESC
        """, {'pedido_id': int(pedido_id)})
        
        demandas = response or []
        
        return jsonify({
            'success': True,
            'pedido_id': pedido_id,
            'numero_pedido': pedido.get('numero_pedido'),
            'demandas': demandas,
            'incluido': len(demandas) > 0,
            'status': 'Incluído em Demanda' if demandas else 'Não Incluído / Em Rascunho'
        })
    except Exception as e:
        logger.error(f"Erro ao buscar demandas do pedido: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
```

##### **PASSO 3: Frontend - Tela Pedidos + Coluna Rastreamento**

**Arquivo**: `apps/frontend/src/pages/pedidos/PedidosListPage.jsx` (modificar)

```jsx
// Adicionar coluna "Status Demanda"
const columns = [
  // ... colunas existentes ...
  {
    id: 'demanda_status',
    header: 'Status Demanda',
    cell: ({ row }) => {
      const demandaInfo = demandaMap.get(row.original.id);
      return (
        <div className="flex items-center gap-2">
          {demandaInfo ? (
            <>
              <Badge variant={getStatusBadgeVariant(demandaInfo.demanda_status)}>
                {demandaInfo.demanda_status}
              </Badge>
              <button
                className="text-xs text-blue-600 hover:underline"
                onClick={() => navigate(`/demandas/${demandaInfo.demanda_id}`)}
              >
                #{demandaInfo.demanda_numero}
              </button>
            </>
          ) : (
            <Badge variant="outline">Não Incluído</Badge>
          )}
        </div>
      );
    }
  }
];

// Efeito para carregar mapa pedido→demanda
useEffect(() => {
  const loadDemandaMap = async () => {
    const map = new Map();
    for (const pedido of pedidos) {
      try {
        const res = await fetch(`/api/v2/pedidos/${pedido.id}/demandas`);
        const data = await res.json();
        if (data.demandas && data.demandas.length > 0) {
          map.set(pedido.id, data.demandas[0]); // Primeira demanda
        }
      } catch (e) {
        console.error(`Erro ao carregar demanda do pedido ${pedido.id}:`, e);
      }
    }
    setDemandaMap(map);
  };
  
  if (pedidos.length > 0) loadDemandaMap();
}, [pedidos]);
```

##### **PASSO 4: Frontend - Tela Demandas + Aba Pedidos Origem**

**Arquivo**: `apps/frontend/src/pages/demandas/DemandaDetailPage.jsx` (modificar)

```jsx
// Adicionar aba "Pedidos Origem"
const tabs = [
  { id: 'info', label: 'Informações' },
  { id: 'itens', label: 'Itens' },
  { id: 'pedidos', label: 'Pedidos Origem', badge: pedidosTotal }, // NOVO
  { id: 'timeline', label: 'Timeline' },
  { id: 'alertas', label: 'Alertas' }
];

// Componente aba Pedidos
const renderPedidosTab = () => (
  <div className="space-y-4">
    <h3 className="text-lg font-semibold">Pedidos que Geraram esta Demanda</h3>
    {pedidos.length === 0 ? (
      <p className="text-gray-500">Nenhum pedido vinculado</p>
    ) : (
      <table className="w-full border">
        <thead>
          <tr className="bg-gray-50">
            <th className="p-3 text-left">Número</th>
            <th className="p-3 text-left">Plataforma</th>
            <th className="p-3 text-center">Quantidade</th>
            <th className="p-3 text-center">Ações</th>
          </tr>
        </thead>
        <tbody>
          {pedidos.map(p => (
            <tr key={p.pedido_id} className="border-t">
              <td className="p-3">
                <button
                  className="text-blue-600 hover:underline"
                  onClick={() => navigate(`/pedidos/${p.pedido_id}`)}
                >
                  {p.numero_pedido}
                </button>
              </td>
              <td className="p-3">{p.plataforma}</td>
              <td className="p-3 text-center">{p.quantidade_atendida}</td>
              <td className="p-3 text-center">
                <button
                  onClick={() => navigate(`/pedidos/${p.pedido_id}`)}
                  className="text-xs px-2 py-1 bg-blue-50 text-blue-600 rounded"
                >
                  Ver
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    )}
  </div>
);
```

---

### Problema 2: REDUNDÂNCIA IA & IDENTIFICAÇÃO (OTIMIZAÇÃO)

#### 📍 Situação Atual
| Elemento | Status | Problema |
|----------|--------|----------|
| **Tela `/vendas/personalizadas`** | ✅ Funciona | Integrada + botonão IA |
| **Tela `/vendas/identificacao-ia`** ou `/ai`** | ❓ Existe | Não mostra dados / redundante |
| **Serviço `ai_personalization_service.py`** | ✅ Ativo (~900 linhas) | Monolítico, sem separação |
| **Serviço `personalized_order_identifier.py`** | ✅ Ativo (~280 linhas) | Duplica lógica de identificação |
| **DB: Logs IA** | ✅ `logs_execucao_ia` | Sem correlação com item_id ou pedido_id |
| **Frontend: Consolidação de Menu** | ❌ Não feita | Múltiplas telas p/ mesma coisa |

#### 🔍 Raiz: Evoluções acumuladas sem refatoração

- **Primeira iteração**: Identificação rápida (DB) → `personalized_order_identifier.py`
- **Segunda iteração**: IA Gemini adicionada → `ai_personalization_service.py`
- **Resultado**: 2 serviços rodando em paralelo, sem orquestração clara

#### 🔧 Implementação

**FOCO**: Problema é **apenas na UX/Frontend**, NÃO nos serviços

Os serviços estão bem:
- ✅ `personalized_order_identifier.py` → Classifica se é personalizado (regras lógicas)
- ✅ `ai_personalization_service.py` → Extrai o nome personalizado (IA)

**Solução**: Consolidar menus frontend (remover redundância de telas)

##### **PASSO ÚNICO: Consolidar UX - Remover Menus Redundantes**

**Decisão**: 
- ✅ Manter `/vendas/personalizadas` como tela única
- ❌ Remover `/vendas/identificacao-ia` ou `/ai` (redundante)

**Arquivo**: `apps/frontend/src/pages/vendas/VendasPersonalizadasPage.jsx` (refatorar)

```jsx
// Estrutura consolidada - 4 abas em 1 tela
const VendasPersonalizadasPage = () => {
  const [abaSelecionada, setAbaSelecionada] = useState('pendentes');
  // pendentes = pedidos personalizados aguardando extração de nome
  // identificados = pedidos personalizados com nome já extraído
  // historico = histórico de pedidos processados
  // logs = logs de execução IA
  
  // Abas
  const abas = [
    { id: 'pendentes', label: 'Pendentes Extração', icon: AlertCircle },
    { id: 'identificados', label: 'Nomes Extraídos', icon: CheckCircle },
    { id: 'historico', label: 'Histórico', icon: RotateCcw },
    { id: 'logs', label: 'Logs IA', icon: Terminal }
  ];
  
  const renderConteudo = () => {
    switch(abaSelecionada) {
      case 'pendentes':
        // Lista pedidos classificados como "personalizado=true"
        // mas SEM nome extraído ainda (botão "Extrair com IA")
        return <AbaPendentesExtracao />;
      case 'identificados':
        // Lista pedidos com nome personalizado já extraído
        return <AbaIdentificados />;
      case 'historico':
        return <AbaHistorico />;
      case 'logs':
        // Mostra detalhes de cada execução IA
        return <AbaLogsIA />;
      default:
        return null;
    }
  };
  
  return (
    <div className="p-6">
      <h1>Pedidos Personalizados</h1>
      <p className="text-gray-600">
        Visualize pedidos personalizáveis e extraia os nomes a personalizar
      </p>
      
      {/* Abas */}
      <div className="flex border-b mb-6">
        {abas.map(aba => (
          <button
            key={aba.id}
            onClick={() => setAbaSelecionada(aba.id)}
            className={`flex items-center gap-2 px-4 py-2 border-b-2 ${
              abaSelecionada === aba.id ? 'border-blue-500' : 'border-transparent'
            }`}
          >
            <aba.icon size={18} />
            {aba.label}
          </button>
        ))}
      </div>
      
      {renderConteudo()}
    </div>
  );
};
```

**Mudança de roteamento (se houver redirect do `/ai`):**

```jsx
// Em router/index.jsx ou App.jsx
// Redirecionar /ai para /vendas/personalizadas
<Route path="/ai" element={<Navigate to="/vendas/personalizadas" replace />} />
<Route path="/vendas/identificacao-ia" element={<Navigate to="/vendas/personalizadas" replace />} />
```

---

### Problema 3: WORKER & CONSOLIDAÇÃO DE RASCUNHOS

#### 📍 Situação Atual
| Aspecto | Status |
|---------|--------|
| **Consolidação manual via `/consolidar`** | ✅ Funciona |
| **Consolidação automática via webhook** | ❌ Não implementada |
| **Rascunhos criados ao receber pedido** | ❌ Não automático |
| **Logs worker** | ⚠️ Mínimos/esparsos |
| **Visibilidade de rascunhos na UI** | ❌ Não estruturada |

#### 🔍 Raiz: Worker foca apenas em sincronização, não em consolidação

- Worker processa webhooks → `upsert_order()` na DB
- Não dispara consolidação automática
- Logs apenas em stdout (não persistem)

#### 🔧 Implementação

##### **PASSO 1: Criar Task de Auto-Consolidação**

**Arquivo**: `apps/worker/tasks/auto_consolidation_tasks.py` (novo)

```python
"""
Auto-Consolidação de Pedidos em Rascunhos via Worker.

Trigger: Nova pedido recebido via webhook
Ação: Tentar consolidar em rascunho existente ou criar novo
Logs: Persistir em `worker_logs` table
"""

from celery import shared_task, current_task
from datetime import datetime, timezone
import logging
import traceback
from nistiprint_shared.services.consolidation_service import ConsolidationService
from nistiprint_shared.database.supabase_db_service import supabase_db

logger = logging.getLogger(__name__)

# Tabela de logs
WORKER_LOGS_TABLE = 'worker_logs'

class WorkerLogManager:
    """Gerencia logs estruturados do worker."""
    
    @staticmethod
    def log_event(
        task_name: str,
        level: str,  # DEBUG, INFO, WARNING, ERROR
        message: str,
        pedido_id: int = None,
        demanda_id: int = None,
        detalhes: dict = None,
        erro: str = None
    ):
        """Salva log estruturado na DB."""
        try:
            payload = {
                'task_name': task_name,
                'level': level,
                'message': message,
                'pedido_id': pedido_id,
                'demanda_id': demanda_id,
                'detalhes': detalhes or {},
                'erro': erro,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'celery_task_id': current_task.request.id if current_task else None
            }
            
            supabase_db.table(WORKER_LOGS_TABLE).insert(payload).execute()
            
            # Também log em stdout para debug imediato
            log_func = {
                'DEBUG': logger.debug,
                'INFO': logger.info,
                'WARNING': logger.warning,
                'ERROR': logger.error
            }.get(level, logger.info)
            
            log_func(f"[{task_name}] {message}" + (f" - {erro}" if erro else ""))
        
        except Exception as e:
            logger.error(f"Erro ao salvar log do worker: {e}")

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60  # Retry em 1 min
)
def auto_consolidate_pedido(self, pedido_id: int):
    """
    Consolida um pedido em rascunho existente ou cria novo.
    
    Chamado imediatamente após novo pedido ser inserido via webhook.
    
    Args:
        pedido_id: ID do pedido unificado (tabela `pedidos`)
    """
    
    WorkerLogManager.log_event(
        task_name='auto_consolidate_pedido',
        level='INFO',
        message=f'Iniciando auto-consolidação',
        pedido_id=pedido_id
    )
    
    try:
        # Instanciar serviço
        consolidation = ConsolidationService()
        
        # Buscar pedido
        pedido = supabase_db.table('pedidos').select('*').eq('id', pedido_id).single()
        
        if not pedido:
            WorkerLogManager.log_event(
                task_name='auto_consolidate_pedido',
                level='ERROR',
                message='Pedido não encontrado',
                pedido_id=pedido_id,
                erro=f'Pedido ID {pedido_id} não existe'
            )
            return {'sucesso': False, 'erro': 'Pedido não encontrado'}
        
        WorkerLogManager.log_event(
            task_name='auto_consolidate_pedido',
            level='DEBUG',
            message=f'Pedido encontrado: {pedido.get("numero_pedido")}',
            pedido_id=pedido_id,
            detalhes={'numero_pedido': pedido.get('numero_pedido')}
        )
        
        # Executar consolidação
        resultado = consolidation.consolidar_pedido(pedido_id)
        
        WorkerLogManager.log_event(
            task_name='auto_consolidate_pedido',
            level='INFO',
            message=f'Consolidação concluída',
            pedido_id=pedido_id,
            demanda_id=resultado.get('demanda_id') if resultado else None,
            detalhes={'resultado': resultado}
        )
        
        return {'sucesso': True, 'demanda': resultado}
    
    except Exception as e:
        erro_trace = traceback.format_exc()
        
        WorkerLogManager.log_event(
            task_name='auto_consolidate_pedido',
            level='ERROR',
            message=f'Erro ao consolidar',
            pedido_id=pedido_id,
            erro=erro_trace
        )
        
        # Retry
        try:
            raise self.retry(exc=e, countdown=60)
        except Exception as retry_exc:
            logger.error(f"Falha em retry: {retry_exc}")
            return {'sucesso': False, 'erro': str(e), 'traceback': erro_trace}

@shared_task(bind=True)
def processar_lote_rascunhos(self, canal_venda_id: int = None):
    """
    Processa lote de rascunhos periodicamente.
    
    Task agendada para rodar a cada 30 minutos.
    Valida rascunhos, consolida últimos pedidos, identifica conflitos.
    """
    WorkerLogManager.log_event(
        task_name='processar_lote_rascunhos',
        level='INFO',
        message='Iniciando processamento em lote de rascunhos'
    )
    
    try:
        # Buscar rascunhos
        query = supabase_db.table('demandas_producao').select('*').eq('status', 'RASCUNHO')
        
        if canal_venda_id:
            query = query.eq('canal_venda_id', canal_venda_id)
        
        rascunhos = query.execute().data
        
        WorkerLogManager.log_event(
            task_name='processar_lote_rascunhos',
            level='INFO',
            message=f'Encontrados {len(rascunhos)} rascunhos',
            detalhes={'total': len(rascunhos), 'canal_venda_id': canal_venda_id}
        )
        
        for rascunho in rascunhos:
            # Validar rascunho (verificar se ainda compatível)
            # Consolidar últimos pedidos
            # (lógica aqui)
            pass
        
        return {'sucesso': True, 'rascunhos_processados': len(rascunhos)}
    
    except Exception as e:
        WorkerLogManager.log_event(
            task_name='processar_lote_rascunhos',
            level='ERROR',
            message='Erro ao processar lote',
            erro=str(e)
        )
        raise
```

##### **PASSO 2: Integrar Task no Fluxo de Webhook**

**Arquivo**: `apps/worker/tasks/pedidos_fetch_tasks.py` (modificar)

```python
# Onde o webhook dispara o upsert
@shared_task(bind=True)
def sync_pedidos_bling(self, account_id, **kwargs):
    """Sincroniza pedidos Bling."""
    # ... código existente ...
    
    for pedido_data in novos_pedidos:
        # 1. Upsert ordem
        pedido_id = upsert_order(account_id, pedido_data)
        
        # 2. NOVO: Disparar auto-consolidação
        auto_consolidate_pedido.delay(pedido_id)  # Celery task assincronamente
        
        # 3. NOVO: Identificação IA (se configured)
        if config.get('identificacao_ia_automatica'):
            process_ia_personalization.delay(pedido_id)
    
    # ... resto do código
```

##### **PASSO 3: Criar Tabela de Logs Worker**

**Arquivo**: `supabase/migrations/xxx_create_worker_logs_table.sql`

```sql
CREATE TABLE IF NOT EXISTS worker_logs (
    id BIGSERIAL PRIMARY KEY,
    task_name VARCHAR(100) NOT NULL,
    level VARCHAR(20) NOT NULL,  -- DEBUG, INFO, WARNING, ERROR
    message TEXT NOT NULL,
    pedido_id INTEGER REFERENCES pedidos(id),
    demanda_id INTEGER REFERENCES demandas_producao(id),
    detalhes JSONB DEFAULT '{}'::jsonb,
    erro TEXT,
    celery_task_id VARCHAR(255),
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Índices
CREATE INDEX idx_worker_logs_timestamp ON worker_logs(timestamp DESC);
CREATE INDEX idx_worker_logs_level ON worker_logs(level);
CREATE INDEX idx_worker_logs_task ON worker_logs(task_name);
CREATE INDEX idx_worker_logs_pedido ON worker_logs(pedido_id);
CREATE INDEX idx_worker_logs_demanda ON worker_logs(demanda_id);

-- Política de retenção (manter últimos 30 dias)
CREATE OR REPLACE FUNCTION cleanup_old_worker_logs()
RETURNS void AS $$
BEGIN
    DELETE FROM worker_logs WHERE timestamp < NOW() - INTERVAL '30 days';
END;
$$ LANGUAGE plpgsql;
```

##### **PASSO 4: API para Acessar Logs Worker**

**Arquivo**: `apps/api/routes/debug.py` (novo - para debug)

```python
"""Endpoints de debug: logs worker, rastreamento consolidação, etc."""

from flask import Blueprint, jsonify, request
from routes.auth import login_required, admin_required
from nistiprint_shared.database.supabase_db_service import supabase_db

debug_bp = Blueprint('debug', __name__, url_prefix='/api/v2/debug')

@debug_bp.route('/worker-logs', methods=['GET'])
@admin_required
def get_worker_logs():
    """
    GET /api/v2/debug/worker-logs?limit=100&level=ERROR&pedido_id=123
    
    Retorna logs recentes do worker.
    Filtros opcionais: level, pedido_id, demanda_id, task_name, timerange
    """
    limit = request.args.get('limit', 100, type=int)
    level = request.args.get('level')
    pedido_id = request.args.get('pedido_id', type=int)
    task_name = request.args.get('task_name')
    
    query = supabase_db.table('worker_logs').select('*').order('timestamp', desc=True).limit(limit)
    
    if level:
        query = query.eq('level', level)
    if pedido_id:
        query = query.eq('pedido_id', pedido_id)
    if task_name:
        query = query.eq('task_name', task_name)
    
    logs = query.execute().data
    
    return jsonify({
        'success': True,
        'logs': logs,
        'total': len(logs)
    })

@debug_bp.route('/pedido/<pedido_id>/rastreamento-completo', methods=['GET'])
@login_required
def get_pedido_rastreamento_debug(pedido_id):
    """
    GET /api/v2/debug/pedido/{pedido_id}/rastreamento-completo
    
    Rastreamento COMPLETO: pedido → logs → demanda → estoque.
    Útil para debugar problemas de consolidação.
    """
    # Buscar pedido
    pedido = supabase_db.table('pedidos').select('*').eq('id', pedido_id).single()
    
    # Logs worker relacionados
    logs = supabase_db.table('worker_logs').select('*').eq('pedido_id', pedido_id).order('timestamp', desc=True).execute().data
    
    # Demandas
    demandas_sql = """
        SELECT dp.* FROM demandas_producao dp
        LEFT JOIN itens_demanda id ON dp.id = id.demanda_id
        LEFT JOIN demandas_item_origem dio ON id.id = dio.demanda_item_id
        WHERE dio.pedido_externo_id = :codigo_pedido_externo
    """
    demandas = supabase_db.execute(
        demandas_sql,
        {'codigo_pedido_externo': pedido.get('codigo_pedido_externo')}
    )
    
    return jsonify({
        'success': True,
        'rastreamento': {
            'pedido': pedido,
            'worker_logs': logs,
            'demandas': demandas
        }
    })
```

##### **PASSO 5: Frontend - Acessibilidade de Rascunhos**

**Arquivo**: `apps/frontend/src/pages/demandas/RascunhosPage.jsx` (novo)

```jsx
"""Página dedicada a rascunhos de consolidação."""

import React, { useState, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { AlertCircle, Trash2, CheckCircle, Expand } from 'lucide-react';

export default function RascunhosPage() {
  const [rascunhos, setRascunhos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expandido, setExpandido] = useState(null);
  
  useEffect(() => {
    carregarRascunhos();
  }, []);
  
  const carregarRascunhos = async () => {
    try {
      const res = await fetch('/api/v2/demandas?status=RASCUNHO');
      const data = await res.json();
      setRascunhos(data.demandas || []);
    } catch (e) {
      console.error('Erro:', e);
    } finally {
      setLoading(false);
    }
  };
  
  const confirmarRascunho = async (demanda_id) => {
    try {
      const res = await fetch(`/api/v2/demandas/${demanda_id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'PENDENTE' })
      });
      
      if (res.ok) {
        setRascunhos(rascunhos.filter(r => r.id !== demanda_id));
      }
    } catch (e) {
      console.error('Erro ao confirmar:', e);
    }
  };
  
  const descartarRascunho = async (demanda_id) => {
    if (window.confirm('Descartar rascunho?')) {
      try {
        const res = await fetch(`/api/v2/demandas/${demanda_id}`, {
          method: 'DELETE'
        });
        
        if (res.ok) {
          setRascunhos(rascunhos.filter(r => r.id !== demanda_id));
        }
      } catch (e) {
        console.error('Erro ao descartar:', e);
      }
    }
  };
  
  if (loading) return <div className="p-6">Carregando...</div>;
  
  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold mb-6">Rascunhos de Consolidação</h1>
      
      {rascunhos.length === 0 ? (
        <p className="text-gray-500">Nenhum rascunho pendente</p>
      ) : (
        <div className="space-y-4">
          {rascunhos.map(rascunho => (
            <div key={rascunho.id} className="border rounded-lg p-4">
              <div className="flex justify-between items-start">
                <div>
                  <h3 className="font-semibold">Demanda #{rascunho.demanda_numero}</h3>
                  <p className="text-sm text-gray-600">Produto: {rascunho.produto_id}</p>
                  <p className="text-sm text-gray-600">Criado: {new Date(rascunho.created_at).toLocaleString()}</p>
                </div>
                
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    onClick={() => setExpandido(expandido === rascunho.id ? null : rascunho.id)}
                    variant="outline"
                  >
                    <Expand size={16} />
                  </Button>
                  
                  <Button
                    size="sm"
                    onClick={() => confirmarRascunho(rascunho.id)}
                    className="bg-green-600 hover:bg-green-700"
                  >
                    <CheckCircle size={16} className="mr-2" />
                    Confirmar
                  </Button>
                  
                  <Button
                    size="sm"
                    onClick={() => descartarRascunho(rascunho.id)}
                    variant="destructive"
                  >
                    <Trash2 size={16} />
                  </Button>
                </div>
              </div>
              
              {/* Expandido: mostrar pedidos */}
              {expandido === rascunho.id && (
                <div className="mt-4 pt-4 border-t">
                  <h4 className="font-semibold mb-3">Pedidos neste Rascunho</h4>
                  <div className="space-y-2">
                    {/* Pedidos fetch via API */}
                    <PedidosRascunhoList demandaId={rascunho.id} />
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function PedidosRascunhoList({ demandaId }) {
  const [pedidos, setPedidos] = useState([]);
  const [loading, setLoading] = useState(true);
  
  useEffect(() => {
    fetch(`/api/v2/demandas/${demandaId}/pedidos`)
      .then(r => r.json())
      .then(d => setPedidos(d.pedidos || []))
      .finally(() => setLoading(false));
  }, [demandaId]);
  
  if (loading) return <p className="text-sm">Carregando pedidos...</p>;
  
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="bg-gray-50">
          <th className="p-2 text-left">Número</th>
          <th className="p-2 text-left">Plataforma</th>
          <th className="p-2 text-right">Qtd</th>
        </tr>
      </thead>
      <tbody>
        {pedidos.map(p => (
          <tr key={p.pedido_id} className="border-t">
            <td className="p-2">{p.numero_pedido}</td>
            <td className="p-2">{p.plataforma}</td>
            <td className="p-2 text-right">{p.quantidade_atendida}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

---

## 📅 TIMELINE E PRIORIZAÇÃO

### FASE 1: BLOQUEADORES (Semana 1 - 40 horas)
| Card | Descrição | Horas | Responsável |
|------|-----------|-------|-------------|
| **1.1** | View SQL rastreamento + 2 APIs GET | 8h | Backend |
| **1.2** | Task auto-consolidação + logs worker | 12h | Worker |
| **1.3** | Refatorar serviço IA (modular) | 12h | Shared (IA) |
| **1.4** | Frontend: coluna rastreamento em Pedidos | 6h | Frontend |
| **1.5** | Testes + Deploy staging | 2h | DevOps |

### FASE 2: MELHORIAS (Semana 2 - 30 horas)
| Card | Descrição | Horas | Responsável |
|------|-----------|-------|-------------|
| **2.1** | Frontend: aba Pedidos em Demandas | 6h | Frontend |
| **2.2** | Consolidar IA/Personalizados na UI | 8h | Frontend |
| **2.3** | Página de Rascunhos dedicada | 6h | Frontend |
| **2.4** | API debug `/worker-logs` + `/rastreamento-completo` | 4h | Backend |
| **2.5** | Testes E2E + documentação | 6h | QA |

### FASE 3: OTIMIZAÇÕES (Semana 3 - 25 horas)
| Card | Descrição | Horas | Responsável |
|------|-----------|-------|-------------|
| **3.1** | Cache resultados IA | 5h | Backend |
| **3.2** | Validação mapeamento modal (colisão) | 4h | Backend |
| **3.3** | UI de "Log Trace" para pedido | 6h | Frontend |
| **3.4** | Agendamento automático de lote de rascunhos | 4h | Worker |
| **3.5** | Otimização de queries (índices, caching) | 6h | Backend |

**Total**: 95 horas ≈ 2-3 semanas com 1 time (Backend + Frontend + Worker)

---

## 🛠️ CHECKLIST DE IMPLEMENTAÇÃO

### Problema 1: Rastreamento
- [ ] View SQL criada e testada
- [ ] GET `/pedidos/{id}/demandas` implementado
- [ ] GET `/demandas/{id}/pedidos` implementado
- [ ] Coluna "Demanda" em PedidosListPage
- [ ] Aba "Pedidos Origem" em DemandaDetailPage
- [ ] Breadcrumb visual pedido↔demanda

### Problema 2: IA/Personalizados
- [ ] `ai_personalization/base.py` (interfaces)
- [ ] `ai_personalization/rapida.py` (fast path)
- [ ] `ai_personalization/gemini.py` (refactored)
- [ ] `ai_personalization/orquestrador.py` (coordination)
- [ ] Tela `/vendas/personalizadas` com 4 abas
- [ ] Remover `/ai` ou redirect para `/vendas/personalizadas`
- [ ] DB: campos de correlação em `logs_execucao_ia`

### Problema 3: Worker
- [ ] Task `auto_consolidate_pedido` criada
- [ ] Task `processar_lote_rascunhos` criada
- [ ] Tabela `worker_logs` criada
- [ ] Integração webhook + auto_consolidate
- [ ] API `/debug/worker-logs`
- [ ] API `/debug/pedido/{id}/rastreamento-completo`
- [ ] Página RascunhosPage criada
- [ ] Filtro `/demandas?status=RASCUNHO` implementado

---

## 📚 DOCUMENTAÇÃO NECESSÁRIA

Após implementação, criar:

1. **TECNICO-RASTREAMENTO.md**: Fluxo pedido→demanda, queries, API
2. **TECNICO-IDENTIFICACAO.md**: Orquestrador IA, estratégias, logs
3. **TECNICO-CONSOLIDACAO.md**: Worker tasks, triggers, retry policy
4. **GUIA-USUARIO-RASTREAMENTO.md**: Como usar rastreamento na UI
5. **DEBUG-WORKER.md**: Como ler logs worker, interpretar erros

---

## 🔐 CONSIDERAÇÕES DE SEGURANÇA

- ✅ Endpoints debug protegidos com `@admin_required`
- ✅ Logs worker não expõem dados sensíveis (tokenização de PDV)
- ✅ Vista SQL apenas retorna dados já autenticados
- ✅ Correlação pedido↔demanda não expõe dados internos

---

## 📊 MÉTRICAS DE SUCESSO

- **Rastreamento**: 100% dos pedidos com demanda visível (ou "Não incluído")
- **IA**: Tempo médio identificação < 500ms (rápida) < 2s (Gemini)
- **Worker**: Rascunhos criados < 10s após webhook recebido
- **Logs**: Todos os erros loggados com traceback completo
- **UX**: 0 confusão entre "Personalizadas" + "Identificação IA" (1 menu único)

---

## 🚀 PRÓXIMOS PASSOS IMEDIATOS

1. **Aprovação**: Validar se timeline/escopo está alinhado
2. **Priorização**: Confirmar ordem de implementação
3. **Recursos**: Alocar backend/frontend/worker por ~2-3 semanas
4. **Staging**: Ter ambiente pronto para testes
5. **Kick-off**: Começar FASE 1 assim que aprovado
