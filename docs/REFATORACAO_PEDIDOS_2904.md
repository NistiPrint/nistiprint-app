# Refatoração da ingestão de pedidos — 2026-04-29

Plano de execução para consolidar o ingest de pedidos em uma pipeline única,
corrigindo os bugs que estão deixando pedidos da Shopee na aplicação web sem
itens, sem cliente, sem canal e sem total.

Documento companheiro: o diagnóstico completo está nesta conversa (não
duplicado aqui). Aqui está só o plano de execução.

---

## 0. Glossário de identificadores (não confundir)

Existem três famílias de identificadores que andam juntas no fluxo. Nunca
misturar.

### 0.1 Identificadores que vêm do Bling

| Campo no payload Bling | Significado | Onde usamos hoje |
|---|---|---|
| `id` | ID interno do Bling para o pedido (numérico, estável dentro de uma instância Bling). | `pedidos_bling.bling_id` |
| `numero` | Número do pedido que o usuário do Bling vê em tela. **Não é único entre instâncias Bling diferentes** (Bling reinicia a sequência por conta). | `pedidos_bling.numero_pedido`, `pedidos.numero_pedido` (apenas exibição) |
| `numeroLoja` | ID do pedido no marketplace de origem (ex.: `order_sn` da Shopee). Vazio para pedidos criados direto no Bling. | `pedidos_bling.numero_loja`, `pedidos.codigo_pedido_externo` |
| `loja.id` | ID da loja Bling. Para pedidos de marketplace, casa com o `shop_id` do marketplace (Shopee). | `pedidos_bling.loja_id`, chave para resolver `marketplace_integration_id` |
| `intermediador.cnpj` | CNPJ da empresa Bling (instância Bling). | usado para resolver `bling_integration_id` |

### 0.2 Identificadores que vêm do marketplace (Shopee)

| Campo Shopee | Significado | Onde usamos |
|---|---|---|
| `order_sn` | ID do pedido no Shopee. Igual ao `numeroLoja` do Bling. | `pedidos_shopee.codigo_pedido` / `order_sn` |
| `shop_id` | ID da loja Shopee. Igual ao `loja.id` do Bling. | `pedidos_shopee.shop_id` |
| `buyer_username`, `buyer_user_id` | Identificação do comprador na Shopee. | `pedidos_shopee.buyer_username` / `buyer_user_id` |

### 0.3 Identificadores **internos** do nosso sistema

| Coluna | Significado |
|---|---|
| `pedidos.id` | PK interna do pedido normalizado. **Esse é o ID que circula no resto da aplicação** (demandas, eventos, impressões, etc.). |
| `pedidos.uuid_pedido` | UUID alternativo do pedido (legado, manter). |
| `pedidos.codigo_pedido_externo` | Chave de unicidade externa do pedido. Convenção: `numeroLoja` quando vier do marketplace, senão `BLING-{bling_id}` (NÃO `BLING-{numero}`, porque `numero` colide entre instâncias Bling). |
| `pedidos.numero_pedido` | Espelho de `payload.numero` do Bling. Apenas para exibição amigável. **Não é unique** (já foi removido — ver migration `20260327000000_remove_unique_pedidos_numero_pedido.sql`). |
| `pedidos_bling.id` | PK interna da linha de espelho do payload Bling. |
| `pedidos_bling.bling_id` | `payload.id` do Bling. Será UNIQUE após a migration. |
| `pedidos_shopee.id` | PK interna do espelho enriquecido Shopee. |
| `pedidos_shopee.codigo_pedido` | `order_sn` Shopee. Já é UNIQUE. |
| `pedidos.pedido_bling_id` | FK para `pedidos_bling.id`. |
| `pedidos.pedido_shopee_id` | FK para `pedidos_shopee.id`. NULL para pedidos não-Shopee. |
| `pedidos.bling_integration_id` | FK para `installed_integrations` (a instância Bling que entregou o pedido). |
| `pedidos.marketplace_integration_id` | FK para `installed_integrations` (a instância marketplace = "canal de venda" novo). |

> Regra de ouro: nunca usar `numero` do Bling como chave única; nunca tratar
> `bling_id` como visível ao usuário; nunca confundir `pedidos.id` (interno)
> com `pedidos_bling.bling_id` (externo).

---

## 1. Objetivo da refatoração

1. Pipeline única para todo pedido novo/atualizado:
   `webhook Redis → fetch detalhe Bling → upsert pedidos_bling → resolve marketplace → (se Shopee) enriquece → upsert pedidos_shopee → upsert pedidos → upsert itens_pedido → cria/atualiza demanda`.
2. `pedidos` passa a ter, sozinho, todos os campos que a tela precisa exibir
   (cliente, total, datas, Flex, marketplace, status). Tela não precisa mais
   ler `pedidos_bling` ou `pedidos_shopee`.
3. `pedidos_bling` e `pedidos_shopee` continuam existindo só como espelho
   bruto (auditoria e re-processamento).
4. Aposentar a pipeline paralela `order_sync_service.sync_bling_order` /
   `sync_shopee_order` e a chamada extra a `MarketplaceEnrichmentService`
   dentro de `order_service.upsert_order`.

---

## 2. Mudanças de schema

### 2.1 Migration nova: `supabase/migrations/20260429000000_pedidos_ingest_consolidacao.sql`

```sql
-- 1. UNIQUE em pedidos_bling.bling_id (sem isso, on_conflict='bling_id'
--    do worker quebra com 42P10 - "no unique or exclusion constraint
--    matching the ON CONFLICT specification").
ALTER TABLE public.pedidos_bling
    DROP CONSTRAINT IF EXISTS pedidos_bling_numero_pedido_key;
ALTER TABLE public.pedidos_bling
    ADD CONSTRAINT pedidos_bling_bling_id_key UNIQUE (bling_id);
-- numero_pedido deixa de ser UNIQUE global porque o mesmo `numero` pode
-- aparecer em instâncias Bling diferentes. Se for necessário garantir,
-- criar UNIQUE (bling_integration_id, numero_pedido) em fase posterior
-- após backfill.

-- 2. Garantir colunas em pedidos que a tela já consome mas o ingest
--    novo ainda não preenche. (Várias já existem por migrations anteriores;
--    repetimos com IF NOT EXISTS por idempotência.)
ALTER TABLE public.pedidos
    ADD COLUMN IF NOT EXISTS cliente_documento  varchar(20),
    ADD COLUMN IF NOT EXISTS cliente_telefone   varchar(50),
    ADD COLUMN IF NOT EXISTS cliente_email      varchar(255),
    ADD COLUMN IF NOT EXISTS data_limite_envio  timestamptz,
    ADD COLUMN IF NOT EXISTS servico_logistico  varchar(255),
    ADD COLUMN IF NOT EXISTS buyer_username     varchar(255),
    ADD COLUMN IF NOT EXISTS shipping_carrier   varchar(255),
    ADD COLUMN IF NOT EXISTS message_to_seller  text,
    ADD COLUMN IF NOT EXISTS status_original    varchar(50);

-- 3. (Opcional) Confirmar UNIQUE em pedidos.codigo_pedido_externo (já existe).
--    Não recria.

-- 4. Tabela de auditoria pedido_ingest_log (já criada na migration
--    'arquitetura_definitiva'; só garantir).
```

### 2.2 Sem mudança destrutiva nesta fase
- Não dropar `canal_venda_id` em `pedidos`. O ingest novo passa a preencher
  os DOIS (`canal_venda_id` derivado de `channel_connections.channel_id` +
  `marketplace_integration_id`) até a tela estar 100% migrada.
- Não dropar `canais_venda` ainda. Plano dela está em
  `PLANO-REFACTOR-2026-04.md`.

---

## 3. Mudanças de código

### 3.1 `bling_order_processing_service.process_webhook` (pipeline única)

Arquivo: `packages/shared/nistiprint_shared/services/bling_order_processing_service.py`

**Mantém** os passos atuais de resolução de instância Bling, fetch detalhe,
resolução de marketplace, classificação Flex e criação de demanda.

**Corrige**:

1. `_upsert_pedido_bling`: trocar `on_conflict='bling_id'` (já fica correto
   após a migration) e adicionar `bling_integration_id` no `data`. Conferir
   que `numero_pedido` é gravado como `str(payload['numero'])` (NÃO mexer no
   nome — segue padrão de coluna existente; semanticamente é "número de
   exibição do pedido no Bling").
2. `_upsert_pedido_shopee`: passa a gravar **todas** as colunas novas
   (`shop_id, order_sn, order_status, buyer_username, buyer_user_id,
   fulfillment_flag, shipping_carrier, package_list, item_list,
   recipient_address, pay_time, raw_payload, enriched_at,
   marketplace_integration_id`) usando os campos retornados pelo driver
   Shopee. Manter `codigo_pedido` (= `order_sn`) como chave de upsert.
3. **Reescrever `_upsert_pedido_master`** para popular todos os campos da
   tela:

```python
def _upsert_pedido_master(payload, *,
                         pedido_bling_id, pedido_shopee_id,
                         bling_integration_id, marketplace_integration_id,
                         canal_venda_id,           # derivado de channel_connections
                         is_flex, modalidade,
                         shopee_data,              # dict ou None
                         ):
    # Identificadores
    bling_id      = payload.get('id')                          # ID interno Bling
    bling_numero  = str(payload.get('numero') or '')           # número exibido
    numero_loja   = payload.get('numeroLoja')                  # ID marketplace
    codigo_externo = numero_loja or f"BLING-{bling_id}"

    # Cliente (sempre do Bling — fonte canônica)
    contato = payload.get('contato') or {}

    # Datas
    data_venda          = clean_date(payload.get('data'))
    data_limite_envio   = clean_date(
        (shopee_data or {}).get('ship_by_date')
        or payload.get('dataPrevista')
    )

    # Logística
    transporte = payload.get('transporte') or {}
    volumes    = transporte.get('volumes') or []
    servico    = volumes[0].get('servico') if volumes else None

    # Status interno
    situacao_pedido_id = _resolve_situacao_interna(
        bling_integration_id,
        payload.get('situacao', {}).get('id'),
    )

    data = {
        'numero_pedido':              bling_numero,        # NÃO é unique
        'codigo_pedido_externo':      codigo_externo,      # UNIQUE
        'origem':                     'BLING',
        'pedido_bling_id':            pedido_bling_id,
        'pedido_shopee_id':           pedido_shopee_id,
        'bling_integration_id':       bling_integration_id,
        'marketplace_integration_id': marketplace_integration_id,
        'canal_venda_id':             canal_venda_id,
        'situacao_pedido_id':         situacao_pedido_id,
        'status_original':            str(payload.get('situacao', {}).get('id') or ''),

        # Cliente
        'cliente_nome':               contato.get('nome'),
        'cliente_documento':          contato.get('numeroDocumento'),
        'cliente_telefone':           contato.get('telefone') or contato.get('celular'),
        'cliente_email':              contato.get('email'),
        'informacoes_cliente':        contato,             # JSONB completo

        # Financeiro
        'total_pedido':               safe_float(payload.get('total')),
        'moeda':                      'BRL',

        # Datas
        'data_venda':                 data_venda,
        'data_limite_envio':          data_limite_envio,

        # Logística / Flex
        'servico_logistico':          servico,
        'is_flex':                    is_flex,
        'modalidade_logistica':       modalidade,

        # Marketplace (preenchido só se houver enriquecimento)
        'buyer_username':             (shopee_data or {}).get('buyer_username'),
        'shipping_carrier':           (shopee_data or {}).get('shipping_carrier'),
        'message_to_seller':          (shopee_data or {}).get('raw', {}).get('message_to_seller'),

        'updated_at':                 now_iso(),
    }
    # filtra None para não sobrescrever em update
    data = {k: v for k, v in data.items() if v is not None}

    res = supabase_db.table('pedidos').upsert(
        data, on_conflict='codigo_pedido_externo'
    ).execute()
    return res.data[0]['id']
```

4. **Reescrever `_upsert_itens_pedido`** para usar `vinculos_bling.codigo_bling`
   (o cadastro real de mapeamento) em vez de `produtos.sku`:

```python
def _upsert_itens_pedido(pedido_id, itens_bling):
    if not pedido_id or not itens_bling:
        return
    supabase_db.table('itens_pedido').delete().eq('pedido_id', pedido_id).execute()
    rows = []
    for it in itens_bling:
        codigo = it.get('codigo')                          # SKU vendido
        produto_bling_id = (it.get('produto') or {}).get('id')
        produto_id = _resolve_produto_interno(codigo, produto_bling_id)
        rows.append({
            'pedido_id':       pedido_id,
            'produto_id':      produto_id,
            'sku_externo':     codigo,
            'descricao':       it.get('descricao'),
            'quantidade':      safe_float(it.get('quantidade'), 1.0),
            'preco_unitario':  safe_float(it.get('valor')),
            'subtotal':        safe_float(it.get('valor'))
                               * safe_float(it.get('quantidade'), 1.0),
            'updated_at':      now_iso(),
        })
    supabase_db.table('itens_pedido').insert(rows).execute()


def _resolve_produto_interno(codigo, produto_bling_id):
    # 1ª tentativa: vinculos_bling por bling_id
    if produto_bling_id:
        v = (supabase_db.table('vinculos_bling')
             .select('produto_id')
             .eq('codigo_bling', str(produto_bling_id))
             .limit(1).execute().data)
        if v:
            return v[0]['produto_id']
    # 2ª tentativa: vinculos_bling por SKU
    if codigo:
        v = (supabase_db.table('vinculos_bling')
             .select('produto_id')
             .eq('codigo_bling', str(codigo))
             .limit(1).execute().data)
        if v:
            return v[0]['produto_id']
    # 3ª tentativa: produtos por SKU
    if codigo:
        p = (supabase_db.table('produtos')
             .select('id')
             .eq('sku', codigo)
             .limit(1).execute().data)
        if p:
            return p[0]['id']
    return None
```

5. **Resolver `canal_venda_id`** pela `channel_connection` ativa (mesmo lookup
   da resolução de marketplace), e gravar nas duas colunas até `canal_venda_id`
   ser aposentado.

6. **Personalizado**: manter chamada a `personalized_order_identifier` após
   o upsert do `pedidos`, igual hoje.

7. **Auditoria**: gravar `pedido_ingest_log` (tabela já existe) com
   `pedido_id, bling_id, marketplace_integration_id, is_flex, flex_motivo,
   matched_rule_id`.

### 3.2 Aposentar `order_sync_service.sync_bling_order` / `sync_shopee_order`

- Remover chamadas externas a esses métodos. Os usos atuais estão em:
  - `pedidos_bling_import_service._sync_bling_order_phase1` →
    substituir por `process_webhook(full_order, bling_integration_hint=...)`.
  - `pedidos_bling_import_service._enrich_from_marketplace` → não chamar
    mais; o enriquecimento agora é feito dentro do `process_webhook`.
- Não apagar o arquivo no primeiro PR — só remover as chamadas e marcar
  o módulo como deprecated. Apagar fisicamente em PR posterior, depois
  de confirmar que nada mais importa.

### 3.3 Fetch periódico vira "rede de segurança" sobre o Redis

Arquivo: `packages/shared/nistiprint_shared/services/pedidos_bling_import_service.py`

Em vez de chamar `order_sync_service` direto, lista pedidos no Bling e
publica cada item na fila Redis com o mesmo formato do webhook (apenas o
header com `id`/`numero`/`numeroLoja` + `companyId`). O worker consome
naturalmente.

```python
def run_fetch_pedidos_em_andamento(...):
    ...
    for cfg in configs:
        ...
        for o in orders:
            payload = {
                'data': {'id': o['id'], 'numero': o.get('numero'),
                         'numeroLoja': o.get('numeroLoja')},
                'companyId': cfg.get('bling_company_id'),
            }
            redis_client.rpush(BLING_WEBHOOK_QUEUE, json.dumps(payload))
```

Vantagens: uma fonte única, sem código duplicado; idempotente (worker já
deduplica por `bling_id` no upsert).

### 3.4 `order_service.upsert_order` (legado consumido por outros lugares?)

- Remover a chamada interna a `MarketplaceEnrichmentService`
  (`packages/shared/nistiprint_shared/services/order_service.py:206`).
- Tirar as proteções "uma vez Flex sempre Flex" e "não sobrescrever buyer
  vazio" — a fonte de verdade do Flex passa a ser o `flex_classifier_service`
  rodando no ingest.
- Verificar callers restantes (planilha de pedidos, import manual). Se
  algum precisar, redirecionar para `process_webhook` ou para uma função
  pública nova `ingest_bling_order(payload, bling_integration_id)` extraída
  de `process_webhook`.

### 3.5 Consumidor Redis

Arquivo: `packages/shared/nistiprint_shared/services/redis_queue_tasks.py`

Sem mudança funcional. Apenas garantir que o `data.get('data')` continua
sendo passado ao `process_webhook` e o `companyId` é repassado.

---

## 4. Frontend / API

Sem mudança nesta fase. As rotas já leem `pedidos` + joins certos
(`marketplace_integration`, `canal_venda`, `itens_pedido`,
`vinculos_integracao_pedido`). Vão voltar a exibir tudo assim que a
pipeline única popular as colunas.

Conferências pós-implementação:
- `apps/api/routes/pedidos.py` `get_pedido_detalhe`: cliente, financeiro,
  datas, logística, itens devem aparecer.
- RPC `list_pedidos_filtrados` deve trazer `marketplace_*` populado para
  pedidos de marketplace.

---

## 5. Backfill

Após o deploy:

1. Rodar `run_fetch_pedidos_em_andamento(dias=14)` para todas as instâncias
   Bling ativas. Como agora é "lista + enfileira", isso vai re-disparar o
   ingest unificado para todos os pedidos recentes.
2. Spot-check em 5 pedidos Shopee e 5 pedidos não-Shopee:
   - `pedidos.codigo_pedido_externo` correto (numeroLoja vs `BLING-{id}`).
   - `pedidos_bling`, `pedidos_shopee` com FKs preenchidas em `pedidos`.
   - `itens_pedido` populados, com `produto_id` quando há vínculo.
   - Cliente, total, datas, Flex, marketplace na tela.

---

## 6. Ordem de execução / PRs

1. **PR-1 — Schema**: aplicar a migration
   `20260429000000_pedidos_ingest_consolidacao.sql`. Sem mudança de código.
   Deploy em produção.
2. **PR-2 — Pipeline única**: reescrever `_upsert_pedido_master`,
   `_upsert_itens_pedido`, `_upsert_pedido_shopee`, e fazer o fetch
   periódico publicar no Redis (3.3). Remover chamadas a
   `order_sync_service.sync_bling_order`/`sync_shopee_order` e à
   `MarketplaceEnrichmentService`. Não apagar arquivos.
3. **PR-3 — Backfill**: script/endpoint para re-disparar o fetch de N dias.
4. **PR-4 — Limpeza**: apagar `order_sync_service.sync_bling_order`,
   `sync_shopee_order`, `_save_to_shopee_table`, e o que mais ficou órfão.
   Atualizar docs (`ARQUITETURA.md`, `MODELO-DADOS.md`).

---

## 7. Critérios de aceitação

- [ ] Webhook Bling de pedido novo cria 1 linha em `pedidos`, 1 em
      `pedidos_bling`, N em `itens_pedido`, e (se Shopee) 1 em
      `pedidos_shopee`. Todas com FKs corretas.
- [ ] Tela de detalhe do pedido exibe cliente, telefone, e-mail, total,
      data de venda, data limite de envio, serviço logístico, marketplace
      (com cor e nome), Flex e itens com descrição/qtd/preço.
- [ ] Mesmo pedido recebido duas vezes via webhook não duplica linhas em
      nenhuma das três tabelas (idempotência por `pedidos_bling.bling_id`,
      `pedidos_shopee.codigo_pedido` e `pedidos.codigo_pedido_externo`).
- [ ] Pedido fora da Shopee (ex.: criado direto no Bling) é exibido com
      `codigo_pedido_externo = BLING-{bling_id}`, sem `pedido_shopee_id`,
      sem `marketplace_integration_id`, com `origem='BLING'`.
- [ ] Fetch periódico não chama mais `order_sync_service` — só enfileira
      no Redis. Logs do worker mostram um único caminho de processamento.
- [ ] Tabelas `pedidos_bling` e `pedidos_shopee` continuam servindo de
      auditoria (raw payload preservado).
