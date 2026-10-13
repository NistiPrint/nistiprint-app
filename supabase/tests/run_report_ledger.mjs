// npm install --prefix temp/logistica-sql @electric-sql/pglite
// node supabase/tests/run_report_ledger.mjs (a partir da raiz do repositorio)
import { readFile } from 'node:fs/promises';
import { PGlite } from '../../temp/logistica-sql/node_modules/@electric-sql/pglite/dist/index.js';

const db = new PGlite();
const migrations = [
  'supabase/tests/fixtures/estoque_command_schema.sql',
  'supabase/migrations/20261009175729_estoque_comando_idempotente.sql',
  'supabase/migrations/20261009181200_alocacoes_transacionais.sql',
  'supabase/migrations/20261009191857_consumo_diario_agregado.sql',
  'supabase/migrations/20261010153814_relatorio_consumo_mensal_ledger.sql',
];

try {
  for (const file of migrations) {
    await db.exec(await readFile(file, 'utf8'));
    console.log(`OK: ${file}`);
  }

  await db.exec(`
    INSERT INTO public.produtos(id, nome) VALUES (1, 'Papel');
    INSERT INTO public.depositos(id) VALUES (1);
    INSERT INTO public.estoque_atual(produto_id, deposito_id, saldo_atual) VALUES (1, 1, 1);
  `);

  const allocations = [
    { produto_id: 1, quantidade: '1', item_id: 'item-101', demanda_id: 'D-101',
      correlation_id: '11111111-1111-4111-8111-111111111111' },
    { produto_id: 1, quantidade: '1', item_id: 'item-102', demanda_id: 'D-102',
      correlation_id: '22222222-2222-4222-8222-222222222222' },
  ];
  const [firstAllocation, secondAllocation] = allocations;
  const reserve = async (operationId, contentHash, rows) => db.query(
    'SELECT public.reservar_alocacoes_estoque($1, $2, $3::jsonb, NULL, 1, $4::jsonb) AS result',
    [operationId, contentHash, JSON.stringify({ source_id: operationId }), JSON.stringify(rows)],
  );
  const firstOperation = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  const secondOperation = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
  const firstHash = 'a'.repeat(64);
  const secondHash = 'b'.repeat(64);
  const firstResult = (await reserve(firstOperation, firstHash, [firstAllocation])).rows[0].result;
  const replayResult = (await reserve(firstOperation, firstHash, [firstAllocation])).rows[0].result;
  if (JSON.stringify(firstResult) !== JSON.stringify(replayResult)) {
    throw new Error('Replay de reserva mudou o resultado');
  }
  await reserve(secondOperation, secondHash, [secondAllocation]);
  const { rows: reservationRows } = await db.query(
    'SELECT saldo_atual, reservado, disponivel FROM public.estoque_atual WHERE produto_id=1 AND deposito_id=1',
  );
  if (Number(reservationRows[0].saldo_atual) !== 1
      || Number(reservationRows[0].reservado) !== 2
      || Number(reservationRows[0].disponivel) !== -1) {
    throw new Error(`Reserva/backorder inesperado: ${JSON.stringify(reservationRows)}`);
  }

  try {
    await reserve('cccccccc-cccc-4ccc-8ccc-cccccccccccc', 'c'.repeat(64), [
      { ...firstAllocation, item_id: 'item-103', correlation_id: '33333333-3333-4333-8333-333333333333' },
      { produto_id: 1, quantidade: '1', item_id: 'item-104', demanda_id: 'D-104' },
    ]);
    throw new Error('Reserva inválida foi confirmada');
  } catch (error) {
    if (error.message === 'Reserva inválida foi confirmada') throw error;
  }
  const { rows: rollbackRows } = await db.query(`
    SELECT
      (SELECT count(*) FROM public.estoque_operacoes
        WHERE operation_id='cccccccc-cccc-4ccc-8ccc-cccccccccccc') AS operations,
      (SELECT count(*) FROM public.demanda_alocacoes_estoque) AS allocations,
      (SELECT reservado FROM public.estoque_atual WHERE produto_id=1 AND deposito_id=1) AS reserved
  `);
  if (Number(rollbackRows[0].operations) !== 0
      || Number(rollbackRows[0].allocations) !== 2
      || Number(rollbackRows[0].reserved) !== 2) {
    throw new Error('Falha de reserva deixou a operação parcial persistida');
  }

  await db.exec(`
    INSERT INTO public.estoque_operacoes
      (operation_id, command_type, content_hash, status, result, confirmed_at)
    VALUES
      ('11111111-1111-4111-8111-111111111111', 'ENTRADA', 'consumption-aug', 'CONFIRMADO', '{}'::jsonb, now()),
      ('22222222-2222-4222-8222-222222222222', 'ENTRADA', 'compensation-aug', 'CONFIRMADO', '{}'::jsonb, now()),
      ('33333333-3333-4333-8333-333333333333', 'ENTRADA', 'consumption-sep', 'CONFIRMADO', '{}'::jsonb, now());
    INSERT INTO public.movimentacoes_estoque
      (produto_id, deposito_id, tipo_movimentacao, quantidade, data_movimentacao, operation_id)
    VALUES
      (1, 1, 'CONS_MP', 5, '2026-08-01 10:00:00', '11111111-1111-4111-8111-111111111111'),
      (1, 1, 'COMPENSACAO_CONS_MP', 1, '2026-08-02 10:00:00', '22222222-2222-4222-8222-222222222222'),
      (1, 1, 'CONS_INT', 2, '2026-09-01 10:00:00', '33333333-3333-4333-8333-333333333333'),
      (1, 1, 'BALANCO', 20, '2026-09-02 10:00:00', NULL);
  `);
  console.log('OK: atomic allocations replay and backorder');

  const { rows } = await db.query(
    'SELECT periodo, consumo_liquido, movimentos '
      + 'FROM public.relatorio_consumo_mensal_produto(1)',
  );
  const { rows: dailyRows } = await db.query(
    'SELECT produto_id, total_periodo, periodo_dias, nome_insumo '
      + 'FROM public.consumo_medio_diario(3660)',
  );
  const expected = [
    { periodo: '2026-08', consumo: 4, movementTypes: ['CONS_MP', 'COMPENSACAO_CONS_MP'] },
    { periodo: '2026-09', consumo: 2, movementTypes: ['CONS_INT'] },
  ];
  const actual = rows.map((row) => ({
    periodo: row.periodo,
    consumo: Number(row.consumo_liquido),
    movementTypes: row.movimentos.map((movement) => movement.tipo),
  }));
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(`Resultado inesperado: ${JSON.stringify(actual)}`);
  }
  if (dailyRows.length !== 1 || dailyRows[0].produto_id !== 1
      || Number(dailyRows[0].total_periodo) !== 6
      || dailyRows[0].periodo_dias !== 3660 || dailyRows[0].nome_insumo !== 'Papel') {
    throw new Error(`Consumo diário inesperado: ${JSON.stringify(dailyRows)}`);
  }
  console.log(`OK: monthly=${JSON.stringify(actual)}; daily=${JSON.stringify(dailyRows)}`);
} finally {
  await db.close();
}
