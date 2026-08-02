# Plano de Implementação — Correções Prioritárias

**Data:** 01/08/2026
**Base:** `ASSESSMENT_PONTOS_CRITICOS_2026-08-01.md`, revisado com as decisões de produto do Leandro
**Horizonte:** 6 fases, ~8 semanas de engenharia

---

## 0. O que mudou em relação ao assessment

As observações recebidas alteram cinco recomendações. Registro para não haver ambiguidade:

| Item | Recomendação original | Decisão | Nova direção |
|---|---|---|---|
| **3.4 Chat** | Criar chave estável `buyer_user_id` + tabela de vínculo | ❌ Rejeitada | **Manter vínculo por `buyer_username`.** A janela de conversa Shopee é única por comprador, e o comprador pode ter vários pedidos simultâneos — o username é a chave certa. O trabalho é garantir que ele seja preenchido, não trocá-lo |
| **3.5 IA** | Religar o pipeline Gemini | 🔄 Ampliada | Transformar `run_model` em **roteador de provedores** (Gemini \| OpenRouter), com `openrouter/auto` como no legado |
| **3.7 Consolidação** | "Religar o worker" | 🔄 Corrigida | O worker agrupa, mas a **regra de janela está errada**. Diagnóstico refinado na §4 |
| **3.9 Estoque** | Popular `produtos_externos` como tarefa de engenharia | 🔄 Reclassificada | **Cadastro é ação humana**, sai do caminho crítico de engenharia. O escopo técnico é **eleger o v2 e remover o v1** |
| **3.10 PDF** | Gerar PDF server-side, usar `print_jobs` | ❌ Rejeitada | Comportamento atual (`window.print()`) **está correto e deve ser idêntico ao legado**. `print_jobs` é outra funcionalidade (impressão de artes/capas, futuro) — fora de escopo |
| **4.2 Assinatura** | Corrigir Bling; implementar verificação Shopee/ML em modo shadow | ❌ Obsoleta | **Validação vive no n8n, na borda.** O incidente Bling já foi diagnosticado e corrigido; o ML não assina webhooks (garantia é allowlist de IP); modo shadow já é a convenção. Ver §F0.1 |
| **4.4 Workers** | "Religar consumidores de fila parados" | 🔄 Corrigida | As `consumir_fila_*` foram **aposentadas de propósito**. O problema real é que **o beat não foi recarregado** após habilitar duas tasks — 0 tentativas em 1.609 + 261 itens. Ver §F0.4 |

---

## 1. Visão geral das fases

| Fase | Tema | Duração | Depende de |
|---|---|---|---|
| **F0** | Desbloqueio: assinatura, enriquecimento, workers | 1 semana | — |
| **F1** | Personalizados ponta a ponta: chat + roteador de IA | 2–3 semanas | F0 |
| **F2** | Consolidação inteligente de demandas | 2 semanas | F0 |
| **F3** | Estoque canônico (v2) | 2 semanas | F2 + cadastro humano |
| **F4** | Impressão fiel ao legado + coleta parcial | 1 semana | F1 |
| **F5** | Segurança, efeitos e dívida | 2 semanas | paralelo |

Caminho crítico: **F0 → F1**. Tudo em Personalizados depende de `buyer_username` voltar a ser preenchido.

---

## FASE 0 — Desbloqueio (1 semana)

> **Revisão de 02/08.** Esta fase foi reescrita depois de incorporar `docs/tecnico/convencao-validacao-assinatura.md` e `docs/tecnico/diagnostico-agendamentos-ingest-2026-08-01.md`. Boa parte do que eu havia proposto **já estava diagnosticado e corrigido**; o que restou é diferente e mais urgente.

### F0.1 · Assinatura — confirmar, não reinvestigar ✅ *(reescrito)*

**A convenção vigente.** A decisão de autenticidade vive no **n8n**, na borda, antes do evento entrar na inbox. O app registra o veredito e não o recalcula. Minha proposta original de "implementar verificação por provider em modo shadow" **já é exatamente a convenção adotada** — nada a construir.

**Reinterpretação dos números que motivaram a recomendação original:**

| Leitura original | Leitura correta |
|---|---|
| "2.832 webhooks Bling descartados, perda contínua" | **Incidente de 3 dias, encerrado.** Zero descartes até 29/07; 1.132 em 30/07; 1.689 em 31/07; 7 em 01/08, o último às 14:21. **Desde 15:54 de 01/08, 8 de 8 eventos Bling com `signature_valid`.** Causa: placeholder literal `...` em `INGEST_WEBHOOK_SECRETS_BLING`. Correção já implementada em `webhook_secret_resolver.py` |
| "ML sem verificação de assinatura" | **O ML não assina webhooks.** Confirmado nos cabeçalhos de tráfego real: não existe `x-signature`. A garantia de origem é allowlist de IP no n8n. `signature_unverified` é o estado correto e final |
| "Shopee sem verificação" | Validado no n8n pós-ACK, veredito em `np:ingest:signature:{event_id}`. `signature_unverified` no app significa veredito não recebido dentro de `INGEST_SIGNATURE_VERDICT_GRACE_SECONDS=30`, não ausência de validação |

**O que fazer (pequeno, de confirmação):**

1. Confirmar em produção que `INGEST_WEBHOOK_SECRETS_BLING` e `..._MERCADOLIVRE` estão **vazias ou ausentes** — um placeholder ali derruba o ingest de novo
2. Definir `INGEST_SIGNATURE_POLICY_BLING` explicitamente (hoje o `.env` local nem tem a variável)
3. **Instrumentar o alerta que sustenta a convenção**: sob validação na borda, `signature_status = discarded_invalid_signature` deveria ser **sempre zero**. Valor diferente de zero = evento entrando **por fora do n8n**. Ligar `INGEST_INVALID_SIGNATURE_ALERT_THRESHOLD` com esse significado
4. **Persistir o header de assinatura** junto do `raw_body`. Hoje só o corpo é guardado, o que impediu diagnosticar o formato do digest (hex × base64) sem esperar tráfego novo
5. Avaliar aposentar a **porta paralela** `POST /api/v2/webhooks/{shopee,mercadolivre}`. Já foi corrigida de fail-open para fail-closed em 01/08, mas continua sendo uma segunda entrada na inbox sem validação. Uma porta a menos é melhor que uma porta bem trancada
6. Registrar no runbook: **cadastrar conta Bling nova exige atualizar `BLING_CLIENT_SECRETS` no n8n também** — a duplicação do segredo foi assumida conscientemente, mas precisa de processo

**Aceite.** `discarded_invalid_signature` em zero por 7 dias, com alerta ativo caso saia de zero.

---

### F0.3 · Restaurar enriquecimento no ingest direto 🔴 *(pré-requisito de F1)*

**Problema.** A migração Shopee de Bling para API direta derrubou a cobertura de campos essenciais:

| Campo | Ingest via Bling | Ingest direto |
|---|---:|---:|
| `buyer_username` | 4.467 / 4.467 (100%) | 174 / 1.530 (11,4%) |
| `buyer_user_id` | 100% | 11,4% |
| `modalidade_logistica` | 100% | 11,4% |
| `data_limite_envio` | 100% | 11,4% |

Além disso, **100% dos 313 pedidos Mercado Livre estão sem `canal_venda_id`** — o estágio `resolve_canal_venda` não roda no caminho direto.

**Fazer.**

1. No driver Shopee direto, garantir a chamada de detalhe do pedido que traz `buyer_username`, `buyer_user_id`, `days_to_ship`/`ship_by_date` e serviço logístico — hoje o upsert acontece antes ou sem esse enriquecimento
2. Executar os estágios `resolve_canal_venda`, `classify_flex` e `classify_fulfillment` também no caminho `marketplace_direct` (hoje aparecem apenas no fluxo Bling no `pedido_ingest_log`)
3. **Backfill** dos 1.356 pedidos Shopee e 313 ML afetados, via reprocessamento por `order_reprocess_service`
4. Adicionar assert no ingest: pedido Shopee sem `buyer_username` gera `pedido_ingest_log` com `status = error` em vez de passar silencioso

**Arquivos.** `marketplace_webhook_ingest_service.py`, `platform_drivers/`, `order_reprocess_service.py`, `reliable_ingest_service.py`

**Aceite.** ≥ 98% dos pedidos Shopee e ML criados nas últimas 24h com `buyer_username`, `canal_venda_id`, `modalidade_logistica` e `data_limite_envio` preenchidos.

---

### F0.4 · Reiniciar o Celery beat 🔴 *(ação imediata, minutos)*

**Esta é a ação de maior retorno do sistema hoje.**

**Problema.** Em 01/08 às 16:54 a configuração `celery_task_schedules` foi atualizada habilitando `reconcile-pending-erp-references` (60s) e `process-marketplace-lifecycle-effects` (30s). **Nenhuma das duas executou uma única vez desde então:**

| Fila | Itens `pending` | Tentativas | Erros |
|---|---:|:---:|---|
| `pending_order_reconciliations` | **1.609** | **0 em 100%** | nenhum |
| `marketplace_order_effects` | **261** | **0 em 100%** | nenhum |

Zero tentativas **e** zero erros prova que a task nunca foi disparada — não que ela falhou. E as filas seguem crescendo (1.596 → 1.609 e 260 → 261 durante o assessment).

**Causa.** `load_dynamic_schedules()` lê o banco **na inicialização do beat**. Alterar o JSON em `configuracoes_aplicacao` não tem efeito até o restart.

**Fazer.** Reiniciar o Celery beat e confirmar em log a linha `"Task periódica ativa: reconcile-pending-erp-references (60s)"`. Verificar em 5 minutos que `attempts > 0` começa a aparecer nas duas filas.

**Aceite.** `pending_order_reconciliations` < 50 e `marketplace_order_effects` = 0 em 24h.

---

### F0.5 · Fechar a lacuna de observabilidade das tasks 🔴

**Problema.** `reconcile_pending` e `process_pending_effects` vivem em `packages/shared/services/` e têm apenas `@shared_task` — **não usam o decorator `@log_task_execution`** de `apps/worker/task_logger.py`. Por isso não aparecem em `task_execution_logs` nem quando rodam corretamente.

As duas únicas tasks visíveis no painel (`process_eventos_producao_task`, `renew_app_managed_credentials_task`) são justamente as que moram em `apps/worker/tasks/`. **Metade das tasks agendadas falha em silêncio** — foi isso que permitiu que F0.4 passasse despercebido.

**Fazer.**

1. Aplicar `@log_task_execution` às tasks de `packages/shared/services/` (`order_erp_reference_service.reconcile_pending`, `marketplace_lifecycle_tasks.process_pending_effects`, `reconcile_marketplace_lifecycle`)
2. **Alerta por ausência**, não por erro: notificar quando qualquer task com `enabled: true` ficar mais de 3× o seu intervalo sem registro. Alerta que depende de a task rodar para disparar não protege contra a task não rodar
3. Expor na tela de agendamentos a **última execução real**, ao lado do `enabled` — hoje a tela mostra a intenção, não o fato

**Aceite.** Toda task agendada com registro em `task_execution_logs`; alerta disparando em teste de parada induzida.

---

### F0.6 · Ligar a checagem de autoridade no handler Bling 🔴 *(fazer ANTES do Bling voltar a volume)*

**Problema.** `bling_order_processing_service._upsert_pedido_master` (linha 1703) chama `_resolve_situacao_interna()` e grava `situacao_pedido_id` direto (linha 1752), **sem checagem de autoridade**. Um webhook do Bling sobrescreve o estado de um pedido cujo ciclo pertence ao marketplace.

O lado marketplace já está protegido (`marketplace_webhook_ingest_service.py:555`) — só o lado ERP não está.

**Urgência.** Enquanto o Bling esteve descartando webhooks (30/07–01/08), o problema ficou latente. **Com o ingest Bling restabelecido em 01/08 15:54, ele volta a ser ativo.** Toda a camada de canonização de status descrita no assessment §3.2 — que é o melhor componente do sistema — é contornada por esse caminho.

**Fazer.** O vínculo já é resolvido logo abaixo (`resolve_erp_marketplace_link`, linha 1718). Passar `situacao_pedido_id=None` quando `is_authoritative(link['ingest_origin_mode'], 'erp', 'order')` for falso.

**Aceite.** Webhook Bling de pedido `marketplace_direct` não altera `situacao_pedido_id`; teste cobrindo os dois modos de origem.

---

### F0.7 · Reabilitar `consolidar-pedidos-pendentes`

Está `enabled: false` no banco — é a razão de nenhuma demanda existir desde 16/07.

**Não reabilitar antes da Fase 2.** Com a regra de janela atual (4h deslizante, sem teto), religar reproduz o padrão defeituoso: canal EXPRESS agrupa, STANDARD cria uma demanda por pedido, e existe risco de repetir a demanda de 1.038 pedidos. Ligar **depois** de F2.1 e F2.2.

---

### F0.8 · Propagar `kwargs` dos agendamentos

`load_dynamic_schedules()` já foi corrigido para propagar `kwargs` e `args`. Validar com `reconcile-marketplace-lifecycle`, cuja configuração no banco declara `{"dry_run": true, "days": 90, "limit": 100, "offset": 0}` — antes da correção rodaria com `days=60` da assinatura em vez dos 90 configurados.

**Aceite.** Task de backfill executando com os parâmetros do banco, confirmado em log.

---

## FASE 1 — Personalizados ponta a ponta (2–3 semanas)

### F1.1 · Consolidar o vínculo por `buyer_username`

**Decisão de arquitetura.** O vínculo é **por nome de usuário**, não por ID de pedido nem por conversa. Justificativa registrada: a janela de conversa da Shopee é única por comprador, e o mesmo comprador pode ter múltiplos pedidos simultâneos — logo, o contexto correto para a IA é *a conversa do comprador*, não *a conversa de um pedido*.

**O que já está certo e deve ser mantido.** `_fetch_chat_messages` já consulta `from_user_name` e `to_user_name` sobre `view_mensagens_chat_ai_v2`, com dedupe, filtro por `installed_integration_id` e ordenação cronológica. A lógica está correta — falta o dado de entrada (resolvido em F0.3).

**Fazer.**

1. **Normalização defensiva do username** em ambos os lados da junção: `trim` + `lower` na gravação de `pedidos.buyer_username` e de `mensagem_chat_shopee.from_user_name`/`to_user_name`. Adicionar índice funcional `lower(buyer_username)` em `pedidos` e `lower(from_user_name)` / `lower(to_user_name)` em `mensagem_chat_shopee`
2. **Revisar `CHAT_LOOKBACK_DAYS = 7`.** Para personalização, a mensagem que carrega o nome costuma vir logo após a compra, mas pedidos parados na fila por mais de uma semana perdem o contexto. Tornar configurável em `configuracoes_aplicacao` e subir o default para 15 dias
3. **Escopo por integração.** Garantir que a junção respeite `marketplace_integration_id` — hoje há 2 lojas em `mensagem_chat_shopee` e o filtro por `installed_integration_id` é aplicado só quando o campo existe na linha. Tornar obrigatório após backfill

**Aceite.** ≥ 80% dos pedidos Shopee personalizados em `Em Andamento` com pelo menos uma mensagem de chat associada (hoje: 0,4%).

---

### F1.2 · Exibir a conversa do comprador na tela de Personalizados

**Contexto.** Os webhooks de mensagem de chat passaram a ser recebidos recentemente (1.110 eventos `chat_persisted` + 438 `skipped_chat_notification`). A funcionalidade precisa ficar consistente na tela.

**O que já existe.** Endpoint `GET /personalizados/chat/<username>` → `get_chat_messages(username, limit)`, que consulta `view_mensagens_chat_ai_v2` por `from_user_name` **ou** `to_user_name`, com janela de 7 dias e `compact_chat_messages`.

**Lacunas a corrigir.**

1. **438 eventos `skipped_chat_notification`.** Investigar o que está sendo descartado — `classify_shopee_webhook` só aceita payloads com `conversation_id`/`message_id`, e `process()` rejeita push sem esses campos. Se são notificações que exigem um `get_message` de follow-up, implementar a busca
2. **Reconciliação de conversa.** `shopee_chat_service.reconcile_conversation()` já existe (paginação até 100 páginas). Expor como ação na tela: *"Recarregar conversa"* — resolve buracos de webhook perdido sem esperar mensagem nova
3. **Consistência de exibição.** A tela deve mostrar a conversa completa do comprador, sinalizando visualmente quando `chat_context_ambiguous = true` (comprador com mais de um pedido aberto) — o campo já é calculado em `_assemble_orders`, só não é exibido
4. **Tempo real.** Ao receber webhook de chat, invalidar cache/refetch da conversa aberta

**Arquivos.** `apps/api/routes/personalizados.py`, `shopee_chat_service.py`, `apps/frontend/src/pages/vendas/VendasPersonalizadasPage.jsx`

**Aceite.** Conversa do comprador visível e completa para qualquer pedido personalizado com histórico; badge de ambiguidade quando aplicável; ação de recarregar conversa funcional.

---

### F1.3 · Roteador de provedores de IA (Gemini + OpenRouter)

**Problema.** `run_model()` está acoplado ao Gemini: importa `google.genai` diretamente, mantém singleton de módulo `_genai_client`, e valida contra `ALLOWED_MODELS` com três modelos Gemini. Não há como usar OpenRouter.

> **Achado de segurança colateral:** `_get_genai_client()` contém `print("Caminho do .env:", find_dotenv())` e `print(api_key[-4:])` — vaza fragmento de credencial em stdout. Remover na mesma alteração.

**Desenho proposto.**

Novo módulo `packages/shared/nistiprint_shared/services/ai/` com:

```
ai/
├── __init__.py
├── router.py          # seleciona provider por config, aplica fallback
├── base.py            # interface AIProvider: complete(system, user) -> AIResponse
├── gemini_provider.py # wrapper do google.genai atual
└── openrouter_provider.py  # POST /api/v1/chat/completions
```

**Interface.**

```python
@dataclass(frozen=True)
class AIResponse:
    text: str
    provider: str          # "gemini" | "openrouter"
    model_requested: str    # ex.: "openrouter/auto"
    model_used: str | None  # OpenRouter devolve o modelo real escolhido
    usage: dict | None
    latency_ms: int

class AIProvider(Protocol):
    name: str
    def complete(self, system_prompt: str, user_payload: str) -> AIResponse: ...
```

**Configuração** (em `configuracoes_aplicacao`, categoria `ia`):

| `nome` | `tipo_valor` | Default | `protegido` |
|---|---|---|---|
| `ia_provider` | string | `gemini` | não |
| `ia_model` | string | `gemini-2.0-flash` | não |
| `ia_fallback_provider` | string | *(vazio)* | não |
| `ia_timeout_seconds` | int | `30` | não |
| `ia_max_processing` | int | `50` | não |

Chaves de API seguem em variável de ambiente (`NISTIPRINT_AI_KEY` para Gemini, `OPENROUTER_API_KEY` para OpenRouter) — **nunca em `configuracoes_aplicacao`**. Ambas precisam ser adicionadas ao `.env.example`, onde hoje não constam.

**OpenRouter.** `POST https://openrouter.ai/api/v1/chat/completions`, headers `Authorization: Bearer $OPENROUTER_API_KEY`, `HTTP-Referer` e `X-Title` para atribuição. Suporte a `model = "openrouter/auto"` (roteamento automático, como no legado) e a modelos explícitos. A resposta traz o modelo efetivamente usado — **persistir em `logs_execucao_ia.metadata`**, senão perde-se rastreabilidade de qual modelo produziu cada nome.

**Validação de modelo.** Substituir `ALLOWED_MODELS` fixo por validação por provider: Gemini mantém allowlist; OpenRouter aceita `openrouter/auto` e qualquer `vendor/model` com formato válido.

**Reaproveitar o cliente HTTP existente.** O módulo já tem `_httpx_client` com pool configurado — usar o mesmo, não criar outro.

**Fallback.** Se `ia_fallback_provider` estiver configurado e o primário falhar (timeout, 5xx, resposta não-JSON), tentar o secundário uma vez e registrar em `logs_execucao_ia` qual foi usado.

**Parsing.** O tratamento atual (`replace("```json","")` + `json.loads`) é frágil e vale generalizar: extrair o primeiro bloco JSON válido por regex, com erro tipado quando não houver.

**Arquivos.** Novo pacote `services/ai/`; refatorar `ai_personalization_service.run_model`, `get_model_name`, `get_ai_config`, `update_ai_config`, `_get_genai_client`; UI em `/personalizados/config`.

**Testes.** Estender `test_ai_personalization_service.py`: seleção de provider por config, `openrouter/auto` com `model_used` diferente do requisitado, fallback acionado, parsing de resposta suja, timeout.

**Aceite.** Alternar entre Gemini e OpenRouter apenas por configuração, sem deploy; `openrouter/auto` processando pedidos reais; `logs_execucao_ia` registrando provider e modelo efetivo.

---

### F1.4 · Religar o processamento em lote

Com F0.3, F1.1 e F1.3 concluídos, processar os pedidos elegíveis. O filtro atual (`canal Shopee` + `situação Em Andamento` + item `personalizado`) **está correto e não deve mudar**.

Piloto: os ~321 pedidos hoje elegíveis, em lote controlado, com revisão manual da amostra antes de liberar o processamento automático.

**Aceite.** ≥ 90% dos pedidos elegíveis processados; `personalizacoes_pedido` com volume compatível; taxa de acerto validada em amostra de 50 pedidos.

---

## FASE 2 — Consolidação inteligente (2 semanas)

### Diagnóstico refinado

A observação está correta: **o agrupamento existe, mas frequentemente cria um rascunho por pedido**. Os dados mostram o padrão exato:

| Canal | Modalidade | Pedidos por demanda |
|---|---|---|
| 27 | EXPRESS / Flex | 31, 31, 23, 11, 7, 6, 4, 3, 3, 2, 2 — **agrupa bem** |
| 31 | STANDARD | 1, 1, 1, 1, 1, 1, 1 — **nunca agrupa** |
| 27 | STANDARD (demanda #23) | **1.038** — agrupou demais |

Quatro defeitos identificados no código:

**D1 — A janela de agrupamento não tem relação com o horário de corte.**
`regras_consolidacao_canal` tem uma única regra global com `janela_agrupamento_horas = 4`, e `_adicionar_ao_rascunho` reabre a janela a cada pedido (janela deslizante). No canal EXPRESS o volume é alto e a janela nunca fecha — agrupa. No STANDARD chega ~1 pedido por dia, a janela de 4h sempre expirou — nunca agrupa.
**O critério de negócio correto não é "4h após o último pedido", é "todos os pedidos que compartilham a mesma janela logística de coleta"** — exatamente o que `logistica_coleta_service.calcular_data_coleta()` já retorna.

**D2 — Janela deslizante sem teto.** A demanda #23 ficou aberta 6 dias e acumulou 1.038 pedidos, porque cada novo pedido empurrava `rascunho_expira_em` adiante. Não existe limite absoluto.

**D3 — Assimetria entre a chave e a busca.** `_calcular_chave()` compõe `produto_id`, `miolo_id` e `data_entrega`, mas `_buscar_rascunho_compativel()` filtra **apenas** `canal_venda_id`, `modalidade_logistica`, `is_flex`, `rascunho_expira_em` e opcionalmente `produto_id`. Pior: `pedido.get('produto_id')` e `pedido.get('id_produto_miolo')` **não existem na tabela `pedidos`** — retornam sempre `None`. Ou seja, as três flags `agrupar_por_*` estão `true` na regra e **não têm efeito algum**.

**D4 — Duas fontes de horário logístico.** O docstring de `consolidar_pedido` diz *"3. Resolver horário de coleta (`regras_logisticas_canal`)"* — a tabela legada com 1 linha — enquanto o serviço canônico é `logistica_coleta_service` sobre `regras_logisticas_integracao`. E pedido sem `canal_venda_id` faz `return None` logo no início, o que exclui 100% dos pedidos ML.

### F2.1 · Trocar a janela temporal pela janela logística

**Fazer.**

1. Substituir `janela_agrupamento_horas` por **chave de janela logística**: `(marketplace_integration_id, modalidade, data_coleta, horario_coleta)` — derivada de `logistica_coleta_service.calcular_data_coleta()`, que já devolve dia e horário de coleta considerando corte, dias da semana e prioridade
2. Persistir a janela resolvida em `demandas_producao` (`data_coleta` e `horario_coleta` já existem como colunas)
3. Rascunho fecha automaticamente no **horário de corte**, não N horas após o último pedido
4. Manter `janela_agrupamento_horas` apenas como fallback quando não houver regra logística cadastrada, com teto absoluto (D2): `rascunho_expira_em` nunca ultrapassa `criado_em + 24h`

**Dependência.** Exige as regras logísticas cadastradas (F2.4). Sem elas, todo canal cai no fallback.

### F2.2 · Alinhar chave e busca

**Fazer.**

1. `_buscar_rascunho_compativel()` passa a aplicar **todos** os campos da chave que estiverem preenchidos — incluindo `data_entrega` e a nova janela de coleta
2. Resolver de fato `produto_id` e `id_produto_miolo` (hoje sempre `None`): derivar dos itens do pedido, ou desligar as flags `agrupar_por_produto` / `agrupar_por_miolo` na regra até que a resolução exista. **Não deixar flag ligada sem efeito**
3. Tratar `canal_venda_id IS NULL` explicitamente — depende de F0.3, que preenche o canal para ML

### F2.3 · Publicação de demanda

Nenhuma das 39 demandas foi publicada (`publicado_em` sempre nulo). Definir e implementar o gatilho: publicação automática no horário de corte, ou manual com o corte como prazo sugerido. **Sem publicação, a produção nunca começa** — é o que trava a Fase 3.

### F2.4 · Cadastrar as regras logísticas reais

Não é código — é cadastro, mas é **pré-requisito de F2.1**. Hoje existem 2 regras, ambas FLEX, ambas `COLETA_LOCAL`, ambas com `ponto_coleta_id` nulo.

Mínimo necessário:

- Uma regra **STANDARD** por canal ativo (hoje nenhuma existe → todo pedido STANDARD cai em `SEM_REGRA`)
- A **regra alternativa** do cenário descrito: coleta local 12h (`prioridade_uso` alta) + ponto de coleta 17h (`prioridade_uso` menor, `ponto_coleta_id` preenchido). O motor já ordena por horário e prioridade — **é só cadastro**
- Popular `pontos_coleta` (hoje 1 linha)

**Aceite da fase.** Pedidos do mesmo grupo logístico caem na mesma demanda independentemente do intervalo entre eles; nenhuma demanda excede o teto de janela; demandas publicam no corte.

---

## FASE 3 — Estoque canônico (2 semanas)

### F3.1 · Eleger o v2 e remover o v1

**Confirmado: o v2 é o mais recente e o correto.**

| | v1 `motor_reconciliacao_estoque` | v2 `motor_estoque_v2` |
|---|---|---|
| Data no cabeçalho | 2026-03-25 | **2026-05-08** |
| Liquidação | Só na finalização (E7) | **Por etapa (E1, E2, E4, E7)** |
| Sincronismo | Assíncrono via fila | **Síncrono (Dashboard → transação)** |
| Idempotência | Por item | **Por `lote_id`** |
| Reversibilidade | Não explícita | **Por deltas negativos** |
| Cobertura de teste | nenhuma | `test_motor_estoque_v2.py` |

**A semântica de delta do v2 já é exatamente a descrita.** Em `_emitir_delta_movimentos`:

```python
delta_estoque = alvo.estoque - consumido_ledger
if delta_estoque != 0:
    movs.append({
        'tipo_movimentacao': 'CONS_INT',
        'quantidade': float(-delta_estoque),  # Consumo é negativo
    })
```

Incrementar a coluna no dashboard → `delta_estoque > 0` → movimento **negativo** = alocação do intermediário na demanda = **saída do estoque**. Decrementar → delta negativo → movimento **positivo** = **retorno ao estoque**. É a operação inversa descrita, e já está implementada.

**Problema real: os dois motores estão ligados em paralelo, com premissas conflitantes.**

| Chamador | Motor |
|---|---|
| `demanda/items.py` (dashboard, `registrar_producao_incremental` e `registrar_producao_lote`) | **v2** |
| `demanda_alocacao/estoque.py:399` | **v2** |
| `demanda_alocacao/estoque.py:143,163,252` (`_explodir_bom_consumo`, `processar_fila_unificada`) | **v1** |
| `worker/tasks/eventos_tasks.py:39` (`process_eventos_producao_task` — **ainda executando**, 1.843 rodadas) | **v1** |
| `api/routes/tasks_api.py:404,427` | **v1** |
| `consolidador_estoque.py`, `worker_reconciliacao_estoque.py` | **v1** |

O mesmo arquivo `demanda_alocacao/estoque.py` importa os dois. O dashboard escreve pelo v2 (liquidação por etapa) enquanto o worker reconcilia pelo v1 (liquidação só na finalização). **Hoje o conflito é invisível porque as tabelas estão vazias — no dia em que o estoque for ligado, ele se manifesta imediatamente como divergência de saldo.**

**Fazer.**

1. Declarar o v2 como motor canônico em `docs/specs/02-domains/estoque/spec.md`
2. Migrar `demanda_alocacao/estoque.py` para usar exclusivamente o v2 — reimplementar `_explodir_bom_consumo` sobre o `_computar_mp_alvo` do v2
3. Substituir `process_eventos_producao_task` (v1) por consumidor equivalente do v2, ou desativá-lo se o caminho síncrono do dashboard já cobre o caso
4. Remover de `tasks_api.py` os endpoints que chamam o v1
5. Deletar `motor_reconciliacao_estoque.py`, `consolidador_estoque.py`, `worker_reconciliacao_estoque.py` e os `.bak`/`.legacy` de estoque (`estoque_service_atomic.py.bak`, `estoque_service_updated.py.bak`, `stock_reconciliation_service.py.bak`, `stock_tasks.py.bak`, `stock_tasks.py.legacy`)

**Aceite.** Uma única referência de motor no código; `grep motor_reconciliacao_estoque` retorna vazio; testes do v2 passando.

### F3.2 · Ampliar cobertura de teste do v2

Antes de ligar com dados reais, cobrir: reversão por delta negativo (o caso do dashboard decrementado), idempotência por `lote_id` repetido, invariante de intermediário não-negativo, explosão de BOM multinível, e produção JIT quando o saldo não cobre o alvo.

**Aceite.** Cobertura dos cinco cenários com asserts sobre os movimentos emitidos.

### F3.3 · Cadastro de produtos *(ação humana, fora do caminho crítico)*

Conforme decidido, o cadastro é responsabilidade humana. Registro do tamanho do trabalho para dimensionamento: **298 dos 322 SKUs externos** distintos não têm correspondente no catálogo. A resolução hoje é por igualdade exata contra `produtos.sku`.

**Apoio de engenharia (pequeno, alta alavancagem):**

1. Fazer o resolvedor consultar `produtos_externos` (`produto_id`, `codigo_externo`, `plataforma`) **antes** de cair no `sku` exato — a tabela existe e está vazia
2. Tela de de-para com os SKUs não resolvidos ranqueados por volume de pedidos, para o cadastro atacar primeiro o que mais aparece
3. Alerta quando um SKU novo aparecer sem correspondência

**Aceite.** Tela de de-para funcional; resolvedor consultando `produtos_externos`; ranking por volume disponível.

---

## FASE 4 — Impressão e coleta parcial (1 semana)

### F4.1 · Replicar a ordenação do legado 🔧

**Confirmado: a ordenação atual está incompleta.** O legado (`kb/legado/services/bling/bling.py:227-234`) documenta e implementa:

```python
""" Ordena por:
    1. itens personalizados: não depois sim (agrupa pedidos com item personalizado)
    2. quais itens personalizados: ordem alfabética (agrupa os personalizados por modelo)
    3. quantidade total de itens: ordem crescente
    4. quantos itens diferentes: ordem crescente
"""
bling_orders_data.sort(key=lambda x: (
    x['hasCustomItem'],
    x['total_items'],
    len(x['itens']),
    len([item for item in x['itens'] if item['custom_tag'] != '']),
    next((item['custom_tag'] for item in x['itens'] if item['custom_tag'] != ''), '')
))
```

A versão atual (`impressao.py`) faz apenas:

```python
orders_data.sort(key=lambda order: (
    0 if order.get('hasCustomItem') == 0 else 1,
    str(order.get('numeroLoja') or ''),
))
```

O primeiro critério está certo (não-personalizados primeiro), mas os quatro seguintes foram substituídos por `numeroLoja` — **o que destrói o agrupamento dos personalizados por modelo**, que é justamente o ganho operacional da ordenação.

**Fazer.** Substituir pela chave de 5 elementos do legado, adaptando os nomes de campo (`total_items`, `itens`, `custom_tag` já existem no dict montado por `_build_order_print_data`).

**Aceite.** Ordem de impressão idêntica à do legado para o mesmo conjunto de pedidos — validar comparando as duas saídas lado a lado.

### F4.2 · Garantir exibição do nome da personalização

**O template já está correto.** `PrintTemplate.jsx:324-340` renderiza `p.customization_name`, `p.customization_initial` e `quantity_to_personalize`. Não há alteração de frontend necessária.

**Mas a fonte de dados não entrega.** `_build_order_print_data` busca personalizações com `.eq('shopee_order_sn', codigo_pedido_externo)` numa tabela com **1 linha** — o nome nunca aparece na prática. Isso se resolve com a Fase 1; nada a fazer aqui além de validar após F1.4.

### F4.3 · Corrigir dois bugs latentes na impressão 🐛

1. **`vinculos_integracao_pedido` tem 0 linhas.** `_build_order_print_data` lê essa tabela e, **se o parâmetro `plataforma` for informado, retorna `None` para todos os pedidos** (`if not vinculos: return None`). Hoje o frontend não passa o parâmetro, então não quebra — mas é uma armadilha. Além disso, `plataforma_nome` fica sempre vazio, e o `PrintTemplate` usa `order.plataforma` para ícone e cabeçalho. Derivar de `marketplace_module_id` do próprio pedido
2. **Campo `variacao` fixo em `None`** com `# TODO: adicionar coluna se necessário` — confirmar se o legado imprime variação e, em caso positivo, popular

### F4.4 · Persistir coleta parcial como evento

**Problema.** `demanda_producao_service.registrar_coleta()` tem TODO explícito: `ponto_coleta_id` e `observacoes` **são recebidos e descartados**, com log informando que foram ignorados. Não há histórico — só um contador mutável.

**Fazer.**

1. Nova tabela `eventos_coleta`: `demanda_id`, `quantidade`, `ponto_coleta_id`, `transportadora`, `observacoes`, `user_id`, `created_at`, `estornado_de_id` (para reversão auditável)
2. `registrar_coleta_parcial` grava o evento e recalcula o contador a partir da soma dos eventos — contador vira projeção, não estado primário
3. Remover o TODO e persistir os dois campos
4. Exibir o histórico de coletas no card da demanda

**Nota de escopo.** `print_jobs` **não faz parte deste trabalho** — é a funcionalidade futura de envio das artes (capas, contracapas) direto pelo sistema.

**Aceite.** "Transportadora coletou 20/30" registrado com ponto, transportadora, responsável e timestamp; histórico visível; estorno auditável.

---

## FASE 5 — Segurança, efeitos e dívida (2 semanas, paralelo)

### F5.1 · Exibir os alertas de cancelamento na demanda

> **Revisado.** A recomendação original era "criar o worker consumidor". **O consumidor já existe** (`marketplace_lifecycle_tasks.process_pending_effects`, idempotente por `(transition_id, effect_type)`) — só não estava sendo disparado. Isso é F0.4.

Depois que F0.4 drenar os 261 efeitos, resta a ponta de UI: garantir que os registros gerados em `alertas_demanda` (hoje 0 linhas, tabela pronta) apareçam no card da demanda e no kanban. **Pedido cancelado no marketplace precisa ser visível para quem está produzindo.**

O acúmulo não duplica — os efeitos são idempotentes, então drenar 261 de uma vez é seguro.

### F5.2 · Políticas RLS

99 das 117 tabelas com RLS habilitado e **zero policies**. Funciona só porque o backend usa `service_role`. Escrever policies para as tabelas expostas ao cliente, ou registrar formalmente em `docs/specs/01-system/security-and-rls.md` a decisão de operar exclusivamente via `service_role`, com os controles compensatórios.

### F5.3 · Eleger fonte de verdade única

| Domínio | Manter | Deprecar |
|---|---|---|
| Vínculo canal ↔ integração | `erp_marketplace_links` + `channel_connections` (definir qual) | `integracao_canais_config` |
| Regra logística | `regras_logisticas_integracao` | `regras_logisticas_canal`, `canal_modalidade_mapeamento` |
| Timeline de pedido | `marketplace_order_transitions` | `eventos_pedido`, `transicoes_situacao` |
| Motor de estoque | `motor_estoque_v2` | `motor_reconciliacao_estoque` (F3.1) |

Corrigir também os **2 links com `marketplace_integration_id = NULL`** (`amazon_fulfillment`, `mercadolivre`/ERP 3) e o drift correspondente em `channel_connections`.

### F5.4 · Higiene de repositório

Remover os `.bak`/`.legacy` versionados (11 arquivos) e a tabela `_snapshot_produtos_tipo_20260508`.

### F5.5 · Triagem de erros

- 14 transições `unmapped` (Shopee) sem processo
- 867 `mercadolivre_webhook_done/error` (58% de taxa de erro)
- 219 ML `skipped_unresolved_payment_reference`
- 809 `shopee_webhook_done/pending` nunca finalizados

Criar tela de triagem e alerta por limiar.

---

## 6. Sequenciamento e dependências

```
AGORA (minutos)
  F0.4 reiniciar beat ──> drena 1.609 reconciliações + 261 efeitos
  F0.6 autoridade Bling ──> antes do Bling voltar a volume

HOJE / ESTA SEMANA
  F0.5 observabilidade de tasks
  F0.1 confirmar env + alerta de assinatura
  F0.3 enriquecimento ingest ────┐
  F0.8 validar kwargs            │
                                 │
        ┌────────────────────────┘
        v
F1.1 vínculo username          F2.1 janela logística  <── F2.4 cadastro regras
F1.2 chat na tela              F2.2 chave × busca
F1.3 roteador IA                        │
        │                               v
        v                          F0.7 religar consolidação
F1.4 lote em produção                   │
        │                               v
        │                          F2.3 publicação
        │                               │
        v                               v
F4.1 ordenação legado            F3.1 v2 canônico  <── F3.3 cadastro produtos
F4.2 nome personalização         F3.2 testes v2
F4.3 bugs impressão
F4.4 eventos de coleta

F5.* em paralelo (F5.1 depende de F0.4)
```

**Bloqueios duros:**

- F1.* inteira depende de **F0.3** — sem `buyer_username` não há chat, e sem chat não há IA
- **F0.7 não pode vir antes de F2.1/F2.2** — religar a consolidação com a regra de janela atual reproduz o defeito
- F2.1 depende de **F2.4** (cadastro de regras logísticas — ação humana)
- F3.* depende de **F2.3** (sem demanda publicada não há produção) e de **F3.3** (cadastro de produtos — ação humana)
- F4.2 depende de **F1.4**
- **F0.6 é corrida contra o tempo**: o ingest Bling voltou em 01/08 15:54; cada webhook até a correção pode sobrescrever estado de pedido `marketplace_direct`

**Duas ações humanas estão no caminho crítico** e devem começar já, em paralelo à Fase 0: cadastro das regras logísticas (F2.4) e de-para de produtos (F3.3).

---

## 7. Critérios de saída

| Fase | Métrica de saída | Hoje |
|---|---|---|
| F0 | `pending_order_reconciliations` | 1.609 → **< 50** |
| F0 | `marketplace_order_effects` pendentes | 261 → **0** |
| F0 | Tasks agendadas com registro de execução | 2 de 4 → **4 de 4** |
| F0 | `discarded_invalid_signature` | 7/dia → **0, com alerta ativo** |
| F0 | Pedidos novos com enriquecimento completo | 11,4% → **≥ 98%** |
| F0 | Webhook Bling sobrescreve pedido `marketplace_direct` | sim → **não** |
| F1 | Pedidos personalizados com chat associado | 0,4% → **≥ 80%** |
| F1 | Provider de IA alternável por configuração | não → **sim** |
| F1 | `personalizacoes_pedido` | 1 → **≥ 90% dos elegíveis** |
| F2 | Pedidos STANDARD por demanda | 1,0 → **> 1 quando compartilham janela** |
| F2 | Demandas publicadas | 0 → **> 0** |
| F3 | Motores de estoque no código | 2 → **1** |
| F3 | SKUs externos resolvidos | 7,5% → **≥ 90%** |
| F4 | Ordenação de impressão idêntica ao legado | não → **sim** |
| F4 | Coleta parcial com ponto e histórico | não → **sim** |
| F5 | `marketplace_order_effects` pendentes | 260 → **0** |

---

*Plano derivado do assessment de 01/08/2026. Todos os diagnósticos são baseados em leitura de código e medição direta no banco de produção.*
