-- ============================================
-- Migration: Cleanup Final (Fase 6)
-- ============================================
-- Remove views de compatibilidade
-- Remove campos deprecated
-- Remove tabela plataformas (se existir)
-- ============================================

-- ====================================================
-- ATENÇÃO: Esta migration deve ser executada APÓS:
-- 1. Todas as fases anteriores (1-5) validadas
-- 2. Frontend atualizado para usar novas interfaces
-- 3. Tests de regressão passando
-- 4. Backup completo do banco realizado
-- ====================================================

-- ====================================================
-- PASSO 1: Remover views de compatibilidade
-- ====================================================

-- 1.1 Remover view plataformas_compat (criada na Fase 1)
DROP VIEW IF EXISTS "public"."plataformas_compat" CASCADE;

-- 1.2 Remover view integracao_canais_config_compat (criada na Fase 2)
DROP VIEW IF EXISTS "public"."integracao_canais_config_compat" CASCADE;

-- 1.3 Remover view pedidos_com_external_id (criada na Fase 5)
DROP VIEW IF EXISTS "public"."pedidos_com_external_id" CASCADE;

-- ====================================================
-- PASSO 2: Remover campos deprecated de canais_venda
-- ====================================================

-- 2.1 Remover conta_bling_id
ALTER TABLE "public"."canais_venda" 
DROP COLUMN IF EXISTS conta_bling_id;

-- 2.2 Remover bling_loja_id_principal
ALTER TABLE "public"."canais_venda" 
DROP COLUMN IF EXISTS bling_loja_id_principal;

-- 2.3 Remover integration_id_principal
ALTER TABLE "public"."canais_venda" 
DROP COLUMN IF EXISTS integration_id_principal;

-- ====================================================
-- PASSO 3: Remover campos deprecated de pedidos
-- ====================================================

-- 3.1 Remover codigo_pedido_externo
-- Nota: Certificar-se de que todos os dados foram migrados para vinculos_integracao_pedido
ALTER TABLE "public"."pedidos" 
DROP COLUMN IF EXISTS codigo_pedido_externo;

-- ====================================================
-- PASSO 4: Remover campos deprecated de demandas_producao
-- ====================================================

-- 4.1 Remover horario_coleta
-- Nota: Dados já foram migrados para channel_snapshot na Fase 5
ALTER TABLE "public"."demandas_producao" 
DROP COLUMN IF EXISTS horario_coleta;

-- ====================================================
-- PASSO 5: Remover tabela plataformas (se existir)
-- ====================================================

-- 5.1 Remover foreign key em canais_venda.plataforma_id (se existir)
ALTER TABLE "public"."canais_venda" 
DROP CONSTRAINT IF EXISTS canais_venda_plataforma_id_fkey;

-- 5.2 Remover tabela plataformas
DROP TABLE IF EXISTS "public"."plataformas" CASCADE;

-- 5.3 Remover sequence associada (se existir)
DROP SEQUENCE IF EXISTS "public"."plataformas_id_seq" CASCADE;

-- ====================================================
-- PASSO 6: Limpeza de índices órfãos
-- ====================================================

-- 6.1 Remover índices de campos removidos
DROP INDEX IF EXISTS "public"."idx_canais_venda_bling_loja_id";
DROP INDEX IF EXISTS "public"."idx_canais_venda_conta_bling_id";

-- ====================================================
-- PASSO 7: Atualizar comentários para refletir estado final
-- ====================================================

COMMENT ON COLUMN "public"."canais_venda"."plataforma_id" IS 
  'DEPRECATED: vínculo agora é feito via channel_connections.
   Este campo será removido em futura migration.';

COMMENT ON COLUMN "public"."channel_connections"."aggregator_store_id" IS 
  'Identificador da loja no agregador (ex: Bling).
   Para Bling: bling_loja_id (ex: 204047801, 205218967).
   Null quando a integração é direta (Shopee OAuth conectado diretamente).';

-- ====================================================
-- PASSO 8: Atualizar tipos TypeScript (manual)
-- ====================================================

-- Arquivo: apps/frontend/src/types/producao.ts
-- Ações necessárias:
-- 1. Remover interface Plataforma (ou marcar como deprecated)
-- 2. Remover CanalVenda.conta_bling_id
-- 3. Remover DemandaProducao.horario_coleta
-- 4. Remover IntegracaoCanaisConfig (usar apenas ChannelConnection)

-- ====================================================
-- PASSO 9: Atualizar serviços Python (manual)
-- ====================================================

-- Arquivos para atualizar:
-- 1. packages/shared/nistiprint_shared/services/canal_venda_service.py
--    - Remover referências a conta_bling_id
-- 
-- 2. packages/shared/nistiprint_shared/services/order_service.py
--    - Remover referências a codigo_pedido_externo
--    - Usar vinculos_integracao_pedido ou fn_external_id()
--
-- 3. packages/shared/nistiprint_shared/services/demanda_producao_service.py
--    - Remover referências a horario_coleta
--    - Usar channel_snapshot->>'horario_coleta'

-- ====================================================
-- ROLLBACK (se necessário)
-- ====================================================

-- Para rollback, executar na ordem inversa:
-- 1. Recriar tabela plataformas
-- 2. Recriar campos deprecated
-- 3. Recriar views de compatibilidade
-- 4. Restaurar dados de backup

-- Exemplo de rollback parcial (recriar campos):
-- ALTER TABLE "public"."canais_venda" ADD COLUMN conta_bling_id varchar(255);
-- ALTER TABLE "public"."pedidos" ADD COLUMN codigo_pedido_externo varchar(100);
-- ALTER TABLE "public"."demandas_producao" ADD COLUMN horario_coleta time;
