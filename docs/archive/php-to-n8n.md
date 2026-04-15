# ===========================================
# GUIA DE MIGRAÇÃO - PHP PARA N8N
# ===========================================
# Status: ✅ PRONTO PARA MIGRAÇÃO
# Data: 20 de Fevereiro de 2026
# ===========================================

## Visão Geral da Migração

### Arquitetura Antiga (PHP)
```
Shopee/Bling → PHP (webhook_service) → Supabase
```

**Problemas:**
- Código PHP para manter
- Sem fila de processamento
- Processamento síncrono (bloqueante)
- Sem retry automático
- Sem monitoramento centralizado

### Nova Arquitetura (n8n + Celery)
```
Shopee/Bling → n8n (Webhook) → Redis (Fila) → Celery Worker → Supabase
```

**Benefícios:**
- ✅ Sem código para manter (n8n é low-code)
- ✅ Fila de processamento (Redis)
- ✅ Processamento assíncrono (Celery)
- ✅ Retry automático com backoff
- ✅ Monitoramento via Flower/n8n
- ✅ Workflows visuais e fáceis de ajustar

---

## Passo a Passo da Migração

### Fase 1: Preparação (Desenvolvimento)

#### 1.1 Atualizar repositório

```bash
git pull origin main
```

#### 1.2 Subir stack com n8n

```bash
# Desenvolvimento local
docker-compose up -d n8n redis worker api frontend

# Ver status
docker-compose ps

# Ver logs do n8n
docker-compose logs -f n8n
```

#### 1.3 Acessar n8n

- URL: `http://localhost:5678`
- Primeiro login: Criar conta admin

#### 1.4 Importar workflows

1. No n8n: **Settings** → **Import from URL**
2. URLs dos workflows (GitHub):
   - `https://raw.githubusercontent.com/seu-usuario/nistiprint-erp/main/n8n/workflows/shopee-webhook.json`
   - `https://raw.githubusercontent.com/seu-usuario/nistiprint-erp/main/n8n/workflows/bling-webhook.json`
3. Ativar workflows (toggle **Active**)

#### 1.5 Configurar credenciais Redis no n8n

1. **Credentials** → **Add Credential**
2. **Type:** Redis
3. **Connection:** `redis://redis:6379/0`
4. **Name:** `Redis Credentials`

#### 1.6 Configurar variáveis de ambiente no n8n

1. **Settings** → **Environment Variables**
2. Adicionar:
   - `WEBHOOK_TOKEN`: (token da Shopee)
   - `BLING_WEBHOOK_SECRET`: (token do Bling)

---

### Fase 2: Testes (Desenvolvimento)

#### 2.1 Testar webhook Shopee

```bash
# Simular webhook da Shopee
curl -X POST http://localhost:5678/webhook/shopee-webhook \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Token: SEU_TOKEN" \
  -d '{
    "order_sn": "SP20240101001",
    "event_type": "order.created",
    "payload": {
      "order_sn": "SP20240101001",
      "status": "NEW"
    }
  }'

# Ver resposta
# Deve retornar: {"success": true, "message": "Webhook received and queued"}
```

#### 2.2 Verificar fila Redis

```bash
# Acessar Redis
docker-compose exec redis redis-cli

# Ver tamanho da fila
LLEN celery

# Ver mensagens (primeiras 5)
LRANGE celery 0 5

# Sair
exit
```

#### 2.3 Verificar processamento do worker

```bash
# Ver logs do worker
docker-compose logs -f worker

# Deve aparecer:
# Task services.webhook_tasks.process_shopee_webhook succeeded
```

#### 2.4 Verificar no Supabase

```sql
-- Ver webhook logs
SELECT * FROM webhook_logs 
ORDER BY created_at DESC 
LIMIT 10;
```

---

### Fase 3: Produção (Portainer)

#### 3.1 Criar redes Docker

```bash
# Rede para NPM
docker network create gateway_net

# Rede interna (isolada)
docker network create app-internal --internal
```

#### 3.2 Criar volumes

```bash
docker volume create nistiprint-n8n-data
docker volume create nistiprint-redis-data
```

#### 3.3 Deploy no Portainer

1. **Stacks** → **Add stack**
2. **Name:** `app-core`
3. **Build method:** Git Repository
4. **Repository:** `https://github.com/seu-usuario/nistiprint-erp.git`
5. **Reference:** `main`
6. **Compose Path:** `docker-compose.prod.yml`

#### 3.4 Configurar variáveis no Portainer

Em **Environment Variables**:

```env
# Redis
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0
REDIS_URL=redis://redis:6379/0

# N8N
N8N_HOST=automacao.nistiprint.neolabs.com.br
N8N_ENCRYPTION_KEY=(gerar aleatório)
WEBHOOK_TOKEN=(token Shopee)
BLING_WEBHOOK_SECRET=(token Bling)

# Supabase
DATABASE_URL=postgresql://...:6543/...?pgbouncer=true
SUPABASE_URL=https://...
SUPABASE_SERVICE_KEY=...
```

#### 3.5 Deploy e validação

```bash
# Ver status
docker-compose ps

# Ver logs do n8n
docker-compose logs -f n8n

# Testar saúde do n8n
curl https://automacao.nistiprint.neolabs.com.br/healthcheck
```

---

### Fase 4: Configurar NPM (Proxy Reverso)

#### 4.1 Adicionar Proxy Host para n8n

No NPM (npm.nistiprint.neolabs.com.br):

1. **Hosts** → **Add Proxy Host**
2. **Domain Name:** `automacao.nistiprint.neolabs.com.br`
3. **Forward Hostname/IP:** `n8n`
4. **Forward Port:** `5678`
5. **Advanced:** Marcar **Websockets Support**
6. **SSL:** Habilitar (Let's Encrypt)
7. **Save**

#### 4.2 Testar URL externa

```bash
curl -X POST https://automacao.nistiprint.neolabs.com.br/webhook/shopee-webhook \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Token: SEU_TOKEN" \
  -d '{"test": true}'
```

---

### Fase 5: Migrar Plataformas

#### 5.1 Shopee

1. **Shopee Partner Platform** → **Development** → **Webhook**
2. Atualizar URL:
   - **De:** `https://seudominio.com/webhook_service/shopee_webhook.php`
   - **Para:** `https://automacao.nistiprint.neolabs.com.br/webhook/shopee-webhook`
3. Manter token de validação
4. **Save**

#### 5.2 Bling

1. **Bling ERP** → **Configurações** → **Webhooks**
2. Atualizar URL:
   - **De:** `https://seudominio.com/webhook_service/bling_webhook.php`
   - **Para:** `https://automacao.nistiprint.neolabs.com.br/webhook/bling-webhook`
3. **Save**

---

### Fase 6: Validação Final

#### 6.1 Monitorar processamento

```bash
# Ver logs em tempo real
docker-compose logs -f n8n worker

# Ver filas Redis
docker-compose exec redis redis-cli LLEN celery

# Ver webhooks processados
SELECT COUNT(*) FROM webhook_logs WHERE processed = true;
```

#### 6.2 Testar webhook real

1. Criar pedido de teste na Shopee
2. Verificar no n8n se webhook foi recebido
3. Verificar no worker se foi processado
4. Verificar no Supabase se dados foram salvos

#### 6.3 Verificar retry

```bash
# Simular falha (parar worker temporariamente)
docker-compose stop worker

# Disparar webhook
curl -X POST https://automacao.nistiprint.neolabs.com.br/webhook/shopee-webhook \
  -H "Content-Type: application/json" \
  -d '{"order_sn": "TEST001"}'

# Verificar fila cresceu
docker-compose exec redis redis-cli LLEN celery

# Reiniciar worker
docker-compose start worker

# Verificar fila diminuiu (processado)
watch -n 1 'docker-compose exec redis redis-cli LLEN celery'
```

---

### Fase 7: Desativar PHP (Legado)

#### 7.1 cPanel (se aplicável)

```bash
# Renomear arquivos PHP (backup)
cd public_html/webhook_service
mv shopee_webhook.php shopee_webhook.php.deprecated
mv bling_webhook.php bling_webhook.php.deprecated

# Opcional: Remover após validação
rm *.php.deprecated
```

#### 7.2 Validar que nada quebrou

- [ ] Webhooks Shopee estão chegando no n8n?
- [ ] Webhooks Bling estão chegando no n8n?
- [ ] Worker está processando filas?
- [ ] Dados estão sendo salvos no Supabase?

Se **SIM** para todos, migração concluída!

---

## Rollback (Plano B)

Se algo der errado:

### 1. Reativar PHP (cPanel)

```bash
cd public_html/webhook_service
mv shopee_webhook.php.deprecated shopee_webhook.php
mv bling_webhook.php.deprecated bling_webhook.php
```

### 2. Reverter URLs nas plataformas

- Shopee: Apontar para URL antiga do PHP
- Bling: Apontar para URL antiga do PHP

### 3. Investigar problema

```bash
# Ver logs de erro
docker-compose logs n8n worker redis

# Verificar conexões
docker-compose exec redis redis-cli ping
docker-compose exec n8n wget http://localhost:5678/healthcheck
```

---

## Checklist de Migração

### Preparação
- [ ] Docker Compose atualizado
- [ ] Workflows n8n importados
- [ ] Credenciais Redis configuradas no n8n
- [ ] Variáveis de ambiente configuradas

### Testes
- [ ] Webhook Shopee testado localmente
- [ ] Webhook Bling testado localmente
- [ ] Worker processando filas
- [ ] Dados salvos no Supabase

### Produção
- [ ] Stack deploy no Portainer
- [ ] Redes gateway_net e app-internal criadas
- [ ] Volumes persistentes criados
- [ ] NPM configurado para n8n
- [ ] Websockets ativados no NPM

### Plataformas
- [ ] URL Shopee atualizada
- [ ] URL Bling atualizada
- [ ] Tokens de validação configurados
- [ ] Teste de webhook realizado

### Validação
- [ ] Webhooks estão chegando no n8n
- [ ] Worker está processando
- [ ] Retry automático funcionando
- [ ] Logs estão sendo gerados
- [ ] Métricas OK (fila, processamento)

### Cleanup
- [ ] PHP depreciado (webhook_service/DEPRECATED.md)
- [ ] Documentação atualizada
- [ ] Equipe treinada no n8n

---

## Suporte e Troubleshooting

### n8n não recebe webhooks

```bash
# Verificar NPM logs
docker logs nginx-proxy-manager | grep automacao

# Testar URL
curl -I https://automacao.nistiprint.neolabs.com.br

# Verificar n8n
docker-compose exec n8n wget http://localhost:5678/healthcheck
```

### Worker não processa

```bash
# Verificar worker logs
docker-compose logs worker

# Verificar filas
docker-compose exec redis redis-cli LRANGE celery 0 10

# Inspecionar worker
docker-compose exec worker celery -A services.celery_app inspect active
```

### Redis perde dados

```bash
# Verificar persistência
docker-compose exec redis redis-cli CONFIG GET appendonly

# Deve retornar: yes
# Se não, reiniciar com volume correto
```

---

## Próximos Passos (Pós-Migração)

- [ ] Configurar Flower para monitoramento Celery
- [ ] Implementar alertas (Discord/Slack)
- [ ] Dashboard de métricas de webhooks
- [ ] Load balancing para workers (se necessário)
- [ ] Otimizar queries do Supabase

---

**Migração concluída com sucesso!**

Para dúvidas: `docs/ARQUITETURA_N8N.md` | `docs/DEPLOY_GUIDE.md`
