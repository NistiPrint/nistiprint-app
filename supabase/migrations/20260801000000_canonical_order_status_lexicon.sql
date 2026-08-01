-- Canonizacao de status de pedido entre origens de ingest.
-- Contrato: docs/specs/03-contracts/canonizacao-status-pedido.md
--
-- 1. `integration_status_mappings` passa a carregar o estagio canonico, sua
--    precedencia e se ele projeta situacao. Vira a fonte autoritativa do lexico.
-- 2. Seed completo da matriz da §6 para shopee, mercadolivre e bling.
--
-- `apply_marketplace_order_event` NAO e alterada: a projecao vigente ja preserva
-- o estado anterior quando o alvo e 3, e 4 continua sendo alvo legitimo de
-- ingest externo ("etiqueta/documentacao emitida pelo marketplace").
--
-- Correcoes de comportamento em producao, todas no seed:
--   mercadolivre/payment/rejected      7 -> 1   tentativa recusada nao cancela venda
--   mercadolivre/payment/refunded      7 -> 8|7 conforme evidencia de despacho
--   mercadolivre/shipping/cancelled    7 -> —   etiqueta cancelada nao cancela venda
--   mercadolivre/shipping/pending      (novo)   nao e evidencia de pagamento
--   shopee/order/IN_CANCEL             (novo)   solicitacao sujeita a recusa
--   shopee/return/PARTIAL_REFUND       (novo)   parcial nao encerra o pedido

-- --------------------------------------------------------------------------
-- 1. Schema do lexico
-- --------------------------------------------------------------------------

ALTER TABLE public.integration_status_mappings
  ADD COLUMN IF NOT EXISTS lifecycle_stage TEXT,
  ADD COLUMN IF NOT EXISTS stage_rank INTEGER,
  ADD COLUMN IF NOT EXISTS projects_situacao BOOLEAN NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS is_terminal BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS is_modifier BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS implies TEXT;

COMMENT ON COLUMN public.integration_status_mappings.lifecycle_stage IS
  'Estagio canonico (vocabulario fechado da §3 da spec de canonizacao).';
COMMENT ON COLUMN public.integration_status_mappings.stage_rank IS
  'Precedencia da §7.1: entre observacoes do mesmo pedido vence o maior rank.';
COMMENT ON COLUMN public.integration_status_mappings.is_modifier IS
  'Estagio que qualifica o estado subjacente (devolucao em andamento, reembolso parcial) em vez de descrever uma situacao propria. A decisao cai para o proximo estagio que projeta.';
COMMENT ON COLUMN public.integration_status_mappings.implies IS
  'O que o valor tambem afirma sobre outros dominios. Documental: alimenta os campos de estado externo em pedidos, nunca a decisao.';

CREATE UNIQUE INDEX IF NOT EXISTS ux_integration_status_mappings_global
  ON public.integration_status_mappings (module_id, status_domain, external_status_id)
  WHERE integration_id IS NULL;

CREATE INDEX IF NOT EXISTS ix_integration_status_mappings_lookup
  ON public.integration_status_mappings (module_id, status_domain, external_status_id)
  WHERE is_active;

-- --------------------------------------------------------------------------
-- 2. Seed da matriz da §6
--
-- Gerado a partir de `order_status_lexicon.SEED_LEXICON`, para que tabela e
-- codigo nao possam divergir por edicao manual. Regras globais
-- (integration_id IS NULL); linhas com integration_id preenchido continuam
-- sobrepondo, o que e o mecanismo para as 3 instancias Bling.
-- --------------------------------------------------------------------------

WITH seed (
  module_id, status_domain, external_status_id, lifecycle_stage, stage_rank,
  internal_situacao_pedido_id, is_terminal, is_modifier, implies
) AS (VALUES
  ('bling', 'order', '12', 'cancelled', 60, 7, false, false, NULL),
  ('bling', 'order', '15', 'paid_preparation', 40, 2, false, false, NULL),
  ('bling', 'order', '18', 'ignored', 1, NULL, false, false, NULL),
  ('bling', 'order', '24', 'fulfillment_ready', 45, 4, false, false, NULL),
  ('bling', 'order', '6', 'awaiting_payment', 10, 1, false, false, NULL),
  ('bling', 'order', '9', 'shipped', 70, 5, false, false, NULL),
  ('mercadolivre', 'order', 'canceled', 'cancelled', 60, 7, false, false, NULL),
  ('mercadolivre', 'order', 'cancelled', 'cancelled', 60, 7, false, false, NULL),
  ('mercadolivre', 'order', 'confirmed', 'awaiting_payment', 10, 1, false, false, NULL),
  ('mercadolivre', 'order', 'invalid', 'cancelled', 60, 7, false, false, NULL),
  ('mercadolivre', 'order', 'opened', 'awaiting_payment', 10, 1, false, false, NULL),
  ('mercadolivre', 'order', 'paid', 'paid_preparation', 40, 2, false, false, NULL),
  ('mercadolivre', 'order', 'partially_paid', 'awaiting_payment', 10, 1, false, false, NULL),
  ('mercadolivre', 'order', 'partially_refunded', 'partially_refunded', 95, NULL, false, true, NULL),
  ('mercadolivre', 'order', 'payment_in_process', 'awaiting_payment', 10, 1, false, false, NULL),
  ('mercadolivre', 'order', 'payment_required', 'awaiting_payment', 10, 1, false, false, NULL),
  ('mercadolivre', 'order', 'pending_cancel', 'cancellation_pending', 55, NULL, false, false, NULL),
  ('mercadolivre', 'payment', 'approved', 'paid_preparation', 40, 2, false, false, NULL),
  ('mercadolivre', 'payment', 'authorized', 'paid_preparation', 40, 2, false, false, NULL),
  ('mercadolivre', 'payment', 'canceled', 'awaiting_payment', 10, 1, false, false, NULL),
  ('mercadolivre', 'payment', 'cancelled', 'awaiting_payment', 10, 1, false, false, NULL),
  ('mercadolivre', 'payment', 'charged_back', 'chargeback_pending', 30, NULL, false, false, NULL),
  ('mercadolivre', 'payment', 'in_mediation', 'chargeback_pending', 30, NULL, false, false, NULL),
  ('mercadolivre', 'payment', 'in_process', 'payment_in_analysis', 20, 1, false, false, NULL),
  ('mercadolivre', 'payment', 'pending', 'payment_in_analysis', 20, 1, false, false, NULL),
  ('mercadolivre', 'payment', 'refunded', 'returned', 100, 8, true, false, NULL),
  ('mercadolivre', 'payment', 'rejected', 'awaiting_payment', 10, 1, false, false, NULL),
  ('mercadolivre', 'payment_detail', 'charged_back:reimbursed', 'returned', 100, 8, true, false, NULL),
  ('mercadolivre', 'payment_detail', 'charged_back:settled', 'returned', 100, 8, true, false, NULL),
  ('mercadolivre', 'return', 'cancelled', 'ignored', 1, NULL, false, false, NULL),
  ('mercadolivre', 'return', 'closed', 'returned', 100, 8, true, false, NULL),
  ('mercadolivre', 'return', 'delivered', 'returned', 100, 8, true, false, NULL),
  ('mercadolivre', 'return', 'label_generated', 'return_in_progress', 90, NULL, false, true, NULL),
  ('mercadolivre', 'return', 'pending', 'return_in_progress', 90, NULL, false, true, NULL),
  ('mercadolivre', 'return', 'pending_delivered', 'return_in_progress', 90, NULL, false, true, NULL),
  ('mercadolivre', 'return', 'pending_expiration', 'return_in_progress', 90, NULL, false, true, NULL),
  ('mercadolivre', 'return', 'pending_failure', 'return_in_progress', 90, NULL, false, true, NULL),
  ('mercadolivre', 'return', 'refunded', 'returned', 100, 8, true, false, NULL),
  ('mercadolivre', 'return', 'scheduled', 'return_in_progress', 90, NULL, false, true, NULL),
  ('mercadolivre', 'return', 'shipped', 'return_in_progress', 90, NULL, false, true, NULL),
  ('mercadolivre', 'shipping', 'canceled', 'ignored', 1, NULL, false, false, NULL),
  ('mercadolivre', 'shipping', 'cancelled', 'ignored', 1, NULL, false, false, NULL),
  ('mercadolivre', 'shipping', 'delivered', 'delivered', 80, 6, false, false, NULL),
  ('mercadolivre', 'shipping', 'handling', 'paid_preparation', 40, 2, false, false, NULL),
  ('mercadolivre', 'shipping', 'not_delivered', 'shipping_exception', 65, 5, false, false, NULL),
  ('mercadolivre', 'shipping', 'pending', 'ignored', 1, NULL, false, false, NULL),
  ('mercadolivre', 'shipping', 'ready_to_ship', 'paid_preparation', 40, 2, false, false, NULL),
  ('mercadolivre', 'shipping', 'shipped', 'shipped', 70, 5, false, false, NULL),
  ('mercadolivre', 'shipping', 'to_be_shipped', 'paid_preparation', 40, 2, false, false, NULL),
  ('mercadolivre', 'shipping_substatus', 'authorized_by_carrier', 'shipped', 70, 5, false, false, NULL),
  ('mercadolivre', 'shipping_substatus', 'dropped_off', 'shipped', 70, 5, false, false, NULL),
  ('mercadolivre', 'shipping_substatus', 'in_hub', 'shipped', 70, 5, false, false, NULL),
  ('mercadolivre', 'shipping_substatus', 'in_transit', 'shipped', 70, 5, false, false, NULL),
  ('mercadolivre', 'shipping_substatus', 'picked_up', 'shipped', 70, 5, false, false, NULL),
  ('mercadolivre', 'shipping_substatus', 'picked_up_for_return', 'return_in_progress', 90, NULL, false, true, NULL),
  ('mercadolivre', 'shipping_substatus', 'returned', 'returned', 100, 8, true, false, NULL),
  ('mercadolivre', 'shipping_substatus', 'returned_to_agency', 'return_in_progress', 90, NULL, false, true, NULL),
  ('mercadolivre', 'shipping_substatus', 'returned_to_hub', 'return_in_progress', 90, NULL, false, true, NULL),
  ('mercadolivre', 'shipping_substatus', 'returned_to_warehouse', 'returned', 100, 8, true, false, NULL),
  ('mercadolivre', 'shipping_substatus', 'returning_to_hub', 'return_in_progress', 90, NULL, false, true, NULL),
  ('mercadolivre', 'shipping_substatus', 'returning_to_sender', 'return_in_progress', 90, NULL, false, true, NULL),
  ('mercadolivre', 'shipping_substatus', 'returning_to_warehouse', 'return_in_progress', 90, NULL, false, true, NULL),
  ('mercadolivre', 'shipping_substatus', 'soon_to_be_returned', 'return_in_progress', 90, NULL, false, true, NULL),
  ('shopee', 'order', 'CANCELLED', 'cancelled', 60, 7, false, false, NULL),
  ('shopee', 'order', 'COMPLETED', 'delivered', 80, 6, false, false, 'shipping:delivered'),
  ('shopee', 'order', 'INVOICE_PENDING', 'paid_preparation', 40, 2, false, false, 'payment:paid'),
  ('shopee', 'order', 'IN_CANCEL', 'cancellation_pending', 55, NULL, false, false, NULL),
  ('shopee', 'order', 'PROCESSED', 'fulfillment_ready', 45, 4, false, false, 'payment:paid,shipping:label_issued'),
  ('shopee', 'order', 'READY_TO_SHIP', 'paid_preparation', 40, 2, false, false, 'payment:paid'),
  ('shopee', 'order', 'RETRY_SHIP', 'paid_preparation', 40, 2, false, false, 'payment:paid,shipping:pickup_failed'),
  ('shopee', 'order', 'SHIPPED', 'shipped', 70, 5, false, false, 'shipping:dispatched'),
  ('shopee', 'order', 'TO_CONFIRM_RECEIVE', 'shipped', 70, 5, false, false, 'shipping:in_transit'),
  ('shopee', 'order', 'TO_RETURN', 'returned', 100, 8, true, false, 'return:open'),
  ('shopee', 'order', 'UNPAID', 'awaiting_payment', 10, 1, false, false, 'payment:pending'),
  ('shopee', 'return', 'ACCEPTED', 'returned', 100, 8, true, false, NULL),
  ('shopee', 'return', 'APPROVED', 'returned', 100, 8, true, false, NULL),
  ('shopee', 'return', 'CANCELLED', 'ignored', 1, NULL, false, false, NULL),
  ('shopee', 'return', 'CLOSED', 'returned', 100, 8, true, false, NULL),
  ('shopee', 'return', 'COMPLETED', 'returned', 100, 8, true, false, NULL),
  ('shopee', 'return', 'JUDGING', 'return_in_progress', 90, NULL, false, true, NULL),
  ('shopee', 'return', 'PARTIALLY_REFUNDED', 'partially_refunded', 95, NULL, false, true, NULL),
  ('shopee', 'return', 'PARTIAL_REFUND', 'partially_refunded', 95, NULL, false, true, NULL),
  ('shopee', 'return', 'PROCESSING', 'return_in_progress', 90, NULL, false, true, NULL),
  ('shopee', 'return', 'REFUNDED', 'returned', 100, 8, true, false, NULL),
  ('shopee', 'return', 'REFUND_PAID', 'returned', 100, 8, true, false, NULL),
  ('shopee', 'return', 'REQUESTED', 'return_in_progress', 90, NULL, false, true, NULL),
  ('shopee', 'return', 'RETURN', 'return_in_progress', 90, NULL, false, true, NULL),
  ('shopee', 'return', 'RETURNED', 'returned', 100, 8, true, false, NULL),
  ('shopee', 'return', 'RETURNING', 'return_in_progress', 90, NULL, false, true, NULL),
  ('shopee', 'return', 'RETURN_COMPLETED', 'returned', 100, 8, true, false, NULL),
  ('shopee', 'return', 'SELLER_DISPUTE', 'return_in_progress', 90, NULL, false, true, NULL),
  ('shopee', 'return', 'SELLER_DISPUTE_SUCCESS', 'ignored', 1, NULL, false, false, NULL),
  ('shopee', 'return', 'TO_RETURN', 'return_in_progress', 90, NULL, false, true, NULL)
)
INSERT INTO public.integration_status_mappings (
  module_id, integration_id, status_domain, external_status_id,
  external_status_name, internal_situacao_pedido_id, lifecycle_stage,
  stage_rank, projects_situacao, is_terminal, is_modifier, implies, is_active
)
SELECT
  s.module_id, NULL, s.status_domain, s.external_status_id,
  s.external_status_id, s.internal_situacao_pedido_id, s.lifecycle_stage,
  s.stage_rank, s.internal_situacao_pedido_id IS NOT NULL, s.is_terminal,
  s.is_modifier, s.implies, true
FROM seed s
ON CONFLICT (module_id, status_domain, external_status_id)
  WHERE integration_id IS NULL
DO UPDATE SET
  internal_situacao_pedido_id = EXCLUDED.internal_situacao_pedido_id,
  lifecycle_stage = EXCLUDED.lifecycle_stage,
  stage_rank = EXCLUDED.stage_rank,
  projects_situacao = EXCLUDED.projects_situacao,
  is_terminal = EXCLUDED.is_terminal,
  is_modifier = EXCLUDED.is_modifier,
  implies = EXCLUDED.implies,
  is_active = true,
  updated_at = now();

-- --------------------------------------------------------------------------
-- 3. Guardas
--
-- Aplicadas depois do seed: as linhas antigas de mercadolivre ainda apontavam
-- para valores que estas restricoes rejeitam.
-- --------------------------------------------------------------------------

ALTER TABLE public.integration_status_mappings
  DROP CONSTRAINT IF EXISTS integration_status_mappings_lifecycle_stage_check;
ALTER TABLE public.integration_status_mappings
  ADD CONSTRAINT integration_status_mappings_lifecycle_stage_check
  CHECK (lifecycle_stage IS NULL OR lifecycle_stage IN (
    'returned', 'partially_refunded', 'return_in_progress', 'delivered',
    'shipped', 'shipping_exception', 'cancelled', 'cancellation_pending',
    'fulfillment_ready', 'paid_preparation', 'chargeback_pending',
    'payment_in_analysis', 'awaiting_payment', 'ignored', 'unknown'
  ));

-- 3 (Produzido) e do modulo de producao interna: ingest externo nunca projeta.
ALTER TABLE public.integration_status_mappings
  DROP CONSTRAINT IF EXISTS integration_status_mappings_external_situacao_check;
ALTER TABLE public.integration_status_mappings
  ADD CONSTRAINT integration_status_mappings_external_situacao_check
  CHECK (internal_situacao_pedido_id IS DISTINCT FROM 3);
