// Disposable database only. Never connects to Supabase or a marketplace.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import { performance } from 'node:perf_hooks';

const { PGlite } = await import(pathToFileURL(process.env.GESTAO_PGLITE_MODULE).href);
const db = new PGlite();
let checks = 0;
try {
  for (const path of ['supabase/tests/fixtures/gestao_schema.sql',
    'supabase/migrations/20261020160000_gestao_business_intelligence.sql',
    'supabase/migrations/20261020200000_marketplace_insights.sql',
    'supabase/migrations/20261020210000_gestao_queries.sql']) {
    await db.exec(await readFile(path, 'utf8'));
    if (path.endsWith('gestao_schema.sql')) await db.exec(`
      ALTER TABLE pedido_snapshots ADD items jsonb NOT NULL DEFAULT '[]';
      ALTER TABLE pedido_snapshots ADD identity jsonb NOT NULL DEFAULT '{}';
      CREATE TABLE snapshot_sync_calls(n integer);
      CREATE FUNCTION sync_marketplace_snapshot_items() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN INSERT INTO snapshot_sync_calls VALUES(1); RETURN NEW; END $$;
    `);
  }
  await db.exec(`INSERT INTO installed_integrations VALUES(6,'Shopee'),(7,'Mercado Livre');
    INSERT INTO produtos VALUES(2,10);
    INSERT INTO pedidos VALUES(1,6,null,null,null,'shopee','2026-10-01','delivered',100);
    INSERT INTO pedidos VALUES(2,7,null,null,null,'mercadolivre','2026-10-02','delivered',100);`);
  await db.exec(`INSERT INTO produto_anuncios VALUES(1,6,'ITEM_A','1',2),(2,6,'ITEM_B','1',2),(3,6,'ITEM_A','2',2),(4,7,'ITEM_A','1',2);`);
  const listings=(await db.query('SELECT marketplace_insights_listing_batch(6,0) data')).rows[0].data;
  assert.deepEqual(listings.map(r=>r.item_externo_id),['ITEM_B','ITEM_A']); checks++;
  assert.deepEqual((await db.query('SELECT marketplace_insights_listing_batch(6,3) data')).rows[0].data,[]); checks++;
  const fact = (id, account, provider, version = 'v1') => ({
    id, account_id: account, account_name: provider, marketplace: provider, sold_on: '2026-10-01',
    sold_at: '2026-10-01T10:00:00-03:00', hour: 10, weekday: 3, stage: 'delivered', eligible: true, total: 100,
    buyer_key: `${account}:buyer`, region: 'SP', city: 'São Paulo', personalized: true,
    items: [{ id: id * 10, product_id: 2, name: 'Produto', mapping: 'direct', family_id: 2, quantity: 2, subtotal: 100, unit_cost: 10, cost_estimated: true }],
    names: [{ id: `${provider}:${id}`, item_id: id * 10, name: 'Maria Clara', quantity: 2, status: 'SUCCESS', confirmed: true }],
    events: [], finance: null,
    insights: { account_id: account, resource_id: `${id}`, version, enrichments: [provider === 'shopee' ? 'shopee_escrow' : 'ml_billing'] },
  });
  const store = async f => db.query(`INSERT INTO gestao_fatos_pedido VALUES($1,$2,$3,$4,$5,now())
    ON CONFLICT(pedido_id) DO UPDATE SET payload=excluded.payload`, [f.id, f.sold_on, f.account_id, f.marketplace, f]);
  await store(fact(1, 6, 'shopee')); await store(fact(1, 6, 'shopee')); await store(fact(2, 7, 'mercadolivre'));
  assert.equal((await db.query('SELECT count(*) n FROM marketplace_insight_requests')).rows[0].n, 2); checks++;
  for (const [account, cap] of [[6, 'shopee_escrow'], [7, 'ml_billing']]) {
    const claim = (await db.query('SELECT marketplace_insights_claim($1,$2) data', [account, cap])).rows[0].data;
    assert.equal(claim.length, 1); checks++;
    assert.equal((await db.query('SELECT marketplace_insights_claim($1,$2) data', [account, cap])).rows[0].data.length, 0); checks++;
    await store(fact(account === 6 ? 1 : 2, account, account === 6 ? 'shopee' : 'mercadolivre', 'v2'));
    const old = (await db.query(`SELECT marketplace_insights_store_finance($1,$2,$3,'v1','{"net_payout":1}',false,'{}') ok`, [account, cap, `${account === 6 ? 1 : 2}`])).rows[0].ok;
    assert.equal(old, false); checks++;
  }
  assert.equal((await db.query('SELECT count(*) n FROM gestao_financeiro')).rows[0].n, 0); checks++;
  await db.exec(`UPDATE gestao_coletas SET enabled=false WHERE account_id=6;`);
  assert.deepEqual((await db.query("SELECT marketplace_insights_claim(6,'shopee_escrow') data")).rows[0].data, []); checks++;
  const query = () => db.query("SELECT gestao_report_data('2026-10-01','2026-10-19','{}',true) data");
  let report = (await query()).rows[0].data;
  assert.equal(report.summary.sales, 200); checks++;
  assert.equal(report.products[0].units, 4); checks++;
  assert.equal(report.names[0].occurrences, 2); checks++;
  assert.equal(report.customers.identified, 2); checks++;
  assert.equal(report.personalization.identified_orders, 2); checks++;
  await db.query('SELECT gestao_refresh_daily()');
  assert.deepEqual((await query()).rows[0].data.summary, report.summary); checks++;
  const page = (await db.query("SELECT gestao_order_page('2026-10-01','2026-10-19','{}',1) data")).rows[0].data;
  assert.equal(page.total, 2); checks++;
  assert.ok(!('unit_cost' in page.data[0].items[0])); checks++;
  const rev = (await db.query('SELECT gestao_report_revision() r')).rows[0].r;
  await store({ ...fact(1, 6, 'shopee', 'v3'), stage: 'cancelled', eligible: false });
  assert.ok((await db.query('SELECT gestao_report_revision() r')).rows[0].r > rev); checks++;
  assert.equal((await query()).rows[0].data.summary.sales, 100); checks++;
  const cachedQuery = () => db.query("SELECT gestao_report_cached('2026-10-01','2026-10-19','{}',true) data");
  assert.equal((await cachedQuery()).rows[0].data.summary.sales, 100); checks++;
  await store(fact(1, 6, 'shopee', 'v4'));
  assert.equal((await cachedQuery()).rows[0].data.summary.sales, 200); checks++;
  const components={net_payout:80,taxes:2,operating_cost:1,ads:3};
  // A canonical change can precede the new analytic projection. Do not accept
  // finance against the older fact while its order is still in the outbox.
  assert.equal((await db.query(`SELECT marketplace_insights_store_finance(6,'shopee_escrow','1','v4',$1,false,'{}') ok`,[components])).rows[0].ok,false); checks++;
  await db.exec('DELETE FROM gestao_outbox');
  assert.equal((await db.query(`SELECT marketplace_insights_store_finance(6,'shopee_escrow','1','v4',$1,false,'{}') ok`,[components])).rows[0].ok,true); checks++;
  await store({...fact(1,6,'shopee','v4'),finance:{components,source:'shopee_escrow',settled:false}});
  const financial=(await query()).rows[0].data.profitability;
  assert.equal(financial.before_ads,57); checks++;
  assert.equal(financial.channels.find(c=>c.account_id===6).before_ads,57); checks++;
  assert.equal(financial.products[0].after_ads,54); checks++;
  await db.exec("UPDATE gestao_financeiro SET source='manual' WHERE pedido_id=1");
  await db.exec('DELETE FROM gestao_outbox');
  await db.query(`SELECT marketplace_insights_store_finance(6,'shopee_escrow','1','v4','{"net_payout":1}',false,'{}')`);
  assert.equal((await db.query("SELECT components->>'net_payout' value FROM gestao_financeiro WHERE pedido_id=1")).rows[0].value,'80'); checks++;
  await db.exec(`INSERT INTO pedidos_shopee VALUES(9,'{"buyer_user_id":10,"update_time":1}'); UPDATE pedidos SET pedido_shopee_id=9 WHERE id=1;`);
  const generation=(await db.query('SELECT generation FROM gestao_outbox WHERE pedido_id=1')).rows[0].generation;
  await db.exec(`UPDATE pedidos_shopee SET raw_payload='{"buyer_user_id":10,"update_time":2}' WHERE id=9;`);
  assert.equal((await db.query('SELECT generation FROM gestao_outbox WHERE pedido_id=1')).rows[0].generation,generation); checks++;
  await db.exec(`INSERT INTO pedido_snapshots(id,pedido_id,items,identity) VALUES(1,1,'[{"sku":"A"}]','{"ingest_source":"shopee"}');
    UPDATE pedido_snapshots SET items='[{"sku":"A"}]',identity=identity||'{"erp_order_id":123}' WHERE id=1;`);
  assert.equal((await db.query('SELECT count(*) n FROM snapshot_sync_calls')).rows[0].n,1); checks++;
  await db.exec(`UPDATE pedido_snapshots SET items='[{"sku":"B"}]' WHERE id=1`);
  assert.equal((await db.query('SELECT count(*) n FROM snapshot_sync_calls')).rows[0].n,2); checks++;
  await db.exec('BEGIN; SET LOCAL ROLE authenticated;');
  await assert.rejects(db.query("SELECT marketplace_insights_claim(6,'shopee_escrow')"), /permission denied/); checks++;
  await db.exec('ROLLBACK;');
  console.log(`Marketplace insights: ${checks} SQL assertions passed.`);
  if (process.env.GESTAO_BENCHMARK === '1') {
    await db.exec('TRUNCATE gestao_fatos_pedido,marketplace_insight_requests,gestao_daily,gestao_daily_dirty;');
    // Seed time is excluded. Correctness of these triggers was asserted above.
    await db.exec('ALTER TABLE pedidos DISABLE TRIGGER USER; ALTER TABLE gestao_fatos_pedido DISABLE TRIGGER USER;');
    for (const count of [20000, 100000]) {
      const seed = fact(1, 6, 'shopee'); delete seed.insights;
      await db.query(`INSERT INTO pedidos SELECT n,6,null,null,null,'shopee','2026-08-01','delivered',100
        FROM generate_series(3,$1) n ON CONFLICT DO NOTHING`, [count]);
      await db.query(`INSERT INTO gestao_fatos_pedido SELECT n,'2026-08-01'::date+(n%80),
        CASE WHEN n%2=0 THEN 6 ELSE 7 END,CASE WHEN n%2=0 THEN 'shopee' ELSE 'mercadolivre' END,
        $2::jsonb||jsonb_build_object('id',n,'sold_on',('2026-08-01'::date+(n%80))::text,
          'buyer_key','buyer:'||(n%10000)::text,'account_id',CASE WHEN n%2=0 THEN 6 ELSE 7 END),now()
        FROM generate_series(1,$1) n ON CONFLICT DO NOTHING`, [count, seed]);
      await db.exec(`INSERT INTO gestao_daily_dirty SELECT DISTINCT sold_on FROM gestao_fatos_pedido ON CONFLICT DO NOTHING;
        TRUNCATE gestao_report_cache; UPDATE gestao_report_revisions SET revision=revision+1;`);
      while ((await db.query('SELECT gestao_refresh_daily() n')).rows[0].n > 0) { /* bounded batches */ }
      await db.exec('ANALYZE gestao_fatos_pedido;');
      const durations = [];
      for (let i = 0; i < 3; i++) {
        const before = performance.now(); report = (await query()).rows[0].data;
        durations.push(Math.round(performance.now() - before));
      }
      console.log(JSON.stringify({ orders: count, database_report_ms: durations, response_bytes: JSON.stringify(report).length,
        note: 'PGlite synthetic SQL benchmark; not production HTTP or operational p95.' }));
      await cachedQuery();
      const warm=[];
      for(let i=0;i<20;i++) { const before=performance.now(); await cachedQuery(); warm.push(performance.now()-before); }
      warm.sort((a,b)=>a-b);
      const p95=warm[Math.ceil(warm.length*.95)-1];
      console.log(JSON.stringify({orders:count,warm_sql_cache_p95_ms:Math.round(p95),samples:warm.length}));
      assert.ok(p95<=2000,'Warm SQL cache p95 exceeded two seconds');
    }
  }
} catch (error) {
  console.error(error.message, error.where || ''); process.exitCode = 1;
} finally { await db.close(); }
