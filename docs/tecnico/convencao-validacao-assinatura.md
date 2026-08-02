# Convenção: validação de assinatura vive no n8n

Status: adotada em 01/08/2026.

## A regra

> **O n8n decide se um webhook é autêntico. O app registra a decisão e não a
> recalcula.**

Nenhum evento inválido deve entrar na fila. A consequência é que a inbox
(`np:ingest:inbox:ready:v1`) passa a ser um canal confiável por construção: tudo
que está lá já foi aceito na borda.

## Por que na borda

O ganho não é só de CPU. Rejeitar antes do envelope evita:

- espaço em Redis e no spool durável para tráfego que seria descartado;
- linhas em `webhook_events` que só existem para registrar uma rejeição;
- ciclos de worker fazendo HMAC de payload que já se sabia inválido;
- ruído de log que compete com sinal real.

Em 30/07 o Bling gerou 2.829 linhas de descarte em três dias. Com a validação na
borda, esse volume nem teria entrado.

## Mecanismo por origem

Cada provider oferece uma garantia diferente, e a convenção é sobre *onde* a
decisão acontece, não sobre *qual* mecanismo é usado.

| Origem | Mecanismo | Segredo / fonte | Onde |
|---|---|---|---|
| Bling | HMAC-SHA256 do corpo cru | `BLING_CLIENT_SECRETS` (array JSON, um por conta) | nós `Verify Bling Signature` / `Assinatura aceita?` |
| Shopee | HMAC-SHA256, veredito pós-ACK | `partner_key` do perfil parceiro | workflow Shopee, veredito em `np:ingest:signature:{event_id}` |
| Mercado Livre | allowlist de IP — **não há assinatura** | faixa publicada pelo ML | nós `Resolve Client IP` / `IP autorizado?` |

O Mercado Livre não assina nada: verificado nos cabeçalhos de tráfego real, não
existe `x-signature`. A garantia de origem é o IP de quem conecta.

## Regras que a convenção não dispensa

**1. Falta de material nunca vira "inválido".** Sem segredo configurado, ou sem
header de assinatura, o veredito é `signature_unverified` e o evento segue.
Só um HMAC calculado que *não bate* é rejeição. Confundir os dois foi a causa do
incidente de 30/07: um placeholder (`...`) em `INGEST_WEBHOOK_SECRETS_BLING`
produziu uma lista não-vazia sem segredo real, e todo evento virou descarte
terminal.

**2. Placeholder não é segredo.** Toda leitura de segredo descarta `...`,
`changeme`, `secret` e valores com menos de 8 caracteres, com log. Vale no n8n e
no app.

**3. Estreia em modo observação.** Ao ligar ou trocar a fonte de um segredo, o
veredito é calculado e registrado mas nada é bloqueado, até confirmação em
tráfego real. No n8n isso é `BLING_SIGNATURE_ENFORCE`; no app é
`INGEST_SIGNATURE_POLICY_<ORIGEM>=observe`. Promover só depois de ver
`signature_valid` numa execução.

**4. Aceitar hex e base64.** O formato do digest no header não é verificável sem
tráfego. Comparar contra as duas representações remove a dependência de acertar
o palpite.

**5. A inbox tem uma única porta.** A convenção só vale enquanto o n8n for o
único caminho até a fila. Ver abaixo.

## A porta paralela — removida em 02/08/2026

`POST /api/v2/webhooks/shopee` e `/mercadolivre` enfileiravam no **mesmo** inbox
sem validar assinatura, e o n8n nunca os usou — ele escreve direto no Redis.

Até 01/08/2026 `_marketplace_webhook_authorized()` era **fail-open**: sem
`MARKETPLACE_WEBHOOK_TOKEN` definido, aceitava qualquer requisição. A variável
não existia em nenhum `.env`. Qualquer um que conhecesse a URL podia injetar
eventos na fila.

A correção intermediária tornou a rota fail-closed. Mas trancar uma porta não é
o mesmo que não ter a porta: enquanto ela existir, a regra 5 acima depende de
alguém lembrar de mantê-la trancada a cada mudança.

**As duas rotas foram removidas.** A garantia "tudo que está na inbox foi aceito
na borda" agora é estrutural, não um acordo.

Para reinjetar um evento manualmente, use
`POST /api/v2/webhooks/events/<id>/reprocess`, que parte de um evento já
persistido e auditado — não de um payload cru vindo de fora.

`MARKETPLACE_WEBHOOK_TOKEN` deixou de ter uso e pode sair do ambiente.

## O que muda no app

O app **não deixa de ter** capacidade de validar — ela permanece como defesa em
profundidade e como caminho para eventos que cheguem sem veredito. O que muda é
a expectativa: a validação do app é rede de segurança, não o ponto de decisão.

Consequência prática: `webhook_events.signature_status` continua sendo a fonte de
auditoria, e o alerta de taxa de assinaturas inválidas
(`reliable_ingest_worker`, `INGEST_INVALID_SIGNATURE_ALERT_THRESHOLD`) continua
valendo. Se a borda passar a rejeitar, esse alerta deve ficar em zero — e um
valor diferente de zero indica evento entrando por fora do n8n.

## Custo assumido

O segredo do Bling passa a existir em dois lugares: `BLING_CLIENT_SECRETS` no
n8n e `installed_integrations.credentials.client_secret` no banco. É a mesma
duplicação que causou o incidente original, aceita conscientemente em troca de
filtrar na borda.

**Ao cadastrar uma conta Bling nova, atualize também `BLING_CLIENT_SECRETS`.**
Esquecer não derruba nada enquanto o enforcement estiver desligado; com ele
ligado, os webhooks daquela conta passam a ser rejeitados com 401.

## Alertas que sustentam a convenção

- volume de 401 (`invalid_signature`) e 403 (`forbidden_source_ip`) no n8n;
- `signature_status = discarded_invalid_signature` em `webhook_events`, que sob
  esta convenção deveria ser sempre zero;
- a allowlist de IP do Mercado Livre é configuração de terceiro e muda sem
  aviso — uma alteração lá derruba o ingest do mesmo jeito que o placeholder
  derrubou o do Bling.
