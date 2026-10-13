-- Mercado Livre: nota emitida / etiqueta disponivel avanca para a fila de envio.
-- ready_to_ship sozinho continua significando aguardando preparacao; os
-- substatus ready_to_print e printed sao a evidencia de documentacao de envio.

INSERT INTO public.integration_status_mappings (
  module_id, integration_id, status_domain, external_status_id,
  external_status_name, internal_situacao_pedido_id, lifecycle_stage,
  stage_rank, projects_situacao, is_terminal, is_modifier, is_active
) VALUES
  ('mercadolivre', NULL, 'shipping_substatus', 'ready_to_print',
   'ready_to_print', 4, 'fulfillment_ready', 45, true, false, false, true),
  ('mercadolivre', NULL, 'shipping_substatus', 'printed',
   'printed', 4, 'fulfillment_ready', 45, true, false, false, true)
ON CONFLICT (module_id, status_domain, external_status_id)
  WHERE integration_id IS NULL
DO UPDATE SET
  external_status_name = EXCLUDED.external_status_name,
  internal_situacao_pedido_id = EXCLUDED.internal_situacao_pedido_id,
  lifecycle_stage = EXCLUDED.lifecycle_stage,
  stage_rank = EXCLUDED.stage_rank,
  projects_situacao = EXCLUDED.projects_situacao,
  is_terminal = EXCLUDED.is_terminal,
  is_modifier = EXCLUDED.is_modifier,
  is_active = true,
  updated_at = now();

-- A torre normalmente aceita as situacoes 2, 3 e 4. No Mercado Livre, a
-- documentacao pronta para impressao indica que a producao ja foi assumida;
-- o pedido avanca para situacao 4, mas sai da fila de entrada da torre.
-- pedidos recebe colunas novas ao longo do tempo. Expandir p.* aqui pode
-- deslocar aliases existentes da view (ex.: modalidade_codigo) e faz o
-- CREATE OR REPLACE tentar renomea-los. Reproduzimos primeiro as colunas ja
-- expostas pela view, depois os aliases conhecidos e por fim colunas novas.
DO $migration_view$
DECLARE
  v_col record;
  v_projection text := '';
  v_seen text[] := ARRAY[]::text[];
  v_expression text;
  v_type text;
BEGIN
  FOR v_col IN
    SELECT a.attname::text AS name
      FROM pg_attribute a
      JOIN pg_class c ON c.oid = a.attrelid
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public'
       AND c.relname = 'vw_pedidos_pendentes_despacho'
       AND c.relkind = 'v'
       AND a.attnum > 0
       AND NOT a.attisdropped
     ORDER BY a.attnum
  LOOP
    IF EXISTS (
      SELECT 1 FROM pg_attribute a
      JOIN pg_class c ON c.oid = a.attrelid
      JOIN pg_namespace n ON n.oid = c.relnamespace
      WHERE n.nspname = 'public' AND c.relname = 'pedidos'
        AND a.attname = v_col.name AND a.attnum > 0 AND NOT a.attisdropped
    ) THEN
      v_expression := format('p.%I', v_col.name);
    ELSE
      v_expression := CASE v_col.name
        WHEN 'modalidade_codigo' THEN 'COALESCE(m.codigo, ''NAO_CLASSIFICADA'')'
        WHEN 'modalidade_nome' THEN 'COALESCE(m.nome, ''Modalidade nao classificada'')'
        WHEN 'modalidade_tipo_prazo' THEN 'COALESCE(m.tipo_prazo, ''FIXO'')'
        WHEN 'modalidade_ordem' THEN 'COALESCE(m.ordem_exibicao, 0)::smallint'
        WHEN 'modalidade_entrega_rapida' THEN 'COALESCE(m.entrega_rapida, false)'
        WHEN 'marketplace_nome' THEN 'i.instance_name'
        ELSE NULL
      END;
      IF v_expression IS NULL THEN
        RAISE EXCEPTION 'Coluna % da view % nao pode ser preservada automaticamente',
          v_col.name, 'vw_pedidos_pendentes_despacho';
      END IF;
      -- Expressions such as COALESCE(varchar(50), '...') can lose the
      -- typmod. Keep the precise existing view type to satisfy CREATE OR
      -- REPLACE VIEW's positional type contract.
      SELECT format_type(a.atttypid, a.atttypmod)
        INTO v_type
        FROM pg_attribute a
       WHERE a.attrelid = 'public.vw_pedidos_pendentes_despacho'::regclass
         AND a.attname = v_col.name
         AND a.attnum > 0
         AND NOT a.attisdropped;
      IF v_type IS NOT NULL THEN
        v_expression := format('(%s)::%s', v_expression, v_type);
      END IF;
    END IF;
    v_projection := concat_ws(', ', NULLIF(v_projection, ''),
      format('%s AS %I', v_expression, v_col.name));
    v_seen := array_append(v_seen, v_col.name);
  END LOOP;

  -- Mantem os atributos de conveniencia da view mesmo em bancos cuja versao
  -- anterior ainda nao os exponha.
  FOR v_col IN
    SELECT * FROM (VALUES
      ('modalidade_codigo', 'COALESCE(m.codigo, ''NAO_CLASSIFICADA'')'),
      ('modalidade_nome', 'COALESCE(m.nome, ''Modalidade nao classificada'')'),
      ('modalidade_tipo_prazo', 'COALESCE(m.tipo_prazo, ''FIXO'')'),
      ('modalidade_ordem', 'COALESCE(m.ordem_exibicao, 0)::smallint'),
      ('modalidade_entrega_rapida', 'COALESCE(m.entrega_rapida, false)'),
      ('marketplace_nome', 'i.instance_name')
    ) AS aliases(name, expression)
  LOOP
    IF NOT (v_col.name = ANY(v_seen)) THEN
      v_projection := concat_ws(', ', NULLIF(v_projection, ''),
        format('%s AS %I', v_col.expression, v_col.name));
      v_seen := array_append(v_seen, v_col.name);
    END IF;
  END LOOP;

  -- Colunas de pedidos adicionadas depois da criacao da view vao ao final,
  -- sem deslocar os aliases existentes.
  FOR v_col IN
    SELECT a.attname::text AS name
      FROM pg_attribute a
      JOIN pg_class c ON c.oid = a.attrelid
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public' AND c.relname = 'pedidos'
       AND c.relkind = 'r' AND a.attnum > 0 AND NOT a.attisdropped
     ORDER BY a.attnum
  LOOP
    IF NOT (v_col.name = ANY(v_seen)) THEN
      v_projection := concat_ws(', ', NULLIF(v_projection, ''),
        format('p.%I', v_col.name));
      v_seen := array_append(v_seen, v_col.name);
    END IF;
  END LOOP;

  EXECUTE format($view$
    CREATE OR REPLACE VIEW public.vw_pedidos_pendentes_despacho AS
    SELECT %s
      FROM public.pedidos p
      LEFT JOIN public.modalidades_logisticas m ON m.id = p.modalidade_logistica_id
      LEFT JOIN public.installed_integrations i ON i.id = p.marketplace_integration_id
     WHERE p.despachado_em IS NULL
       AND p.situacao_pedido_id IN (2, 3, 4)
       AND COALESCE(m.entra_na_torre, NOT COALESCE(p.is_fulfillment, false))
       AND NOT (p.marketplace_module_id = 'mercadolivre' AND p.situacao_pedido_id = 4)
  $view$, v_projection);
END;
$migration_view$;

COMMENT ON VIEW public.vw_pedidos_pendentes_despacho IS
  'Pedidos que ainda precisam ser lancados na torre. No Mercado Livre, situacao 4 registra nota/documentacao de envio pronta; esse marco permanece fora da torre mesmo se o substatus fiscal regredir.';
