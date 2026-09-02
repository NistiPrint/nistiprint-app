-- Migration to add "Fechando" status to itens_demanda
-- Created at: 2026-04-11
-- Description: Adds new status "Fechando" to represent items that have been withdrawn by expedition
-- but not yet assembled/closed. This addresses the conceptual error where withdrawn items
-- were incorrectly marked as "Concluído" (finalized).

-- Note: No constraint change needed as status_item is a varchar(50) field
-- The new status will be used in application logic
