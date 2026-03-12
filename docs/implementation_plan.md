# Normalização de Pedidos e Roteamento de Integrações (Multi-Conta Bling)

## Contexto e Objetivo Estratégico
A empresa opera com múltiplas contas Bling (CNPJs diferentes) para emissão de Notas Fiscais, mas precisa de uma visão unificada e processos automatizados que saibam qual conta utilizar para cada operação (NFe, Sincronização de Estoque, Importação de Pedidos).
O objetivo é normalizar a entrada de pedidos (evitando duplicidade via ID externo) e permitir o mapeamento granular de funções por Canal de Venda ou Plataforma.
Além disso, a planilha de consolidação (`ConsolidarPage`) deve atuar como uma fonte de entrada oficial, salvando os pedidos no banco de dados unificado.

## Arquitetura e Entidades
- **Nova Entidade: `integration_account_routing`**
  - Mapeia (Função, Escopo) -> Conta Bling.
  - Funções: `ORDER_IMPORT`, `NFE_EMISSION`, `CATALOG_SYNC`, `STOCK_SYNC`.
  - Escopo: `GLOBAL`, `PLATFORM`, `CHANNEL`.
- **Alteração em Entidade: `pedidos` (Core)**
  - Adicionar coluna `canal_venda_id` (FK para `canais_venda`). Isso permite saber exatamente de qual loja (Canal) o pedido veio, facilitando o roteamento para a conta Bling correta.
- **Alteração em Entidade: `vinculos_integracao_pedido`**
  - Adicionar coluna `integration_id` (FK para `installed_integrations` ou `contas_bling`) ou `account_id` para desambiguar IDs que podem existir em múltiplas contas da mesma plataforma.

## Plano de Ação (Para Execução no CLine)

- [ ] **Task 1: Migração de Banco de Dados**
  - Criar a tabela `integration_account_routing` no Supabase com colunas: `id`, `module` (bling), `function_name`, `scope_type`, `scope_id`, `account_id`, `is_active`.
  - Alterar tabela `pedidos`: Adicionar coluna `canal_venda_id` (Integer, Nullable).
  - Alterar tabela `vinculos_integracao_pedido`: Adicionar coluna `integration_id` (String/Integer, Nullable).
  - *Critério de aceite:* Schema atualizado e refletido nas definições do Supabase.

- [ ] **Task 2: Shared Service de Roteamento**
  - Criar `IntegrationRoutingService` em `nistiprint_shared/services`.
  - Implementar lógica de busca hierárquica:
    1. Busca por Canal (`scope_type='CHANNEL'`, `scope_id=channel_id`).
    2. Se não achar, busca por Plataforma (`scope_type='PLATFORM'`, `scope_id=platform_name`).
    3. Se não achar, busca Global (`scope_type='GLOBAL'`).
  - *Critério de aceite:* Método `get_account(function, channel_id, platform_name)` retornando o ID da conta correta.

- [ ] **Task 3: Refatoração do BlingClient**
  - Atualizar `BlingClient.create_client_for_platform` para utilizar o novo `IntegrationRoutingService`.
  - Permitir passar `channel_id` ou `context` para a factory, garantindo que o cliente criado aponte para a conta correta.
  - *Critério de aceite:* O client deve ser instanciado com a conta configurada para a função específica.

- [ ] **Task 4: Unificação da Importação (OrderService)**
  - Atualizar `OrderService.upsert_order` para aceitar e persistir `canal_venda_id`.
  - Atualizar a criação de vínculos para salvar `integration_id` se disponível.
  - *Critério de aceite:* Pedidos salvos contêm a referência do canal de venda.

- [ ] **Task 5: Atualização do Processo de Consolidação**
  - Refatorar rota `/api/v2/consolidar` em `apps/api/routes/consolidar.py`.
  - Extrair o `channel_id` do request (já disponível via slug).
  - Iterar sobre os pedidos processados (retornados por `file_processors.py`) e chamar `OrderService.upsert_order` para cada um, efetivando a importação no banco de dados unificado.
  - Utilizar o `IntegrationRoutingService` para obter o cliente Bling correto para as operações de impressão (se solicitado).
  - *Critério de aceite:* Upload de planilha resulta em pedidos salvos na tabela `pedidos` com `canal_venda_id` correto.

- [ ] **Task 6: UI de Gerenciamento de Roteamento**
  - Criar interface em `Configurações > Integrações` (Frontend) para permitir que o usuário defina qual conta Bling cuida de qual canal.
  - *Critério de aceite:* Usuário consegue salvar um mapeamento "Canal Shopee 02 -> Bling Conta 02 para NFe".

- [ ] **Task 7: Validação de Fluxo Completo**
  - Testar a importação de uma planilha na `ConsolidarPage.jsx` selecionando um canal específico.
  - Verificar se o pedido foi criado no banco com o `canal_venda_id`.
  - Verificar se a tentativa de "Gerar NFe" (mockada ou real) utilizaria a conta Bling correta baseada no roteamento.

## Observações de Manutenção
- **Débito Técnico:** As rotas de webhook (`webhooks_v2.py`) também devem ser futuramente atualizadas para usar `OrderService.upsert_order` passando o `instance_id` correto.
- **Compatibilidade:** Manter fallback para comportamento antigo se nenhuma rota for configurada.
