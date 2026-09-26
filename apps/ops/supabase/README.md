# Supabase on-prem para Nistiprint

Stack oficial Supabase fixada em `self-hosted/v0.8.2` (`UPSTREAM_VERSION`). O Postgres usa a imagem oficial 17.6.1.136. O Compose preserva os serviços centrais e desativa o Supavisor. O gateway recebe o alias `supabase-api:8000` na rede Docker externa `gateway_net`, compartilhada com o Nginx Proxy Manager. Gateway e Postgres são publicados somente em portas de loopback do host (`127.0.0.1:8000` e `127.0.0.1:5432`, configuráveis), para os serviços systemd.

## Preparação no Portainer

1. Confirme no host que existe a rede Docker `gateway_net` e que o Nginx Proxy Manager consegue resolver containers nela. Crie a rede como `bridge` se ainda não existir e conecte o container do NPM.
2. Copie este diretório para `/opt/nistiprint-supabase` na VPS. No Portainer, crie a stack `nistiprint-supabase` no ambiente `local` usando **Upload** com `compose.portainer.yaml`. Esse arquivo usa caminhos absolutos para os volumes mantidos em `/opt/nistiprint-supabase`; o `compose.yaml` continua disponível para execução direta fora do Portainer.
3. Configure as variáveis da stack a partir de `.env.example` pelo formulário do Portainer. Gere chaves novas no host com `sh utils/generate-keys.sh --update-env` após copiar `.env.example` para `.env` no diretório da stack; importe o `.env` pelo botão **Load variables from .env file**. Não reutilize as chaves do Supabase Cloud. Preencha `POSTGRES_PASSWORD`, `DASHBOARD_PASSWORD`, as chaves de assinatura, `SECRET_KEY_BASE`, `PG_META_CRYPTO_KEY` e demais valores exigidos pela stack. Desative signup aberto (`DISABLE_SIGNUP=true`). Backup externo fica desativado nesta etapa: não inicie o perfil `external-backup` e mantenha `WAL_ARCHIVE_MODE=off`; as variáveis S3 e de criptografia podem ficar vazias. O arquivo `.env` contém segredos: mantenha permissões restritas e não o adicione ao Git.
4. Não crie DNS nem proxy host separado para o Supabase. No proxy host existente `app.nistiprint.neolabs.com.br`, adicione Custom Locations para `/auth/v1`, `/rest/v1`, `/realtime/v1`, `/storage/v1`, `/functions/v1` e `/graphql/v1`, todas apontando para `http://supabase-api:8000`; habilite WebSockets para `/realtime/v1`. Preserve `/` para o frontend e `/api` para o backend da aplicação. O NPM e a stack Supabase devem compartilhar `gateway_net`. O domínio público do app continua necessário para os navegadores; `127.0.0.1` só serve aos processos no host. O Studio fica acessível localmente no servidor em `http://127.0.0.1:8000/` e deve ser administrado por sessão local/túnel SSH, sem publicar sua raiz no proxy do app. A porta PostgreSQL no host pode ser ajustada em `POSTGRES_HOST_PORT` se 5432 já estiver ocupada; ela permanece limitada ao loopback.
5. Configure RAM/CPU e disco no servidor antes de iniciar. Registre `free -h`, `df -h /var/lib/docker`, `docker stats --no-stream` e saúde dos containers antes e depois de um ensaio com carga. O requisito recomendado oficial é 8 GB+ RAM e 80 GB+ SSD para a stack completa; a VPS compartilha 8,1 GB com a aplicação. Se houver OOM, pressão sustentada de memória, degradação ou espaço livre insuficiente, não faça o corte.

Não coloque senha de banco, service role key, chave Shopee, segredo S3 ou senha de criptografia de backup no Git nem nesta conversa. Insira os segredos diretamente no Portainer ou no ambiente seguro do host.

Para obter os dados S3, crie no provedor compatível um bucket fora da VPS e uma chave de serviço limitada ao bucket/prefixo `nistiprint-supabase`, com permissões de listar, ler, gravar e apagar objetos (o uploader aplica retenção removendo objetos antigos). Copie endpoint HTTPS, região, nome do bucket e chave/segredo do painel do provedor para os campos `BACKUP_S3_*` do Portainer. Gere duas senhas aleatórias distintas para criptografia e use `rclone obscure` para o valor aceito pela configuração do rclone; guarde também as senhas originais fora da VPS para poder restaurar os dados. A saída obscura do rclone não substitui o armazenamento seguro da senha original.

## Exportação e restauração

Use a connection string exibida em Supabase Dashboard → projeto `nistiprint-supabase` → **Connect**. Prefira **Direct connection**; se a rede aceitar apenas IPv4, selecione **Session pooler**. O Supabase CLI requer a connection string completa no `--db-url`. Leia-a oculta em uma variável temporária para não gravá-la no histórico do shell e execute o dump num usuário confiável do host.

Faça primeiro um ensaio numa instância descartável e vazia. Os dumps de plataforma são a fonte autoritativa; não reaplique as 221 migrations locais sobre esse estado. Exemplo com Supabase CLI instalado:

```sh
umask 077
read -rsp 'Connection string Cloud (cole a URL de Connect): ' SUPABASE_DB_URL; printf '\n'
supabase db dump --db-url "$SUPABASE_DB_URL" -f roles.sql --role-only
supabase db dump --db-url "$SUPABASE_DB_URL" -f schema.sql
supabase db dump --db-url "$SUPABASE_DB_URL" -f data.sql --use-copy --data-only
unset SUPABASE_DB_URL
```

Se a connection string solicitar senha indisponível, obtenha-a com o responsável pelo projeto. Redefinir a senha em **Project Settings → Database** pode afetar outros clientes Cloud; coordene essa rotação com o responsável antes de fazê-la. A string completa é passada pelo CLI ao container temporário de `pg_dump`, então use um host/usuário confiável e não a publique em logs, tickets ou Git.

Restaure os papéis, esquema e dados no destino vazio, no próprio host Docker, sem abrir a porta PostgreSQL na Internet:

```sh
{
  cat roles.sql schema.sql
  printf '\nSET session_replication_role = replica;\n'
  cat data.sql
} | docker exec -i supabase-db psql --single-transaction --variable ON_ERROR_STOP=1 --dbname postgres
```

Mantenha os arquivos fora do repositório e apague-os de modo seguro após a validação/backup. O dump não transporta objetos de Storage, Edge Functions, segredos de Auth nem configuração de SMTP.

Depois do restore:

- confira extensões, funções, triggers, políticas RLS e contagens das tabelas críticas e de `auth.users`;
- confirme publicação Realtime de `demandas_producao` e `itens_demanda`;
- recrie o bucket `public` com `public=true` se a linha de `storage.buckets` não tiver sido restaurada; inventário da origem registrou zero objetos;
- confira `pg_cron` e recrie idempotentemente `purga-retencao-logs` com schedule `17 * * * *` e comando `SELECT public.purgar_logs_retencao(20000)`;
- configure SMTP antes de depender de reset/convite por e-mail e teste login: a assinatura JWT nova invalida sessões emitidas pelo Cloud;
- mantenha o callback Shopee atual em `https://automacao.nistiprint.neolabs.com.br/webhook/shopee`: o fluxo de produção passa pelo n8n, Redis e worker antes de gravar no Supabase. A Edge Function `shopee-webhook` incluída nos arquivos é uma alternativa **não utilizada** nessa arquitetura; não mova o callback para `/functions/v1/shopee-webhook` nem configure `SHOPEE_PARTNER_KEY` na stack Supabase para a migração do banco. No corte, atualize a conexão e as chaves Supabase do worker para o destino local e teste o fluxo n8n → Redis → worker de ponta a ponta.

## Corte e retorno

Faça a migração numa janela de manutenção. Primeiro pare os consumidores que gravam no banco e bloqueie gravações pela aplicação. Deixe n8n e Redis recebendo webhooks; aguarde os consumidores drenarem operações ativas. Faça o dump final, restaure o destino, compare dados e faça testes REST/RPC, Auth, Realtime, Storage e webhook antes de liberar gravações. Nos serviços systemd do host, defina `SUPABASE_URL=http://127.0.0.1:8000`, `SUPABASE_DB_URL=postgresql://postgres:<senha-codificada>@127.0.0.1:5432/postgres` (ajuste a porta conforme `POSTGRES_HOST_PORT`) e atualize `SUPABASE_SERVICE_KEY` e `SUPABASE_ANON_KEY`. `DATABASE_URL` continua reservado ao bind legado MySQL. Para o browser, configure `VITE_SUPABASE_URL=https://app.nistiprint.neolabs.com.br` e a chave pública. `deploy.sh` lê `VITE_SUPABASE_URL` e `SUPABASE_ANON_KEY` do `/opt/nistiprint/.env` e as injeta no build; a chave de serviço não chega ao bundle.

Monitore filas Redis, spool local e DLQ até confirmarem progresso sem perda ou duplicação. Se falhar antes de liberar gravações no destino, reverta as URLs para Cloud. Após qualquer gravação no destino, pause novamente e reconcilie os eventos antes do retorno. Mantenha o Cloud por 30 dias.

## Backup e critério de aceite

Backup externo está adiado. Os serviços `backup-base` e `backup-uploader` ficam no perfil Compose `external-backup` e não iniciam no deploy padrão; `WAL_ARCHIVE_MODE=off` evita acumular WAL local sem uploader. Quando o bucket S3 estiver disponível, preencha as credenciais e senhas de criptografia, altere `WAL_ARCHIVE_MODE=on` e suba a stack com o perfil `external-backup`. Até lá, a instância não terá recuperação de desastre independente da VPS; mantenha o Cloud ativo durante o ensaio e a validação.

Antes do corte, registre uso de CPU, memória, swap, disco e saúde dos serviços existentes com a stack ligada. Faça um ensaio com o dump recente de aproximadamente 735 MB; compare as tabelas e monitore por tempo suficiente para pegar o job cron e fluxos assíncronos. O estado inicial conhecido é 125 tabelas públicas, 3 usuários Auth, bucket sem objetos, uma função ativa e uma rotina cron; valide novamente na janela, pois a origem segue em uso.

Os arquivos `verify-restore.sql` e `post-restore.sql` fornecem, respectivamente, consultas de comparação e a recriação idempotente do cron/publicação Realtime.

Referências: [restore de plataforma](https://supabase.com/docs/guides/self-hosting/restore-from-platform), [Docker self-hosted e requisitos](https://supabase.com/docs/guides/self-hosting/docker), [Postgres 17](https://supabase.com/docs/guides/self-hosting/postgres-upgrade-17).
