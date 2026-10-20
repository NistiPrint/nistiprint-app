// Disposable PostgreSQL (PGlite) migration/queue checks. No application database access.
// Set GESTAO_PGLITE_MODULE to the installed @electric-sql/pglite entry point.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';

if (!process.env.GESTAO_PGLITE_MODULE) throw new Error('Set GESTAO_PGLITE_MODULE to a temporary PGlite installation.');
const { PGlite } = await import(pathToFileURL(process.env.GESTAO_PGLITE_MODULE).href);
const db = new PGlite();
let checks = 0;
try {
  await db.exec(await readFile(new URL('../supabase/tests/fixtures/gestao_schema.sql', import.meta.url), 'utf8'));
  await db.exec(await readFile(new URL('../supabase/migrations/20261020160000_gestao_business_intelligence.sql', import.meta.url), 'utf8'));
  checks++;
  await db.exec(`INSERT INTO installed_integrations VALUES(6,'Loja A');
    INSERT INTO produtos VALUES(2,10);
    INSERT INTO pedidos_shopee VALUES(9,'{"buyer_user_id":10}');
    INSERT INTO pedidos VALUES(1,6,null,9,null,'shopee','2026-10-01T10:00:00-03:00','delivered',100);
    INSERT INTO itens_pedido VALUES(11,1,2,'ABC',2,50,100);`);
  let source = (await db.query('SELECT gestao_claim(100) AS data')).rows[0].data[0];
  assert.equal(Number(source.items[0].quantidade), 2); checks++;
  assert.equal((await db.query('SELECT gestao_claim(100) AS data')).rows[0].data.length, 0); checks++;
  const payload = s => ({ id:1, generation:s.generation, sold_on:'2026-10-01', account_id:6, marketplace:'shopee', items:[] });
  await db.exec('UPDATE itens_pedido SET quantidade=3,subtotal=150 WHERE id=11');
  assert.equal((await db.query('SELECT gestao_finish($1::jsonb) AS n',[JSON.stringify([payload(source)])])).rows[0].n,0); checks++;
  const fresh = (await db.query('SELECT gestao_claim(100) AS data')).rows[0].data[0];
  assert.ok(fresh.generation>source.generation); checks++;
  assert.equal(Number(fresh.items[0].quantidade),3); checks++;
  assert.equal((await db.query('SELECT gestao_finish($1::jsonb) AS n',[JSON.stringify([payload(fresh)])])).rows[0].n,1); checks++;
  assert.equal((await db.query('SELECT gestao_finish($1::jsonb) AS n',[JSON.stringify([payload(fresh)])])).rows[0].n,0); checks++;
  await db.exec(`UPDATE pedidos_shopee SET raw_payload='{"buyer_user_id":20}' WHERE id=9`);
  source = (await db.query('SELECT gestao_claim(100) AS data')).rows[0].data[0];
  assert.equal(source.shopee.buyer_user_id,20); checks++;
  await db.exec(`INSERT INTO pedidos VALUES(2,6,null,null,null,'shopee','2026-10-01T10:00:00-03:00','delivered',100);
    UPDATE itens_pedido SET pedido_id=2 WHERE id=11;`);
  assert.equal(Number((await db.query('SELECT count(*) AS n FROM gestao_outbox WHERE pedido_id IN (1,2)')).rows[0].n),2); checks++;
  assert.ok((await db.query('SELECT generation FROM gestao_outbox WHERE pedido_id=1')).rows[0].generation>source.generation); checks++;
  await db.exec('UPDATE produtos SET preco_custo=12 WHERE id=2');
  assert.equal((await db.query('SELECT unit_cost FROM gestao_custos ORDER BY valid_from DESC LIMIT 1')).rows[0].unit_cost,'12'); checks++;
  assert.equal((await db.query("SELECT gestao_collection_lease(6,'ml_visits') AS leased")).rows[0].leased,true); checks++;
  assert.equal((await db.query("SELECT gestao_collection_lease(6,'ml_visits') AS leased")).rows[0].leased,false); checks++;
  await db.exec(`INSERT INTO gestao_financeiro(pedido_id,components,source) VALUES(2,'{"net_payout":80}','manual');
    UPDATE gestao_financeiro SET updated_at=clock_timestamp() WHERE pedido_id=2;`);
  assert.equal(Number((await db.query('SELECT count(*) AS n FROM gestao_financeiro_historico')).rows[0].n),1); checks++;
  await db.exec(`UPDATE gestao_financeiro SET components='{"net_payout":75}' WHERE pedido_id=2`);
  assert.equal(Number((await db.query('SELECT count(*) AS n FROM gestao_financeiro_historico')).rows[0].n),2); checks++;
  await db.exec('BEGIN; SET LOCAL ROLE authenticated;');
  await assert.rejects(db.query('SELECT * FROM gestao_fatos_pedido'),/permission denied/); checks++;
  await db.exec('ROLLBACK; BEGIN; SET LOCAL ROLE anon;');
  await assert.rejects(db.query('SELECT gestao_claim(1)'),/permission denied/); checks++;
  await db.exec('ROLLBACK; DELETE FROM pedidos WHERE id=1');
  assert.equal((await db.query('SELECT count(*) AS n FROM gestao_fatos_pedido')).rows[0].n,0); checks++;
  console.log(`Gestão SQL: ${checks} checks passed in isolated PostgreSQL.`);
} finally {
  await db.close();
}
