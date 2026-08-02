# Assessment de Aderência e Maturidade — Pontos Críticos NistiPrint

**Data:** 01/08/2026
**Escopo:** repositório `nistiprint-app` (monorepo) + banco Supabase de produção `nistiprint-supabase` (`cfknrplrqvyirjxovuvi`)
**Método:** leitura de código-fonte (serviços, rotas, migrations, frontend) cruzada com o estado real dos dados em produção (117 tabelas, contagens, distribuições e logs de execução)

---

## 1. Sumário executivo

O sistema tem **um projeto muito acima da sua operação**. A arquitetura, os contratos e as camadas de domínio estão em nível de maturidade alto — há especificação formal versionada (`docs/specs/` com governance, contracts e quality), separação limpa de camadas (drivers de provider → observações de domínio → decisão canônica → projeção), léxico de status provider-agnóstico, auditoria por estágio de ingest e ~40 testes automatizados na fronteira de integrações.

Porém, **a maior parte dos módulos a jusante do ingest não está sendo exercida em produção**. Estoque, produção, IA de personalização e coleta parcial têm modelo de dados completo, motores implementados e endpoints prontos — e **zero linhas** nas tabelas correspondentes.

| Dimensão | Nota (0–5) | Leitura |
|---|---|---|
| **Aderência de projeto** (o desenho cobre o requisito?) | **4,2** | Muito boa. Praticamente todo ponto crítico tem modelo e serviço dedicados |
| **Maturidade operacional** (funciona hoje, com dados reais?) | **1,9** | Baixa. Metade da cadeia de valor nunca saiu do estado inicial |
| **Gap de execução** | **2,3** | O maior risco do sistema não é técnico de desenho — é de ativação |

**Escala usada:** 0 Inexistente · 1 Inicial · 2 Repetível · 3 Definido · 4 Gerenciado · 5 Otimizado

---

## 2. Scorecard consolidado

| # | Ponto crítico | Projeto | Operação | Risco |
|---|---|:---:|:---:|:---:|
| 1 | Identificação do pedido ao marketplace de origem | 4,5 | 3,0 | 🟠 Médio-alto |
| 2 | Controle de estado dos pedidos | 5,0 | 4,0 | 🟢 Baixo |
| 3 | Identificação de itens personalizados | 4,0 | 3,5 | 🟡 Médio |
| 4 | Associação pedido Shopee ↔ comprador ↔ chat | 3,5 | **1,0** | 🔴 **Crítico** |
| 5 | IA para extração de nomes personalizados | 4,0 | **0,5** | 🔴 **Crítico** |
| 6 | Formas de envio, horários de corte e alternativas | 4,0 | 1,5 | 🟠 Médio-alto |
| 7 | Agrupamento logístico de pedidos em demanda | 4,0 | 1,5 | 🟠 Médio-alto |
| 8 | Acompanhamento da produção com rastreabilidade | 4,0 | **0,5** | 🔴 **Crítico** |
| 9 | Reconciliação de estoque | 4,5 | **0,0** | 🔴 **Crítico** |
| 10 | Geração do PDF da demanda | 2,5 | 2,0 | 🟡 Médio |
| 11 | Geração de NF no ERP correto | 4,0 | 3,0 | 🟡 Médio |
| 12 | Registro de coleta parcial | 3,5 | **0,5** | 🟠 Médio-alto |

---

## 3. Detalhamento por ponto crítico

### 3.1 Identificação do pedido ao marketplace de origem — Projeto 4,5 · Operação 3,0

**O que existe.** O desenho é sólido e multi-camada:

- `erp_marketplace_links` (10 linhas) — vínculo ERP ↔ marketplace com `erp_store_id` (código de loja Bling), `process_webhooks`, `ingest_origin_mode` (`erp_bling` | `marketplace_direct`) e `nf_emission_mode`
- `channel_connections` (10 linhas) — vínculo canal ↔ integração, declarado na migration como substituto de `integracao_canais_config`
- `integration_resolution_service` — índices em memória (TTL 60s) resolvendo por `shop_id`, `bling_loja_id`, `company_id`, `cnpj`, com escopo opcional por instância Bling
- `marketplace_account_identity` — normalização de identidade por provider (`shop_id` Shopee, `user_id` ML, `seller_id` Amazon) com aliases e campos legados
- `pedido_integration_refs` (12.614 linhas) e `entity_correlation_mapping` (333) — rastreabilidade de referências cruzadas
- `pedido_ingest_log` (10.201 linhas) com estágios nomeados: `received` → `resolve_bling_instance` → `fetch_bling` → `upsert_bling` → `resolve_marketplace` → `resolve_canal_venda` → `classify_flex` → `classify_fulfillment` → `upsert_pedido` → `detect_personalizado` → `done`

Isso resolve o requisito de origem independente do caminho de ingest: 4.467 pedidos Shopee entraram via Bling e 1.530 via API direta, todos com `marketplace_module_id = shopee`.

**Lacunas medidas.**

| Evidência | Impacto |
|---|---|
| **3 modelos de vínculo coexistindo** (`erp_marketplace_links`, `channel_connections`, `integracao_canais_config` com 7 linhas) | Fonte de verdade ambígua; o `_sync_channel_connection` mantém dois em espelho por código, não por constraint |
| **2 links com `marketplace_integration_id = NULL`** (`amazon_fulfillment`/ERP 1 e `mercadolivre`/ERP 3) | Esses caminhos não resolvem instância de marketplace; são exatamente os 2 links sem par em `channel_connections` (drift confirmado) |
| **1.596 `pending_order_reconciliations` com `reason = erp_reference_pending`**, acumulados entre 29/07 e 01/08 | Backlog crescente de pedidos sem referência ERP resolvida — bloqueia impressão e NF |
| **685 pedidos (9,6%) sem `erp_integration_id`** e **1.669 sem `erp_order_id`** | Não é possível emitir NF nem imprimir para essa fatia |
| **313 pedidos Mercado Livre (100%) sem `canal_venda_id`** | O estágio `resolve_canal_venda` não roda no ingest direto ML; quebra qualquer agrupamento por canal |
| `shop_id_shopee` **nulo em 100%** dos pedidos | Coluna morta; a identidade real vive em `marketplace_integration_id` |

**Veredito.** O requisito está atendido no desenho e majoritariamente na prática, mas com **drift de configuração** e um **backlog de reconciliação que cresce mais rápido do que é drenado**.

---

### 3.2 Controle de estado dos pedidos — Projeto 5,0 · Operação 4,0

**Este é o melhor componente do sistema.** `order_status_decision.py` implementa as camadas [B] e [C] do contrato `docs/specs/03-contracts/canonizacao-status-pedido.md`, com uma regra explícita no próprio docstring: *"Se aparecer aqui um `if provider == ...`, a regra está no lugar errado."*

Elementos de qualidade real:

- `DomainObservation` / `DecisionContext` / `CanonicalDecision` — fatos brutos separados da decisão
- `order_status_lexicon` (455 linhas) + `integration_status_mappings` (93 linhas em banco) — tradução por dado, não por código
- Guardas de terminalidade e não-regressão, precedência de pagamento (`PAYMENT_PRECEDENCE`), distinção cancelamento × devolução via `shipped_at`, tratamento de reembolso parcial
- `marketplace_order_transitions` (3.858 linhas) com decisão auditada

**Decisões reais registradas em produção:**

| Decisão | Shopee | Mercado Livre |
|---|---:|---:|
| `applied` | 2.505 | 333 |
| `ignored_regression` | 528 | 277 |
| `external_state_only` | 191 | — |
| `ignored_stale` | — | 11 |
| `unmapped` | 14 | — |

As 805 regressões corretamente ignoradas são a prova de que a guarda funciona — sem ela, esses eventos teriam corrompido o estado.

**Lacunas.**

- ~~**`marketplace_order_effects`: 260 registros, 100% `pending`**~~ → **resolvido em 02/08.** Com o beat reiniciado, os 262 efeitos foram processados. Ver §4.4.
- 14 transições `unmapped` (Shopee) sem processo de triagem visível.
- **Correção do assessment:** `eventos_pedido` **não é tabela morta.** Ela é escrita pelo RPC `process_marketplace_order_effect`, que estava parado — hoje tem 262 linhas (86 cancelamentos + 176 devoluções). Quem continua sem uso é `transicoes_situacao` (0 linhas), coexistindo com `marketplace_order_transitions` (3.858), que é a fonte real.
- Situação interna **"Produzido" com 0 pedidos** — o estado que faria a ponte entre produção e expedição nunca é atingido.
- **Achado novo (02/08): 398 pedidos cancelados estavam vinculados a demandas em RASCUNHO.** O RPC só alertava demandas já publicadas, então os 262 efeitos foram marcados `processed` com **zero alertas** — sucesso silencioso sobre um caso não coberto. Se qualquer rascunho fosse publicado, a produção receberia pedidos cancelados. Corrigido e limpo (§4.7).

---

### 3.3 Identificação de itens personalizados — Projeto 4,0 · Operação 3,5

**O que existe.** `personalized_order_identifier.py` com cascata de custo crescente, documentada no próprio módulo:

1. Descrição do item contém `"personaliza"` — sem chamada de API
2. Nome do produto contém `"personaliza"` — chamada Bling se não cacheado
3. Campo customizado do produto = true — via `erp_marketplace_links.get_custom_field_id()`

Com cache interno de produtos e batch lookup por IDs únicos. Flag persistida em dois níveis: `pedidos.personalizado` e `itens_pedido.personalizado`. Coberto por `test_personalized_order_identifier.py` e `test_personalized_classification_service.py`.

**Números reais:** 4.810/7.140 pedidos (67,4%) e 4.892/7.248 itens marcados como personalizados. O estágio `detect_personalizado/success` aparece 332× no ingest log.

**Lacunas.**

- A cascata **depende do campo customizado do Bling**. No ingest `marketplace_direct` (Shopee e ML hoje), esse caminho não existe — restam apenas as heurísticas de string.
- Heurística `contains("personaliza")` é frágil a variações de cadastro e não tem métrica de precisão/recall.
- Não há **revisão ou override manual auditável** da classificação — se marcar errado, não há trilha de correção.

---

### 3.4 Associação pedido Shopee ↔ comprador ↔ chat — Projeto 3,5 · Operação 1,0 🔴

**Este é o achado mais grave do assessment.**

O modelo existe: `mensagem_chat_shopee` (12.475 mensagens, 1.406 usuários distintos, 2 lojas, período 06/2024–08/2026), `grupo_mensagens_chat_shopee` (5.456), `shopee_chat_service` + `shopee_chat_api`, e campos `buyer_username` / `buyer_user_id` / `contact_marketplace_id` em `pedidos`.

**Mas o vínculo não fecha:**

```
Pedidos Shopee com buyer_username             : 4.641
Usernames distintos em pedidos                : 4.345
Usuários distintos no chat                    : 1.406
Interseção de usernames                       :    23
Pedidos que casam com alguma mensagem         :    26  (0,4%)
Pedidos que casam por buyer_user_id           :    27  (0,6%)
```

**Causa-raiz identificada.** A migração do ingest Shopee de Bling para API direta regrediu a cobertura de enriquecimento:

| Fonte de ingest | Pedidos | Com `buyer_username` | Com `buyer_user_id` | Com `modalidade_logistica` | Com `data_limite_envio` | Período |
|---|---:|---:|---:|---:|---:|---|
| `bling` | 4.467 | **4.467 (100%)** | 4.467 (100%) | 4.467 (100%) | 4.467 (100%) | 28/06 → **16/07** |
| `shopee` (direto) | 1.530 | **174 (11,4%)** | 174 (11,4%) | 174 (11,4%) | 174 (11,4%) | 27/06 → 01/08 |

Ou seja: **desde 16/07 praticamente nenhum pedido novo carrega identidade de comprador**, e por consequência não há como ancorar a conversa de chat.

Os formatos são compatíveis (username textual + ID numérico em ambas as tabelas), então **não é um problema de modelo de identidade — é um problema de enriquecimento não executado**. `pending_marketplace_enrichments` tem 394 registros `matched` e apenas 2 `pending`, o que sugere que o enriquecimento roda mas não popula esses campos.

**Lacunas estruturais adicionais.**

- O join é por **string de username**, não por chave estável. Não existe tabela de vínculo `pedido ↔ conversa`.
- `ai_personalization_service` já detecta ambiguidade (`chat_context_ambiguous` quando o mesmo comprador tem >1 pedido aberto), mas não há resolução.
- Ainda que o vínculo funcionasse, `CHAT_LOOKBACK_DAYS = 7` limita a janela.

---

### 3.5 IA para extração de nomes personalizados — Projeto 4,0 · Operação 0,5 🔴

**O que existe.** `ai_personalization_service.py` (1.047 linhas) é um pipeline completo e bem construído:

- Modelos permitidos: `gemini-2.5-flash`, `gemini-2.5-pro`, `gemini-2.0-flash`
- Prompt template configurável via `configuracoes_aplicacao` com fallback em arquivo
- Filtro de seleção explícito: `canal_venda_id IN (canais Shopee)` **AND** `situacao_pedido_id = 2` (Em Andamento) **AND** item com `personalizado = true`
- Montagem de contexto de chat com sanitização por papel (`_sanitize_chat_message_for_llm`), compactação e limite de 60 mensagens
- Processamento em lote via Celery (`processar_batch_ia` / `processar_pedido_ia`), log de execução, feedback do usuário
- Coberto por `test_ai_personalization_service.py`

O filtro de seleção **está correto** conforme o requisito — é preciso e defensável.

**Mas o pipeline está parado:**

| Tabela | Linhas |
|---|---:|
| `personalizacoes_pedido` | **1** |
| `logs_execucao_ia` | **0** |
| `execucoes_ai_batch` | **0** |
| `execucoes_ai_item` | **0** |
| `feedbacks_execucao_ia` | **0** |

Hoje há **321 pedidos elegíveis** (Shopee + personalizado + Em Andamento). Nenhum foi processado com sucesso.

**Diagnóstico.** Este ponto é **dependente do 3.4**. Sem chat vinculado, o prompt vai ao modelo sem o contexto que carrega o nome solicitado. O gargalo não está na IA — está na entrada dela.

---

### 3.6 Formas de envio, horários de corte e alternativas — Projeto 4,0 · Operação 1,5

**O que existe.** `logistica_coleta_service.py` é o serviço canônico e o desenho **cobre exatamente o cenário descrito** ("coleta no local às 12h, mas consigo levar até um ponto de coleta até 17h"):

- `JanelaColeta` com `horario_corte`, `horario_coleta`, `horario_limite`, `tipo_envio`, `ponto_coleta_id`, `prioridade_uso`, `dias_semana`
- Múltiplas regras por integração × modalidade, ordenadas por horário e prioridade — **é assim que a alternativa é modelada**: regra primária COLETA_LOCAL 12h + regra secundária PONTO_COLETA 17h com prioridade menor
- Varredura de até 15 dias à frente respeitando dias da semana
- Timezone explícito `America/Sao_Paulo`
- Alias FLEX ↔ EXPRESS
- Coberto por `test_logistica_coleta_service.py`

**Mas a configuração está vazia:**

| Regra | Integração | Modalidade | Tipo | Corte | Coleta | Ponto |
|---|---|---|---|---|---|---|
| 2 | 6 (Shopee) | FLEX | COLETA_LOCAL | 13:00 | 13:00 | — |
| 5 | 7091 (ML) | FLEX | COLETA_LOCAL | 12:00 | 14:00 | — |

- **Apenas 2 regras** para 8 canais ativos
- **Nenhuma regra STANDARD** — toda modalidade padrão cai em `SEM_REGRA`
- **Nenhuma regra alternativa** (`ponto_coleta_id` nulo nas duas; `pontos_coleta` tem 1 linha)
- **6.671/7.140 pedidos (93,4%) sem `regra_logistica_integracao_id`**
- **2.482 pedidos sem `data_limite_envio`** e **1.669 sem `modalidade_logistica`**
- Modelo concorrente `regras_logisticas_canal` (1 linha) e `canal_modalidade_mapeamento` (0) ainda presentes

**Veredito.** O motor está pronto e testado; falta **cadastro operacional** e a segunda regra que materializa a alternativa.

---

### 3.7 Agrupamento logístico de pedidos em demanda — Projeto 4,0 · Operação 1,5

**O que existe.** `consolidation_service.py` implementa a chave de consolidação (`_calcular_chave` a partir de canal + modalidade + horário resolvidos), busca de rascunho compatível (`_buscar_rascunho_compativel`), adição incremental e criação de demanda direta. `regras_consolidacao_canal` com precedência (canal+modalidade → canal → global → default hardcoded), resolvida via RPC `get_regras_consolidacao_canal` com fallback Python. Complementado por `demanda_autofill_service`, `demandas_override_service` (com trilha de quem alterou, quando e por quê) e `demandas_sugestoes_service`.

O cenário do requisito — *"pedidos Shopee, modalidade Flex, corte 12h, coleta 13h"* — **é exatamente a chave que o serviço calcula**.

**Estado real:**

- **39 demandas, 100% em `RASCUNHO`** — 20 EXPRESS, 19 STANDARD, todas `origem_demanda = AUTOMATICA`
- **Nenhuma publicada** (`publicado_em` nunca preenchido)
- **Última demanda criada em 16/07/2026** — 16 dias de silêncio
- `consolidar_pedidos_pendentes` **parou de executar em 28/07/2026** (700 execuções acumuladas até lá)
- `demandas_pedidos` tem 3.837 vínculos distribuídos nas 39 demandas — o agrupamento em si funcionou quando rodou
- `regras_consolidacao_canal`: 1 linha apenas

**Veredito.** O agrupamento **funciona e foi comprovado** (3.837 pedidos agrupados corretamente), mas o ciclo parou e nenhuma demanda chegou a ser publicada para produção.

---

### 3.8 Acompanhamento da produção com rastreabilidade — Projeto 4,0 · Operação 0,5 🔴

**O que existe.** Modelo notavelmente rico. `itens_demanda` carrega contadores por etapa do fluxo real de fabricação:

`capas_impressas_qtd` → `capas_produzidas_qtd` → `capas_prontas_retirada_qtd` / `miolos_prontos_retirada_qtd` → `expedicao_capas_retiradas_qtd` / `expedicao_miolos_retirados_qtd` → `finalizados_qtd`

Somado a: `eventos_producao` (documentada como "sinais visuais E1-E6 + liquidação E7"), `eventos_producao_v2`, `demandas_item_origem` (rastreabilidade item→pedido), `contextos_producao`, `sinalizacoes_demanda`, `regras_priorizacao` (4 regras), `alertas_demanda`, `capacity_planning_service`, `production_planning_service`, `daily_production_log_service`, kanban e dashboard dedicados.

**Estado real — todas vazias:**

| Tabela | Linhas |
|---|---:|
| `itens_demanda` | **0** |
| `eventos_producao` | **0** |
| `eventos_producao_v2` | **0** |
| `entrega_producao` | **0** |
| `logs_producao_diaria` | **0** |
| `alertas_demanda` | **0** |
| `sinalizacoes_demanda` | **0** |
| `contextos_producao` | **0** |
| `ordens_producao` | **0** |

**Consequência direta.** A rastreabilidade **pedido → demanda** existe (3.837 vínculos em `demandas_pedidos`). A rastreabilidade **demanda → produção → pedido atendido não existe na prática** — não há um único apontamento de produção registrado. É impossível hoje responder "quais pedidos desta demanda já estão prontos".

Agrava: cobertura de testes desproporcional. Dos ~40 testes, apenas 4 tocam produção/demanda (`test_demanda_core_aggregation_resilience`, `test_demanda_pedidos_origem_metadata`, `test_demanda_producao_api_resilience`, `test_motor_estoque_v2`) — a fatia menos exercitada em produção é também a menos testada.

---

### 3.9 Reconciliação de estoque — Projeto 4,5 · Operação 0,0 🔴

**O que existe.** A afirmação de que "já existe um motor que realiza o devido tratamento" **procede — e o motor é bom.** `motor_reconciliacao_estoque.py` (1.074 linhas) documenta premissas explícitas:

1. Intermediários nunca ficam negativos (produção compensatória)
2. Matérias-primas podem ficar negativas (apenas alerta)
3. Finalização é o gatilho de liquidação (explosão de BOM completa)
4. Etapas anteriores são apenas sinais visuais
5. Cálculo por delta (ledger + estado esperado)
6. Processamento assíncrono com fila
7. Idempotência e atomicidade garantidas

Com `Decimal` em todo o caminho numérico, waterfall top-down (`QuantidadesEfetivas`), `demanda_alocacoes_estoque` para evitar duplicação de consumo, e `snapshots_reconciliacao` para auditoria.

**Estado real — reconciliação nunca executou:**

| Tabela | Linhas |
|---|---:|
| `estoque_atual` | **0** |
| `movimentacoes_estoque` | **0** |
| `estoque_consolidado` | **0** |
| `snapshots_reconciliacao` | **0** |
| `demanda_alocacoes_estoque` | **0** |
| `demanda_estoque_processado` | **0** |
| `fila_processamento_estoque` | **0** |

**Bloqueador raiz identificado.** O de-para de produto está quebrado:

```
itens_pedido total                    : 7.248
  sem produto_id                      : 6.890  (95,1%)
  sem sku_externo                     :     0
SKUs externos distintos               :   322
  resolvíveis em produtos.sku         :    24  (7,5%)
produtos cadastrados (com sku)        :   357
ficha_tecnica (BOM)                   :   985
produtos_externos (tabela de de-para) :     0  ← VAZIA
```

O SKU externo chega em **100%** dos itens, mas a resolução para `produto_id` é feita por **igualdade exata contra `produtos.sku`** — e apenas **24 dos 322 SKUs de marketplace** têm correspondente idêntico no catálogo (os 358 itens resolvidos batem exatamente com esse casamento por string).

A tabela projetada para resolver isso — `produtos_externos` (`produto_id`, `codigo_externo`, `plataforma`, `metadados`) — **existe e está vazia**. É o elo faltante: sem `produto_id` não há BOM; sem BOM não há explosão; sem explosão não há movimentação de estoque. O cadastro-mestre está pronto (357 produtos, 985 linhas de ficha técnica) — **falta apenas o mapeamento de aliases**, que são ~298 linhas de de-para.

**Dívida adicional.** Dois motores coexistem: `motor_reconciliacao_estoque` (v1, assíncrono, liquidação na finalização) e `motor_estoque_v2` (v2, síncrono, liquidação por etapa E1/E2/E4/E7). Premissas **conflitantes** (P3' contradiz a premissa 4 do v1). Mais `estoque_service.py` (1.001 linhas), `estoque_service_atomic.py.bak`, `estoque_service_updated.py.bak`, `consolidador_estoque.py`, `worker_reconciliacao_estoque.py` e `stock_reconciliation_service.py.bak`. **Não há fonte de verdade única declarada.**

---

### 3.10 Geração do PDF da demanda — Projeto 2,5 · Operação 2,0

**O que existe de fato — e o que não existe.**

Não há geração de PDF. O fluxo documentado no cabeçalho de `apps/api/routes/impressao.py` é:

> 1. Frontend chama `GET /api/v2/pedidos/impressao?order_ids=1,2,3`
> 2. Backend monta dados completos de cada pedido
> 3. Frontend renderiza componente React com CSS `@media print` e dispara `window.print()`

Confirmado: `PrintTemplate.jsx` e `ConsolidarPage.jsx` usam `window.print()` / `@media print`. `jspdf` está no `package.json` do frontend mas só é usado no legado (`kb/legado/templates/results.html`). Não há `reportlab`, `weasyprint` nem `wkhtmltopdf` no backend.

**Pontos positivos.** O endpoint tem um guard-rail bom: `order_erp_reference_service.resolve_many(..., allow_remote=True)` bloqueia impressão de pedidos sem referência ERP resolvida, devolvendo `blocked_orders` — evita imprimir o que não pode ser faturado.

**Lacunas.**

- O endpoint é **por `order_ids`, não por demanda** — a "geração do PDF da demanda" é montada no cliente, não é uma operação de domínio
- **Nenhum artefato persistido**: sem versionamento, sem hash, sem prova do que foi impresso e quando
- `print_jobs`: **0 linhas** — a tabela de controle de impressão existe e nunca foi usada
- Sem reimpressão idempotente e sem controle de "esta demanda já foi impressa"
- Depende do diálogo de impressão do navegador — sem consistência de layout entre máquinas/navegadores

---

### 3.11 Geração de NF no ERP correto — Projeto 4,0 · Operação 3,0

**O que existe.** `apps/api/routes/nfe.py` faz o roteamento correto:

1. Aceita `instance_id` explícito
2. Se ausente, resolve pela origem dos pedidos já persistidos (busca `bling_integration_id` por `codigo_pedido_externo`/`numeroLoja`)
3. **Recusa explicitamente lotes multi-conta**: *"Pedidos pertencem a múltiplas contas Bling. Gere NF por conta separadamente."*
4. Fallback por `marketplace_integration_id`
5. Progresso via SSE (`stream_with_context`)

Suportado por `integration_capability_service` com capability `INVOICING`, `nf_emission_mode` por vínculo em `erp_marketplace_links` (todos os 10 links = `bling`) e `NfEmitterBanner.tsx` no frontend indicando o emissor ativo.

A guarda anti-multi-conta é a decisão certa — evita a classe de erro mais cara desse domínio.

**Lacunas.**

- **Nenhuma tabela registra o resultado da emissão.** Não há histórico de NF emitida, número, chave, status ou erro — só o stream efêmero para o cliente
- Sem **idempotência explícita**: reenvio do mesmo lote não é protegido por chave
- Resolução depende de `codigo_pedido_externo` — os **685 pedidos sem `erp_integration_id`** e **1.669 sem `erp_order_id`** não são faturáveis por esse caminho
- Fluxo é por lista de pedidos, não por demanda — o requisito "NF dos pedidos da demanda" é composto no frontend
- Os 1.596 `pending_order_reconciliations` são, na prática, **1.596 pedidos que ainda não podem virar NF**

---

### 3.12 Registro de coleta parcial — Projeto 3,5 · Operação 0,5

**O que existe.** O conceito é de primeira classe no domínio:

- Constante `STATUS_DEMANDA_COLETA_PARCIAL = 'COLETA_PARCIAL'` em `constants.py`, presente na lista canônica de status
- `demanda/status.py` promove automaticamente para `COLETA_PARCIAL` quando `algum_finalizado_parcial` e desconta o já baixado ("*Subtraímos o que já foi baixado via coleta parcial*")
- `demanda_producao_service.registrar_coleta_parcial(demanda_id, quantidade_coletar, user_id)` e `finalizar_item_parcial(demanda_id, item_id, quantidade, user_id)`
- Endpoints REST: `POST /<demanda_id>/item/<item_id>/finalizar-parcial` e a rota de coleta
- Considerado nas consultas de demandas ativas e no kanban/dashboard

**Lacunas.**

- **TODO explícito no código** (`demanda_producao_service.py`, linhas 222-230): `ponto_coleta_id` e `observacoes` **não são persistidos**. Ou seja, registra-se *quanto* foi coletado, mas não *onde* nem *por quem* — e o requisito de alternativas logísticas (3.6) depende justamente do ponto
- **Não existe tabela de evento de coleta.** Não há registro de transportadora, data/hora, responsável ou romaneio. O "20/30 coletados" vive como contador mutável no item, sem histórico
- `entrega_producao`: **0 linhas**
- **Nenhuma demanda alcançou `COLETA_PARCIAL`** — as 39 estão em `RASCUNHO`. O caminho nunca foi exercido com dados reais
- Sem reversão auditável de uma coleta registrada por engano

---

## 4. Achados transversais

### 4.1 Segurança — 🔴 crítico

| Achado | Número |
|---|---|
| Tabelas com RLS habilitado | 117 de 117 |
| Tabelas com **RLS habilitado e ZERO policies** | **99 (84,6%)** |
| Tabelas com policy | 18 (36 policies) |

RLS ligado sem policy = **deny-all**. Funciona hoje porque o backend usa `service_role`, que ignora RLS. Consequência: **qualquer acesso via chave `anon` ou `authenticated` quebra silenciosamente**, e a proteção real do dado depende inteiramente da chave de serviço não vazar. Não há defesa em profundidade.

### 4.2 Verificação de assinatura de webhook — 🟢 resolvido *(revisado em 02/08)*

> **Correção deste assessment.** A leitura original tratava os números agregados como um problema ativo. Cruzando com a distribuição temporal e com `docs/tecnico/convencao-validacao-assinatura.md`, a conclusão correta é outra: **o incidente já foi diagnosticado e corrigido**, e boa parte do que parecia lacuna é decisão de arquitetura.

**A convenção vigente (adotada em 01/08).** A decisão de autenticidade vive no **n8n**, na borda, antes do evento entrar na inbox. O app registra o veredito e não o recalcula — a validação do app permanece apenas como rede de segurança. Cada origem tem mecanismo próprio:

| Origem | Mecanismo | Onde |
|---|---|---|
| Bling | HMAC-SHA256 do corpo cru, por conta (`companyId` → segredo) | app (`validate_signature`), com nós de verificação no n8n em modo observação |
| Shopee | HMAC-SHA256, veredito pós-ACK em `np:ingest:signature:{event_id}` | n8n (`Validate Shopee Signature Post-ACK`) |
| Mercado Livre | **allowlist de IP — não há assinatura** | n8n (`Resolve Client IP` / `IP autorizado?`) |

**Reinterpretação dos números.**

1. **Os 2.832 descartes Bling foram um incidente de 3 dias, já encerrado.** A distribuição temporal mostra: zero descartes até 29/07, **1.132 em 30/07, 1.689 em 31/07**, e apenas 7 em 01/08 — o último às 14:21. A partir de **15:54 de 01/08 todos os eventos Bling registram `signature_valid`** (8 de 8). Causa-raiz identificada no diagnóstico interno: um placeholder literal `...` em `INGEST_WEBHOOK_SECRETS_BLING` produzia lista não-vazia sem segredo real, e o caminho "há segredos mas nenhum bate" gerava descarte **terminal independente da política**. Correção já implementada (`webhook_secret_resolver.py`, segredo lido do banco, placeholders filtrados, ausência de segredo volta a produzir `signature_unverified`).

2. **`signature_unverified` no Mercado Livre é o estado correto e final, não uma lacuna.** Verificado em tráfego real: o ML **não assina webhooks** — não existe `x-signature` nos cabeçalhos. A garantia de origem é a allowlist de IP no n8n. O `_validate_meli` do app nunca teve material para validar.

3. **`signature_unverified` no Shopee é esperado sob a convenção.** A validação ocorre no n8n pós-ACK; o app consome o veredito do Redis dentro de `INGEST_SIGNATURE_VERDICT_GRACE_SECONDS`. `signature_unverified` no app significa que o veredito não chegou a tempo, não que ninguém validou.

**O que permanece em aberto.**

- **`discarded_invalid_signature` deveria ser sempre zero** sob esta convenção. Qualquer valor diferente de zero indica evento entrando **por fora do n8n** — é o alerta correto a monitorar, e não estava instrumentado como tal
- **Porta paralela.** `POST /api/v2/webhooks/{shopee,mercadolivre}` enfileira no mesmo inbox sem validar, e era **fail-open** até 01/08 — sem `MARKETPLACE_WEBHOOK_TOKEN` definido, aceitava qualquer requisição, e a variável não existia em nenhum `.env`. Já corrigido para fail-closed com `hmac.compare_digest`, mas a porta continua existindo
- **Duplicação consciente do segredo Bling** entre `BLING_CLIENT_SECRETS` (n8n) e o banco. Cadastrar conta nova exige atualizar os dois — com enforcement ligado, esquecer rejeita aquela conta
- **Confirmar em produção** que `INGEST_WEBHOOK_SECRETS_BLING` e `..._MERCADOLIVRE` estão vazias ou ausentes, e definir `INGEST_SIGNATURE_POLICY_BLING` explicitamente
- **A allowlist de IP do ML é configuração de terceiro** e muda sem aviso — uma alteração lá derruba o ingest do mesmo modo que o placeholder derrubou o do Bling

### 4.3 Confiabilidade do ingest

| Métrica | Valor |
|---|---|
| `webhook_event_attempts` com `failed` | **1.882** |
| `webhook_event_attempts` com `success` | 323 |
| `mercadolivre_webhook_done/error` | **867** (vs 621 success — 58% de erro) |
| `shopee_webhook_done/pending` nunca finalizados | 809 |
| `shopee_webhook_failed/failed` | 100 |
| ML `skipped_unresolved_payment_reference` | 219 |

### 4.4 Agendamentos — a fonte de verdade é o banco 🔴 *(revisado em 02/08)*

> **Correção deste assessment.** A leitura original ("workers pararam") estava incompleta. As `consumir_fila_*` foram **deliberadamente aposentadas** — o `reliable_ingest_worker` cobre o consumo, e elas estavam sendo filtradas em runtime por `obsolete_webhook_tasks` mesmo com `enabled: true` no banco. Já foram removidas da configuração. O problema real é outro e mais grave.

`load_dynamic_schedules()` lê `configuracoes_aplicacao.celery_task_schedules` — **o banco é a fonte efetiva**, e os defaults de `get_default_schedules()` só valem se a configuração não existir (ela existe).

**Estado da configuração em 01/08 16:54:**

| Task | `enabled` | Intervalo |
|---|:---:|---|
| `reconcile-pending-erp-references` | ✅ true | 60s |
| `process-marketplace-lifecycle-effects` | ✅ true | 30s |
| `processar-eventos-producao-periodic` | ✅ true | 300s |
| `renew-app-managed-credentials` | ✅ true | 7200s |
| `consolidar-pedidos-pendentes` | ❌ **false** | 300s |
| `renew-shopee-tokens` | ❌ false | 7200s |
| `reconcile-marketplace-lifecycle` | ❌ false | 300s |

**Achado crítico: as duas tasks habilitadas às 16:54 não executaram uma única vez.**

| Fila | Itens `pending` | `attempts` / `attempt_count` | `last_error` |
|---|---:|:---:|---|
| `pending_order_reconciliations` | **1.609** | **0 em 100%** | nenhum |
| `marketplace_order_effects` | **261** | **0 em 100%** | nenhum |

Zero tentativas e zero erros significa que a task **nunca foi disparada** — não que ela falhou. E as filas continuam crescendo (1.596 → 1.609 e 260 → 261 durante este assessment).

**Causa provável: o Celery beat não foi reiniciado após a alteração da configuração.** `load_dynamic_schedules()` roda na inicialização do beat; alterar o JSON no banco não tem efeito até o restart. **Reiniciar o beat é a ação de maior retorno imediato do sistema hoje** — destrava duas filas de uma vez.

**Lacuna de observabilidade que mascarou isso.** `reconcile_pending` e `process_pending_effects` vivem em `packages/shared/services/` e têm apenas `@shared_task` — **não usam o decorator `@log_task_execution`**, que existe em `apps/worker/task_logger.py`. Por isso não aparecem em `task_execution_logs` nem quando rodam. As duas únicas tasks visíveis lá (`process_eventos_producao_task`, `renew_app_managed_credentials_task`) são justamente as que moram em `apps/worker/tasks/`. Ou seja: **metade das tasks agendadas é invisível no painel de execução**.

**Consequência da `consolidar-pedidos-pendentes` desligada:** nenhuma demanda é criada desde 16/07 — é o que trava toda a cadeia de produção.

### 4.7 Estado após as correções de 02/08

Beat reiniciado, código publicado. Resultado medido:

| Métrica | 01/08 | 02/08 |
|---|---:|---:|
| `pending_order_reconciliations` pendentes | 1.609 | **7** |
| — resolvidos (`applied`) | 0 | **1.496** |
| — encerrados por situação terminal | — | **64** |
| — falhas reais (`failed`) | 0 | **64** |
| `marketplace_order_effects` pendentes | 261 | **0** (262 processados) |
| `eventos_pedido` | 0 | **262** |
| Tasks agendadas com registro de execução | 2 de 4 | **4 de 4** |
| Pedidos cancelados dentro de rascunhos | 398 | **0** |
| `alertas_demanda` | 0 | **398** (rastro da limpeza) |

**Três descobertas que só apareceram depois de ligar as filas:**

1. **Cancelado dentro de rascunho.** O RPC filtrava demandas em `AGUARDANDO/EM_PRODUCAO/COLETA_PARCIAL/COLETADO`; as 39 demandas estão em `RASCUNHO`. Os 262 efeitos processaram com zero alertas — comportamento correto para o código escrito, e errado para o negócio. Agora rascunho remove o pedido e ajusta a quantidade; demanda publicada continua exigindo decisão humana.

2. **Metade da fila de falhas não era falha.** Dos 128 itens que esgotaram 20 tentativas, 64 eram devoluções e 18 entregas — pedidos que o Bling nunca importaria, por definição. Novo estado `skipped_terminal` separa "não tinha o que resolver" de "falhou", e o encerramento acontece antes de gastar chamada de API.

3. **Fila órfã.** 5 itens com `reason = marketplace_module_unresolved` parados desde 29/06: a task filtra `reason = erp_reference_pending` e **nenhuma outra os consome**. Continuam em aberto.

**O que permanece:** 64 falhas legítimas (pedidos ML em `Pronto para Envio`, `Em Andamento`, `Entregue`, `Enviado` sem pedido correspondente no Bling) — exigem investigação caso a caso, possivelmente ligada ao vínculo ML com `marketplace_integration_id = NULL`.

### 4.5 Dívida arquitetural

- **3 modelos de vínculo canal/integração** sobrepostos
- **2 motores de estoque** com premissas conflitantes
- **2 modelos de regra logística** (`regras_logisticas_canal` vs `regras_logisticas_integracao`)
- **3 modelos de timeline de pedido** (`eventos_pedido`, `transicoes_situacao`, `marketplace_order_transitions` — só o último em uso)
- Arquivos `.bak` / `.legacy` versionados: `cadastros.py.bak`, `demanda_producao.py.bak`, `marketplace_api.py.bak`, `produtos.py.bak`, `producao.py.bak`, `stock_tasks.py.bak`, `stock_tasks.py.legacy`, `estoque_service_atomic.py.bak`, `estoque_service_updated.py.bak`, `stock_reconciliation_service.py.bak`, `conta_bling_service_updated.py`
- Tabela `_snapshot_produtos_tipo_20260508` ainda em produção com nota "*pode ser removido após validação*"
- ~30 das 117 tabelas sem uso algum

### 4.6 O que está acima da média

Vale registrar, porque é raro e sustenta a recuperação:

- **Especificação formal versionada** — `docs/specs/` com 00-governance (incluindo matriz de rastreabilidade e template de decision record), 01-system, 02-domains, 03-contracts, 04-quality, 05-roadmap
- **Camada de canonização de status exemplar** — provider-agnóstica por design, com a regra de fronteira escrita no código
- **Observabilidade de ingest por estágio** — `pedido_ingest_log` com 11 estágios nomeados e `correlation_id` é diagnóstico de primeira linha
- **~40 testes automatizados** concentrados na fronteira mais volátil (integrações, webhooks, credenciais, OAuth, rate limit)
- **Guard-rails de negócio corretos** nos pontos caros: recusa de NF multi-conta, bloqueio de impressão sem referência ERP, não-regressão de status

---

## 5. Top 10 riscos priorizados

*Revisado em 02/08 após incorporar `convencao-validacao-assinatura.md` e `diagnostico-agendamentos-ingest-2026-08-01.md`.*

| # | Risco | Prob. | Impacto | Ponto |
|---|---|:---:|:---:|---|
| 1 | **Beat não recarregado** — 2 tasks habilitadas às 16:54 com 0 tentativas; 1.609 + 261 itens em fila crescendo | Certa | Crítico | 4.4 |
| 2 | **Reconciliação de estoque nunca executou** — só 24 de 322 SKUs externos resolvem produto; `produtos_externos` vazia | Certa | Crítico | 3.9 |
| 3 | **Vínculo pedido↔chat Shopee em 0,4%** — inviabiliza a IA e a personalização | Certa | Crítico | 3.4 |
| 4 | **Ingest direto não enriquece** — 89% dos pedidos novos sem buyer, modalidade e prazo | Certa | Crítico | 3.4 / 3.6 |
| 5 | **Bling sobrescreve estado de pedido `marketplace_direct`** sem checagem de autoridade — agrava quando o Bling voltar a volume | Alta | Crítico | 3.2 |
| 6 | **`consolidar-pedidos-pendentes` desabilitada** — nenhuma demanda desde 16/07 | Certa | Alto | 3.7 |
| 7 | **99 tabelas com RLS sem policy** — segurança depende só do `service_role` | Média | Crítico | 4.1 |
| 8 | **Metade das tasks agendadas não registra execução** — falha silenciosa por design | Certa | Alto | 4.4 |
| 9 | **Produção sem nenhum apontamento** — rastreabilidade demanda→pedido inexistente na prática | Certa | Alto | 3.8 |
| 10 | **Coleta parcial não persiste ponto nem histórico** (TODO no código) | Alta | Médio | 3.12 |

**Saíram do top 10 após a revisão:** descarte de assinatura Bling (incidente encerrado em 01/08 15:54, correção implementada) e `signature_unverified` em Shopee/ML (comportamento correto sob a convenção de validação na borda).

---

## 6. Recomendações priorizadas

### P0 — Destravar a cadeia (2 a 4 semanas)

1. **Corrigir a verificação de assinatura Bling.** 2.832 descartes contra 7 aceitos é falha de configuração, não de volume. Validar segredo e algoritmo em `webhook_secret_resolver`, e adicionar alerta quando a taxa de descarte por assinatura passar de 5% em 1h.
2. **Restabelecer o enriquecimento no ingest direto.** Garantir que o caminho `marketplace_direct` popule `buyer_username`, `buyer_user_id`, `modalidade_logistica` e `data_limite_envio` com a mesma cobertura do caminho Bling (100%). Fazer backfill dos 1.356 pedidos Shopee afetados.
3. **Popular `produtos_externos` e usá-la na resolução.** ~298 SKUs de marketplace precisam de alias para os 357 produtos com BOM, e o resolvedor precisa consultar a tabela antes de cair no `sku` exato. É o único bloqueador entre 7.248 itens e o motor de estoque — sem isso nenhum motor pode rodar, por melhor que seja.
4. **Consumir `marketplace_order_effects`.** 260 alertas de demanda pendentes; criar o worker e drenar. Isso fecha o requisito de "consistência da produção das demandas".
5. **Religar `consolidar_pedidos_pendentes`** e instrumentar heartbeat dos consumidores de fila com alerta de ausência.

### P1 — Fechar os requisitos (4 a 8 semanas)

6. **Criar chave estável pedido ↔ conversa Shopee.** Tabela de vínculo explícita, resolvida no ingest por `buyer_user_id` + `marketplace_integration_id`, com fallback por username e marcação de ambiguidade. Só então religar o pipeline de IA (os 321 pedidos elegíveis são o piloto natural).
7. **Cadastrar as regras logísticas reais.** Mínimo: uma regra STANDARD por canal ativo + a regra alternativa com `ponto_coleta_id` e `prioridade_uso` menor — o motor já suporta, é cadastro.
8. **Persistir coleta parcial como evento.** Nova tabela `eventos_coleta` com demanda, quantidade, ponto, transportadora, responsável e timestamp. Resolver o TODO de `ponto_coleta_id`/`observacoes`.
9. **Eleger fonte de verdade única** para: vínculo canal↔integração, motor de estoque e regra logística. Marcar os demais como deprecated com data de remoção. Deletar os `.bak`/`.legacy` do versionamento.
10. **Publicar demandas de ponta a ponta** com um piloto controlado, gerando apontamentos reais em `itens_demanda` e `eventos_producao` — sem isso a produção segue não validada.

### P2 — Robustez (8 a 16 semanas)

11. **Escrever policies RLS** para as 99 tabelas expostas, ou documentar formalmente a decisão de operar apenas via `service_role` com controles compensatórios.
12. **PDF como artefato de domínio**: geração server-side por demanda, persistida em storage, registrada em `print_jobs`, com versionamento e reimpressão idempotente.
13. **Registrar o resultado da emissão de NF** (número, chave, status, erro) com chave de idempotência por lote.
14. **Elevar cobertura de testes** em produção/demanda/estoque ao patamar da camada de integrações.
15. **Processo de triagem para `unmapped`** (14 hoje) e para os 867 erros de webhook ML.

---

## 7. Conclusão

O sistema **não tem um problema de concepção — tem um problema de ativação.** Os pontos críticos que você listou estão, quase sem exceção, corretamente modelados: existe serviço dedicado, tabela dedicada, contrato escrito e, em boa parte, teste automatizado. A camada de canonização de status é genuinamente boa e sustentaria auditoria externa.

O que falha é a metade a jusante da cadeia. Estoque, produção, coleta parcial e IA de personalização são código pronto sobre tabelas vazias, e três bloqueadores concretos explicam quase tudo:

- **de-para de SKU inexistente** (`produtos_externos` vazia; 7,5% de resolução) trava estoque e produção
- **enriquecimento ausente no ingest direto** trava chat, IA, modalidade e prazo
- **efeitos e workers não consumidos** travam a consistência entre marketplace e demanda

São três correções pontuais, não três reescritas. Resolvidas, a maturidade operacional deve saltar de ~1,9 para a faixa de 3,5 sem trabalho arquitetural novo — o que é a definição de um sistema bem projetado e mal ativado.

---

*Assessment gerado em 01/08/2026 a partir de análise estática do repositório `nistiprint-app` e consulta ao banco de produção `nistiprint-supabase`. Todos os números são medições diretas, não estimativas.*
