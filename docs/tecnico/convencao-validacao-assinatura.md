# Convenção: validação de assinatura vive no n8n

Status: adotada em 01/08/2026.

## A regra

> **O n8n decide se um webhook é autêntico. O app registra a decisão e não a
> recalcula. Para Shopee, o worker só encaminha o evento após receber o
> veredito positivo; ausência de veredito ou falta de material vai para
> quarentena, sem efeitos de domínio.**

Os fluxos Bling e Mercado Livre validam antes de enfileirar. Shopee precisa
persistir o envelope e responder ao provider antes de consultar o veredito
HMAC, então eventos Shopee ainda não verificados podem entrar na inbox de
transporte. A inbox não é prova de autenticidade: o worker só encaminha um
evento Shopee para a fila de pedidos/chat depois de `signature_valid`; caso
contrário, ele registra a razão e o mantém em quarentena.

## Por que na borda

Quando o contrato permite decidir antes do ACK, rejeitar antes do envelope evita:

- espaço em Redis e no spool durável para tráfego que seria descartado;
- linhas em `webhook_events` que só existem para registrar uma rejeição;
- ciclos de worker fazendo HMAC de payload que já se sabia inválido;
- ruído de log que compete com sinal real.

Em 30/07 o Bling gerou 2.829 linhas de descarte em três dias. Com enforcement
válido na borda, esse volume não teria entrado. Para Shopee, a decisão fica
registrada no worker porque a verificação acontece após a persistência/ACK.

## Mecanismo por origem

Cada provider oferece uma garantia diferente, e a convenção é sobre *onde* a
decisão acontece, não sobre *qual* mecanismo é usado.

| Origem | Mecanismo | Segredo / fonte | Onde |
|---|---|---|---|
| Bling | HMAC-SHA256 do corpo cru | `BLING_CLIENT_SECRETS` (array JSON, um por conta) | nós `Verify Bling Signature` / `Assinatura aceita?` |
| Shopee | HMAC-SHA256 sobre URL de callback + corpo cru, veredito pós-ACK | Partner Key configurada no n8n | workflow Shopee, veredito em `np:ingest:signature:{event_id}`; worker exige `signature_valid` |
| Mercado Livre | HTTPS, allowlist de IP e consulta autenticada do recurso | faixa oficial de IPs + token OAuth da conta | nós `Resolve Client IP` / `IP autorizado?`; validação do recurso no worker |

O contrato de notificações do marketplace Mercado Livre não usa o manifesto
`X-Signature` do Mercado Pago. A documentação oficial recomenda HTTPS, validar
IP de origem e tratar o webhook como aviso, consultando o recurso com o token da
conta. A lista de IPs pode mudar e precisa ser conferida periodicamente na
[documentação de segurança do Mercado Livre](https://developers.mercadolivre.com.br/pt_br/automovel-gerenciamento-de-contatos/seguranca-de-aplicacoes).

## Regras que a convenção não dispensa

**1. Distinguir assinatura inválida de assinatura não verificável.** Falta de
segredo ou de header não deve ser rotulada como HMAC inválido. Para Bling, a
política de observação pode deixar o evento seguir durante o rollout. Para
Shopee, porém, somente `signature_valid` segue ao processamento de domínio;
`signature_unverified`, veredito ausente ou chave indisponível são registrados
como `discarded_signature_unverifiable` e ficam em quarentena. Um HMAC
calculado que não bate é `discarded_invalid_signature`. Isso evita tanto falsos
diagnósticos quanto alterações de pedido/estoque sem autenticidade confirmada.

**2. Placeholder não é segredo.** Toda leitura de segredo descarta `...`,
`changeme`, `secret` e valores com menos de 8 caracteres, com log. Vale no n8n e
no app.

**3. Estreia em modo observação.** Bling pode estrear/trocar segredo com
`BLING_SIGNATURE_ENFORCE=false`, sem bloquear tráfego. Shopee não permite
processamento em modo observação: a fila continua durável, mas o worker deixa
eventos sem veredito positivo em quarentena até a Partner Key e o contrato da
assinatura serem confirmados em execução real.

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
