# Renovação Automática de Tokens Bling - Cloud Run

Esta solução permite a renovação automática de tokens de acesso para múltiplas contas Bling, utilizando uma arquitetura robusta na Google Cloud Platform.

## Arquitetura Recomendada: Cloud Scheduler + Cloud Run + Secret Manager

Esta é a arquitetura mais robusta e recomendada para a sua necessidade.

**Cloud Scheduler**: Atua como o "relógio" (cron job). Ele é extremamente confiável e tem o único propósito de disparar um evento em um horário agendado. Ele iniciará o nosso processo a cada 6 horas.

**Cloud Run**: É a nossa escolha para executar o código. Embora o Cloud Functions também funcione, o Cloud Run oferece mais flexibilidade (qualquer linguagem/binário), timeouts mais longos (útil se você tiver muitas contas Bling para atualizar) e um modelo de escalabilidade mais transparente. Para um processo crítico como este, o Cloud Run é a escolha mais profissional.

**Secret Manager**: Essencial para a segurança. Suas credenciais da API da Bling (client_id, client_secret) nunca devem ser escritas diretamente no código ou em variáveis de ambiente. O Secret Manager armazena esses segredos de forma segura, com controle de acesso e auditoria.

**Firestore**: Continua sendo sua base de dados para ler os refresh_tokens de cada conta e para salvar os novos tokens.

## Estrutura do Projeto

```
gcloud/
├── README.md (este arquivo)
└── run/
    └── bling_token_manager/
        ├── Dockerfile
        ├── main.py
        ├── requirements.txt
```

## Pré-requisitos

### Conta de Serviço
- `sa-bling-refresher@neolabs-nistiprint.iam.gserviceaccount.com`: Executa o serviço Cloud Run
- `sa-scheduler-invoker@neolabs-nistiprint.iam.gserviceaccount.com`: Dispara o scheduler

### Permissões IAM
Execute estes comandos para configurar as permissões:

```bash
# Firewall access para Firestore e Secret Manager
gcloud projects add-iam-policy-binding neolabs-nistiprint \
  --member=serviceAccount:sa-bling-refresher@neolabs-nistiprint.iam.gserviceaccount.com \
  --role=roles/datastore.user

gcloud projects add-iam-policy-binding neolabs-nistiprint \
  --member=serviceAccount:sa-bling-refresher@neolabs-nistiprint.iam.gserviceaccount.com \
  --role=roles/secretmanager.secretAccessor

# Permissão para o scheduler invocar o Cloud Run
gcloud projects add-iam-policy-binding neolabs-nistiprint \
  --member=serviceAccount:sa-scheduler-invoker@neolabs-nistiprint.iam.gserviceaccount.com \
  --role=roles/run.invoker
```

### Segredos no Secret Manager
Os segredos devem estar no formato `BLING_CLIENT_ID_<IDENTIFICADOR>` e `BLING_SECRET_<IDENTIFICADOR>`, onde `<IDENTIFICADOR>` são os primeiros 5 dígitos do CNPJ da empresa Bling.

**Novo**: Para o endpoint de obtenção de tokens, é necessário criar um secret adicional:
- `BLING_API_TOKEN`: Token fixo para autenticação de aplicações consumidoras

### Base de Dados Firestore
A coleção `bling_accounts` deve conter documentos com:
- `cnpj`: CNPJ da empresa (usado para identificar os segredos e buscar contas)
- `refresh_token`: Token de refresh atual
- `access_token`: Token de acesso atual (retornado pelo endpoint GET)
- Outros campos necessários

## Deploy do Serviço

```bash
cd gcloud/run/bling_token_manager

gcloud run deploy bling-token-manager \
  --source . \
  --allow-unauthenticated \
  --service-account sa-bling-refresher@neolabs-nistiprint.iam.gserviceaccount.com \
  --platform managed \
  --region us-east1 \
  --set-env-vars GCP_PROJECT=neolabs-nistiprint
```

## Criar o Cloud Scheduler

Após o deploy bem-sucedido, obtenha a URL do serviço:
```bash
gcloud run services describe bling-token-manager --region us-east1 --format 'value(status.url)'
```

Crie o scheduler para executar a cada 6 horas:
```bash
gcloud scheduler jobs create http bling-token-refresh-job \
  --schedule="0 */6 * * *" \
  --time-zone="America/Sao_Paulo" \
  --location=us-east1 \
  --uri="https://RESULTADO_DO_COMANDO_DESCUBRIR_URL/" \
  --http-method=POST \
  --service-account=sa-scheduler-invoker@neolabs-nistiprint.iam.gserviceaccount.com \
  --description="Job to refresh Bling tokens every 6 hours"
```

Certifique-se de substituir `RESULTADO_DO_COMANDO_DESCUBRIR_URL` pela URL real do serviço Cloud Run.

## Verificação e Teste

### Endpoint de Saúde
GET: `https://bling-token-manager-[HASH].us-east1.run.app/health`
- Retorna `{"status": "healthy"}` se o serviço estiver ativo
- **Nota:** Substitua `[HASH]` pelo hash do serviço após implantar

### Endpoint de Renovação
POST: `https://bling-token-manager-[HASH].us-east1.run.app/`
- Deve ser chamado pelo Cloud Scheduler via POST
- Processa todas as contas na coleção `bling_accounts`

### Endpoint de Obtenção de Token
GET: `https://bling-token-manager-[HASH].us-east1.run.app/token/<CNPJ>`
- Headers: `Authorization: Bearer <API_TOKEN>`
- Retorna o `access_token` para a conta correspondente ao CNPJ
- CNPJ deve existir na coleção `bling_accounts` e ter `access_token` válido

Exemplo de uso com curl:
```bash
curl -H "Authorization: Bearer YOUR_API_TOKEN" \
  https://bling-token-manager-[HASH].us-east1.run.app/token/12345678000123
```

### Visualizar Logs
```bash
# Logs do Cloud Run
gcloud run services logs read bling-token-manager --region us-east1 --limit 50

# Logs do Cloud Scheduler (Console GCP > Cloud Scheduler > Conjuntos -> bling-token-refresh-job)
```

## Problemas Comuns e Soluções

### Erro 404 ao acessar URL
- O endpoint principal `/` só aceita POST. Use `/health` para verificação via navegador.

### Erro 500 / Permission Denied
- Verifique se as permissões IAM foram aplicadas corretamente
- Aguarde alguns minutos após configurar as permissões (propagação pode demorar)
- Confirme que o `GCP_PROJECT` está definido corretamente no ambiente

### Scheduler falhando
- Verifique se o scheduler tem a role `roles/run.invoker`
- Confirme que o serviço foi deployado com `--allow-unauthenticated`
- Verifique os logs do scheduler no Console GCP

### Conta de Serviço do Cloud Run
- A conta `sa-bling-refresher` precisa de acesso ao Firestore e Secret Manager
- O scheduler usa `sa-scheduler-invoker` para invocar o serviço
- Não confundir: a conta que executa o serviço ≠ a conta que dispara o scheduler

### Errors no Endpoint de Obtenção de Token
- Verifique se o secret `BLING_API_TOKEN` existe no Secret Manager
- Confirme que o CNPJ passado existe em `bling_accounts` com `access_token` válido
- Use o formato correto do header Authorization: `Bearer <TOKEN>`

## Evolução Futura

- Adicionar métricas de monitoramento (Cloud Monitoring)
- Implementar alertas para falhas de renovação
- Suporte a notificações (Slack, email) quando tokens expirarem
- Testes automatizados para validação
- Implementar rate limiting no endpoint de obtenção de tokens
- Adicionar versionamento de API (/v1/token/...)

---

**Comandos Resumo:**
1. Configurar permissões IAM
2. Criar secret `BLING_API_TOKEN` se necessário
3. Deploy do serviço: `gcloud run deploy bling-token-manager --source . --allow-unauthenticated --service-account sa-bling-refresher@neolabs-nistiprint.iam.gserviceaccount.com --platform managed --region us-east1 --set-env-vars GCP_PROJECT=neolabs-nistiprint`
4. Obter URL: `gcloud run services describe bling-token-manager --region us-east1 --format 'value(status.url)'`
5. Criar scheduler substituindo a URI pela URL obtida
6. Testar `/health` endpoint

Para dúvidas ou problemas, consulte os logs ou verifique a configuração IAM no Console GCP.
