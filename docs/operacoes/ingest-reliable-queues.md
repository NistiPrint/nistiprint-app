# Ingest confiável: n8n, Redis e workers

Os endpoints públicos de Bling, Shopee e Mercado Livre preservam o corpo bruto, criam um envelope e executam `RPUSH np:ingest:inbox:ready:v1`. O nó
**Respond to Webhook** responde `200` somente depois da confirmação do Redis.
Não há consulta ao Supabase, canonização ou validação de assinatura antes do
ACK.

Payloads maiores que 1 MB recebem `413` e não são enfileirados. Se o Redis
falhar, o workflow grava o envelope em
`/data/webhook-spool/ready/{event_id}.json` e responde `200` após a escrita.
Somente a falha simultânea de Redis e spool produz `503`. O spool replayer
publica o arquivo e só o remove após confirmar o `RPUSH`.

## Envelope

O envelope contém `schema_version`, `event_id`, `source`, `received_at`,
headers em allowlist, `raw_body`, `parsed_payload`, `body_sha256`,
`provider_delivery_id` e o tamanho recebido. Headers de autorização e outros
segredos não são copiados.

## Processamento pós-ACK

O roteador usa `BLMOVE` para `np:ingest:inbox:processing:v1`, valida a
assinatura sobre `raw_body`, registra o evento por
`(source, dedupe_scope, dedupe_key)` e encaminha atomicamente para `orders` ou
`chat`.

Assinatura inválida é terminal (`discarded_invalid_signature`). Quando falta
material de validação, o resultado depende da política configurada por
provider: `required` descarta como `discarded_signature_unverifiable`;
`optional` registra `signature_unverified` e permite o rollout controlado.

Consumidores removem o item somente após o efeito idempotente. Falhas
transitórias vão para o sorted set de retry e falhas terminais para a DLQ.
Claims, conclusão, retry e recuperação de lease são protegidos por
`claim_token` e scripts Lua.

```text
np:ingest:inbox:ready:v1 / processing:v1
np:ingest:orders:ready:v1 / processing:v1
np:ingest:chat:ready:v1 / processing:v1
np:ingest:retry:v1
np:ingest:leases:v1
np:ingest:dlq:v1
```

Os workflows publicados mantêm os caminhos públicos `bling`, `shopee` e
`mercadolivre`. O chat legado não participa deste fluxo e `kb/API/api.php`
permanece inalterado.

Durante o rollout, cada publicação confirmada no inbox novo também é enviada
em shadow para a fila antiga do provider. A falha do shadow não invalida o ACK,
pois o envelope já está durável no inbox novo. Remova o nó
`Legacy Queue Shadow` somente depois que os heartbeats dos consumidores novos
estiverem ativos e a comparação permanecer sem divergências por sete dias.

Na Shopee, o header `Authorization` não é persistido. Após o ACK, o próprio n8n
calcula o HMAC `callback_url|raw_body` em memória e grava no Redis apenas o
veredito associado ao `event_id`. O router aguarda esse veredito antes de
processar; ausência temporária entra em retry curto.

## Arquivamento e retenção

O serviço `ingest-archive` fica desativado por padrão. Para ativá-lo, configure
`INGEST_ARCHIVE_ENABLED=1` e as variáveis `INGEST_ARCHIVE_S3_*`. Cada lote é
serializado como JSONL, comprimido em Zstandard e enviado com chave
determinística `dataset=.../dt=.../part-....jsonl.zst`.

O worker confirma tamanho e checksum SHA-256 do objeto antes de chamar a RPC
transacional que registra `archive_manifests` e só então limpa ou exclui os
dados quentes. Payloads e tentativas de eventos pendentes ou em intervenção
manual não entram no lote. Chat normalizado e metadata terminal permanecem 30
dias; registros de chat ainda referenciados por agrupamentos não são apagados.
