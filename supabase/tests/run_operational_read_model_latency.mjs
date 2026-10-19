// node supabase/tests/run_operational_read_model_latency.mjs
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { PGlite } from '../../temp/logistica-sql/node_modules/@electric-sql/pglite/dist/index.js';

const db = new PGlite();
try {
  await db.exec(`
    CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role;
    CREATE TABLE shopee_personalization_read_model (
      id integer PRIMARY KEY, marketplace_integration_id integer,
      numero_pedido text, numero_loja text, data_pedido timestamptz,
      detalhes jsonb NOT NULL
    );
    CREATE TABLE shopee_personalization_read_model_state (
      singleton boolean PRIMARY KEY, backfill_complete boolean NOT NULL,
      updated_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE operational_read_model_config (
      singleton boolean PRIMARY KEY, personalized_projection_enabled boolean NOT NULL,
      dispatch_snapshot_enabled boolean NOT NULL
    );
    CREATE TABLE operational_read_model_outbox (
      event_key text PRIMARY KEY, personalized boolean NOT NULL DEFAULT false,
      dispatch boolean NOT NULL DEFAULT false, backfill boolean NOT NULL DEFAULT false,
      dispatch_calendar boolean NOT NULL DEFAULT false,
      created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE canais_venda (id integer PRIMARY KEY, slug text NOT NULL);
    CREATE TABLE pedidos (
      id integer PRIMARY KEY, canal_venda_id integer, situacao_pedido_id integer,
      numero_pedido text, codigo_pedido_externo text, data_venda timestamptz,
      marketplace_integration_id integer, buyer_username text
    );
    CREATE TABLE itens_pedido (id integer PRIMARY KEY, pedido_id integer, personalizado boolean);
    CREATE TABLE despacho_janelas_read_model_state (
      singleton boolean PRIMARY KEY, data_inicio date, data_fim date,
      updated_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE despacho_janelas_read_model (
      integration_id integer, modalidade_id integer, dia date,
      coleta_em timestamptz, payload jsonb
    );
    CREATE TABLE despacho_grupos_janelas_read_model (
      integration_id integer, modalidade_id integer, data_inicio date, data_fim date
    );
    CREATE VIEW vw_pedidos_pendentes_despacho AS
      SELECT NULL::integer AS modalidade_logistica_id,
             NULL::integer AS marketplace_integration_id WHERE false;
    CREATE FUNCTION janelas_logisticas(integer, integer, date)
    RETURNS TABLE(coleta_em timestamptz) LANGUAGE sql AS $$
      SELECT NULL::timestamptz WHERE false
    $$;
    CREATE TABLE despacho_contexto_read_model (
      data date PRIMARY KEY, payload jsonb, refreshed_at timestamptz, valid_until timestamptz
    );
    CREATE TABLE snapshot_builds (count integer NOT NULL);
    INSERT INTO snapshot_builds VALUES (0);
    INSERT INTO shopee_personalization_read_model_state VALUES (true, true, '2020-01-01');
    INSERT INTO operational_read_model_config VALUES (true, true, true);
    INSERT INTO despacho_janelas_read_model_state(singleton, data_inicio, data_fim)
      VALUES (true, current_date, current_date + 31);
    INSERT INTO canais_venda VALUES (1, 'shopee');
    INSERT INTO pedidos VALUES
      (1, 1, 2, '494001', '2601A', now() - interval '3 days', 6, 'ana'),
      (2, 1, 3, '494002', '2601B', now() - interval '2 days', 7, 'bia'),
      (3, 1, 4, '550003', '2601C', now() - interval '1 day', 8, 'caio');
    INSERT INTO itens_pedido VALUES (11, 1, true), (12, 2, true), (13, 3, true);
    CREATE FUNCTION rebuild_shopee_personalization_read_model(p_ids integer[])
    RETURNS integer LANGUAGE plpgsql AS $$
    DECLARE v_count integer;
    BEGIN
      INSERT INTO shopee_personalization_read_model
        (id, marketplace_integration_id, numero_pedido, numero_loja, data_pedido, detalhes)
      SELECT p.id, p.marketplace_integration_id, p.numero_pedido,
             p.codigo_pedido_externo, p.data_venda,
             jsonb_build_object('id', p.id, 'numero_pedido', p.numero_pedido,
               'numero_loja', p.codigo_pedido_externo, 'marketplace_integration_id',
               p.marketplace_integration_id, 'itens', '[]'::jsonb)
        FROM pedidos p WHERE p.id = ANY(p_ids)
      ON CONFLICT (id) DO UPDATE SET detalhes = EXCLUDED.detalhes;
      GET DIAGNOSTICS v_count = ROW_COUNT;
      RETURN v_count;
    END $$;
    CREATE FUNCTION rebuild_despacho_janelas_read_model()
    RETURNS integer LANGUAGE sql AS $$ SELECT 0 $$;
    CREATE FUNCTION despacho_arvore_contexto_raw(p_data date)
    RETURNS jsonb LANGUAGE plpgsql AS $$
    BEGIN
      UPDATE snapshot_builds SET count = count + 1;
      RETURN jsonb_build_object('rows', '[]'::jsonb, 'timeline', '[]'::jsonb);
    END $$;
  `);
  await db.exec(await readFile('supabase/migrations/20261019124500_operational_read_model_latency.sql', 'utf8'));
  const calendar = await db.query('SELECT rebuild_despacho_janelas_read_model() AS groups');
  assert.equal(calendar.rows[0].groups, 0);

  await db.query('SELECT refresh_operational_read_models(100)');
  const backfill = await db.query(`
    SELECT (SELECT backfill_complete FROM shopee_personalization_read_model_state) AS ready,
           (SELECT count(*)::integer FROM shopee_personalization_read_model) AS total
  `);
  assert.deepEqual(backfill.rows[0], { ready: true, total: 3 });

  const first = await db.query(`SELECT buscar_pedidos_personalizados_projetados('494', 1, 1) AS result`);
  const second = await db.query(`SELECT buscar_pedidos_personalizados_projetados('494', 2, 1) AS result`);
  assert.equal(first.rows[0].result.total, 2);
  assert.equal(first.rows[0].result.rows[0].id, 2);
  assert.equal(second.rows[0].result.rows[0].id, 1);
  assert.equal(first.rows[0].result.ready, true);

  await db.exec(`UPDATE shopee_personalization_read_model_state SET updated_at = '2020-01-01'`);
  await db.query('SELECT refresh_operational_read_models(100)');
  const state = await db.query('SELECT updated_at FROM shopee_personalization_read_model_state');
  assert.equal(new Date(state.rows[0].updated_at).getUTCFullYear(), 2020);

  await db.exec(`INSERT INTO operational_read_model_outbox(event_key, dispatch)
                 VALUES ('dispatch:global', true)`);
  await db.query('SELECT despacho_arvore_contexto(current_date)');
  let builds = await db.query('SELECT count FROM snapshot_builds');
  assert.equal(builds.rows[0].count, 1);
  await db.exec(`UPDATE despacho_contexto_read_model
                   SET refreshed_at = now() - interval '6 seconds'`);
  const snapshot = await db.query('SELECT despacho_arvore_contexto(current_date) AS result');
  assert.ok(snapshot.rows[0].result.snapshot_gerado_em);
  await db.query('SELECT despacho_arvore_contexto(current_date)');
  builds = await db.query('SELECT count FROM snapshot_builds');
  assert.equal(builds.rows[0].count, 2);
  console.log('OK: backfill 2/3/4, busca global paginada, snapshot compartilhado');
} catch (error) {
  console.error(error.message, error.internalQuery || '');
  process.exitCode = 1;
} finally {
  await db.close();
}
