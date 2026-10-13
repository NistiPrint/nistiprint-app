import test from 'node:test';
import assert from 'node:assert/strict';
import { batchFromOperation, batchStage, firstPassPercent, mergeBatchSnapshots } from './mercadolivreBatchProgress.js';

test('falhas avançam a primeira passagem sem encerrar as retentativas', () => {
  const batch = { status: 'PENDING', phase: 'RETRY', total: 50, processed: 50, success_count: 48, retry_pending_count: 2 };
  assert.equal(firstPassPercent(batch), 100);
  assert.equal(batchStage(batch), 'Aguardando retentativa');
  assert.equal(batchStage({ ...batch, status: 'RUNNING' }), 'Retentando falhas');
  assert.equal(batchStage({ ...batch, status: 'COMPLETED', failed_count: 1 }), 'Concluído com falhas');
});

test('evento preserva fase e contadores distintos de sucesso e analisados', () => {
  const batch = batchFromOperation({ origem_id: 'b', status: 'EM_ANDAMENTO', dados_adicionais: {
    phase: 'RETRY', batch_status: 'PENDING', processed: 10, total: 10, sucesso: 8, retry_total: 2, retry_processed: 0,
  } });
  assert.equal(batch.processed, 10);
  assert.equal(batch.success_count, 8);
  assert.equal(batch.phase, 'RETRY');
  assert.equal(batch.status, 'PENDING');
});

test('consulta atrasada não substitui conclusão nem regride os contadores', () => {
  const current = [{ id: 'b', status: 'COMPLETED', processed: 10, updated_at: '2026-10-13T12:00:05Z' }];
  const stale = { id: 'b', status: 'RUNNING', processed: 8, updated_at: '2026-10-13T12:00:01Z' };
  assert.deepEqual(mergeBatchSnapshots(current, [stale]), current);
});
