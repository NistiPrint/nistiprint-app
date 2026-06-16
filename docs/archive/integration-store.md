> Documento legado.
> Pode descrever uma versao anterior do dominio de integracoes.
> Fonte atual: [Spec de Integracoes](../specs/02-domains/integracoes/spec.md), [Supabase Contracts](../specs/03-contracts/supabase-contracts.md) e [Decision Record 2026-06](../specs/00-governance/2026-06-integracoes-pedidos-canonicos.md).

# Evolution Plan: Integration Store V3 (Single-Tenant & Legacy Coexistence)

## Contexto e Objetivo EstratÃ©gico
O sistema opera em modalidade **Single-Tenant**, focado na operaÃ§Ã£o da NistiPrint. Atualmente, as integraÃ§Ãµes estÃ£o divididas entre tabelas legadas (`contas_bling`), tabelas de transiÃ§Ã£o (`installed_integrations`) e dependÃªncias externas (Firestore/GCM).

Este plano visa unificar essa estrutura sob o modelo de **Integration Store**, garantindo que a V3 possa evoluir sem quebrar o sistema legado (que ainda depende do Firestore para o Bling) e organizando mÃºltiplas instÃ¢ncias de conectores de forma segura.

## Arquitetura e Entidades

### AnÃ¡lise das Tabelas Atuais (Supabase)
- **`integration_modules`**: JÃ¡ existe e atua como o catÃ¡logo (Definitions).
- **`installed_integrations`**: Tabela de transiÃ§Ã£o para instÃ¢ncias. Possui colunas de token que serÃ£o migradas para `integration_secrets`.
- **`contas_bling`**: Tabela legada que armazena credenciais do Bling V3 e estÃ¡ vinculada aos `canais_venda`.
- **`integration_refresh_logs`**: Log de execuÃ§Ãµes de refresh.

### Novas Entidades e Ajustes
- **`integration_secrets`**: Nova tabela para armazenar `client_secret`, `api_key` e `refresh_token` criptografados (AES-256).
- **`integration_links`**: Mapeamento entre instÃ¢ncias de ERP e Canais (ex: vincular uma instÃ¢ncia especÃ­fica da Shopee a uma conta especÃ­fica do Bling).
- **`contas_bling` (Legacy Bridge)**: Durante a transiÃ§Ã£o, esta tabela continuarÃ¡ sendo a fonte de verdade para os tokens do Bling atualizados pelo processo legado.

## Plano de AÃ§Ã£o (ConvivÃªncia e ExecuÃ§Ã£o)

### Fase 1: FundaÃ§Ã£o e Criptografia
- [ ] **Task 1: Encryption Service** - Implementar `EncryptionService` no `nistiprint-shared` (AES-256-GCM). CritÃ©rio de aceite: MÃ©todos `encrypt/decrypt` funcionando com `MASTER_KEY` local.
- [ ] **Task 2: Secrets Table** - Criar a tabela `integration_secrets` (id, instance_id, key, encrypted_value).
- [ ] **Task 3: BaseConnector Refactoring** - Criar a abstraÃ§Ã£o `BaseConnector` que suporte o modo `read_only_auth` (para casos como o Bling legado).

### Fase 2: ConvivÃªncia Bling (Legacy First)
- [ ] **Task 4: Bling Read-Only Connector** - Implementar o conector Bling na V3 que, em vez de dar refresh, consome o token de uma fonte sincronizada.
- [ ] **Task 5: Firestore-to-Supabase Sync** - Ajustar o `legacy_sync_service.py` para garantir que o token renovado pelo legado no Firestore seja espelhado em `contas_bling` e `installed_integrations` no Supabase. 
  - *AtenÃ§Ã£o:* O Worker V3 **nÃ£o deve** executar `refresh_token` para o Bling nesta fase.
- [ ] **Task 6: Instance Unification** - Criar uma View ou disparar Triggers para manter `contas_bling` e `installed_integrations` (tipo 'bling') em sincronia de ID e Nome.

### Fase 3: MigraÃ§Ã£o Shopee e Novos Conectores
- [ ] **Task 7: Shopee V3 Migration** - Migrar a Shopee para o novo modelo de instÃ¢ncias. Como a Shopee na V3 jÃ¡ Ã© independente do legado, ela pode usar o fluxo completo de refresh e armazenamento em `integration_secrets`.
- [ ] **Task 8: Secrets Migration** - Mover `client_secret` e `refresh_token` da Shopee de variÃ¡veis de ambiente/config para a tabela `integration_secrets`.

### Fase 4: OrquestraÃ§Ã£o e Webhooks
- [ ] **Task 9: Dynamic Webhook Router** - Implementar `/webhooks/<instance_id>` que utilize a nova tabela de instÃ¢ncias para rotear o payload.
- [ ] **Task 10: Integration Links** - Implementar a tabela e o serviÃ§o de vÃ­nculos para que o Worker saiba em qual conta do Bling deve injetar um pedido da Shopee ou ML.

### Fase 5: UI e Monitoramento
- [ ] **Task 11: Integration Store UI** - Interface unificada para gerenciar instÃ¢ncias de ERP e Marketplaces.
- [ ] **Task 12: Health Check Dashboard** - VisualizaÃ§Ã£o do status de cada instÃ¢ncia e logs de erro de sincronizaÃ§Ã£o.

## EstratÃ©gia de ConvivÃªncia (Riscos e MitigaÃ§Ã£o)
1. **Refresh de Token Bling**: O refresh continuarÃ¡ sendo feito pelo processo que atualiza o Firestore. A V3 serÃ¡ apenas consumidora desse token via Supabase (apÃ³s o sync). 
2. **Duplicidade de Dados**: As tabelas `contas_bling` e `installed_integrations` coexistirÃ£o atÃ© que todos os mÃ³dulos (API, Worker, Frontend) estejam apontando para o novo modelo.
3. **SeguranÃ§a**: Remover gradualmente credenciais hardcoded em `.env` ou `GCP Secrets` em favor da `integration_secrets` criptografada.

## ObservaÃ§Ãµes TÃ©cnicas
- **Single-Tenant**: NÃ£o hÃ¡ necessidade de `tenant_id` ou RLS complexo por usuÃ¡rio externo, simplificando as queries.
- **Ordem de DependÃªncia**: Task 5 Ã© crÃ­tica. Sem o sync confiÃ¡vel do token legado para o Supabase, a V3 pode tentar usar tokens expirados.

## EstratÃ©gia de Branching e MigraÃ§Ã£o (Plano Gratuito Supabase)
Dado que o recurso nativo de branching do Supabase Ã© limitado/pago, adotaremos uma estratÃ©gia baseada em **Supabase CLI** e **Git**:

1. **Local Development**:
   - Desenvolvedores utilizam o comando `supabase start` para rodar uma instÃ¢ncia local do Supabase via Docker.
   - AlteraÃ§Ãµes de schema sÃ£o feitas localmente e capturadas com `supabase db diff -f nome_da_migracao`.
2. **Ambientes**:
   - **Projeto ProduÃ§Ã£o (Free)**: InstÃ¢ncia principal da NistiPrint.
   - **Projeto Staging (Free)**: Utilizar o 2Âº projeto gratuito permitido pelo Supabase para testar migraÃ§Ãµes crÃ­ticas (ex: criaÃ§Ã£o das tabelas de integraÃ§Ãµes) antes do deploy final.
3. **Fluxo de Deploy**:
   - `Feature Branch (Git)` -> `Pull Request` -> `Merge em develop/main`.
   - O deploy das migraÃ§Ãµes para o Supabase de ProduÃ§Ã£o Ã© feito via `supabase db push` apÃ³s validaÃ§Ã£o local e em staging.
4. **Isolamento de Segredos**:
   - A `MASTER_KEY` de criptografia em Staging deve ser diferente da de ProduÃ§Ã£o.
   - Tokens de teste da Shopee/Bling devem ser usados no ambiente de Staging.
