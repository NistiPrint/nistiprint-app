# TODO - Integracoes, Pedidos Canonicos e Credenciais

Este backlog consolida as decisoes e pendencias levantadas na conversa sobre o sistema como roteador/integrador de ERP, marketplaces, webhooks, pedidos e notas fiscais.

## Status Geral

- [x] Diagnosticar inconsistencias entre `installed_integrations`, modulos, origem da venda, webhooks, ingest e pedidos.
- [x] Confirmar que Bling continua necessario como ERP vinculado para emissao de notas fiscais.
- [x] Corrigir teste Shopee para usar o mesmo fallback de credenciais usado pelo ingest de pedidos.
- [x] Centralizar teste de conexao Shopee no driver da plataforma.
- [x] Adicionar teste de conexao Mercado Livre no driver da plataforma.
- [x] Impedir que updates parciais em `installed_integrations` apaguem `config` ou `credentials`.
- [x] Criar resolvedor inicial de capacidades por integracao instalada.
- [x] Usar resolvedor de capacidade para emissao de NF quando o pedido veio de marketplace direto.
- [x] Atualizar UI de configuracao para explicitar origem de pedidos e ERP responsavel por NF.
- [ ] Consolidar `pedido_snapshots` como fonte canonica oficial de leitura de pedidos.
- [ ] Reduzir dependencia progressiva de `pedidos_bling`, `pedidos_shopee` e espelhos similares como fonte principal.

## Integracoes e Roteamento

- [x] Tratar `installed_integrations` como instancia instalada, nao como simples configuracao do modulo.
- [x] Diferenciar modulo de integracao, instancia instalada e conta externa conectada.
- [x] Preservar vinculo Marketplace -> ERP/Bling para emissao de NF.
- [x] Permitir multiplas contas Mercado Livre, cada uma vinculada a uma conta Bling diferente.
- [x] Permitir uma mesma conta marketplace vinculada a multiplas contas Bling por shop.id diferente.
- [ ] Formalizar capacidades por integracao instalada:
  - `ORDER_IMPORT`
  - `ORDER_UPDATE`
  - `INVOICING`
  - `TOKEN_REFRESH`
  - `CONNECTION_TEST`
  - `WEBHOOK_INGEST`
- [x] Criar/validar servico unico de resolucao de capacidade:
  - quem importa pedido
  - quem atualiza pedido
  - quem emite NF
  - quem renova credencial
  - quem processa webhook
- [ ] Garantir que Shopee e Mercado Livre diretos sejam prioridade para ingest quando configurados.
- [ ] Manter Bling como fallback para demais marketplaces/dummy integrations.

## Credenciais

- [x] Criar visao publica de credenciais com `credential_status`.
- [x] Ocultar tokens e segredos das respostas publicas.
- [x] Indicar status de credencial: valida, ausente, expirada, refresh falhou, sync externo etc.
- [x] Diferenciar credenciais gerenciadas localmente de credenciais sincronizadas externamente.
- [x] Bloquear renovacao local para Bling quando a credencial vem do Firebase.
- [x] Permitir refresh local para Shopee e Mercado Livre.
- [x] Normalizar credenciais legadas em `config` e `credentials`.
- [x] Corrigir teste Shopee para buscar `partner_id`/`partner_key` em variaveis de ambiente.
- [x] Corrigir Mercado Livre para usar token em `credentials`, top-level ou legado.
- [ ] Criar migration/backfill para replicar credenciais existentes para os campos canonicos.
- [ ] Criar tela/endpoint de diagnostico de credenciais por instalacao.
- [ ] Exibir corretamente expiracao, ultima renovacao, erro de renovacao e origem da credencial.
- [ ] Registrar historico de eventos de credenciais por integracao.
- [ ] Avaliar criptografia/secret storage para campos sensiveis em `credentials`.

## Teste de Conexao e Drivers

- [x] Adicionar `test_connection()` ao driver Shopee.
- [x] Adicionar `test_connection()` ao driver Mercado Livre.
- [x] Adicionar `PlatformApiService.test_connection()`.
- [x] Atualizar rota `/api/v2/marketplace/installed/<id>/test` para tentar primeiro o driver.
- [ ] Remover gradualmente logica paralela de teste em `platform_auth_service`.
- [ ] Padronizar contrato de retorno dos drivers:
  - `success`
  - `message`
  - `details`
  - `error`
  - `code`
- [ ] Fazer drivers usarem resolvedor compartilhado de credenciais.
- [ ] Padronizar fallback para env vars apenas quando explicitamente permitido pela estrategia da integracao.

## Webhooks e Ingest

- [x] Definir Shopee como importacao/atualizacao via webhook direto Shopee.
- [x] Definir Mercado Livre como importacao/atualizacao via webhook direto Mercado Livre.
- [x] Manter demais marketplaces via webhook Bling.
- [x] Confirmar que `marketplace_webhook_ingest_service` grava snapshot canonico para Shopee/ML.
- [ ] Garantir idempotencia por `marketplace_order_id` + `marketplace_integration_id`.
- [ ] Garantir deduplicacao entre Bling e webhook direto do marketplace.
- [ ] Definir regra de precedencia quando Bling e marketplace direto atualizam o mesmo pedido.
- [ ] Criar auditoria de origem do dado por campo: Bling, Shopee, Mercado Livre, local.
- [ ] Revisar dead-letter/reprocessamento para webhooks Shopee e Mercado Livre.

## Pedido Canonico

- [x] Identificar `pedido_snapshots` como caminho ja existente para payload canonico.
- [x] Identificar `platform_fields` como local correto para particularidades por marketplace.
- [x] Preservar comprador, itens, logisticas, financeiro, identidade e referencias brutas no snapshot.
- [ ] Definir contrato formal do pedido canonico:
  - identidade
  - comprador
  - itens
  - financeiro
  - logistica
  - status
  - timestamps operacionais
  - referencias externas
  - campos especificos de plataforma
- [ ] Garantir que todas as importacoes gravem `pedido_snapshots`.
- [ ] Migrar telas de pedido para lerem preferencialmente `pedido_snapshots`.
- [ ] Padronizar armazenamento de particularidades:
  - Shopee: `buyer_username`, `buyer_user_id`, regra Flex, pacote, carrier, mensagem do comprador
  - Mercado Livre: buyer nickname/id, shipment, SLA, payment status, shipping status
  - Bling: numero, loja, nota fiscal, contato, transporte
- [ ] Definir validadores por modulo para `platform_fields`.
- [ ] Criar testes de contrato para snapshots Shopee, Mercado Livre e Bling.

## Notas Fiscais

- [ ] Criar dominio explicito de Notas Fiscais.
- [ ] Modelar configuracao de emissao por marketplace instalado.
- [ ] Permitir opcoes por conta:
  - emissao local
  - ERP Bling vinculado
  - desabilitado
- [ ] Exibir apenas ERPs vinculados ao marketplace na configuracao de NF.
- [ ] Criar roteamento `INVOICING` por integracao instalada.
- [ ] Registrar tentativas de emissao, retorno do ERP e vinculo com pedido.
- [ ] Validar caso Mercado Livre com duas contas, cada uma emitindo por Bling diferente.

## Frontend

- [x] Ajustar cards/lista de integracoes para usar `credential_status`.
- [x] Evitar botao de renovar para credencial Bling sincronizada externamente.
- [x] Reabilitar renovacao Shopee/ML quando o modulo suporta refresh.
- [x] Criar tela clara de vinculo Marketplace -> ERP.
- [x] Criar UI inicial de configuracao de funcionalidades expostas por integracao.
- [x] Criar UI inicial de emissao de NF por marketplace instalado.
- [x] Remover dependencia de configurar vinculo direto apenas dentro da instancia Bling:
  - Marketplace direto aponta para a conta Bling associada.
  - ERP/Bling adiciona vinculos de marketplaces dummy sem integracao direta.
- [x] Ajustar configuracao para dummies serem instancias instaladas, nao apenas modulos soltos.
- [x] Bloquear resolucao de NF ambigua quando marketplace possui mais de um ERP e o pedido nao informa shop.id/Bling.
- [ ] Mostrar status de webhook/processamento por integracao.
- [ ] Mostrar diagnostico de credenciais sem expor segredos.

## Banco de Dados

- [ ] Criar migration/backfill de credenciais legadas.
- [ ] Revisar `installed_integrations` para separar claramente:
  - identificadores publicos da conta
  - credenciais sensiveis
  - status de credencial
  - capacidades da integracao
  - vinculos com ERP
- [ ] Formalizar tabela/contrato para funcionalidades expostas por integracao.
- [ ] Formalizar tabela/contrato para configuracao de NF.
- [ ] Consolidar leitura de pedidos em `pedido_snapshots`.
- [ ] Transformar tabelas especificas de marketplace em espelhos/auditoria, nao fonte primaria.
- [ ] Criar views de compatibilidade para telas antigas durante a transicao.

## Validacao

- [x] Testes unitarios para credential status.
- [x] Testes unitarios para Shopee driver/teste com env vars.
- [x] Testes unitarios para Mercado Livre driver/teste.
- [x] Testes para update parcial de `installed_integrations`.
- [ ] Testes end-to-end para:
  - webhook Shopee -> pedido canonico
  - webhook Mercado Livre -> pedido canonico
  - webhook Bling -> pedido canonico
  - emissao NF via Bling vinculado
  - duas contas Mercado Livre vinculadas a dois Blings diferentes
- [ ] Teste de migracao/backfill em base staging antes de producao.
