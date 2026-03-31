-- ============================================
-- Adiciona coluna is_placeholder em installed_integrations
-- ============================================
-- Esta coluna identifica integrações criadas automaticamente
-- como placeholders para vínculos órfãos.
--
-- Uso:
-- - is_placeholder = true: Integração criada automaticamente, precisa configuração
-- - is_placeholder = false (ou NULL): Integração instalada pelo usuário
-- ============================================

BEGIN;

-- Adicionar coluna is_placeholder
ALTER TABLE "public"."installed_integrations"
ADD COLUMN IF NOT EXISTS "is_placeholder" boolean DEFAULT false;

-- Adicionar comentário
COMMENT ON COLUMN "public"."installed_integrations"."is_placeholder" IS
'Indica se esta integração é um placeholder criado automaticamente para vínculos órfãos. Placeholders precisam ser configurados pelo usuário antes de usar.';

-- Criar índice para filtrar placeholders rapidamente
CREATE INDEX IF NOT EXISTS "idx_installed_integrations_is_placeholder"
ON "public"."installed_integrations"("is_placeholder")
WHERE "is_placeholder" = true;

-- ============================================
-- Atualizar visão de integrações para mostrar status de placeholder
-- ============================================

-- Criar ou substituir view auxiliar para diagnóstico
CREATE OR REPLACE VIEW "public"."v_integracoes_com_status" AS
SELECT
    ii.id,
    ii.module_id,
    ii.instance_name,
    ii.description,
    ii.is_active,
    ii.is_placeholder,
    ii.sync_status,
    ii.last_sync,
    ii.created_at,
    ii.updated_at,
    CASE
        WHEN ii.is_placeholder THEN '🟡 Placeholder (precisa configurar)'
        WHEN NOT ii.is_active THEN '🔴 Inativa'
        WHEN ii.sync_status = 'error' THEN '🔴 Erro no sync'
        WHEN ii.sync_status = 'success' THEN '🟢 Ativa e sincronizada'
        ELSE '🟡 Pendente'
    END as status_descritivo,
    (
        SELECT COUNT(*)
        FROM integracao_canais_config icc
        WHERE icc.bling_integration_id = ii.id
           OR icc.marketplace_integration_id = ii.id
           OR icc.integration_id = ii.id
    ) as total_vinculos
FROM "public"."installed_integrations" ii
ORDER BY ii.is_placeholder, ii.is_active DESC, ii.module_id, ii.instance_name;

-- Comentário na view
COMMENT ON VIEW "public"."v_integracoes_com_status" IS
'Visão auxiliar para diagnóstico de integrações, mostrando status e se é placeholder.';

-- ============================================
-- Grants
-- ============================================

GRANT ALL ON TABLE "public"."installed_integrations" TO "anon";
GRANT ALL ON TABLE "public"."installed_integrations" TO "authenticated";
GRANT ALL ON TABLE "public"."installed_integrations" TO "service_role";

GRANT ALL ON VIEW "public"."v_integracoes_com_status" TO "anon";
GRANT ALL ON VIEW "public"."v_integracoes_com_status" TO "authenticated";
GRANT ALL ON VIEW "public"."v_integracoes_com_status" TO "service_role";

COMMIT;

-- ============================================
-- Exemplo de uso:
-- ============================================
-- Listar todas as integrações placeholders:
-- SELECT * FROM v_integracoes_com_status WHERE is_placeholder = true;
--
-- Contar placeholders por módulo:
-- SELECT module_id, COUNT(*) as total
-- FROM installed_integrations
-- WHERE is_placeholder = true
-- GROUP BY module_id;
-- ============================================
