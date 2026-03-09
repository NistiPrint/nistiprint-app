# Evolution Plan: Integration Store V3 (Single-Tenant & Legacy Coexistence)

## Contexto e Objetivo Estratégico
O sistema opera em modalidade **Single-Tenant**, focado na operação da NistiPrint. Atualmente, as integrações estão divididas entre tabelas legadas (`contas_bling`), tabelas de transição (`installed_integrations`) e dependências externas (Firestore/GCM).

Este plano visa unificar essa estrutura sob o modelo de **Integration Store**, garantindo que a V3 possa evoluir sem quebrar o sistema legado (que ainda depende do Firestore para o Bling) e organizando múltiplas instâncias de conectores de forma segura.

## Arquitetura e Entidades

### Análise das Tabelas Atuais (Supabase)
- **`integration_modules`**: Já existe e atua como o catálogo (Definitions).
- **`installed_integrations`**: Tabela de transição para instâncias. Possui colunas de token que serão migradas para `integration_secrets`.
- **`contas_bling`**: Tabela legada que armazena credenciais do Bling V3 e está vinculada aos `canais_venda`.
- **`integration_refresh_logs`**: Log de execuções de refresh.

### Novas Entidades e Ajustes
- **`integration_secrets`**: Nova tabela para armazenar `client_secret`, `api_key` e `refresh_token` criptografados (AES-256).
- **`integration_links`**: Mapeamento entre instâncias de ERP e Canais (ex: vincular uma instância específica da Shopee a uma conta específica do Bling).
- **`contas_bling` (Legacy Bridge)**: Durante a transição, esta tabela continuará sendo a fonte de verdade para os tokens do Bling atualizados pelo processo legado.

## Plano de Ação (Convivência e Execução)

### Fase 1: Fundação e Criptografia
- [ ] **Task 1: Encryption Service** - Implementar `EncryptionService` no `nistiprint-shared` (AES-256-GCM). Critério de aceite: Métodos `encrypt/decrypt` funcionando com `MASTER_KEY` local.
- [ ] **Task 2: Secrets Table** - Criar a tabela `integration_secrets` (id, instance_id, key, encrypted_value).
- [ ] **Task 3: BaseConnector Refactoring** - Criar a abstração `BaseConnector` que suporte o modo `read_only_auth` (para casos como o Bling legado).

### Fase 2: Convivência Bling (Legacy First)
- [ ] **Task 4: Bling Read-Only Connector** - Implementar o conector Bling na V3 que, em vez de dar refresh, consome o token de uma fonte sincronizada.
- [ ] **Task 5: Firestore-to-Supabase Sync** - Ajustar o `legacy_sync_service.py` para garantir que o token renovado pelo legado no Firestore seja espelhado em `contas_bling` e `installed_integrations` no Supabase. 
  - *Atenção:* O Worker V3 **não deve** executar `refresh_token` para o Bling nesta fase.
- [ ] **Task 6: Instance Unification** - Criar uma View ou disparar Triggers para manter `contas_bling` e `installed_integrations` (tipo 'bling') em sincronia de ID e Nome.

### Fase 3: Migração Shopee e Novos Conectores
- [ ] **Task 7: Shopee V3 Migration** - Migrar a Shopee para o novo modelo de instâncias. Como a Shopee na V3 já é independente do legado, ela pode usar o fluxo completo de refresh e armazenamento em `integration_secrets`.
- [ ] **Task 8: Secrets Migration** - Mover `client_secret` e `refresh_token` da Shopee de variáveis de ambiente/config para a tabela `integration_secrets`.

### Fase 4: Orquestração e Webhooks
- [ ] **Task 9: Dynamic Webhook Router** - Implementar `/webhooks/<instance_id>` que utilize a nova tabela de instâncias para rotear o payload.
- [ ] **Task 10: Integration Links** - Implementar a tabela e o serviço de vínculos para que o Worker saiba em qual conta do Bling deve injetar um pedido da Shopee ou ML.

### Fase 5: UI e Monitoramento
- [ ] **Task 11: Integration Store UI** - Interface unificada para gerenciar instâncias de ERP e Marketplaces.
- [ ] **Task 12: Health Check Dashboard** - Visualização do status de cada instância e logs de erro de sincronização.

## Estratégia de Convivência (Riscos e Mitigação)
1. **Refresh de Token Bling**: O refresh continuará sendo feito pelo processo que atualiza o Firestore. A V3 será apenas consumidora desse token via Supabase (após o sync). 
2. **Duplicidade de Dados**: As tabelas `contas_bling` e `installed_integrations` coexistirão até que todos os módulos (API, Worker, Frontend) estejam apontando para o novo modelo.
3. **Segurança**: Remover gradualmente credenciais hardcoded em `.env` ou `GCP Secrets` em favor da `integration_secrets` criptografada.

## Observações Técnicas
- **Single-Tenant**: Não há necessidade de `tenant_id` ou RLS complexo por usuário externo, simplificando as queries.
- **Ordem de Dependência**: Task 5 é crítica. Sem o sync confiável do token legado para o Supabase, a V3 pode tentar usar tokens expirados.

## Estratégia de Branching e Migração (Plano Gratuito Supabase)
Dado que o recurso nativo de branching do Supabase é limitado/pago, adotaremos uma estratégia baseada em **Supabase CLI** e **Git**:

1. **Local Development**:
   - Desenvolvedores utilizam o comando `supabase start` para rodar uma instância local do Supabase via Docker.
   - Alterações de schema são feitas localmente e capturadas com `supabase db diff -f nome_da_migracao`.
2. **Ambientes**:
   - **Projeto Produção (Free)**: Instância principal da NistiPrint.
   - **Projeto Staging (Free)**: Utilizar o 2º projeto gratuito permitido pelo Supabase para testar migrações críticas (ex: criação das tabelas de integrações) antes do deploy final.
3. **Fluxo de Deploy**:
   - `Feature Branch (Git)` -> `Pull Request` -> `Merge em develop/main`.
   - O deploy das migrações para o Supabase de Produção é feito via `supabase db push` após validação local e em staging.
4. **Isolamento de Segredos**:
   - A `MASTER_KEY` de criptografia em Staging deve ser diferente da de Produção.
   - Tokens de teste da Shopee/Bling devem ser usados no ambiente de Staging.
