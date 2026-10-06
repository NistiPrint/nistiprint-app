// Dependencia compartilhada com run_logistica.mjs:
// npm install --prefix temp/logistica-sql @electric-sql/pglite
// node supabase/tests/run_despacho.mjs (a partir da raiz do repositorio)
import { readFile } from 'node:fs/promises';
import { PGlite } from '../../temp/logistica-sql/node_modules/@electric-sql/pglite/dist/index.js';
const db = new PGlite();
try {
  for (const file of [
    'supabase/tests/fixtures/logistica_schema.sql',
    'supabase/migrations/20261002120000_logistica_agenda_e_alertas.sql',
    'supabase/tests/fixtures/despacho_leituras.sql',
    'supabase/migrations/20260916165919_despacho_abas_por_limite_envio.sql',
    'supabase/migrations/20261002122000_despacho_ml_agrupado_por_prazo.sql',
    'supabase/migrations/20261005190000_despacho_leituras_em_lote.sql',
    'supabase/tests/despacho_leituras_em_lote.sql',
    'supabase/migrations/20261005191000_shopee_prazos_confirmados.sql',
    'supabase/migrations/20261005200000_despacho_sem_prazo_proxima_coleta.sql',
    'supabase/tests/despacho_sem_prazo_proxima_coleta.sql',
    'supabase/tests/despacho_abas_por_prazo.sql',
  ]) {
    await db.exec(await readFile(file, 'utf8'));
    console.log(`OK: ${file}`);
  }
  await db.exec(`DO $$ BEGIN
    IF (SELECT data_limite_envio FROM pedidos WHERE id=3) IS NOT NULL
    THEN RAISE EXCEPTION 'Estimativa antiga nao foi removida'; END IF;
    UPDATE pedidos SET data_limite_envio='2026-10-04T23:59:59-03:00' WHERE id=3;
    IF (SELECT data_limite_envio FROM pedidos WHERE id=3) IS NOT NULL
    THEN RAISE EXCEPTION 'Estimativa antiga voltou apos reingest'; END IF;
    IF (SELECT data_limite_envio FROM pedidos WHERE id=1) <> '2026-10-06T23:59:59-03:00'::timestamptz
    THEN RAISE EXCEPTION 'Prazo confirmado nao foi aplicado'; END IF;
    UPDATE pedido_snapshots SET logistics=logistics || jsonb_build_object(
      'deadline','2026-10-07T23:59:59-03:00','dispatch_deadline_source','shopee.pay_time+days_to_ship')
      WHERE pedido_id=1;
    IF (SELECT logistics->>'dispatch_deadline_source' FROM pedido_snapshots WHERE pedido_id=1)
       <> 'shopee.seller_panel.confirmed'
    THEN RAISE EXCEPTION 'Estimativa apagou confirmacao no snapshot'; END IF;
    UPDATE pedidos SET data_limite_envio='2026-10-07T23:59:59-03:00' WHERE id=1;
    IF (SELECT data_limite_envio FROM pedidos WHERE id=1) <> '2026-10-06T23:59:59-03:00'::timestamptz
    THEN RAISE EXCEPTION 'Estimativa sobrescreveu prazo confirmado'; END IF;
    UPDATE pedidos_shopee SET ship_by_date='2026-10-08T23:59:59-03:00' WHERE codigo_pedido='261005T9TABWHR';
    UPDATE pedido_snapshots SET logistics=logistics || jsonb_build_object(
      'deadline','2026-10-08T23:59:59-03:00','dispatch_deadline_source','shopee.ship_by_date') WHERE pedido_id=1;
    UPDATE pedidos SET data_limite_envio='2026-10-08T23:59:59-03:00' WHERE id=1;
    IF (SELECT data_limite_envio FROM pedidos WHERE id=1) <> '2026-10-08T23:59:59-03:00'::timestamptz
    THEN RAISE EXCEPTION 'Prazo novo da API foi bloqueado'; END IF;
  END $$;`);
  console.log('OK: prazo conferido preservado; prazo novo da API aceito');
  const oldQuery = `SELECT sum(extract(epoch from c.coleta_em)) AS total FROM pedidos p
    LEFT JOIN LATERAL despacho_coleta_do_pedido(p.marketplace_module_id,p.modalidade_logistica_id,
       p.marketplace_integration_id,p.data_pagamento_marketplace,p.data_limite_envio,
       '2026-10-02T09:00:00-03:00'::timestamptz) c ON true WHERE p.id<=300`;
  const newQuery = `SELECT sum(extract(epoch from coleta_em)) AS total FROM despacho_coletas_em_lote(
    ARRAY(SELECT id FROM pedidos WHERE id<=300),'2026-10-02T09:00:00-03:00'::timestamptz)`;
  const durations = [];
  for (const query of [oldQuery, newQuery]) {
    const start = performance.now();
    const result = await db.query(query);
    durations.push({ ms: performance.now() - start, total: result.rows[0].total });
  }
  if (durations[0].total !== durations[1].total) throw new Error('Benchmark mudou as coletas');
  console.log(`Coletas, 300 pedidos: anterior ${durations[0].ms.toFixed(0)} ms; em lote ${durations[1].ms.toFixed(0)} ms`);
} catch (error) {
  console.error(error.message, error.where || '');
  process.exitCode = 1;
} finally { await db.close(); }
