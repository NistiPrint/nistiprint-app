-- Canonical order identity and provider-neutral ERP aliases.

ALTER TABLE public.pedidos
  ADD COLUMN IF NOT EXISTS marketplace_module_id TEXT,
  ADD COLUMN IF NOT EXISTS erp_integration_id INTEGER
    REFERENCES public.installed_integrations(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS erp_store_id VARCHAR(100),
  ADD COLUMN IF NOT EXISTS erp_order_id BIGINT,
  ADD COLUMN IF NOT EXISTS erp_order_number VARCHAR(100);

UPDATE public.pedidos p
   SET marketplace_module_id = lower(ii.module_id)
  FROM public.installed_integrations ii
 WHERE p.marketplace_integration_id = ii.id
   AND p.marketplace_module_id IS NULL;

UPDATE public.pedidos p
   SET marketplace_module_id = lower(eml.marketplace_module_id)
  FROM public.erp_marketplace_links eml
 WHERE p.marketplace_module_id IS NULL
   AND eml.erp_integration_id = p.bling_integration_id
   AND eml.erp_store_id = p.bling_loja_id
   AND (
     p.marketplace_integration_id IS NULL
     OR eml.marketplace_integration_id = p.marketplace_integration_id
   );

UPDATE public.pedidos
   SET marketplace_module_id = lower(origem)
 WHERE marketplace_module_id IS NULL
   AND lower(origem) IN ('shopee', 'mercadolivre');

UPDATE public.pedidos
   SET marketplace_order_id = codigo_pedido_externo
 WHERE marketplace_order_id IS NULL
   AND codigo_pedido_externo IS NOT NULL;

UPDATE public.pedidos
   SET erp_integration_id = COALESCE(erp_integration_id, bling_integration_id),
       erp_store_id = COALESCE(erp_store_id, bling_loja_id),
       erp_order_id = COALESCE(erp_order_id, bling_order_id),
       erp_order_number = COALESCE(erp_order_number, bling_order_number, numero_pedido);

CREATE TABLE IF NOT EXISTS public.order_identity_conflicts (
  id BIGSERIAL PRIMARY KEY,
  marketplace_module_id TEXT,
  marketplace_order_id TEXT,
  pedido_ids BIGINT[] NOT NULL,
  conflict_kind TEXT NOT NULL,
  details JSONB NOT NULL DEFAULT '{}'::jsonb,
  resolved_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO public.order_identity_conflicts (
  marketplace_module_id, marketplace_order_id, pedido_ids, conflict_kind, details
)
SELECT
  marketplace_module_id,
  marketplace_order_id,
  array_agg(id::BIGINT ORDER BY id),
  'duplicate_canonical_identity',
  jsonb_build_object(
    'marketplace_integration_ids',
    jsonb_agg(DISTINCT marketplace_integration_id)
  )
FROM public.pedidos
WHERE marketplace_module_id IS NOT NULL
  AND marketplace_order_id IS NOT NULL
GROUP BY marketplace_module_id, marketplace_order_id
HAVING count(*) > 1;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM public.pedidos
    WHERE marketplace_module_id IS NOT NULL
      AND marketplace_order_id IS NOT NULL
    GROUP BY marketplace_module_id, marketplace_order_id
    HAVING count(*) > 1
  ) THEN
    RAISE EXCEPTION
      'Duplicate canonical identities found. Resolve order_identity_conflicts first.';
  END IF;
END $$;

DROP INDEX IF EXISTS public.ux_pedidos_marketplace_identity;
ALTER TABLE public.pedidos
  DROP CONSTRAINT IF EXISTS pedidos_codigo_pedido_externo_key;
CREATE UNIQUE INDEX IF NOT EXISTS ux_pedidos_canonical_identity
  ON public.pedidos (marketplace_module_id, marketplace_order_id);

CREATE TABLE IF NOT EXISTS public.pending_order_reconciliations (
  id BIGSERIAL PRIMARY KEY,
  pedido_id BIGINT REFERENCES public.pedidos(id) ON DELETE CASCADE,
  erp_integration_id INTEGER
    REFERENCES public.installed_integrations(id) ON DELETE SET NULL,
  erp_store_id VARCHAR(100),
  erp_order_id BIGINT,
  marketplace_order_id TEXT,
  reason TEXT NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'matched', 'applied', 'expired', 'failed')),
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_pending_order_reconciliation_order
  ON public.pending_order_reconciliations (pedido_id)
  WHERE pedido_id IS NOT NULL AND status = 'pending';

CREATE UNIQUE INDEX IF NOT EXISTS ux_pending_order_reconciliation_erp_order
  ON public.pending_order_reconciliations (
    erp_integration_id, erp_order_id, status
  ) NULLS NOT DISTINCT;

INSERT INTO public.pending_order_reconciliations (
  pedido_id, erp_integration_id, erp_store_id, erp_order_id,
  marketplace_order_id, reason, payload
)
SELECT
  p.id, p.erp_integration_id, p.erp_store_id, p.erp_order_id,
  p.marketplace_order_id, 'marketplace_module_unresolved',
  jsonb_build_object(
    'origem', p.origem,
    'marketplace_integration_id', p.marketplace_integration_id,
    'canal_venda_id', p.canal_venda_id
  )
FROM public.pedidos p
WHERE p.marketplace_module_id IS NULL
ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS public.pending_marketplace_enrichments (
  id BIGSERIAL PRIMARY KEY,
  marketplace_integration_id INTEGER NOT NULL
    REFERENCES public.installed_integrations(id) ON DELETE CASCADE,
  marketplace_module_id TEXT NOT NULL,
  marketplace_order_id TEXT NOT NULL,
  event_type TEXT,
  source_event_id TEXT,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'matched', 'applied', 'expired', 'failed')),
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL DEFAULT (now() + interval '30 days'),
  matched_pedido_id BIGINT REFERENCES public.pedidos(id) ON DELETE SET NULL,
  applied_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_pending_marketplace_event
  ON public.pending_marketplace_enrichments (
    marketplace_integration_id, marketplace_order_id, source_event_id
  ) NULLS NOT DISTINCT;

CREATE INDEX IF NOT EXISTS idx_pending_marketplace_reconcile
  ON public.pending_marketplace_enrichments (
    marketplace_module_id, marketplace_order_id, status
  );

-- Generic provider references replace provider-specific foreign keys over time.
CREATE TABLE IF NOT EXISTS public.pedido_integration_refs (
  id BIGSERIAL PRIMARY KEY,
  pedido_id BIGINT NOT NULL REFERENCES public.pedidos(id) ON DELETE CASCADE,
  integration_id INTEGER REFERENCES public.installed_integrations(id) ON DELETE SET NULL,
  module_id TEXT NOT NULL,
  role TEXT NOT NULL
    CHECK (role IN ('sales_origin', 'ingest_source', 'erp', 'enrichment')),
  external_order_id TEXT NOT NULL,
  external_record_id TEXT,
  external_status TEXT,
  last_synced_at TIMESTAMPTZ,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_pedido_ref_sales_origin
  ON public.pedido_integration_refs (module_id, external_order_id)
  WHERE role = 'sales_origin';

CREATE UNIQUE INDEX IF NOT EXISTS ux_pedido_ref_provider_record
  ON public.pedido_integration_refs (
    module_id, COALESCE(integration_id, 0), external_order_id, role
  )
  WHERE role <> 'sales_origin';

CREATE UNIQUE INDEX IF NOT EXISTS ux_pedido_ref_integration_role
  ON public.pedido_integration_refs (pedido_id, integration_id, role)
  NULLS NOT DISTINCT;

CREATE INDEX IF NOT EXISTS idx_pedido_refs_pedido
  ON public.pedido_integration_refs (pedido_id);

-- Keep new canonical names and legacy columns synchronized during migration.
CREATE OR REPLACE FUNCTION public.sync_canonical_order_compat_fields()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF NEW.marketplace_module_id IS NULL AND NEW.marketplace_integration_id IS NOT NULL THEN
    SELECT lower(ii.module_id)
      INTO NEW.marketplace_module_id
      FROM public.installed_integrations ii
     WHERE ii.id = NEW.marketplace_integration_id;
  END IF;

  NEW.marketplace_module_id := lower(NULLIF(NEW.marketplace_module_id, ''));
  NEW.marketplace_order_id := COALESCE(
    NULLIF(NEW.marketplace_order_id, ''), NEW.codigo_pedido_externo
  );
  NEW.erp_integration_id := COALESCE(
    NEW.erp_integration_id, NEW.bling_integration_id
  );
  NEW.erp_store_id := COALESCE(NULLIF(NEW.erp_store_id, ''), NEW.bling_loja_id);
  NEW.erp_order_id := COALESCE(NEW.erp_order_id, NEW.bling_order_id);
  NEW.erp_order_number := COALESCE(
    NULLIF(NEW.erp_order_number, ''), NEW.bling_order_number, NEW.numero_pedido
  );

  NEW.codigo_pedido_externo := COALESCE(
    NEW.codigo_pedido_externo, NEW.marketplace_order_id
  );
  NEW.numero_pedido := COALESCE(
    NULLIF(NEW.numero_pedido, ''), NEW.erp_order_number, NEW.marketplace_order_id
  );
  NEW.origem := COALESCE(
    NULLIF(NEW.origem, ''), upper(NEW.marketplace_module_id)
  );
  NEW.informacoes_cliente := COALESCE(NEW.informacoes_cliente, '{}'::jsonb);

  NEW.bling_integration_id := COALESCE(
    NEW.bling_integration_id, NEW.erp_integration_id
  );
  NEW.bling_loja_id := COALESCE(NULLIF(NEW.bling_loja_id, ''), NEW.erp_store_id);
  NEW.bling_order_id := COALESCE(NEW.bling_order_id, NEW.erp_order_id);
  NEW.bling_order_number := COALESCE(
    NULLIF(NEW.bling_order_number, ''), NEW.erp_order_number
  );

  IF TG_OP = 'UPDATE'
     AND OLD.marketplace_module_id IS NOT NULL
     AND OLD.marketplace_order_id IS NOT NULL
     AND (
       OLD.marketplace_module_id IS DISTINCT FROM NEW.marketplace_module_id
       OR OLD.marketplace_order_id IS DISTINCT FROM NEW.marketplace_order_id
     )
     AND COALESCE(current_setting('app.allow_order_identity_correction', true), 'false') <> 'true' THEN
    RAISE EXCEPTION
      'Canonical order identity is immutable; use correct_canonical_order_identity';
  END IF;

  IF TG_OP = 'INSERT'
     AND (NEW.marketplace_module_id IS NULL OR NEW.marketplace_order_id IS NULL) THEN
    RAISE EXCEPTION
      'Canonical order identity is required (marketplace_module_id + marketplace_order_id)';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_sync_canonical_order_compat_fields ON public.pedidos;
CREATE TRIGGER trg_sync_canonical_order_compat_fields
BEFORE INSERT OR UPDATE ON public.pedidos
FOR EACH ROW
EXECUTE FUNCTION public.sync_canonical_order_compat_fields();

-- Backfill generic references for existing canonical and ERP identities.
INSERT INTO public.pedido_integration_refs (
  pedido_id, integration_id, module_id, role, external_order_id,
  external_record_id, external_status, last_synced_at
)
SELECT
  p.id, p.marketplace_integration_id, p.marketplace_module_id, 'sales_origin',
  p.marketplace_order_id,
  CASE
    WHEN p.marketplace_module_id = 'shopee' THEN p.pedido_shopee_id::TEXT
    WHEN p.marketplace_module_id = 'mercadolivre' THEN p.pedido_mercadolivre_id::TEXT
    ELSE NULL
  END,
  p.status_original,
  p.updated_at::TIMESTAMPTZ
FROM public.pedidos p
WHERE p.marketplace_module_id IS NOT NULL
  AND p.marketplace_order_id IS NOT NULL
ON CONFLICT (module_id, external_order_id)
  WHERE role = 'sales_origin'
DO UPDATE SET
  integration_id = EXCLUDED.integration_id,
  external_record_id = COALESCE(
    EXCLUDED.external_record_id, public.pedido_integration_refs.external_record_id
  ),
  external_status = COALESCE(
    EXCLUDED.external_status, public.pedido_integration_refs.external_status
  ),
  last_synced_at = EXCLUDED.last_synced_at,
  updated_at = now();

INSERT INTO public.pedido_integration_refs (
  pedido_id, integration_id, module_id, role, external_order_id,
  external_record_id, last_synced_at, metadata
)
SELECT
  p.id, p.erp_integration_id, 'bling', 'erp',
  COALESCE(p.erp_order_id::TEXT, p.erp_order_number),
  p.pedido_bling_id::TEXT,
  p.updated_at::TIMESTAMPTZ,
  jsonb_build_object('store_id', p.erp_store_id)
FROM public.pedidos p
WHERE p.erp_integration_id IS NOT NULL
  AND COALESCE(p.erp_order_id::TEXT, p.erp_order_number) IS NOT NULL
ON CONFLICT (
  module_id, (COALESCE(integration_id, 0)), external_order_id, role
)
  WHERE role <> 'sales_origin'
DO UPDATE SET
  pedido_id = EXCLUDED.pedido_id,
  external_record_id = COALESCE(
    EXCLUDED.external_record_id, public.pedido_integration_refs.external_record_id
  ),
  metadata = public.pedido_integration_refs.metadata || EXCLUDED.metadata,
  last_synced_at = EXCLUDED.last_synced_at,
  updated_at = now();

-- Atomic canonical persistence: order, snapshot and provider references.
CREATE OR REPLACE FUNCTION public.upsert_canonical_order(
  p_order JSONB,
  p_snapshot JSONB DEFAULT NULL,
  p_refs JSONB DEFAULT '[]'::jsonb
)
RETURNS BIGINT
LANGUAGE plpgsql
AS $$
DECLARE
  v_pedido_id BIGINT;
  v_module_id TEXT := lower(NULLIF(p_order->>'marketplace_module_id', ''));
  v_marketplace_order_id TEXT := NULLIF(p_order->>'marketplace_order_id', '');
  v_ref JSONB;
BEGIN
  IF v_module_id IS NULL OR v_marketplace_order_id IS NULL THEN
    RAISE EXCEPTION
      'Canonical order identity is required (marketplace_module_id + marketplace_order_id)';
  END IF;

  INSERT INTO public.pedidos (
    marketplace_module_id, marketplace_order_id, marketplace_integration_id,
    ingest_source, erp_integration_id, erp_store_id, erp_order_id,
    erp_order_number, situacao_pedido_id, status_original, total_pedido,
    moeda, data_venda, cliente_nome, cliente_documento, cliente_telefone,
    cliente_email, is_flex, is_fulfillment, modalidade_logistica,
    servico_logistico, data_limite_envio, data_compra_marketplace,
    data_pagamento_marketplace, data_coleta, data_envio_marketplace,
    regra_logistica_integracao_id, personalizado, canal_venda_id,
    informacoes_cliente, pedido_bling_id, pedido_shopee_id,
    pedido_mercadolivre_id, buyer_username, shipping_carrier,
    message_to_seller, updated_at
  ) VALUES (
    v_module_id,
    v_marketplace_order_id,
    NULLIF(p_order->>'marketplace_integration_id', '')::INTEGER,
    NULLIF(p_order->>'ingest_source', ''),
    NULLIF(p_order->>'erp_integration_id', '')::INTEGER,
    NULLIF(p_order->>'erp_store_id', ''),
    NULLIF(p_order->>'erp_order_id', '')::BIGINT,
    NULLIF(p_order->>'erp_order_number', ''),
    NULLIF(p_order->>'situacao_pedido_id', '')::INTEGER,
    NULLIF(p_order->>'status_original', ''),
    NULLIF(p_order->>'total_pedido', '')::NUMERIC,
    COALESCE(NULLIF(p_order->>'moeda', ''), 'BRL'),
    NULLIF(p_order->>'data_venda', '')::TIMESTAMPTZ,
    NULLIF(p_order->>'cliente_nome', ''),
    NULLIF(p_order->>'cliente_documento', ''),
    NULLIF(p_order->>'cliente_telefone', ''),
    NULLIF(p_order->>'cliente_email', ''),
    COALESCE((p_order->>'is_flex')::BOOLEAN, false),
    COALESCE((p_order->>'is_fulfillment')::BOOLEAN, false),
    NULLIF(p_order->>'modalidade_logistica', ''),
    NULLIF(p_order->>'servico_logistico', ''),
    NULLIF(p_order->>'data_limite_envio', '')::TIMESTAMPTZ,
    NULLIF(p_order->>'data_compra_marketplace', '')::TIMESTAMPTZ,
    NULLIF(p_order->>'data_pagamento_marketplace', '')::TIMESTAMPTZ,
    NULLIF(p_order->>'data_coleta', '')::TIMESTAMPTZ,
    NULLIF(p_order->>'data_envio_marketplace', '')::TIMESTAMPTZ,
    NULLIF(p_order->>'regra_logistica_integracao_id', '')::BIGINT,
    COALESCE((p_order->>'personalizado')::BOOLEAN, false),
    NULLIF(p_order->>'canal_venda_id', '')::INTEGER,
    COALESCE(p_order->'customer', '{}'::jsonb),
    NULLIF(p_order->>'pedido_bling_id', '')::BIGINT,
    NULLIF(p_order->>'pedido_shopee_id', '')::BIGINT,
    NULLIF(p_order->>'pedido_mercadolivre_id', '')::INTEGER,
    NULLIF(p_order->>'buyer_username', ''),
    NULLIF(p_order->>'shipping_carrier', ''),
    NULLIF(p_order->>'message_to_seller', ''),
    now()
  )
  ON CONFLICT (marketplace_module_id, marketplace_order_id)
  DO UPDATE SET
    marketplace_integration_id = COALESCE(EXCLUDED.marketplace_integration_id, public.pedidos.marketplace_integration_id),
    ingest_source = COALESCE(EXCLUDED.ingest_source, public.pedidos.ingest_source),
    erp_integration_id = COALESCE(EXCLUDED.erp_integration_id, public.pedidos.erp_integration_id),
    erp_store_id = COALESCE(EXCLUDED.erp_store_id, public.pedidos.erp_store_id),
    erp_order_id = COALESCE(EXCLUDED.erp_order_id, public.pedidos.erp_order_id),
    erp_order_number = COALESCE(EXCLUDED.erp_order_number, public.pedidos.erp_order_number),
    situacao_pedido_id = COALESCE(EXCLUDED.situacao_pedido_id, public.pedidos.situacao_pedido_id),
    status_original = COALESCE(EXCLUDED.status_original, public.pedidos.status_original),
    total_pedido = COALESCE(EXCLUDED.total_pedido, public.pedidos.total_pedido),
    moeda = COALESCE(EXCLUDED.moeda, public.pedidos.moeda),
    data_venda = COALESCE(EXCLUDED.data_venda, public.pedidos.data_venda),
    cliente_nome = COALESCE(EXCLUDED.cliente_nome, public.pedidos.cliente_nome),
    cliente_documento = COALESCE(EXCLUDED.cliente_documento, public.pedidos.cliente_documento),
    cliente_telefone = COALESCE(EXCLUDED.cliente_telefone, public.pedidos.cliente_telefone),
    cliente_email = COALESCE(EXCLUDED.cliente_email, public.pedidos.cliente_email),
    is_flex = CASE WHEN p_order ? 'is_flex' THEN EXCLUDED.is_flex ELSE public.pedidos.is_flex END,
    is_fulfillment = CASE WHEN p_order ? 'is_fulfillment' THEN EXCLUDED.is_fulfillment ELSE public.pedidos.is_fulfillment END,
    modalidade_logistica = COALESCE(EXCLUDED.modalidade_logistica, public.pedidos.modalidade_logistica),
    servico_logistico = COALESCE(EXCLUDED.servico_logistico, public.pedidos.servico_logistico),
    data_limite_envio = COALESCE(EXCLUDED.data_limite_envio, public.pedidos.data_limite_envio),
    data_compra_marketplace = COALESCE(EXCLUDED.data_compra_marketplace, public.pedidos.data_compra_marketplace),
    data_pagamento_marketplace = COALESCE(EXCLUDED.data_pagamento_marketplace, public.pedidos.data_pagamento_marketplace),
    data_coleta = COALESCE(EXCLUDED.data_coleta, public.pedidos.data_coleta),
    data_envio_marketplace = COALESCE(EXCLUDED.data_envio_marketplace, public.pedidos.data_envio_marketplace),
    regra_logistica_integracao_id = COALESCE(EXCLUDED.regra_logistica_integracao_id, public.pedidos.regra_logistica_integracao_id),
    personalizado = CASE WHEN p_order ? 'personalizado' THEN EXCLUDED.personalizado ELSE public.pedidos.personalizado END,
    canal_venda_id = COALESCE(EXCLUDED.canal_venda_id, public.pedidos.canal_venda_id),
    informacoes_cliente = CASE
      WHEN EXCLUDED.informacoes_cliente = '{}'::jsonb THEN public.pedidos.informacoes_cliente
      ELSE EXCLUDED.informacoes_cliente
    END,
    pedido_bling_id = COALESCE(EXCLUDED.pedido_bling_id, public.pedidos.pedido_bling_id),
    pedido_shopee_id = COALESCE(EXCLUDED.pedido_shopee_id, public.pedidos.pedido_shopee_id),
    pedido_mercadolivre_id = COALESCE(EXCLUDED.pedido_mercadolivre_id, public.pedidos.pedido_mercadolivre_id),
    buyer_username = COALESCE(EXCLUDED.buyer_username, public.pedidos.buyer_username),
    shipping_carrier = COALESCE(EXCLUDED.shipping_carrier, public.pedidos.shipping_carrier),
    message_to_seller = COALESCE(EXCLUDED.message_to_seller, public.pedidos.message_to_seller),
    updated_at = now()
  RETURNING id INTO v_pedido_id;

  IF p_snapshot IS NOT NULL THEN
    INSERT INTO public.pedido_snapshots (
      pedido_id, identity, customer, items, logistics, financial,
      platform_fields, raw_refs, source_history, updated_at
    ) VALUES (
      v_pedido_id,
      COALESCE(p_snapshot->'identity', '{}'::jsonb),
      COALESCE(p_snapshot->'customer', '{}'::jsonb),
      COALESCE(p_snapshot->'items', '[]'::jsonb),
      COALESCE(p_snapshot->'logistics', '{}'::jsonb),
      COALESCE(p_snapshot->'financial', '{}'::jsonb),
      COALESCE(p_snapshot->'platform_fields', '{}'::jsonb),
      COALESCE(p_snapshot->'raw_refs', '{}'::jsonb),
      COALESCE(p_snapshot->'source_history', '[]'::jsonb),
      now()
    )
    ON CONFLICT (pedido_id) DO UPDATE SET
      identity = public.pedido_snapshots.identity || EXCLUDED.identity,
      customer = public.pedido_snapshots.customer || EXCLUDED.customer,
      items = CASE WHEN EXCLUDED.items = '[]'::jsonb
        THEN public.pedido_snapshots.items ELSE EXCLUDED.items END,
      logistics = public.pedido_snapshots.logistics || EXCLUDED.logistics,
      financial = public.pedido_snapshots.financial || EXCLUDED.financial,
      platform_fields = public.pedido_snapshots.platform_fields || EXCLUDED.platform_fields,
      raw_refs = public.pedido_snapshots.raw_refs || EXCLUDED.raw_refs,
      source_history = COALESCE(public.pedido_snapshots.source_history, '[]'::jsonb)
        || COALESCE(EXCLUDED.source_history, '[]'::jsonb),
      updated_at = now();
  END IF;

  FOR v_ref IN
    SELECT value FROM jsonb_array_elements(COALESCE(p_refs, '[]'::jsonb))
  LOOP
    IF v_ref->>'role' = 'sales_origin' THEN
      INSERT INTO public.pedido_integration_refs (
        pedido_id, integration_id, module_id, role, external_order_id,
        external_record_id, external_status, last_synced_at, metadata
      ) VALUES (
        v_pedido_id,
        NULLIF(v_ref->>'integration_id', '')::INTEGER,
        lower(v_ref->>'module_id'),
        'sales_origin',
        v_ref->>'external_order_id',
        NULLIF(v_ref->>'external_record_id', ''),
        NULLIF(v_ref->>'external_status', ''),
        COALESCE(NULLIF(v_ref->>'last_synced_at', '')::TIMESTAMPTZ, now()),
        COALESCE(v_ref->'metadata', '{}'::jsonb)
      )
      ON CONFLICT (module_id, external_order_id)
        WHERE role = 'sales_origin'
      DO UPDATE SET
        pedido_id = EXCLUDED.pedido_id,
        integration_id = COALESCE(EXCLUDED.integration_id, public.pedido_integration_refs.integration_id),
        external_record_id = COALESCE(EXCLUDED.external_record_id, public.pedido_integration_refs.external_record_id),
        external_status = COALESCE(EXCLUDED.external_status, public.pedido_integration_refs.external_status),
        last_synced_at = EXCLUDED.last_synced_at,
        metadata = public.pedido_integration_refs.metadata || EXCLUDED.metadata,
        updated_at = now();
    ELSE
      INSERT INTO public.pedido_integration_refs (
        pedido_id, integration_id, module_id, role, external_order_id,
        external_record_id, external_status, last_synced_at, metadata
      ) VALUES (
        v_pedido_id,
        NULLIF(v_ref->>'integration_id', '')::INTEGER,
        lower(v_ref->>'module_id'),
        v_ref->>'role',
        v_ref->>'external_order_id',
        NULLIF(v_ref->>'external_record_id', ''),
        NULLIF(v_ref->>'external_status', ''),
        COALESCE(NULLIF(v_ref->>'last_synced_at', '')::TIMESTAMPTZ, now()),
        COALESCE(v_ref->'metadata', '{}'::jsonb)
      )
      ON CONFLICT (
        module_id, (COALESCE(integration_id, 0)), external_order_id, role
      )
        WHERE role <> 'sales_origin'
      DO UPDATE SET
        pedido_id = EXCLUDED.pedido_id,
        integration_id = COALESCE(EXCLUDED.integration_id, public.pedido_integration_refs.integration_id),
        external_record_id = COALESCE(EXCLUDED.external_record_id, public.pedido_integration_refs.external_record_id),
        external_status = COALESCE(EXCLUDED.external_status, public.pedido_integration_refs.external_status),
        last_synced_at = EXCLUDED.last_synced_at,
        metadata = public.pedido_integration_refs.metadata || EXCLUDED.metadata,
        updated_at = now();
    END IF;
  END LOOP;

  UPDATE public.pending_marketplace_enrichments
     SET status = CASE WHEN COALESCE(p_order->>'ingest_source', '') = 'bling'
                       THEN 'applied' ELSE 'matched' END,
         matched_pedido_id = v_pedido_id,
         applied_at = CASE WHEN COALESCE(p_order->>'ingest_source', '') = 'bling'
                           THEN now() ELSE applied_at END,
         updated_at = now()
   WHERE marketplace_module_id = v_module_id
     AND marketplace_order_id = v_marketplace_order_id
     AND status = 'pending';

  UPDATE public.pending_order_reconciliations
     SET pedido_id = v_pedido_id, status = 'applied', resolved_at = now(), updated_at = now()
   WHERE status = 'pending'
     AND erp_integration_id = NULLIF(p_order->>'erp_integration_id', '')::INTEGER
     AND erp_order_id = NULLIF(p_order->>'erp_order_id', '')::BIGINT;

  RETURN v_pedido_id;
END;
$$;

REVOKE ALL ON FUNCTION public.upsert_canonical_order(JSONB, JSONB, JSONB) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.upsert_canonical_order(JSONB, JSONB, JSONB) TO service_role;
-- Legacy readers can keep their old field names while writers move to the
-- canonical provider-neutral contract.
CREATE OR REPLACE VIEW public.pedidos_legacy_compat
WITH (security_invoker = true)
AS
SELECT
  p.*,
  COALESCE(p.erp_integration_id, p.bling_integration_id) AS canonical_bling_integration_id,
  COALESCE(p.erp_store_id, p.bling_loja_id) AS canonical_bling_loja_id,
  COALESCE(p.erp_order_id, p.bling_order_id) AS canonical_bling_order_id,
  COALESCE(p.erp_order_number, p.bling_order_number, p.numero_pedido)
    AS canonical_bling_order_number
FROM public.pedidos p;

REVOKE ALL ON TABLE public.order_identity_conflicts FROM anon, authenticated;
REVOKE ALL ON TABLE public.pending_order_reconciliations FROM anon, authenticated;
REVOKE ALL ON TABLE public.pending_marketplace_enrichments FROM anon, authenticated;
REVOKE ALL ON TABLE public.pedido_integration_refs FROM anon, authenticated;

GRANT ALL ON TABLE public.order_identity_conflicts TO service_role;
GRANT ALL ON TABLE public.pending_order_reconciliations TO service_role;
GRANT ALL ON TABLE public.pending_marketplace_enrichments TO service_role;
GRANT ALL ON TABLE public.pedido_integration_refs TO service_role;
GRANT ALL ON SEQUENCE public.order_identity_conflicts_id_seq TO service_role;
GRANT ALL ON SEQUENCE public.pending_order_reconciliations_id_seq TO service_role;
GRANT ALL ON SEQUENCE public.pending_marketplace_enrichments_id_seq TO service_role;
GRANT ALL ON SEQUENCE public.pedido_integration_refs_id_seq TO service_role;

ALTER TABLE public.order_identity_conflicts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.pending_order_reconciliations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.pending_marketplace_enrichments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.pedido_integration_refs ENABLE ROW LEVEL SECURITY;

DROP INDEX IF EXISTS public.idx_pedidos_marketplace_order_id;
DROP INDEX IF EXISTS public.ix_pedidos_marketplace;
DROP INDEX IF EXISTS public.idx_pedidos_marketplace_integration_id_filter;
DROP INDEX IF EXISTS public.idx_pedidos_flags_filter;
DROP INDEX IF EXISTS public.idx_pedidos_situacao_filter;
DROP INDEX IF EXISTS public.idx_pedidos_data_limite_envio_filter;
DROP INDEX IF EXISTS public.idx_pedidos_shopee_codigo_pedido;
DROP INDEX IF EXISTS public.ix_pedidos_shopee_order_sn;

CREATE INDEX IF NOT EXISTS idx_pedidos_listing_marketplace_status_date
  ON public.pedidos (
    marketplace_integration_id, situacao_pedido_id, data_venda DESC
  );
CREATE INDEX IF NOT EXISTS idx_pedidos_status_shipping_deadline
  ON public.pedidos (situacao_pedido_id, data_limite_envio);
CREATE INDEX IF NOT EXISTS idx_pedidos_erp_store
  ON public.pedidos (erp_integration_id, erp_store_id);

ANALYZE public.pedidos;
ANALYZE public.pedido_integration_refs;
-- Provider-agnostic, bidirectional equivalence rules. Resolution precedence is
-- ERP/marketplace link -> installed integration -> module default.
CREATE TABLE IF NOT EXISTS public.integration_mapping_rules (
  id BIGSERIAL PRIMARY KEY,
  module_id TEXT NOT NULL REFERENCES public.integration_modules(id) ON DELETE CASCADE,
  integration_id INTEGER REFERENCES public.installed_integrations(id) ON DELETE CASCADE,
  erp_marketplace_link_id UUID REFERENCES public.erp_marketplace_links(id) ON DELETE CASCADE,
  domain TEXT NOT NULL CHECK (domain IN (
    'order_status', 'payment', 'shipping_package', 'logistics_mode',
    'carrier', 'erp_warehouse', 'operation_nature', 'fiscal_series'
  )),
  direction TEXT NOT NULL CHECK (direction IN ('inbound', 'outbound')),
  provider_value TEXT NOT NULL,
  internal_value TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 0,
  is_active BOOLEAN NOT NULL DEFAULT true,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (erp_marketplace_link_id IS NULL OR integration_id IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_integration_mapping_rule_scope
  ON public.integration_mapping_rules (
    module_id, integration_id, erp_marketplace_link_id,
    domain, direction, provider_value
  ) NULLS NOT DISTINCT;
CREATE INDEX IF NOT EXISTS idx_integration_mapping_resolution
  ON public.integration_mapping_rules (
    module_id, domain, direction, integration_id, erp_marketplace_link_id,
    priority DESC
  ) WHERE is_active = true;

ALTER TABLE public.integration_mapping_rules ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS authenticated_manage_integration_mapping_rules
  ON public.integration_mapping_rules;
CREATE POLICY authenticated_manage_integration_mapping_rules
  ON public.integration_mapping_rules
  FOR ALL TO authenticated
  USING (true) WITH CHECK (true);
REVOKE ALL ON TABLE public.integration_mapping_rules FROM anon;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.integration_mapping_rules TO authenticated;
GRANT ALL ON TABLE public.integration_mapping_rules TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.integration_mapping_rules_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.integration_mapping_rules_id_seq TO service_role;

CREATE TABLE IF NOT EXISTS public.order_identity_corrections (
  id BIGSERIAL PRIMARY KEY,
  pedido_id BIGINT NOT NULL REFERENCES public.pedidos(id) ON DELETE CASCADE,
  old_marketplace_module_id TEXT NOT NULL,
  old_marketplace_order_id TEXT NOT NULL,
  new_marketplace_module_id TEXT NOT NULL,
  new_marketplace_order_id TEXT NOT NULL,
  reason TEXT NOT NULL,
  actor_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE public.order_identity_corrections ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.order_identity_corrections FROM anon, authenticated;
GRANT ALL ON TABLE public.order_identity_corrections TO service_role;
GRANT ALL ON SEQUENCE public.order_identity_corrections_id_seq TO service_role;

CREATE OR REPLACE FUNCTION public.correct_canonical_order_identity(
  p_pedido_id BIGINT,
  p_marketplace_module_id TEXT,
  p_marketplace_order_id TEXT,
  p_reason TEXT,
  p_actor_id TEXT DEFAULT NULL
)
RETURNS BIGINT
LANGUAGE plpgsql
AS $$
DECLARE
  v_old public.pedidos%ROWTYPE;
  v_module TEXT := lower(NULLIF(trim(p_marketplace_module_id), ''));
  v_order_id TEXT := NULLIF(trim(p_marketplace_order_id), '');
BEGIN
  IF v_module IS NULL OR v_order_id IS NULL OR NULLIF(trim(p_reason), '') IS NULL THEN
    RAISE EXCEPTION 'New canonical identity and correction reason are required';
  END IF;

  SELECT * INTO v_old FROM public.pedidos WHERE id = p_pedido_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Pedido % not found', p_pedido_id;
  END IF;

  INSERT INTO public.order_identity_corrections (
    pedido_id, old_marketplace_module_id, old_marketplace_order_id,
    new_marketplace_module_id, new_marketplace_order_id, reason, actor_id
  ) VALUES (
    p_pedido_id, v_old.marketplace_module_id, v_old.marketplace_order_id,
    v_module, v_order_id, p_reason, p_actor_id
  );

  PERFORM set_config('app.allow_order_identity_correction', 'true', true);

  UPDATE public.pedidos
     SET marketplace_module_id = v_module,
         marketplace_order_id = v_order_id,
         codigo_pedido_externo = v_order_id,
         origem = upper(v_module),
         updated_at = now()
   WHERE id = p_pedido_id;

  UPDATE public.pedido_integration_refs
     SET module_id = v_module,
         external_order_id = v_order_id,
         updated_at = now()
   WHERE pedido_id = p_pedido_id AND role = 'sales_origin';

  RETURN p_pedido_id;
END;
$$;
REVOKE ALL ON FUNCTION public.correct_canonical_order_identity(BIGINT, TEXT, TEXT, TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.correct_canonical_order_identity(BIGINT, TEXT, TEXT, TEXT, TEXT) TO service_role;
