# Diagnóstico: agendamentos e ingest — 01/08/2026

Levantamento feito direto no banco de produção (`cfknrplrqvyirjxovuvi`) e no
código. Nada foi alterado além do que está registrado nas migrations
`20260801000000` e `20260801010000`. Os itens abaixo são diagnóstico.

---

## 1. URGENTE — o ingest do Bling está parado há 3 dias

Nenhum webhook do Bling é processado com sucesso desde **29/07 às 18:36**.

| Dia | Descartados por assinatura | Sucesso |
|---|---|---|
| 21/07 a 28/07 | 0 | 29 a 74 por dia |
| 29/07 | 4 | 30 |
| **30/07** | **1.132** | **0** |
| **31/07** | **1.689** | **0** |
| 01/08 (parcial) | 4 | 0 |

Corte limpo entre 29 e 30/07: de zero descartes para 100% descartados, com
`last_status = discarded_invalid_signature`. Shopee e Mercado Livre seguem
saudáveis no mesmo período (último sucesso Shopee 01/08 12:08).

Isso não é regressão do trabalho de canonização — é anterior e independente.

**Causa confirmada.** Em 30/07 00:22 o workflow n8n `Bling Webhook Handler` foi
reduzido a proxy durável: ele deixou de validar HMAC e passou a apenas montar o
envelope (preservando `raw_body` e `x-bling-signature-256`) e enfileirar. A
validação migrou para o app, em `reliable_ingest_service.validate_signature`,
que lê os segredos de `INGEST_WEBHOOK_SECRETS_BLING`.

O `.env.example` traz `INGEST_WEBHOOK_SECRETS_BLING=...` — **literalmente três
pontos**, como placeholder. Copiado para produção, `_secrets()` devolve `["..."]`:
lista não-vazia, sem segredo algum. E o caminho "há assinatura e há segredos, mas
nenhum bate" produz `SignatureResult(..., valid=False, enforce=True)`, cujo
`terminal` é **True independente da política**.

Ou seja: a política `optional` protegia o caso "não configurei" e não protegia o
caso "configurei errado" — que é o cenário provável de toda migração. Um
placeholder virou descarte terminal de 2.829 eventos.

**Correção aplicada** (ver §6): segredo passa a vir do banco, placeholders são
filtrados, e ausência de segredo utilizável volta a produzir
`signature_unverified` em vez de descarte.

**Integridade do corpo verificada.** O HMAC é sobre os bytes exatos, então o
`raw_body` precisa sobreviver intacto ao trajeto n8n → Redis → Postgres. Medido
em 2.835 eventos: `sha256(convert_to(raw_body,'UTF8')) = payload_hash` em 100%
dos casos, sem nenhum caractere não-ASCII (o payload do Bling tem 367–397 bytes
e carrega apenas IDs, timestamps e `companyId`). O round-trip não é fonte de
falha de assinatura.

O único elo não verificável com os dados atuais é o **formato do header**
(`x-bling-signature-256`: hex ou base64, com ou sem prefixo), porque o header
não é persistido — só o corpo. Persistir o header junto do `raw_body` tornaria
esse tipo de diagnóstico possível sem esperar tráfego novo. Enquanto isso, as
duas implementações de HMAC aceitam hex **e** base64, o que remove a dependência
de acertar o formato.

### Validação na borda (n8n)

> Convenção adotada: **a decisão de autenticidade vive no n8n**. Ver
> `docs/tecnico/convencao-validacao-assinatura.md`.

O workflow `Bling Webhook Handler` passou a validar HMAC antes do envelope, para
que tráfego inválido não entre na fila. Nós `Verify Bling Signature` e
`Assinatura aceita?`; segredos em `BLING_CLIENT_SECRETS` (array JSON).

Estreia em **modo observação**: o veredito é calculado e anexado ao item, mas
nada é bloqueado até `BLING_SIGNATURE_ENFORCE=true`. Sem segredo utilizável ou
sem header, o resultado é `signature_unverified` — nunca `invalid`. Placeholders
e valores com menos de 8 caracteres são descartados da lista, pela mesma razão
que no app.

**Custo assumido:** o segredo do Bling passa a existir em dois lugares — o env
do n8n e o banco lido pelo app. É a mesma duplicação que causou o incidente
original, aceita conscientemente em troca de filtrar na borda. Cadastrar uma
quarta conta Bling exige atualizar `BLING_CLIENT_SECRETS` também; se isso for
esquecido, o modo observação evita o outage, mas o enforcement passará a
rejeitar aquela conta.

**Impacto enquanto durou:** nenhuma atualização de status vinda do ERP chegou, e
nenhum pedido ganhou identidade Bling por webhook — só pela reconciliação, que
também está desligada (§2).

---

## 2. Agendamentos

`load_dynamic_schedules()` lê `configuracoes_aplicacao.celery_task_schedules`.
Os defaults de `get_default_schedules()` só valem se essa configuração **não
existir**. Ela existe. Logo, o banco é a fonte efetiva.

| Task | Banco | Código | Roda de fato |
|---|---|---|---|
| `renew-app-managed-credentials` | true, 7200s | 7200s | ✅ 7200s |
| `processar-eventos-producao-periodic` | true, 300s | 10s | ⚠️ 300s |
| `reconcile-pending-erp-references` | **false** | 60s | ❌ não roda |
| `process-marketplace-lifecycle-effects` | **false** | 30s | ❌ não roda |
| `consumir-fila-bling` | **true**, 60s | — | ❌ filtrada |
| `consumir-fila-shopee` | **true**, 60s | — | ❌ filtrada |
| `consumir-fila-mercadolivre` | **true**, 60s | — | ❌ filtrada |
| `reconcile-marketplace-lifecycle` | false, 300s | — | ❌ não roda |
| `renew-shopee-tokens` | false | — | ❌ |
| `consolidar-pedidos-pendentes` | false | — | ❌ |
| `sync-firestore-tokens` | false | — | ❌ filtrada |

**Duas tasks ativas no total.** Consequências medidas:

- 1.398 pedidos aguardando número Bling em `pending_order_reconciliations`,
  sem consumidor.
- 249 efeitos pendentes em `marketplace_order_effects` desde 29/07 — alertas de
  cancelamento e devolução não entregues.

Note a data: 29/07 é a mesma do corte do Bling e do item mais antigo das duas
filas. Provavelmente um único evento operacional desligou várias coisas juntas.

### 2.1 Ambiguidades a remover

**A. `enabled: true` que não roda.** As três `consumir-fila-*` estão ativas no
banco e bloqueadas em runtime pelo set `obsolete_webhook_tasks`
(`celery_config.py:66-84`). O log justifica com *"As credenciais Bling agora sao
gerenciadas pelo app"* — justificativa que não tem relação com consumir fila de
webhook. Quem lê a configuração conclui que estão rodando.

*Conclusão da investigação:* Shopee e Mercado Livre continuam ingerindo
normalmente sem essas tasks, o que confirma que o caminho novo
(`reliable_ingest_worker`) cobre o consumo e as tasks são de fato obsoletas.
Para o Bling não dá para afirmar o mesmo, porque o tráfego está sendo descartado
antes (§1) — a fila não é o gargalo hoje. **Ação: remover as entradas do banco
depois que o §1 estiver resolvido e o Bling voltar a ingerir**, para não
confundir dois problemas.

**B. Defaults que mentem.** `get_default_schedules()` aparenta ser a
configuração real e é fallback morto. `processar-eventos-producao` declara 10s
no código e roda a 300s. Ou o código vira só documentação explícita do fallback,
ou os dois passam a ser gerados da mesma fonte.

**C. `kwargs` descartados silenciosamente.** `load_dynamic_schedules()` monta
apenas `{'task', 'schedule'}` e ignora `kwargs`. A entrada
`reconcile-marketplace-lifecycle` tem `{"dry_run": true, "days": 90, "limit":
100}` no banco; ao ser habilitada, rodaria com os defaults da assinatura —
`dry_run=True` por coincidência, mas `days=60` em vez de 90. Uma task de backfill
configurada como segura pode rodar diferente do configurado. **Ação: propagar
`kwargs` ou rejeitar entradas que os declarem.**

---

## 3. Autoridade do Bling sobre pedidos `marketplace_direct`

Handler localizado: `packages/shared/nistiprint_shared/services/bling_order_processing_service.py`.

- `_upsert_pedido_master:1703` chama `_resolve_situacao_interna(bling_integration_id, payload.situacao.id)`
- `:1752` grava `situacao_pedido_id` direto no row

Não há checagem de autoridade: um webhook do Bling sobrescreve o estado de um
pedido cujo ciclo pertence ao marketplace. O vínculo já é resolvido logo abaixo
(`resolve_erp_marketplace_link`, `:1718`), então o enxerto é curto — passar
`situacao_pedido_id=None` quando
`is_authoritative(link['ingest_origin_mode'], 'erp', 'order')` for falso.

O lado marketplace já está protegido
(`marketplace_webhook_ingest_service.py:555`).

---

## 4. Conta ERP é dinâmica — confirmado

Nada no caminho de reconciliação está preso a uma conta específica:

- `order_erp_reference_service` resolve por
  `integration_capability_service.resolve(marketplace_integration_id, INVOICING)`
  e agrupa lotes por `(erp_integration_id, store_id)`.
- `_resolve_situacao_interna` passa `integration_id=bling_integration_id`.
- O backfill de `20260801010000` usa `p.erp_integration_id` da própria linha.

A observação "conta 1" no diagnóstico anterior era do dado atual, não premissa.
O defeito do índice `NULLS NOT DISTINCT` também não dependia disso: a chave
`(qualquer_conta, NULL, 'pending')` colidia, então com N contas ERP a fila
comportaria N pedidos em vez de 1 — o mesmo bug, apenas multiplicado.

---

## 6. Correção do segredo de webhook — implementada

`packages/shared/nistiprint_shared/services/webhook_secret_resolver.py` (novo) e
`reliable_ingest_service.py`.

**Segredo vem do banco**, com cache de processo e TTL de 5 min. Env vira fallback
de emergência, não fonte. Cadastrar a 4ª conta Bling pela interface passa a
bastar — antes, o OAuth e a API funcionavam e os webhooks eram descartados em
silêncio.

Cada provider guarda o segredo em um lugar diferente, porque o modelo de
aplicativo é diferente. Tratar os três igual gerou avisos falsos na primeira
publicação:

| Origem | Modelo | Segredo | Onde |
|---|---|---|---|
| Bling | 1 app por conta | `client_secret` | cofre `app_profile` (3) + `credentials` |
| Shopee | 1 app parceiro para N lojas | `partner_key` | cofre `app_profile` (1) |
| Mercado Livre | 1 app para N contas | `client_secret` | **não cadastrado** |

Restringir a validação a uma conta só faz sentido quando cada conta tem segredo
próprio — ou seja, apenas no Bling. Shopee e Mercado Livre usam o segredo do
perfil, compartilhado.

O cofre (`integration_secret_values`, cifrado) é consultado primeiro, via
`integration_secret_service.get_secret_map`; `credentials` em texto claro
permanece como compatibilidade.

**Validação contra uma conta, não contra todas.** O payload do Bling traz
`companyId`. Com o vínculo `companyId → integração` conhecido, valida-se apenas
o segredo daquela conta. Isso não é otimização: testar todos os segredos permitia
que a conta A assinasse um evento declarado como da conta B e fosse aceito.

**O vínculo é aprendido, não configurado.** `companyId` desconhecido cai no
try-all; ao acertar, o par é gravado em `installed_integrations.config`. O
aprendizado só ocorre a partir de assinatura válida — caso contrário qualquer
emissor escolheria seu próprio vínculo.

**Placeholders são rejeitados.** `is_usable_secret` descarta `...`, `changeme`,
`secret` e valores com menos de 8 caracteres, com log. Sem segredo utilizável, o
resultado volta a ser `signature_unverified` (não terminal) e o motivo registrado
é `no_usable_secret` — o operador vê a causa em vez de um descarte mudo.

Testes: `tests/services/test_webhook_secret_resolver.py`, incluindo o cenário
exato do incidente. Duas fixtures antigas usavam `"secret"` como segredo e foram
atualizadas — o valor era incidental e hoje é justamente o que o filtro rejeita.

**Avisos são por origem, não por evento.** Em volume alto, um aviso por webhook
treina a equipe a ignorar avisos — que é exatamente como o incidente de 30/07
passou três dias despercebido.

### Estado de verificação após a correção

Cada origem tem um mecanismo diferente, porque cada provider oferece um
mecanismo diferente:

| Origem | Mecanismo | Onde |
|---|---|---|
| Bling | HMAC `client_secret`, por conta | app (`validate_signature`) |
| Shopee | HMAC `partner_key`, compartilhado | n8n valida; app é fallback |
| Mercado Livre | **allowlist de IP** — não há assinatura | n8n, na borda |

**Mercado Livre não assina os webhooks.** Confirmado nos cabeçalhos de tráfego
real: `connection, host, x-forwarded-*, x-real-ip, content-length, user-agent
(github.com/go-loco/restful), accept, content-type, traceparent, x-b3-*`. Não há
`x-signature`. O `_validate_meli` do app, que implementa o HMAC de manifesto
documentado pelo ML, nunca teve material para validar — sempre
`missing_signature_material`.

A garantia de origem passou a ser a faixa de IPs publicada pelo ML, checada no
workflow n8n `MercadoLivre Webhook Handler` (nós `Resolve Client IP` e
`IP autorizado?`), antes do envelope e de qualquer persistência. IP fora da lista
recebe 403 e não entra no inbox nem na fila legada.

**Qual IP é confiável.** O proxy reverso *acrescenta* o peer real ao final de
`X-Forwarded-For`; o primeiro item é o que o cliente enviou e é forjável. A
guarda usa `X-Real-IP` (que o proxy define com `$remote_addr`) e, na falta dele,
o **último** item de `X-Forwarded-For`. Tráfego real confirma um único IP em
ambos os cabeçalhos. Se um segundo proxy entrar na cadeia, este cálculo precisa
ser revisto.

Nenhum evento é descartado por falta de segredo: sem segredo utilizável o
resultado é `signature_unverified`, não terminal.

Pendente:

- Definir `INGEST_SIGNATURE_POLICY_BLING` explicitamente e confirmar que
  `INGEST_WEBHOOK_SECRETS_BLING` e `..._MERCADOLIVRE` estão **vazias ou
  ausentes** em produção (o log acusa o placeholder uma vez por origem).
- Revisar a allowlist de IP do ML periodicamente: é configuração do provider e
  muda sem aviso. Uma mudança lá derruba o ingest do mesmo jeito que o
  placeholder derrubou o do Bling.

---

## 5. Ordem sugerida

1. **§1** — restabelecer o ingest do Bling. Bloqueia tudo que depende do ERP.
2. Habilitar `reconcile-pending-erp-references` — drena os 1.398.
3. Habilitar `process-marketplace-lifecycle-effects` — drena os 249. Efeitos são
   idempotentes por `(transition_id, effect_type)`, o acúmulo não duplica.
4. Ligar `is_authoritative` no handler Bling (§3) — fazer **antes** do Bling
   voltar a alto volume, senão ele reescreve estado de pedido direto.
5. Remover as entradas obsoletas do banco (§2.1-A).
6. Propagar `kwargs` (§2.1-C) e reconciliar defaults (§2.1-B).
