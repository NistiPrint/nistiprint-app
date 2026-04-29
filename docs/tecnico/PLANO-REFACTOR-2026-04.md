# PLANO TÉCNICO DE REFATORAÇÃO — NISTIPRINT
**Versão:** 2026-04-23 (revisão definitiva)
**Escopo:** Arquitetura de canais e ingestão de pedidos, classificação Flex confiável, sync de status em lote, IA de personalização em lote.
**Premissa de simplificação:** A plataforma será modelada **primeiro para as regras da Nisti Print**. Multi-tenancy/parametrização excessiva fica para depois.

---

## 0. PRINCÍPIOS DE PROJETO (NÃO NEGOCIÁVEIS)

1. **Um marketplace = uma `installed_integration`.** "Canal de venda" deixa de ser entidade autônoma e passa a ser sinônimo de **instância instalada de marketplace** (ex.: Shopee Conta 01, Shopee Conta 02, ML Conta 01).
2. **Bling não é canal de venda.** É um agregador usado pela Nisti apenas para emissão de NF (1 conta Bling por CNPJ → 3 contas) e para receber webhooks dos marketplaces. Bling tem suas próprias `installed_integrations`, mas **regras logísticas e classificação Flex apontam para o marketplace**, não para o Bling.
3. **Mapeamento Bling → marketplace é direto via `shop_id`.** O campo `payload.loja.id` (também chamado `shop.id`) que o Bling envia em pedidos de marketplaces é o mesmo identificador exposto na API do marketplace (no caso da Shopee, é o `shop_id`). Esse valor é armazenado em `installed_integrations.config->>'bling_loja_id'` da instância marketplace correspondente. **Nada de tabela de mapeamento intermediária**.
4. **Fluxo de ingestão é linear**:
   ```
   webhook Bling → resolve instância Bling (por CNPJ)
                 → upsert em pedidos_bling
                 → resolve instância marketplace por payload.loja.id
                 → se Shopee: enriquece via API → upsert em pedidos_shopee
                 → classifica is_flex (regras + log explícito)
                 → upsert em pedidos
                 → dispara create_from_order (demanda)
   ```
5. **Logs do worker explicam cada decisão de classificação Flex.** Exemplo: `"order_sn=XYZ shipping_carrier='Entrega Rápida' matched_rule=10 → is_flex=true modalidade=FLEX"`.
6. **Sem triggers escondidos derivando `is_flex`.** Toda classificação acontece no worker, em código auditável.

---

## 1. ARQUITETURA DE DADOS DEFINITIVA

### 1.1 Tabelas centrais e seus papéis

| Tabela | Papel | Status |
|---|---|---|
| `installed_integrations` | Instâncias instaladas. **Esta é a entidade "canal de venda"** quando `module.tipo='marketplace'`. Quando `module.tipo='aggregator'`, é uma conta Bling (1 por CNPJ). | Existe — adicionar campos no `config` |
| `pedidos_bling` | Espelho fiel do payload Bling v3 por instância Bling. | Existe — corrigir uso |
| `pedidos_shopee` | Espelho fiel do payload Shopee v2 enriquecido. | Existe — corrigir preenchimento |
| `pedidos` | Centralizador normalizado. Tem FK para `pedidos_bling`, `pedidos_shopee` e `installed_integrations` (marketplace). | Existe — substituir `canal_venda_id` por `marketplace_integration_id` |
| `regras_logisticas_canal` | Regras de horário de corte, ponto de coleta, modalidade. | Renomear coluna `canal_venda_id` → `marketplace_integration_id` |
| `pontos_coleta` | Pontos físicos de coleta. | OK como está |
| `flex_classification_rules` | Regras parametrizadas de classificação Flex. | Trocar escopo de `canal_venda_id` para `marketplace_integration_id` |

### 1.2 Tabelas a APOSENTAR

| Tabela | Decisão |
|---|---|
| `canais_venda` | **Aposentar.** Conteúdo migra para `installed_integrations` de marketplace. |
| `channel_connections` | **Aposentar.** Mapeamento `bling_loja_id → marketplace_integration` passa a viver em `installed_integrations.config` da instância marketplace. |
| `integracao_canais_config` | **Deletar.** Duplicava `channel_connections`. |
| `loja_bling_shopee_map` | **Não criar.** Versões anteriores deste plano sugeriam — descartado. |
| `canal_modalidade_mapeamento` | **Aposentar.** `flex_classification_rules` cobre. |

### 1.3 Estrutura de `installed_integrations.config` para marketplace

Cada instância de marketplace passa a guardar TUDO no `config`:

```json
{
  "shop_id":       123456,
  "bling_loja_id": "123456",
  "partner_id":    20012345,
  "horario_coleta":     "13:00",
  "horario_corte":      "11:00",
  "ponto_coleta_id":    7,
  "is_flex_capable":    true,
  "color":              "#ee4d2d",
  "default_modalidade": "STANDARD"
}
```

**`bling_loja_id`** é a chave de mapeamento. Em geral é o mesmo valor do `shop_id` para Shopee, mas o campo é mantido separado porque outros marketplaces (ML, Amazon) usam IDs diferentes.

### 1.4 Estrutura de `installed_integrations.config` para Bling

```json
{
  "cnpj":            "13597000000XXX",
  "company_label":   "Bling Antiga",
  "client_id":       "...",
  "client_secret":   "..."
}
```

**Substitui** os hardcodes `BLING_ANTIGA_CNPJ = "13597"` e `BLING_NOVA_CNPJ = "54533"` em [bling_order_processing_service.py:23](packages/shared/nistiprint_shared/services/bling_order_processing_service.py#L23).

---

## 2. MIGRATION ÚNICA

**Arquivo CRIAR:** `supabase/migrations/20260424100000_arquitetura_definitiva.sql`

```sql
-- =============================================================
-- 1. PEDIDOS: substituir canal_venda_id por marketplace_integration_id
-- =============================================================
ALTER TABLE pedidos
    ADD COLUMN IF NOT EXISTS marketplace_integration_id INT
        REFERENCES installed_integrations(id),
    ADD COLUMN IF NOT EXISTS bling_integration_id INT
        REFERENCES installed_integrations(id),
    ADD COLUMN IF NOT EXISTS pedido_bling_id BIGINT
        REFERENCES pedidos_bling(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS pedido_shopee_id BIGINT
        REFERENCES pedidos_shopee(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS ix_pedidos_marketplace ON pedidos(marketplace_integration_id);
CREATE INDEX IF NOT EXISTS ix_pedidos_bling_inst   ON pedidos(bling_integration_id);

-- =============================================================
-- 2. INSTALLED_INTEGRATIONS: índice por bling_loja_id (marketplace)
-- =============================================================
CREATE INDEX IF NOT EXISTS ix_install_int_bling_loja_id
    ON installed_integrations ((config->>'bling_loja_id'))
    WHERE is_active = true;

CREATE INDEX IF NOT EXISTS ix_install_int_cnpj
    ON installed_integrations ((config->>'cnpj'))
    WHERE is_active = true;

-- =============================================================
-- 3. REGRAS LOGÍSTICAS: passar a apontar para marketplace
-- =============================================================
ALTER TABLE regras_logisticas_canal
    ADD COLUMN IF NOT EXISTS marketplace_integration_id INT
        REFERENCES installed_integrations(id);

-- Após backfill (item 6 abaixo), tornar a nova coluna NOT NULL e dropar a antiga:
-- ALTER TABLE regras_logisticas_canal DROP COLUMN canal_venda_id;

-- =============================================================
-- 4. FLEX RULES: já existe (vide migration 20260424000000); ajustar
-- =============================================================
ALTER TABLE flex_classification_rules
    ADD COLUMN IF NOT EXISTS marketplace_integration_id INT
        REFERENCES installed_integrations(id);

CREATE INDEX IF NOT EXISTS ix_flex_rules_marketplace
    ON flex_classification_rules(marketplace_integration_id, ativo);

-- =============================================================
-- 5. PEDIDOS_BLING / PEDIDOS_SHOPEE: garantir colunas
-- =============================================================
ALTER TABLE pedidos_bling
    ADD COLUMN IF NOT EXISTS situacao_id          INT,
    ADD COLUMN IF NOT EXISTS situacao_valor       INT,
    ADD COLUMN IF NOT EXISTS contato              JSONB,
    ADD COLUMN IF NOT EXISTS itens                JSONB,
    ADD COLUMN IF NOT EXISTS transporte           JSONB,
    ADD COLUMN IF NOT EXISTS intermediador_cnpj   TEXT,
    ADD COLUMN IF NOT EXISTS loja_id              BIGINT,
    ADD COLUMN IF NOT EXISTS raw_payload          JSONB,
    ADD COLUMN IF NOT EXISTS bling_integration_id INT
        REFERENCES installed_integrations(id);

CREATE INDEX IF NOT EXISTS ix_pedidos_bling_loja_id ON pedidos_bling(loja_id);
CREATE INDEX IF NOT EXISTS ix_pedidos_bling_inst    ON pedidos_bling(bling_integration_id);

ALTER TABLE pedidos_shopee
    ADD COLUMN IF NOT EXISTS shop_id             BIGINT,
    ADD COLUMN IF NOT EXISTS order_sn            TEXT,
    ADD COLUMN IF NOT EXISTS order_status        TEXT,
    ADD COLUMN IF NOT EXISTS buyer_username      TEXT,
    ADD COLUMN IF NOT EXISTS buyer_user_id       BIGINT,
    ADD COLUMN IF NOT EXISTS fulfillment_flag    TEXT,
    ADD COLUMN IF NOT EXISTS shipping_carrier    TEXT,
    ADD COLUMN IF NOT EXISTS package_list        JSONB,
    ADD COLUMN IF NOT EXISTS item_list           JSONB,
    ADD COLUMN IF NOT EXISTS recipient_address   JSONB,
    ADD COLUMN IF NOT EXISTS pay_time            TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS raw_payload         JSONB,
    ADD COLUMN IF NOT EXISTS enriched_at         TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS marketplace_integration_id INT
        REFERENCES installed_integrations(id);

CREATE INDEX IF NOT EXISTS ix_pedidos_shopee_shop_id     ON pedidos_shopee(shop_id);
CREATE INDEX IF NOT EXISTS ix_pedidos_shopee_order_sn    ON pedidos_shopee(order_sn);
CREATE INDEX IF NOT EXISTS ix_pedidos_shopee_buyer_user  ON pedidos_shopee(buyer_username);

-- =============================================================
-- 6. BACKFILL canais_venda → installed_integrations (marketplace)
-- =============================================================
-- Para cada linha em canais_venda, criar (se não existir) installed_integration
-- de tipo 'marketplace' com config preenchido a partir das colunas.
-- Executar em script Python (ver seção 5.4) por requerer lookup de modules e idempotência.

-- =============================================================
-- 7. REMOVER TRIGGERS LEGADOS DE FLEX
-- =============================================================
DROP TRIGGER  IF EXISTS trg_calcular_is_flex ON pedidos;
DROP FUNCTION IF EXISTS calcular_is_flex();

-- O trigger fn_snapshot_channel_on_insert deve ser reescrito SEM
-- a linha "NEW.is_flex := (NEW.channel_snapshot->>'flex')::boolean;".
-- Recriar a função preservando o restante do snapshot.

-- =============================================================
-- 8. SEED INICIAL DE FLEX RULES (regra global Shopee)
-- =============================================================
-- Apenas "entrega rápida" e variações são FLEX. Xpress NUNCA.
-- Regra global (sem marketplace_integration_id, sem canal_venda_id):
INSERT INTO flex_classification_rules
    (campo, operador, padrao, is_flex, modalidade, prioridade)
VALUES
    ('shipping_carrier',   'ILIKE_NORMALIZED', 'entrega rapida', true, 'FLEX',     10),
    ('servico_logistico',  'ILIKE_NORMALIZED', 'entrega rapida', true, 'FLEX',     10),
    ('shipping_carrier',   'ILIKE',            '%',              false, 'STANDARD', 9999);

-- =============================================================
-- 9. RPC PARA RESOLVER INSTÂNCIAS NO WORKER
-- =============================================================

-- 9.1 Resolve instância Bling pelo CNPJ do intermediador (ou do payload)
CREATE OR REPLACE FUNCTION find_bling_integration_by_cnpj(p_cnpj TEXT)
RETURNS SETOF installed_integrations AS $$
    SELECT *
      FROM installed_integrations ii
      JOIN integration_modules im ON im.id = ii.module_id
     WHERE im.tipo = 'aggregator'
       AND im.slug = 'bling'
       AND ii.is_active = true
       AND (ii.config->>'cnpj' = p_cnpj
            OR position(ii.config->>'cnpj' in p_cnpj) > 0)
     LIMIT 1;
$$ LANGUAGE sql STABLE;

-- 9.2 Resolve instância marketplace pelo bling_loja_id
CREATE OR REPLACE FUNCTION find_marketplace_by_bling_loja(p_loja_id TEXT)
RETURNS SETOF installed_integrations AS $$
    SELECT *
      FROM installed_integrations ii
      JOIN integration_modules im ON im.id = ii.module_id
     WHERE im.tipo = 'marketplace'
       AND ii.is_active = true
       AND ii.config->>'bling_loja_id' = p_loja_id
     LIMIT 1;
$$ LANGUAGE sql STABLE;
```

---

## 3. SERVIÇO DE CLASSIFICAÇÃO FLEX

**Arquivo AFETADO:** [packages/shared/nistiprint_shared/services/flex_classifier_service.py](packages/shared/nistiprint_shared/services/flex_classifier_service.py)

Mudanças:
1. Trocar parâmetro `canal_venda_id` por `marketplace_integration_id`.
2. Adicionar `logger.info(...)` explícito quando uma regra casa.
3. Adicionar `logger.info(...)` explícito quando cai no fallback.

```python
import logging
import unicodedata
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("flex_classifier")

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
    motivo: str   # explicação humana p/ log

def classify(
    db,
    fields: dict,
    marketplace_integration_id: Optional[int] = None,
    log_context: Optional[dict] = None,    # ex.: {'order_sn': '...', 'pedido_id': ...}
) -> FlexResult:
    ctx = log_context or {}
    rules = db.table('flex_classification_rules') \
        .select('*').eq('ativo', True) \
        .order('prioridade', desc=False).execute().data

    def matches(rule, value):
        if value is None:
            return False
        op, pat = rule['operador'], rule['padrao']
        if op == 'EQUALS':
            return value == pat
        if op == 'ILIKE':
            return pat == '%' or pat.replace('%', '').lower() in value.lower()
        if op == 'ILIKE_NORMALIZED':
            return _normalize(pat) in _normalize(value)
        return False

    # 1) Regras com escopo da instância marketplace
    if marketplace_integration_id is not None:
        for r in rules:
            if r.get('marketplace_integration_id') != marketplace_integration_id:
                continue
            val = fields.get(r['campo'])
            if matches(r, val):
                motivo = (f"{r['campo']}={val!r} casou regra #{r['id']} "
                          f"(scope=marketplace:{marketplace_integration_id})")
                logger.info("[flex] %s %s → is_flex=%s modalidade=%s",
                            ctx, motivo, r['is_flex'], r.get('modalidade'))
                return FlexResult(r['is_flex'], r.get('modalidade') or 'STANDARD', r['id'], motivo)

    # 2) Regras globais
    for r in rules:
        if r.get('marketplace_integration_id') is None:
            val = fields.get(r['campo'])
            if matches(r, val):
                motivo = (f"{r['campo']}={val!r} casou regra global #{r['id']}")
                logger.info("[flex] %s %s → is_flex=%s modalidade=%s",
                            ctx, motivo, r['is_flex'], r.get('modalidade'))
                return FlexResult(r['is_flex'], r.get('modalidade') or 'STANDARD', r['id'], motivo)

    # 3) Default
    motivo = (f"nenhuma regra casou para fields={fields!r} → STANDARD por default")
    logger.info("[flex] %s %s", ctx, motivo)
    return FlexResult(False, 'STANDARD', None, motivo)
```

---

## 4. FLUXO DE INGESTÃO REESCRITO

**Arquivo AFETADO:** [packages/shared/nistiprint_shared/services/bling_order_processing_service.py](packages/shared/nistiprint_shared/services/bling_order_processing_service.py)

### 4.1 Pseudo-código definitivo

```python
import logging
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.platform_drivers import shopee as shopee_driver
from nistiprint_shared.services import flex_classifier_service

logger = logging.getLogger("bling_order_processing")

def process_webhook(payload: dict, bling_integration_hint: int | None = None) -> dict:
    """
    Pipeline linear, idempotente.
    - payload: corpo do pedido Bling (já buscado da API com detalhes completos).
    - bling_integration_hint: quando o caller já sabe a instância Bling (ex.: webhook
      veio com header de identificação), evita lookup.
    """
    correlation = {
        'bling_id':    payload.get('id'),
        'numero':      payload.get('numero'),
        'numero_loja': payload.get('numeroLoja'),
    }
    logger.info("[ingest] start %s", correlation)

    # 1. Resolver instância Bling
    bling_inst = _resolve_bling_instance(payload, bling_integration_hint)
    correlation['bling_inst'] = bling_inst['id']
    logger.info("[ingest] bling_instance resolved id=%s cnpj=%s",
                bling_inst['id'], bling_inst['config'].get('cnpj'))

    # 2. UPSERT pedidos_bling (espelho do payload)
    pedido_bling_id = _upsert_pedido_bling(payload, bling_inst['id'])

    # 3. Resolver instância marketplace pela loja_id
    loja_id = str(payload.get('loja', {}).get('id') or '')
    marketplace_inst, pedido_shopee_id, shopee_data = None, None, None
    if loja_id:
        marketplace_inst = _resolve_marketplace_instance(loja_id)
        if marketplace_inst:
            correlation['marketplace_inst'] = marketplace_inst['id']
            logger.info("[ingest] marketplace resolved id=%s plataforma=%s nome=%s",
                        marketplace_inst['id'],
                        marketplace_inst.get('plataforma_slug'),
                        marketplace_inst.get('instance_name'))

            # 4. Enriquecimento via API marketplace (apenas Shopee no MVP)
            if marketplace_inst.get('plataforma_slug') == 'shopee':
                shopee_data = _fetch_shopee_detail(marketplace_inst,
                                                   payload.get('numeroLoja'))
                pedido_shopee_id = _upsert_pedido_shopee(
                    shopee_data,
                    marketplace_integration_id=marketplace_inst['id'],
                )
        else:
            logger.warning("[ingest] loja_id=%s sem instância marketplace mapeada", loja_id)

    # 5. Classificar Flex
    flex = flex_classifier_service.classify(
        supabase_db,
        fields={
            'servico_logistico': _volume_servico(payload),
            'shipping_carrier':  (shopee_data or {}).get('shipping_carrier'),
            'fulfillment_flag':  (shopee_data or {}).get('fulfillment_flag'),
        },
        marketplace_integration_id=(marketplace_inst or {}).get('id'),
        log_context=correlation,
    )

    # 6. UPSERT pedidos
    pedido_id = _upsert_pedido_master(
        payload,
        pedido_bling_id=pedido_bling_id,
        pedido_shopee_id=pedido_shopee_id,
        bling_integration_id=bling_inst['id'],
        marketplace_integration_id=(marketplace_inst or {}).get('id'),
        is_flex=flex.is_flex,
        modalidade=flex.modalidade,
    )
    logger.info("[ingest] pedido upserted id=%s is_flex=%s modalidade=%s",
                pedido_id, flex.is_flex, flex.modalidade)

    # 7. Encadear demanda
    from nistiprint_shared.services import demanda_producao_service
    demanda_producao_service.create_from_order(
        pedido_id=pedido_id,
        is_flex=flex.is_flex,
        modalidade_logistica=flex.modalidade,
        marketplace_integration_id=(marketplace_inst or {}).get('id'),
    )

    logger.info("[ingest] done %s", correlation)
    return {'pedido_id': pedido_id, 'is_flex': flex.is_flex, 'flex_motivo': flex.motivo}


# ---------- helpers ----------

def _resolve_bling_instance(payload, hint):
    if hint:
        row = supabase_db.table('installed_integrations') \
            .select('*').eq('id', hint).single().execute().data
        if row:
            return row
    cnpj = (payload.get('intermediador') or {}).get('cnpj') \
        or (payload.get('loja') or {}).get('cnpj')
    if not cnpj:
        raise ValueError("Não foi possível identificar instância Bling: CNPJ ausente")
    rows = supabase_db.rpc('find_bling_integration_by_cnpj',
                           {'p_cnpj': cnpj}).execute().data
    if not rows:
        raise LookupError(f"Nenhuma installed_integration Bling ativa para CNPJ={cnpj}")
    return rows[0]

def _resolve_marketplace_instance(loja_id: str):
    rows = supabase_db.rpc('find_marketplace_by_bling_loja',
                           {'p_loja_id': loja_id}).execute().data
    if not rows:
        return None
    inst = rows[0]
    # Anexar slug da plataforma para conveniência do caller
    mod = supabase_db.table('integration_modules') \
        .select('slug').eq('id', inst['module_id']).single().execute().data
    inst['plataforma_slug'] = (mod or {}).get('slug')
    return inst

def _fetch_shopee_detail(marketplace_inst, order_sn):
    cfg, cred = marketplace_inst['config'], marketplace_inst.get('credentials') or {}
    integration = {
        'config':       cfg,
        'credentials':  cred,
        'access_token': marketplace_inst.get('access_token') or cred.get('access_token'),
    }
    return shopee_driver.get_order_detail(integration, [order_sn])
```

### 4.2 Mudanças no driver Shopee

**Arquivo AFETADO:** [packages/shared/nistiprint_shared/services/platform_drivers/shopee.py](packages/shared/nistiprint_shared/services/platform_drivers/shopee.py)

Hoje `get_order_detail` ([linha 96](packages/shared/nistiprint_shared/services/platform_drivers/shopee.py#L96)) coloca tudo em `raw` e expõe poucos campos no DTO. Reescrever o `normalized_order` para incluir explicitamente:

```python
normalized_order = {
    "external_id":        order.get("order_sn", ""),
    "platform":           "shopee",
    "shop_id":            int(integration['config'].get('shop_id') or 0) or None,
    "order_status":       order.get("order_status"),
    "fulfillment_flag":   order.get("fulfillment_flag"),
    "shipping_carrier":   order.get("shipping_carrier")
                          or _carrier_from_packages(order.get("package_list")),
    "package_list":       order.get("package_list"),
    "item_list":          order.get("item_list"),
    "buyer_username":     order.get("buyer_username"),
    "buyer_user_id":      order.get("buyer_user_id"),
    "recipient_address":  order.get("recipient_address"),
    "pay_time":           _ts_to_iso(order.get("pay_time")),
    "create_time":        _ts_to_iso(order.get("create_time")),
    "total":              float(order.get("total_amount", 0)),
    "currency":           order.get("currency", "BRL"),
    "raw":                order,
}

def _carrier_from_packages(pkgs):
    if not pkgs:
        return None
    for p in pkgs:
        if p.get("shipping_carrier"):
            return p["shipping_carrier"]
    return None
```

**Trocar `print(...)` por `logger.debug(...)`** nas linhas 64-71 e 194-201.

### 4.3 Função `_upsert_pedido_shopee`

```python
def _upsert_pedido_shopee(shopee_data: dict, marketplace_integration_id: int) -> int:
    row = {
        'shop_id':           shopee_data.get('shop_id'),
        'order_sn':          shopee_data.get('external_id'),
        'order_status':      shopee_data.get('order_status'),
        'buyer_username':    shopee_data.get('buyer_username'),
        'buyer_user_id':     shopee_data.get('buyer_user_id'),
        'fulfillment_flag':  shopee_data.get('fulfillment_flag'),
        'shipping_carrier':  shopee_data.get('shipping_carrier'),
        'package_list':      shopee_data.get('package_list'),
        'item_list':         shopee_data.get('item_list'),
        'recipient_address': shopee_data.get('recipient_address'),
        'pay_time':          shopee_data.get('pay_time'),
        'raw_payload':       shopee_data.get('raw'),
        'enriched_at':       'now()',
        'marketplace_integration_id': marketplace_integration_id,
    }
    res = supabase_db.table('pedidos_shopee') \
        .upsert(row, on_conflict='order_sn').execute()
    return res.data[0]['id']
```

---

## 5. WORKER E LOGGING

### 5.1 Logger nomeado e formatter

**Arquivo AFETADO:** [apps/worker/worker_entrypoint.py](apps/worker/worker_entrypoint.py)

Configurar formatter explícito para o worker:

```python
import logging
LOG_FORMAT = "[%(asctime)s] %(levelname)s %(name)s %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

# Forçar nível INFO nos loggers do pipeline
for name in ("bling_order_processing", "flex_classifier",
             "shopee_driver", "demanda_producao"):
    logging.getLogger(name).setLevel(logging.INFO)
```

### 5.2 Pontos de log obrigatórios

| Etapa | Log |
|---|---|
| Início do processamento | `[ingest] start {correlation}` |
| Resolução Bling | `[ingest] bling_instance resolved id=… cnpj=…` |
| Upsert Bling | `[ingest] pedidos_bling upserted id=…` |
| Resolução marketplace | `[ingest] marketplace resolved id=… plataforma=… nome=…` ou `[ingest] loja_id=… sem instância mapeada` |
| Enriquecimento Shopee | `[shopee] order_detail fetched order_sn=… status=… shipping_carrier=… fulfillment_flag=…` |
| Classificação Flex | `[flex] {ctx} shipping_carrier='Entrega Rápida' casou regra #10 → is_flex=true modalidade=FLEX` (já incluso em §3) |
| Upsert pedidos | `[ingest] pedido upserted id=… is_flex=… modalidade=…` |
| Erro qualquer | `logger.exception(...)` com stack |

### 5.3 Tabela de auditoria opcional (recomendada)

```sql
CREATE TABLE IF NOT EXISTS pedido_ingest_log (
    id BIGSERIAL PRIMARY KEY,
    pedido_id BIGINT,
    bling_id  BIGINT,
    marketplace_integration_id INT,
    is_flex BOOLEAN,
    flex_motivo TEXT,            -- string explicativa do classificador
    matched_rule_id INT,
    raw_decision JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

Ao final de `process_webhook`, gravar uma linha. Permite rastrear "por que esse pedido virou Flex" diretamente no banco, sem `tail` em logs.

### 5.4 Script de migração canais_venda → installed_integrations

**Arquivo CRIAR:** `apps/ops/scripts/migrar_canais_para_marketplace.py`

```python
"""
Para cada linha em canais_venda, criar (ou localizar) installed_integration
de tipo 'marketplace' e popular config a partir das colunas + de channel_connections.

Idempotente: usa instance_name como chave; se já existir, apenas atualiza config.
Após rodar, repointa pedidos.canal_venda_id → marketplace_integration_id e zera
canais_venda (ou deixa marcada como migrated=true se preferir manter histórico).
"""
# Pseudo-código:
# 1. SELECT * FROM canais_venda WHERE ativo
# 2. Para cada canal:
#      cc = channel_connections WHERE channel_id=canal.id LIMIT 1
#      module_id = lookup integration_modules WHERE slug = plataforma.slug AND tipo='marketplace'
#      config = {
#         'shop_id': cc.aggregator_store_id,        # quando aplicável
#         'bling_loja_id': cc.aggregator_store_id,
#         'horario_coleta': canal.horario_coleta,
#         'color': canal.color,
#         'is_flex_capable': canal.flex,
#      }
#      UPSERT em installed_integrations (instance_name=canal.nome, module_id, config)
# 3. UPDATE pedidos SET marketplace_integration_id = X WHERE canal_venda_id = Y
# 4. UPDATE regras_logisticas_canal SET marketplace_integration_id = X WHERE canal_venda_id = Y
# 5. UPDATE flex_classification_rules SET marketplace_integration_id = X WHERE canal_venda_id = Y
```

Após validação manual, executar o `DROP COLUMN canal_venda_id` em segundo migration.

---

## 6. SYNC DE STATUS BLING EM LOTE

### 6.1 Endpoint
**Arquivo CRIAR:** `apps/api/routes/pedidos_sync.py`

```python
POST /api/v2/pedidos/sync-bling-status   { pedido_ids: [1,2,3,...] }   → 202 { batch_id }
GET  /api/v2/pedidos/sync-bling-status/<batch_id>                       → 200 { status, sucesso, falha }
```

### 6.2 Tabelas
```sql
CREATE TABLE IF NOT EXISTS sync_status_batches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pedido_ids BIGINT[] NOT NULL,
    total INT NOT NULL,
    sucesso INT DEFAULT 0,
    falha   INT DEFAULT 0,
    status  TEXT DEFAULT 'PENDENTE',  -- PENDENTE|RODANDO|CONCLUIDO|ERRO
    iniciado_em TIMESTAMPTZ DEFAULT NOW(),
    finalizado_em TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS sync_status_errors (
    id BIGSERIAL PRIMARY KEY,
    batch_id UUID REFERENCES sync_status_batches(id) ON DELETE CASCADE,
    pedido_id BIGINT NOT NULL,
    bling_id  BIGINT,
    erro      TEXT,
    tentado_em TIMESTAMPTZ DEFAULT NOW()
);
```

### 6.3 Task Celery
**Arquivo CRIAR:** `packages/shared/nistiprint_shared/services/bling_status_sync_service.py`

- Agrupar pedidos por `pedidos_bling.bling_integration_id`.
- Para cada grupo: usar token Bling da instância correspondente.
- `ThreadPoolExecutor(max_workers=3)` com sleep de ~333ms entre disparos (rate limit conservador 3 RPS).
- Falha individual grava em `sync_status_errors` e segue.
- Atualizar `pedidos_bling.situacao_id/valor` e propagar para `pedidos.situacao_pedido_id` via `integration_status_mappings`.
- Log: `[sync] batch=… pedido=… bling_id=… ok` ou `[sync] batch=… pedido=… erro=…`.

### 6.4 UI
- Checkbox em cada linha da listagem de pedidos.
- Botão "Atualizar status Bling" → POST + polling de progresso a cada 2s.

### 6.5 Aceitação
- 50 pedidos em <30s.
- Falhas isoladas em `sync_status_errors`.
- Sem efeitos colaterais (estoque, demanda, IA).

---

## 7. IA DE PERSONALIZAÇÃO EM LOTE (POOL SUPABASE)

### 7.1 Diagnóstico
- Legado usava `ThreadPoolExecutor(max_workers=10)` com MySQL próprio (pool grande).
- Novo usa `httpx` REST contra Supabase (singleton). Threads paralelas → `httpx.PoolTimeout` derruba lote.

### 7.2 Estratégia
**Fan-out via Celery** — uma task por pedido. Worker Celery dedicado `-c 4` na fila `ai_personalization`. Cada worker_process tem seu próprio `SupabaseDBService`, naturalmente serializando.

### 7.3 Tabelas de controle
```sql
CREATE TABLE IF NOT EXISTS execucoes_ai_batch (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    criado_em TIMESTAMPTZ DEFAULT NOW(),
    pedido_ids BIGINT[] NOT NULL,
    total INT NOT NULL,
    processados INT DEFAULT 0,
    sucesso INT DEFAULT 0,
    falha INT DEFAULT 0,
    status TEXT DEFAULT 'PENDENTE',
    finalizado_em TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS execucoes_ai_item (
    id BIGSERIAL PRIMARY KEY,
    batch_id UUID REFERENCES execucoes_ai_batch(id) ON DELETE CASCADE,
    pedido_id BIGINT NOT NULL,
    status TEXT NOT NULL,    -- OK|ERRO|IGNORADO
    erro TEXT,
    duracao_ms INT,
    criado_em TIMESTAMPTZ DEFAULT NOW()
);

CREATE OR REPLACE FUNCTION incrementar_batch_ia(
    p_batch_id UUID, p_sucesso INT, p_falha INT
) RETURNS VOID AS $$
DECLARE v_total INT; v_proc INT;
BEGIN
    UPDATE execucoes_ai_batch
       SET processados = processados + 1,
           sucesso     = sucesso + p_sucesso,
           falha       = falha + p_falha
     WHERE id = p_batch_id
    RETURNING total, processados INTO v_total, v_proc;
    IF v_proc >= v_total THEN
        UPDATE execucoes_ai_batch
           SET status='CONCLUIDO', finalizado_em=NOW()
         WHERE id=p_batch_id;
    END IF;
END;
$$ LANGUAGE plpgsql;
```

### 7.4 Tasks
**Arquivo AFETADO:** [packages/shared/nistiprint_shared/services/ai_personalization_service.py](packages/shared/nistiprint_shared/services/ai_personalization_service.py)

```python
@shared_task(name='services.ai_personalization.processar_batch')
def processar_batch_ia(batch_id):
    batch = supabase_db.table('execucoes_ai_batch').select('*') \
        .eq('id', batch_id).single().execute().data
    supabase_db.table('execucoes_ai_batch').update({'status':'RODANDO'}) \
        .eq('id', batch_id).execute()
    for pid in batch['pedido_ids']:
        processar_pedido_ia.apply_async(args=[batch_id, pid],
                                        queue='ai_personalization')

@shared_task(name='services.ai_personalization.processar_pedido',
             bind=True, max_retries=2, default_retry_delay=30, acks_late=True)
def processar_pedido_ia(self, batch_id, pedido_id):
    import time, httpx
    t0 = time.monotonic()
    status, erro = 'OK', None
    try:
        pedido = _load_pedido_com_itens(pedido_id)
        resultado = _run_ia_for_order(pedido)        # função do legado, já funciona individual
        _persistir_personalizacao(pedido, resultado)
    except httpx.PoolTimeout as e:
        raise self.retry(exc=e)
    except Exception as e:
        status, erro = 'ERRO', str(e)[:500]
    finally:
        supabase_db.table('execucoes_ai_item').insert({
            'batch_id': batch_id, 'pedido_id': pedido_id,
            'status': status, 'erro': erro,
            'duracao_ms': int((time.monotonic() - t0) * 1000),
        }).execute()
        supabase_db.rpc('incrementar_batch_ia', {
            'p_batch_id': batch_id,
            'p_sucesso': 1 if status == 'OK' else 0,
            'p_falha':   1 if status == 'ERRO' else 0,
        }).execute()
```

### 7.5 Filas dedicadas
**Arquivo AFETADO:** [apps/worker/celery_config.py](apps/worker/celery_config.py)

```python
task_queues = {
    'default':            {'exchange': 'default'},
    'ai_personalization': {'exchange': 'ai'},
    'bling_status_sync':  {'exchange': 'bling'},
}
task_routes = {
    'services.ai_personalization.*': {'queue': 'ai_personalization'},
    'services.bling_status_sync.*':  {'queue': 'bling_status_sync'},
}
```

`docker-compose.yml`:
```yaml
worker-ai:      command: celery -A apps.worker worker -Q ai_personalization -c 4
worker-bling:   command: celery -A apps.worker worker -Q bling_status_sync -c 2
worker-default: command: celery -A apps.worker worker -Q default            -c 8
```

### 7.6 Hardening do `SupabaseDBService`

**Arquivo AFETADO:** [packages/shared/nistiprint_shared/database/supabase_db_service.py](packages/shared/nistiprint_shared/database/supabase_db_service.py)

```python
import httpx
_httpx_client = httpx.Client(
    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    timeout=httpx.Timeout(30.0, connect=5.0),
)
# Passar para o supabase.create_client() via opções, se a versão suportar;
# caso contrário, usar como cliente alternativo nas RPCs críticas.
```

Circuit breaker simples: se 3× `PoolTimeout` em 30s, sleep global 5s antes da próxima request.

---

## 8. CHECKLIST POR ARQUIVO

| Arquivo | Ação |
|---|---|
| `supabase/migrations/20260424100000_arquitetura_definitiva.sql` | CRIAR (§2) |
| `packages/shared/nistiprint_shared/services/flex_classifier_service.py` | EDITAR — `marketplace_integration_id` + logs (§3) |
| `packages/shared/nistiprint_shared/services/bling_order_processing_service.py` | EDITAR — pipeline linear, remover hardcodes CNPJ, logs (§4) |
| `packages/shared/nistiprint_shared/services/platform_drivers/shopee.py` | EDITAR — expor campos no DTO, trocar `print` por logger (§4.2) |
| `packages/shared/nistiprint_shared/services/demanda_producao_service.py` | EDITAR — aceitar `marketplace_integration_id` em `create_from_order` |
| `packages/shared/nistiprint_shared/services/bling_status_sync_service.py` | CRIAR (§6) |
| `packages/shared/nistiprint_shared/services/ai_personalization_service.py` | EDITAR — fan-out Celery (§7.4) |
| `packages/shared/nistiprint_shared/services/redis_queue_tasks.py` | EDITAR — chamar `process_webhook` real, remover stub `só log` |
| `packages/shared/nistiprint_shared/services/webhook_tasks.py` | DELETAR helpers TODO ou simplificar |
| `packages/shared/nistiprint_shared/database/supabase_db_service.py` | EDITAR — httpx limits + circuit breaker (§7.6) |
| `apps/api/routes/pedidos_sync.py` | CRIAR (§6.1) |
| `apps/api/routes/personalizados.py` | EDITAR — endpoint batch (§7) |
| `apps/worker/worker_entrypoint.py` | EDITAR — formatter + níveis (§5.1) |
| `apps/worker/celery_config.py` | EDITAR — filas e routing (§7.5) |
| `apps/ops/scripts/migrar_canais_para_marketplace.py` | CRIAR (§5.4) |
| `apps/ops/scripts/backfill_pedidos_e_flex.py` | CRIAR — re-classifica pedidos antigos via classifier novo |
| `apps/frontend/src/pages/Pedidos/PedidosList.tsx` (ou equivalente) | EDITAR — UI sync Bling |
| `docker-compose.yml` | EDITAR — workers dedicados |

---

## 9. ORDEM DE EXECUÇÃO

```
F1. Migration arquitetura definitiva + RPCs                   1 dia
F2. Flex classifier (marketplace_integration_id + logs)       0.5 dia
F3. Driver Shopee (expor campos)                              0.5 dia
F4. Pipeline bling_order_processing reescrito                 1.5 dias
F5. Worker logging + pedido_ingest_log                        0.5 dia
F6. Script migrar_canais + backfill                           1 dia
F7. Sync status batch (endpoint + worker + UI)                2 dias
F8. IA personalização batch + filas + hardening               3 dias
F9. Limpeza: drop canais_venda, channel_connections,
   triggers legados, hardcodes CNPJ                          0.5 dia
                                              TOTAL ~10 dias
```

Caminho crítico: F1 → F2 → F4 → F5 → F6 → (F7 e F8 paralelos).

---

## 10. VALIDAÇÕES PÓS-DEPLOY

```sql
-- V1: Nenhum pedido novo sem marketplace_integration_id (origem marketplace)
SELECT COUNT(*) FROM pedidos
 WHERE created_at > NOW() - INTERVAL '24 hours'
   AND origem IN ('SHOPEE','MERCADOLIVRE','AMAZON','SHEIN','TIKTOK')
   AND marketplace_integration_id IS NULL;
-- Esperado: 0

-- V2: Nenhum "Xpress" classificado como Flex
SELECT COUNT(*) FROM pedidos p
  JOIN pedidos_shopee ps ON ps.id = p.pedido_shopee_id
 WHERE ps.shipping_carrier ILIKE '%xpress%'
   AND p.is_flex = true;
-- Esperado: 0

-- V3: Todo "Entrega Rápida" é Flex
SELECT COUNT(*) FROM pedidos p
  JOIN pedidos_shopee ps ON ps.id = p.pedido_shopee_id
 WHERE ps.shipping_carrier ILIKE '%entrega r%pida%'
   AND p.is_flex = false;
-- Esperado: 0

-- V4: Todos pedidos têm pedido_bling_id
SELECT COUNT(*) FROM pedidos
 WHERE pedido_bling_id IS NULL
   AND created_at > NOW() - INTERVAL '24 hours';
-- Esperado: 0

-- V5: Todo pedido Shopee tem pedido_shopee_id e buyer_username
SELECT COUNT(*) FROM pedidos p
  JOIN installed_integrations ii ON ii.id = p.marketplace_integration_id
  JOIN integration_modules im ON im.id = ii.module_id
 WHERE im.slug = 'shopee'
   AND (p.pedido_shopee_id IS NULL
        OR (SELECT buyer_username FROM pedidos_shopee WHERE id=p.pedido_shopee_id) IS NULL)
   AND p.created_at > NOW() - INTERVAL '24 hours';
-- Esperado: 0

-- V6: Triggers legados removidos
SELECT tgname FROM pg_trigger
 WHERE tgname LIKE '%flex%' AND NOT tgisinternal;
-- Esperado: vazio

-- V7: Logs explicativos auditáveis
SELECT pedido_id, is_flex, flex_motivo
  FROM pedido_ingest_log
 ORDER BY id DESC LIMIT 20;
-- Esperado: cada linha tem motivo legível, ex.:
--    "shipping_carrier='Entrega Rápida' casou regra global #10"
```

---

## 11. ANEXOS

### 11.1 Tabelas novas
- `sync_status_batches`, `sync_status_errors`
- `execucoes_ai_batch`, `execucoes_ai_item`
- `pedido_ingest_log`

### 11.2 Tabelas aposentadas (drop após backfill)
- `canais_venda`
- `channel_connections`
- `integracao_canais_config`
- `canal_modalidade_mapeamento`

### 11.3 RPCs novos
- `find_bling_integration_by_cnpj(text)`
- `find_marketplace_by_bling_loja(text)`
- `incrementar_batch_ia(uuid, int, int)`

### 11.4 Triggers removidos
- `trg_calcular_is_flex` + função `calcular_is_flex`
- Linha de override de `is_flex` em `fn_snapshot_channel_on_insert`

### 11.5 Referências
- [docs/tecnico/APIs/bling.md](APIs/bling.md) — payload Bling v3
- [docs/tecnico/APIs/shopee.md](APIs/shopee.md) — payload Shopee v2
- [docs/tecnico/MODELO-DADOS.md](MODELO-DADOS.md) — modelo atual

---

**FIM DO DOCUMENTO.**
