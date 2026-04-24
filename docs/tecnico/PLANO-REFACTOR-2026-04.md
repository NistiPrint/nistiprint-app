# PLANO TÉCNICO DE REFATORAÇÃO — NISTIPRINT
**Data:** 2026-04-23
**Escopo:** Pedidos (modelo de dados + ingestão), Sync status Bling em lote, IA de personalização em lote, Classificação Flex, Consolidação, Estoque sync/async.
**Destino:** Este documento foi escrito para ser consumido por um agente de IA executor. Cada seção traz caminho de arquivo, linhas afetadas, SQL, pseudo-código e critério de aceitação.

---

## 0. CONVENÇÕES

- Caminhos são relativos à raiz do repositório.
- Quando um arquivo não existir, está explicitado "**CRIAR**".
- Migrations novas devem seguir padrão `supabase/migrations/YYYYMMDDHHMMSS_<nome>.sql`.
- Sempre usar `SupabaseDBService` existente para acesso a dados (singleton).
- Celery tasks devem viver em `packages/shared/nistiprint_shared/services/` e ser registradas em `apps/worker/celery_config.py`.

---

## 1. PARTE A — REFATORAÇÃO DO MODELO DE PEDIDOS

### 1.1 Objetivo
Restaurar modelo "mestre + tabelas-plataforma" onde:
- `pedidos_bling` é espelho fiel do payload Bling v3 (`/pedidos/vendas/{id}`).
- `pedidos_shopee` é espelho fiel do payload Shopee v2 (`/api/v2/order/get_order_detail`).
- `pedidos` é o centralizador normalizado, referenciando as tabelas-plataforma via FK.

### 1.2 Estado atual relevante
- As tabelas `pedidos_bling` e `pedidos_shopee` **já existem** (migration `20260301000000_initial_schema.sql`, linhas 1443-1520) mas estão subutilizadas.
- Driver Shopee [packages/shared/nistiprint_shared/services/platform_drivers/shopee.py:24](../../packages/shared/nistiprint_shared/services/platform_drivers/shopee.py#L24) implementa `get_order_detail` mas **não é chamado** a partir do fluxo Bling.
- Pedido Bling identifica Shopee via campo `numeroLoja` (código externo do pedido no marketplace) — ver [bling_order_processing_service.py:106](../../packages/shared/nistiprint_shared/services/bling_order_processing_service.py#L106).
- Webhooks Shopee **não são tratados** — todo fluxo entra por Bling; quando é pedido Shopee (`numeroLoja` preenchido + loja Bling mapeada para Shopee), o sistema deve chamar a API Shopee para enriquecer.
- **Mapeamento loja Bling → conta Shopee já existe em `channel_connections`** — ver [docs/tecnico/MODELO-DADOS.md:135](MODELO-DADOS.md#L135). Campos relevantes:
  - `aggregator_store_id` = ID da loja no Bling (equivale ao `payload.loja.id`).
  - `bling_integration_id` → FK para `installed_integrations` da instância Bling.
  - `marketplace_integration_id` → FK para `installed_integrations` da instância Shopee (contém `shop_id` e credenciais em `config`).
  - `channel_id` → FK para `canais_venda`.
  - **Não é necessário criar tabela adicional** para esse mapeamento.

### 1.3 Mudanças de schema (migration nova)

**Arquivo CRIAR:** `supabase/migrations/20260424000000_pedidos_refactor.sql`

```sql
-- 1.3.1 Colunas de link em pedidos
ALTER TABLE pedidos
    ADD COLUMN IF NOT EXISTS pedido_bling_id BIGINT REFERENCES pedidos_bling(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS pedido_shopee_id BIGINT REFERENCES pedidos_shopee(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS modalidade_logistica TEXT,
    ADD COLUMN IF NOT EXISTS shop_id_shopee BIGINT;

CREATE UNIQUE INDEX IF NOT EXISTS ux_pedidos_pedido_bling_id
    ON pedidos (pedido_bling_id) WHERE pedido_bling_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_pedidos_pedido_shopee_id
    ON pedidos (pedido_shopee_id) WHERE pedido_shopee_id IS NOT NULL;

-- 1.3.2 Garantir colunas em pedidos_shopee
ALTER TABLE pedidos_shopee
    ADD COLUMN IF NOT EXISTS fulfillment_flag TEXT,
    ADD COLUMN IF NOT EXISTS shipping_carrier TEXT,
    ADD COLUMN IF NOT EXISTS package_list JSONB,
    ADD COLUMN IF NOT EXISTS pay_time TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS recipient_address JSONB,
    ADD COLUMN IF NOT EXISTS item_list JSONB,
    ADD COLUMN IF NOT EXISTS shop_id BIGINT,
    ADD COLUMN IF NOT EXISTS raw_payload JSONB,
    ADD COLUMN IF NOT EXISTS enriched_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS ix_pedidos_shopee_shop_id ON pedidos_shopee(shop_id);

-- 1.3.3 Garantir colunas em pedidos_bling
ALTER TABLE pedidos_bling
    ADD COLUMN IF NOT EXISTS situacao_id INT,
    ADD COLUMN IF NOT EXISTS situacao_valor INT,
    ADD COLUMN IF NOT EXISTS contato JSONB,
    ADD COLUMN IF NOT EXISTS transporte JSONB,
    ADD COLUMN IF NOT EXISTS intermediador_cnpj TEXT,
    ADD COLUMN IF NOT EXISTS loja_id BIGINT,
    ADD COLUMN IF NOT EXISTS observacoes TEXT,
    ADD COLUMN IF NOT EXISTS observacoes_internas TEXT,
    ADD COLUMN IF NOT EXISTS raw_payload JSONB,
    ADD COLUMN IF NOT EXISTS integracao_instancia_id BIGINT REFERENCES integracao_instancia(id);

CREATE INDEX IF NOT EXISTS ix_pedidos_bling_loja_id ON pedidos_bling(loja_id);
CREATE INDEX IF NOT EXISTS ix_pedidos_bling_integracao ON pedidos_bling(integracao_instancia_id);

-- 1.3.4 (MAPEAMENTO LOJA BLING → SHOPEE: usa channel_connections existente, nada a criar)
-- Confirmar que os índices abaixo existem; criar se faltarem:
CREATE INDEX IF NOT EXISTS ix_channel_conn_aggregator
    ON channel_connections (bling_integration_id, aggregator_store_id)
    WHERE is_active = true;

-- 1.3.5 Regras parametrizáveis de classificação Flex por instância
CREATE TABLE IF NOT EXISTS flex_classification_rules (
    id BIGSERIAL PRIMARY KEY,
    integracao_instancia_id BIGINT REFERENCES integracao_instancia(id) ON DELETE CASCADE,
    canal_venda_id BIGINT REFERENCES canais_venda(id) ON DELETE CASCADE,
    campo TEXT NOT NULL,              -- 'shipping_carrier' | 'servico_logistico' | 'fulfillment_flag'
    operador TEXT NOT NULL,           -- 'ILIKE' | 'EQUALS' | 'ILIKE_NORMALIZED'
    padrao TEXT NOT NULL,             -- 'entrega rápida' | 'entrega rapida'
    is_flex BOOLEAN NOT NULL,
    modalidade TEXT,                  -- 'FLEX' | 'STANDARD' | 'FULL' ...
    prioridade INT DEFAULT 100,       -- menor = maior prioridade
    ativo BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CHECK (integracao_instancia_id IS NOT NULL OR canal_venda_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS ix_flex_rules_instancia ON flex_classification_rules(integracao_instancia_id, ativo);
CREATE INDEX IF NOT EXISTS ix_flex_rules_canal ON flex_classification_rules(canal_venda_id, ativo);

-- 1.3.6 DROP triggers legadas que interferem em is_flex
DROP TRIGGER IF EXISTS trg_calcular_is_flex ON pedidos;
DROP FUNCTION IF EXISTS calcular_is_flex();
-- O fn_snapshot_channel_on_insert NÃO deve mais tocar is_flex:
-- substitua o CREATE OR REPLACE da função, removendo linha
--    NEW.is_flex := (NEW.channel_snapshot->>'flex')::boolean;
-- Manter o resto do snapshot.
```

### 1.3.7a RPC de lookup de conexão Shopee

```sql
-- Consolidado em um RPC para reduzir round-trips HTTP REST ao Supabase.
CREATE OR REPLACE FUNCTION find_shopee_connection(
    p_bling_integration_id BIGINT,
    p_aggregator_store_id  TEXT
) RETURNS TABLE (
    marketplace_integration_id INT,
    channel_id                 INT,
    shopee_config              JSONB,
    shopee_credentials         JSONB
) AS $$
    SELECT cc.marketplace_integration_id,
           cc.channel_id,
           ii.config      AS shopee_config,
           ii.credentials AS shopee_credentials
      FROM channel_connections cc
      JOIN installed_integrations ii
           ON ii.id = cc.marketplace_integration_id
     WHERE cc.bling_integration_id = p_bling_integration_id
       AND cc.aggregator_store_id  = p_aggregator_store_id
       AND cc.is_active = true
     LIMIT 1;
$$ LANGUAGE sql STABLE;
```

### 1.3.7 Seed inicial de `flex_classification_rules`
```sql
-- Regras globais Shopee: APENAS "entrega rápida" (todas variações) é FLEX.
-- Xpress NUNCA é flex.
INSERT INTO flex_classification_rules
    (canal_venda_id, campo, operador, padrao, is_flex, modalidade, prioridade)
SELECT id, 'servico_logistico', 'ILIKE_NORMALIZED', 'entrega rapida', true, 'FLEX', 10
  FROM canais_venda WHERE plataforma = 'shopee';

INSERT INTO flex_classification_rules
    (canal_venda_id, campo, operador, padrao, is_flex, modalidade, prioridade)
SELECT id, 'shipping_carrier', 'ILIKE_NORMALIZED', 'entrega rapida', true, 'FLEX', 10
  FROM canais_venda WHERE plataforma = 'shopee';

-- Fallback: qualquer coisa Shopee que não caiu em regra acima vai como STANDARD
INSERT INTO flex_classification_rules
    (canal_venda_id, campo, operador, padrao, is_flex, modalidade, prioridade)
SELECT id, 'shipping_carrier', 'ILIKE', '%', false, 'STANDARD', 9999
  FROM canais_venda WHERE plataforma = 'shopee';
```

**Observação importante** (feedback do usuário):
> "Xpress" NUNCA deve ser Flex. Não incluir em regras. A regra default fallback cuida disso.

### 1.4 Serviço de classificação Flex (novo)

**Arquivo CRIAR:** `packages/shared/nistiprint_shared/services/flex_classifier_service.py`

```python
"""
Aplica regras parametrizáveis em flex_classification_rules.
Ordem de resolução (prioridade crescente):
  1) regras por integracao_instancia_id (match exato)
  2) regras por canal_venda_id
  3) fallback (primeira regra com padrão '%')

Operadores:
  - EQUALS               : campo == padrao
  - ILIKE                : campo ILIKE padrao
  - ILIKE_NORMALIZED     : normalize(campo) ILIKE normalize(padrao)
                           onde normalize = lower + strip_accents
"""
from dataclasses import dataclass
from typing import Optional
import unicodedata

def _normalize(s: Optional[str]) -> str:
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()

@dataclass
class FlexResult:
    is_flex: bool
    modalidade: str
    matched_rule_id: Optional[int]

def classify(
    db,  # SupabaseDBService
    fields: dict,                 # {'servico_logistico': ..., 'shipping_carrier': ..., 'fulfillment_flag': ...}
    integracao_instancia_id: Optional[int] = None,
    canal_venda_id: Optional[int] = None,
) -> FlexResult:
    rules = db.table('flex_classification_rules') \
        .select('*') \
        .eq('ativo', True) \
        .order('prioridade', desc=False) \
        .execute().data

    def matches(rule, value):
        op, pat = rule['operador'], rule['padrao']
        if value is None:
            return False
        if op == 'EQUALS':
            return value == pat
        if op == 'ILIKE':
            return pat.replace('%', '').lower() in value.lower() or pat == '%'
        if op == 'ILIKE_NORMALIZED':
            return _normalize(pat) in _normalize(value)
        return False

    # Ordem: instância > canal > global
    for scope_id, scope_field in [
        (integracao_instancia_id, 'integracao_instancia_id'),
        (canal_venda_id, 'canal_venda_id'),
    ]:
        if scope_id is None:
            continue
        for r in rules:
            if r.get(scope_field) != scope_id:
                continue
            val = fields.get(r['campo'])
            if matches(r, val):
                return FlexResult(r['is_flex'], r.get('modalidade') or 'STANDARD', r['id'])

    # Fallback global (sem escopo)
    for r in rules:
        if r.get('integracao_instancia_id') is None and r.get('canal_venda_id') is None:
            val = fields.get(r['campo'])
            if matches(r, val):
                return FlexResult(r['is_flex'], r.get('modalidade') or 'STANDARD', r['id'])

    return FlexResult(False, 'STANDARD', None)
```

### 1.5 Novo fluxo de ingestão Bling→Shopee

**Arquivo AFETADO:** [bling_order_processing_service.py](../../packages/shared/nistiprint_shared/services/bling_order_processing_service.py)

**Fluxo novo** (substitui o atual em `process_webhook` / `_save_order_to_db`):

```
1. Recebe payload Bling (webhook ou sync).
2. UPSERT em pedidos_bling (RAW fiel do payload):
   - numero, numero_loja, situacao.id/valor, contato, itens, transporte,
     intermediador.cnpj, observacoes, raw_payload, integracao_instancia_id
3. Detectar Shopee via channel_connections:
   - loja_bling_id = payload.loja.id
   - SELECT cc.*,
            ii_shopee.config AS shopee_config,
            ii_shopee.credentials AS shopee_credentials,
            cv.id AS canal_venda_id
       FROM channel_connections cc
       JOIN installed_integrations ii_shopee
            ON ii_shopee.id = cc.marketplace_integration_id
       JOIN canais_venda cv ON cv.id = cc.channel_id
      WHERE cc.bling_integration_id = <instancia Bling atual>
        AND cc.aggregator_store_id  = :loja_bling_id::text
        AND cc.is_active = true
      LIMIT 1
   - Se match: é Shopee. Extrair:
       * integracao_shopee_id   = cc.marketplace_integration_id
       * shop_id_shopee         = ii_shopee.config->>'shop_id' (ou credentials)
       * canal_venda_id         = cc.channel_id
4. Se Shopee:
   a. Montar dict `integration` a partir de ii_shopee (config + credentials + access_token)
      — mesmo formato já consumido por shopee.get_order_detail.
   b. Chamar platform_drivers.shopee.get_order_detail(
        integration=integration,
        order_sn_list=[payload.numeroLoja])
   c. UPSERT em pedidos_shopee com campos crus:
      order_sn, order_status, fulfillment_flag, shipping_carrier,
      package_list, pay_time, recipient_address, item_list, shop_id,
      raw_payload, enriched_at=NOW()
5. Derivação centralizada (pedidos):
   - fields = {
       'servico_logistico': <volumes[0].servico do Bling>,
       'shipping_carrier':  <pedidos_shopee.shipping_carrier ou package_list[0].shipping_carrier>,
       'fulfillment_flag':  <pedidos_shopee.fulfillment_flag>,
     }
   - flex = flex_classifier_service.classify(
              db, fields,
              integracao_instancia_id=<shopee quando aplicável, senão bling>,
              canal_venda_id=<resolvido>)
   - UPSERT em pedidos:
       pedido_bling_id, pedido_shopee_id, shop_id_shopee,
       is_flex = flex.is_flex,
       modalidade_logistica = flex.modalidade,
       canal_venda_id, situacao_pedido_id (mapeado), ...
6. Chamar create_from_order passando is_flex e modalidade explicitamente.
```

**Pseudo-diff** em [bling_order_processing_service.py:~426](../../packages/shared/nistiprint_shared/services/bling_order_processing_service.py#L426) (função `_save_order_to_db`):

```python
# ANTES: _save_order_to_db escreve direto em `pedidos`
# DEPOIS:

def _save_order_to_db(self, payload, integracao_bling_id):
    pedido_bling_id = self._upsert_pedido_bling(payload, integracao_bling_id)

    pedido_shopee_id, shop_id, shopee_data = None, None, None
    conn = self._find_channel_connection(
        bling_integration_id=integracao_bling_id,
        aggregator_store_id=str(payload.get('loja', {}).get('id')),
    )
    # conn contém: marketplace_integration_id, channel_id, shopee config/credentials
    canal_venda_id = conn['channel_id'] if conn else None

    if conn and conn.get('marketplace_integration_id'):
        integration_shopee = self._build_shopee_integration_dict(conn)
        shopee_data = shopee_driver.get_order_detail(
            integration=integration_shopee,
            order_sn_list=[payload.get('numeroLoja')],
        )
        pedido_shopee_id = self._upsert_pedido_shopee(
            shopee_data,
            shop_id=integration_shopee['shop_id'],
        )
        shop_id = integration_shopee['shop_id']

    flex = flex_classifier_service.classify(
        self.supabase,
        fields={
            'servico_logistico': _volume_servico(payload),
            'shipping_carrier':  (shopee_data or {}).get('shipping_carrier'),
            'fulfillment_flag':  (shopee_data or {}).get('fulfillment_flag'),
        },
        integracao_instancia_id=(conn or {}).get('marketplace_integration_id') or integracao_bling_id,
        canal_venda_id=canal_venda_id,
    )

    pedido_id = self._upsert_pedido_master(
        payload,
        pedido_bling_id=pedido_bling_id,
        pedido_shopee_id=pedido_shopee_id,
        shop_id_shopee=shop_id,
        canal_venda_id=canal_venda_id,
        is_flex=flex.is_flex,
        modalidade=flex.modalidade,
    )

    demanda_producao_service.create_from_order(
        pedido_id=pedido_id,
        is_flex=flex.is_flex,
        modalidade_logistica=flex.modalidade,
        canal_venda_id=canal_venda_id,
    )

def _find_channel_connection(self, bling_integration_id, aggregator_store_id):
    """
    Consulta channel_connections para mapear loja Bling → integração Shopee + canal.
    Retorna dict com marketplace_integration_id, channel_id, shopee config/credentials,
    ou None se não houver vínculo ativo.
    """
    rows = self.supabase.rpc('find_shopee_connection', {
        'p_bling_integration_id': bling_integration_id,
        'p_aggregator_store_id':  aggregator_store_id,
    }).execute().data
    return rows[0] if rows else None
```

### 1.6 Correções em `create_from_order`
**Arquivo:** [demanda_producao_service.py:415](../../packages/shared/nistiprint_shared/services/demanda_producao_service.py#L415)

1. Aceitar kwargs `is_flex`, `modalidade_logistica`, `canal_venda_id` explícitos.
2. Se não vierem, **derivar** lendo `pedidos.is_flex`, `pedidos.modalidade_logistica`, `pedidos.canal_venda_id`.
3. Passar adiante para `criar_demanda_direta` (linha 592) via kwargs (que já os consome).

### 1.7 Backfill
**Arquivo CRIAR:** `apps/ops/scripts/backfill_pedidos_refactor.py`

```python
# 1. Para cada linha em pedidos, localizar origem:
#    - Se origem='BLING' e não tem pedido_bling_id: buscar pedidos_bling por codigo_pedido_externo, FK
#    - Se numero_loja mapeia para Shopee: chamar get_order_detail, popular pedidos_shopee, FK
# 2. Recalcular is_flex + modalidade via flex_classifier_service.
# 3. Atualizar pedidos.
# 4. Zerar entradas resolvidas em pedidos_nao_classificados.
```

### 1.8 Critério de aceitação — Parte A
- [ ] Todo pedido novo tem `pedidos.pedido_bling_id IS NOT NULL`.
- [ ] Todo pedido Shopee-via-Bling tem `pedidos.pedido_shopee_id IS NOT NULL`.
- [ ] `pedidos.is_flex = true` apenas quando regra em `flex_classification_rules` casa.
- [ ] Zero pedidos "Shopee Xpress" com `is_flex = true` (SQL check).
- [ ] Todos "Entrega Rápida" (com ou sem acento, case) têm `is_flex = true`.
- [ ] Sem triggers `calcular_is_flex` no banco (`\d pedidos` no psql).
- [ ] `channel_snapshot` continua preenchido mas não sobrescreve `is_flex`.

---

## 2. PARTE B — SYNC EM LOTE DE STATUS VIA BLING

### 2.1 Objetivo
UI permite selecionar N pedidos e clicar "Atualizar Bling" → sistema busca cada `pedidos_bling.bling_id` na API Bling, atualiza `situacao_id/valor` em `pedidos_bling` e propaga para `pedidos.situacao_pedido_id` via mapping.

### 2.2 Endpoint novo

**Arquivo CRIAR:** `apps/api/routes/pedidos_sync.py`

```python
from flask import Blueprint, request, jsonify
from nistiprint_shared.services.bling_status_sync_service import agendar_sync_status_batch

bp = Blueprint('pedidos_sync', __name__)

@bp.route('/api/v2/pedidos/sync-bling-status', methods=['POST'])
def sync_bling_status():
    body = request.get_json() or {}
    pedido_ids = body.get('pedido_ids') or []
    if not pedido_ids or len(pedido_ids) > 500:
        return jsonify({'error': 'informe 1..500 pedido_ids'}), 400
    batch_id = agendar_sync_status_batch(pedido_ids)
    return jsonify({'batch_id': batch_id}), 202

@bp.route('/api/v2/pedidos/sync-bling-status/<batch_id>', methods=['GET'])
def sync_bling_status_progress(batch_id):
    from nistiprint_shared.database.supabase_db_service import supabase_db
    row = supabase_db.table('sync_status_batches').select('*').eq('id', batch_id).single().execute()
    return jsonify(row.data)
```

Registrar blueprint em `apps/api/app.py` (ou equivalente).

### 2.3 Tabela de progresso

```sql
-- Adicionar na migration 20260424000000_pedidos_refactor.sql:
CREATE TABLE IF NOT EXISTS sync_status_batches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pedido_ids BIGINT[] NOT NULL,
    total INT NOT NULL,
    sucesso INT DEFAULT 0,
    falha INT DEFAULT 0,
    status TEXT DEFAULT 'PENDENTE',  -- PENDENTE, RODANDO, CONCLUIDO, ERRO
    iniciado_em TIMESTAMPTZ DEFAULT NOW(),
    finalizado_em TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS sync_status_errors (
    id BIGSERIAL PRIMARY KEY,
    batch_id UUID REFERENCES sync_status_batches(id) ON DELETE CASCADE,
    pedido_id BIGINT NOT NULL,
    bling_id BIGINT,
    erro TEXT,
    tentado_em TIMESTAMPTZ DEFAULT NOW()
);
```

### 2.4 Serviço e task Celery

**Arquivo CRIAR:** `packages/shared/nistiprint_shared/services/bling_status_sync_service.py`

```python
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from celery import shared_task
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.bling.bling import bling_get_order_detail, bling_get_token

logger = logging.getLogger(__name__)

BLING_BATCH_SIZE = 100
BLING_RATE_LIMIT_RPS = 3   # limite conservador por app Bling

def agendar_sync_status_batch(pedido_ids):
    batch = supabase_db.table('sync_status_batches').insert({
        'pedido_ids': pedido_ids,
        'total': len(pedido_ids),
        'status': 'PENDENTE',
    }).execute().data[0]
    sync_status_batch_task.delay(batch['id'])
    return batch['id']

@shared_task(name='services.bling_status_sync.sync_batch', bind=True, max_retries=2)
def sync_status_batch_task(self, batch_id: str):
    supabase_db.table('sync_status_batches').update({'status': 'RODANDO'}).eq('id', batch_id).execute()
    batch = supabase_db.table('sync_status_batches').select('*').eq('id', batch_id).single().execute().data
    ids = batch['pedido_ids']

    pedidos = supabase_db.table('pedidos') \
        .select('id, pedido_bling_id, pedidos_bling!inner(bling_id, integracao_instancia_id)') \
        .in_('id', ids).execute().data

    # Agrupar por instância Bling (cada uma tem token próprio + rate limit próprio)
    por_instancia = {}
    for p in pedidos:
        inst = p['pedidos_bling']['integracao_instancia_id']
        por_instancia.setdefault(inst, []).append(p)

    sucesso, falha = 0, 0
    for inst_id, lote in por_instancia.items():
        token = bling_get_token(inst_id)
        # Paralelizar dentro do lote, mas respeitando rate limit
        with ThreadPoolExecutor(max_workers=3) as ex:
            futs = {}
            for i, p in enumerate(lote):
                # Spread de 1/BLING_RATE_LIMIT_RPS segundos entre disparos
                time.sleep(max(0, (1.0/BLING_RATE_LIMIT_RPS) - 0.05))
                futs[ex.submit(_sync_one, token, p, batch_id)] = p
            for fut in as_completed(futs):
                ok = fut.result()
                if ok: sucesso += 1
                else:  falha += 1
                supabase_db.table('sync_status_batches').update({
                    'sucesso': sucesso, 'falha': falha
                }).eq('id', batch_id).execute()

    supabase_db.table('sync_status_batches').update({
        'status': 'CONCLUIDO', 'finalizado_em': 'now()'
    }).eq('id', batch_id).execute()

def _sync_one(token, p, batch_id):
    bling_id = p['pedidos_bling']['bling_id']
    try:
        detail = bling_get_order_detail(token, bling_id)
        situacao = (detail or {}).get('data', {}).get('situacao', {})
        supabase_db.table('pedidos_bling').update({
            'situacao_id': situacao.get('id'),
            'situacao_valor': situacao.get('valor'),
            'raw_payload': detail.get('data'),
        }).eq('bling_id', bling_id).execute()

        # Propaga para pedidos via mapping integration_status_mappings
        mapping = supabase_db.table('integration_status_mappings') \
            .select('situacao_pedido_id') \
            .eq('plataforma', 'bling') \
            .eq('status_externo_id', situacao.get('id')) \
            .maybe_single().execute().data
        if mapping:
            supabase_db.table('pedidos').update({
                'situacao_pedido_id': mapping['situacao_pedido_id']
            }).eq('id', p['id']).execute()
        return True
    except Exception as e:
        supabase_db.table('sync_status_errors').insert({
            'batch_id': batch_id,
            'pedido_id': p['id'],
            'bling_id': bling_id,
            'erro': str(e)[:500],
        }).execute()
        return False
```

**Registrar em:** `apps/worker/celery_config.py` — adicionar import do módulo às tasks do worker. **Sem beat schedule** (on-demand).

### 2.5 UI
**Arquivo AFETADO:** `apps/frontend/src/pages/Pedidos/PedidosList.tsx` (ou equivalente).

- Checkbox em cada linha → seleção múltipla.
- Botão "Atualizar status Bling" → `POST /api/v2/pedidos/sync-bling-status` com `pedido_ids`.
- Polling no `GET /.../sync-bling-status/{batch_id}` a cada 2s até `status === 'CONCLUIDO'`.
- Exibir progress bar `{sucesso + falha} / {total}` e notificação ao final.

### 2.6 Critério de aceitação — Parte B
- [ ] Selecionar 50 pedidos e clicar "Atualizar Bling" completa em <30s.
- [ ] Falhas individuais registradas em `sync_status_errors` sem derrubar o lote.
- [ ] `pedidos_bling.situacao_id` reflete valor atual do Bling para cada pedido.
- [ ] `pedidos.situacao_pedido_id` é atualizado via mapping.
- [ ] Nenhum side-effect em estoque, demanda, ou personalização.

---

## 3. PARTE C — IA DE PERSONALIZAÇÃO EM LOTE

### 3.1 Problema do pool Supabase

O legado ([kb/legado/services/ai_personalization_service.py:566](../../kb/legado/services/ai_personalization_service.py#L566)) usava `ThreadPoolExecutor(max_workers=10)` contra MySQL próprio — cada thread abre sua conexão, pool grande.

O novo usa **Supabase REST via `httpx`** ([packages/shared/nistiprint_shared/database/supabase_db_service.py:30](../../packages/shared/nistiprint_shared/database/supabase_db_service.py#L30)) — singleton HTTP client. Quando 10 threads batem paralelamente no REST, `httpx.PoolTimeout` dispara e o lote todo trava.

### 3.2 Estratégia — fan-out via Celery (uma task por pedido)

Ao invés de ThreadPool dentro do processo web, despachar **uma task Celery por pedido**. Celery respeita concorrência global do worker (`-c` flag), e cada worker_process tem seu próprio `SupabaseDBService` singleton, naturalmente serializando.

**Workers Celery devem rodar com concorrência controlada:**
```yaml
# docker-compose ou similar
celery -A apps.worker.celery_config worker -Q ai_personalization -c 4
```
Concorrência **4** é o alvo: suficiente para Gemini paralelo, baixo o bastante para não saturar httpx pool.

### 3.3 Tabelas de controle

```sql
-- Acrescentar à migration 20260424000000_pedidos_refactor.sql:
CREATE TABLE IF NOT EXISTS execucoes_ai_batch (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    criado_em TIMESTAMPTZ DEFAULT NOW(),
    pedido_ids BIGINT[] NOT NULL,
    total INT NOT NULL,
    processados INT DEFAULT 0,
    sucesso INT DEFAULT 0,
    falha INT DEFAULT 0,
    status TEXT DEFAULT 'PENDENTE',
    finalizado_em TIMESTAMPTZ,
    iniciado_por TEXT
);

CREATE TABLE IF NOT EXISTS execucoes_ai_item (
    id BIGSERIAL PRIMARY KEY,
    batch_id UUID REFERENCES execucoes_ai_batch(id) ON DELETE CASCADE,
    pedido_id BIGINT NOT NULL,
    status TEXT NOT NULL,   -- 'OK' | 'ERRO' | 'IGNORADO'
    erro TEXT,
    duracao_ms INT,
    criado_em TIMESTAMPTZ DEFAULT NOW()
);
```

### 3.4 Refactor do serviço de IA

**Arquivo AFETADO:** [packages/shared/nistiprint_shared/services/ai_personalization_service.py](../../packages/shared/nistiprint_shared/services/ai_personalization_service.py)

Plano:
1. **Manter** `_run_ia_for_order` (linha 854-908) — já funciona individual.
2. **Deletar** `process_orders` atual (linhas 968-1076, pipeline 2-fases quebrado).
3. **Deletar** `_batch_resolve_item_pedido_ids` (linhas 570-624) — resolução agora é intra-task.
4. **Criar** duas novas Celery tasks:

```python
@shared_task(name='services.ai_personalization.processar_batch',
             bind=True, max_retries=0)
def processar_batch_ia(self, batch_id: str):
    """Orquestrador: cria uma task-filha por pedido e atualiza contadores."""
    from nistiprint_shared.database.supabase_db_service import supabase_db
    batch = supabase_db.table('execucoes_ai_batch').select('*') \
        .eq('id', batch_id).single().execute().data
    supabase_db.table('execucoes_ai_batch').update({'status': 'RODANDO'}) \
        .eq('id', batch_id).execute()
    for pid in batch['pedido_ids']:
        processar_pedido_ia.apply_async(
            args=[batch_id, pid],
            queue='ai_personalization',
        )
    # Esta task retorna logo; a finalização acontece via processar_pedido_ia
    # quando processados == total.

@shared_task(name='services.ai_personalization.processar_pedido',
             bind=True, max_retries=2, default_retry_delay=30,
             acks_late=True)
def processar_pedido_ia(self, batch_id: str, pedido_id: int):
    """Task isolada por pedido. Falha de um pedido não contamina outros."""
    from nistiprint_shared.database.supabase_db_service import supabase_db
    import time
    t0 = time.monotonic()
    status, erro = 'OK', None
    try:
        pedido = _load_pedido_com_itens(pedido_id)  # leitura única
        resultado = _run_ia_for_order(pedido)       # reuso da função que funciona
        _persistir_personalizacao(pedido, resultado)  # um INSERT/UPSERT sequencial
    except httpx.PoolTimeout as e:
        raise self.retry(exc=e)   # backoff automático do Celery
    except Exception as e:
        status, erro = 'ERRO', str(e)[:500]
    finally:
        supabase_db.table('execucoes_ai_item').insert({
            'batch_id': batch_id, 'pedido_id': pedido_id,
            'status': status, 'erro': erro,
            'duracao_ms': int((time.monotonic() - t0) * 1000),
        }).execute()
        # Incrementa contadores no batch com SQL atômico
        supabase_db.rpc('incrementar_batch_ia', {
            'p_batch_id': batch_id,
            'p_sucesso': 1 if status == 'OK' else 0,
            'p_falha':   1 if status == 'ERRO' else 0,
        }).execute()
```

### 3.5 RPC de incremento atômico (evita race condition)

```sql
-- Na migration 20260424000000_pedidos_refactor.sql
CREATE OR REPLACE FUNCTION incrementar_batch_ia(
    p_batch_id UUID,
    p_sucesso INT,
    p_falha INT
) RETURNS VOID AS $$
DECLARE
    v_total INT;
    v_proc INT;
BEGIN
    UPDATE execucoes_ai_batch
       SET processados = processados + 1,
           sucesso     = sucesso + p_sucesso,
           falha       = falha + p_falha
     WHERE id = p_batch_id
    RETURNING total, processados INTO v_total, v_proc;

    IF v_proc >= v_total THEN
        UPDATE execucoes_ai_batch
           SET status = 'CONCLUIDO',
               finalizado_em = NOW()
         WHERE id = p_batch_id;
    END IF;
END;
$$ LANGUAGE plpgsql;
```

### 3.6 Endpoint atualizado

**Arquivo AFETADO:** `apps/api/routes/personalizados.py` (linha 59-111).

```python
@bp.route('/api/v2/personalizados/processar', methods=['POST'])
def processar():
    body = request.get_json() or {}
    pedido_ids = body.get('pedido_ids')
    limit = body.get('limit', 100)
    if not pedido_ids:
        pedido_ids = _listar_pendentes(limit)
    if not pedido_ids:
        return jsonify({'message': 'nada a processar'}), 200
    batch = supabase_db.table('execucoes_ai_batch').insert({
        'pedido_ids': pedido_ids,
        'total': len(pedido_ids),
        'iniciado_por': g.user_email if hasattr(g, 'user_email') else None,
    }).execute().data[0]
    processar_batch_ia.delay(batch['id'])
    return jsonify({'batch_id': batch['id']}), 202

@bp.route('/api/v2/personalizados/processar/<batch_id>', methods=['GET'])
def progresso(batch_id):
    row = supabase_db.table('execucoes_ai_batch').select('*') \
        .eq('id', batch_id).single().execute().data
    return jsonify(row)
```

### 3.7 Configuração de fila Celery

**Arquivo AFETADO:** [apps/worker/celery_config.py](../../apps/worker/celery_config.py)

```python
# Adicionar configuração de filas
task_queues = {
    'default': {'exchange': 'default', 'routing_key': 'default'},
    'ai_personalization': {'exchange': 'ai', 'routing_key': 'ai.personalization'},
    'bling_status_sync':  {'exchange': 'bling', 'routing_key': 'bling.status'},
}

task_routes = {
    'services.ai_personalization.processar_batch': {'queue': 'ai_personalization'},
    'services.ai_personalization.processar_pedido': {'queue': 'ai_personalization'},
    'services.bling_status_sync.sync_batch': {'queue': 'bling_status_sync'},
}
```

**docker-compose** (ou equivalente): subir **worker separado** por fila para limitar concorrência sem afetar outras tasks:
```yaml
worker-ai:
  command: celery -A apps.worker worker -Q ai_personalization -c 4 -n ai@%h
worker-bling:
  command: celery -A apps.worker worker -Q bling_status_sync -c 2 -n bling@%h
worker-default:
  command: celery -A apps.worker worker -Q default -c 8 -n default@%h
```

### 3.8 Hardening adicional

1. **Circuit breaker no `SupabaseDBService`** ([supabase_db_service.py:79](../../packages/shared/nistiprint_shared/database/supabase_db_service.py#L79)): ao capturar `httpx.PoolTimeout` 3x em janela de 30s, backoff global de 5s antes de próxima request. Protege contra avalanche.

2. **httpx pool explícito**: passar `httpx.Limits(max_connections=20, max_keepalive_connections=10)` ao criar o client. Fica em ([supabase_db_service.py:30](../../packages/shared/nistiprint_shared/database/supabase_db_service.py#L30)):
   ```python
   import httpx
   _httpx_client = httpx.Client(
       limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
       timeout=httpx.Timeout(30.0, connect=5.0),
   )
   ```

3. **Batch size default = 50**. Lotes grandes (>100) são fatiados pelo endpoint em sub-batches.

### 3.9 Critério de aceitação — Parte C
- [ ] Lote de 50 pedidos com 1 deliberadamente quebrado: 49 sucessos + 1 falha, sem `PoolTimeout`.
- [ ] `execucoes_ai_batch.status = 'CONCLUIDO'` ao final.
- [ ] Nenhuma task retry-loop infinita (max 2 retries no pedido).
- [ ] Request HTTP `/processar` retorna em <500ms (202 Accepted).
- [ ] Worker Celery com `-c 4` na fila `ai_personalization` nunca excede 4 requests simultâneas ao Supabase.

---

## 4. PARTE D — CORREÇÕES PENDENTES (HERANÇA DO RELATÓRIO ANTERIOR)

### 4.1 Consolidação
**Arquivo AFETADO:** `packages/shared/nistiprint_shared/services/consolidacao_service.py` (verificar nome exato).

1. Ao auto-criar demanda rascunho, o worker deve popular:
   - `canal_venda_id` (primeiro pedido do grupo)
   - `modalidade_logistica`
   - `is_flex`
2. Agrupamento deve particionar por `(canal_venda_id, modalidade_logistica, is_flex)` **antes** de agrupar por composição.
3. Popular `regras_logisticas_canal` com linhas por (canal × modalidade):

```sql
-- Shopee Flex: corte 11h
INSERT INTO regras_logisticas_canal (canal_venda_id, modalidade, horario_corte, ...)
SELECT id, 'FLEX', '11:00', ... FROM canais_venda WHERE plataforma='shopee';
-- Shopee Standard: corte 15h
INSERT INTO regras_logisticas_canal (canal_venda_id, modalidade, horario_corte, ...)
SELECT id, 'STANDARD', '15:00', ... FROM canais_venda WHERE plataforma='shopee';
```

4. Resolver duplicação `channel_connections` × `integracao_canais_config`: eleger `channel_connections` como fonte única; migrar dados; dropar `integracao_canais_config` após garantir que nada a usa.

### 4.2 Estoque sync/async

**Arquivo AFETADO:** [demanda_producao_service.py](../../packages/shared/nistiprint_shared/services/demanda_producao_service.py)

**Em `finalizar_item` ([linha 1875](../../packages/shared/nistiprint_shared/services/demanda_producao_service.py#L1875)) e `finalizar_item_parcial` ([linha 1910](../../packages/shared/nistiprint_shared/services/demanda_producao_service.py#L1910)):**

```
ANTES:
  finalizar_item(item, delta):
    agendar_processamento_estoque('ITEM_TOTAL_PROCESSO', item, delta)  # async tudo
    atualizar_contadores_visuais(...)                                   # sync

DEPOIS:
  finalizar_item(item, delta):
    produto_direto = _resolver_produto_direto(item)      # MIOLO, CAPA_IMPRESSAO, etc
    if produto_direto:
        estoque_service.movimentar_por_delta(
            produto_id=produto_direto.id,
            delta=delta,
            demanda_id=item.demanda_id,
            item_id=item.id,
            idempotency_key=f"direto:{item.id}",
        )  # SYNC
    agendar_processamento_estoque(
        'BOM_RECURSIVO_APOS_DIRETO',
        item, delta,
        skip_produto_direto_id=produto_direto.id if produto_direto else None,
    )  # ASYNC — apenas BOM recursivo
    atualizar_contadores_visuais(...)
```

**Novo `tipo_tarefa` em `fila_processamento_estoque`:**
- `'BOM_RECURSIVO_APOS_DIRETO'` — worker faz explosão BOM **exceto** `produto_direto_id`, que já foi baixado sync.

**Em `processar_fila_estoque` ([linha 2394](../../packages/shared/nistiprint_shared/services/demanda_producao_service.py#L2394)):**
- Quando `tipo_tarefa = 'BOM_RECURSIVO_APOS_DIRETO'` e `skip_produto_direto_id` vier setado, pular esse nó.
- Idempotência: tabela `movimentacoes_estoque` ganha coluna `idempotency_key UNIQUE NULLABLE`. Reprocessos não duplicam.

```sql
ALTER TABLE movimentacoes_estoque
    ADD COLUMN IF NOT EXISTS idempotency_key TEXT UNIQUE;
```

### 4.3 Tasks mortas e hardcodes

1. **[redis_queue_tasks.py:40](../../packages/shared/nistiprint_shared/services/redis_queue_tasks.py#L40)** (`consumir_fila_bling`) — substituir corpo atual por chamada real a `process_bling_webhook.delay(webhook_data)`. Se a fila Redis foi abandonada em favor do webhook HTTP direto, deletar a task e seu agendamento em beat.

2. **[webhook_tasks.py:182-222](../../packages/shared/nistiprint_shared/services/webhook_tasks.py#L182)** — os helpers `_process_shopee_*` e `_process_bling_*` estão como TODO. Se o fluxo real vive em `bling_order_processing_service`, deletar helpers e simplificar as tasks para apenas logar. Documentar decisão.

3. **CNPJs hardcoded** (`13597`, `54533`) em `bling_order_processing_service.py`:
   - Mover para `integracao_instancia.config.cnpj_identificador`.
   - Função de detecção passa a ler do banco.

### 4.4 Critério de aceitação — Parte D
- [ ] Usuário aloca 10 miolos → saldo visível cai para 10 em <1s (sync).
- [ ] BOM recursivo continua sendo processado em <30s via worker (async).
- [ ] Nenhum pedido novo entra em `pedidos_nao_classificados` por 7 dias após deploy.
- [ ] Demandas auto-consolidadas têm `canal_venda_id`, `modalidade_logistica`, `is_flex` preenchidos.

---

## 5. ORDEM DE EXECUÇÃO E DEPENDÊNCIAS

```
F1 (Parte A schema + ingestão)         3-5 dias   BLOQUEIA F2, F4
F2 (Parte B sync status)               2-3 dias   Depende de F1
F3 (Parte C IA em lote)                3-4 dias   Independente; pode paralelizar com F2
F4 (Parte D consolidação)              5-7 dias   Depende de F1
F5 (Parte D estoque sync/async)        3-5 dias   Independente
F6 (Parte D limpezas/hardcodes)        1-2 dias   Por último
```

Caminho crítico: F1 → F2/F4 → aceitação global.

---

## 6. CHECKLIST DE IMPLEMENTAÇÃO POR ARQUIVO

| Arquivo | Ação | Seção |
|---|---|---|
| `supabase/migrations/20260424000000_pedidos_refactor.sql` | CRIAR | 1.3, 2.3, 3.3, 3.5, 4.2 |
| `packages/shared/nistiprint_shared/services/flex_classifier_service.py` | CRIAR | 1.4 |
| `packages/shared/nistiprint_shared/services/bling_order_processing_service.py` | EDITAR | 1.5, 4.3 |
| `packages/shared/nistiprint_shared/services/platform_drivers/shopee.py` | EDITAR — expor `fulfillment_flag`, `shipping_carrier`, `package_list` no DTO | 1.5 |
| `packages/shared/nistiprint_shared/services/demanda_producao_service.py` | EDITAR | 1.6, 4.2 |
| `packages/shared/nistiprint_shared/services/ai_personalization_service.py` | EDITAR (refactor Celery) | 3.4 |
| `packages/shared/nistiprint_shared/services/bling_status_sync_service.py` | CRIAR | 2.4 |
| `packages/shared/nistiprint_shared/services/redis_queue_tasks.py` | EDITAR ou DELETAR | 4.3 |
| `packages/shared/nistiprint_shared/services/webhook_tasks.py` | EDITAR ou DELETAR helpers | 4.3 |
| `packages/shared/nistiprint_shared/database/supabase_db_service.py` | EDITAR — httpx limits + circuit breaker | 3.8 |
| `apps/api/routes/pedidos_sync.py` | CRIAR | 2.2 |
| `apps/api/routes/personalizados.py` | EDITAR | 3.6 |
| `apps/worker/celery_config.py` | EDITAR — filas e routing | 3.7 |
| `apps/ops/scripts/backfill_pedidos_refactor.py` | CRIAR | 1.7 |
| `apps/frontend/src/pages/Pedidos/PedidosList.tsx` (ou equivalente) | EDITAR — botão sync Bling | 2.5 |
| `docker-compose.yml` (ou k8s) | EDITAR — workers dedicados por fila | 3.7 |

---

## 7. RISCOS E MITIGAÇÕES

| Risco | Mitigação |
|---|---|
| Backfill reprocessa pedidos e atinge rate limit Shopee | Executar backfill em janelas de 100 pedidos com sleep, ou apenas para pedidos dos últimos 90 dias |
| Pool httpx satura com Celery concorrente | Limite explícito de `max_connections=20` em `httpx.Limits` + `-c 4` no worker de IA |
| Triggers antigos ainda ativos após migration | Conferir com `\df+` e `\d+ pedidos` no psql após migration; incluir assertion no próprio SQL |
| Backward compat: pedidos_nao_classificados em produção | Após backfill, job de limpeza move resolvidos para arquivo; não deletar em lote |
| "Xpress" classificado como Flex por regex frouxo | Seed de `flex_classification_rules` NÃO inclui `xpress`; fallback explícito `shipping_carrier ILIKE '%'` → STANDARD |
| Bling v3 retorna 429 no sync em lote | `ThreadPoolExecutor(max_workers=3)` + sleep 333ms entre disparos (ver [2.4](#24-serviço-e-task-celery)) |

---

## 8. VALIDAÇÕES FINAIS (SQL DE VERIFICAÇÃO)

Após deploy, executar:

```sql
-- V1: Nenhum Xpress classificado como flex
SELECT COUNT(*) AS xpress_flex
FROM pedidos p
JOIN pedidos_shopee ps ON ps.id = p.pedido_shopee_id
WHERE ps.shipping_carrier ILIKE '%xpress%'
  AND p.is_flex = true;
-- Esperado: 0

-- V2: Todos "Entrega Rápida" são flex
SELECT COUNT(*) AS entrega_rapida_nao_flex
FROM pedidos p
JOIN pedidos_shopee ps ON ps.id = p.pedido_shopee_id
WHERE ps.shipping_carrier ILIKE '%entrega r%pida%'
  AND p.is_flex = false;
-- Esperado: 0

-- V3: Cobertura de link
SELECT
  COUNT(*) FILTER (WHERE origem='BLING' AND pedido_bling_id IS NULL) AS bling_sem_link,
  COUNT(*) FILTER (WHERE origem='SHOPEE' AND pedido_shopee_id IS NULL) AS shopee_sem_link
FROM pedidos;
-- Esperado: 0, 0

-- V4: Triggers de flex não existem mais
SELECT tgname FROM pg_trigger WHERE tgname LIKE '%flex%' AND NOT tgisinternal;
-- Esperado: vazio

-- V5: Demandas recentes têm modalidade
SELECT COUNT(*) AS demandas_sem_modalidade
FROM demandas_producao
WHERE created_at > NOW() - INTERVAL '7 days'
  AND (modalidade_logistica IS NULL OR canal_venda_id IS NULL);
-- Esperado: 0
```

---

## 9. ANEXOS

### 9.1 Payload Bling (referência) — [docs/tecnico/APIs/bling.md](APIs/bling.md)
Campos críticos: `data.id`, `data.numeroLoja`, `data.loja.id`, `data.situacao.id/valor`, `data.itens[]`, `data.transporte.volumes[].servico`, `data.intermediador.cnpj`.

### 9.2 Payload Shopee (referência) — [docs/tecnico/APIs/shopee.md](APIs/shopee.md)
Campos críticos: `order_sn`, `order_status`, `fulfillment_flag`, `shipping_carrier` (no root **e** em `package_list[i].shipping_carrier`), `buyer_username`, `buyer_user_id`, `item_list[]`, `pay_time`, `recipient_address`.

### 9.3 Tabelas novas criadas neste plano
- `flex_classification_rules`
- `sync_status_batches`
- `sync_status_errors`
- `execucoes_ai_batch`
- `execucoes_ai_item`

Reutilizada (sem alteração estrutural, apenas índice): `channel_connections` para mapeamento loja Bling → integração Shopee.

### 9.4 Funções/RPCs novas
- `find_shopee_connection(bigint, text)` — SQL STABLE, lookup de conexão Shopee via channel_connections.
- `incrementar_batch_ia(uuid, int, int)` — PL/pgSQL, contador atômico de batch IA.

### 9.5 Triggers removidos
- `trg_calcular_is_flex` (e função `calcular_is_flex`)
- Linha de override em `fn_snapshot_channel_on_insert`

---

**FIM DO DOCUMENTO.**
