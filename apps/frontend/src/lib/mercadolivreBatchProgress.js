export const isBatchActive = batch => ['PENDING', 'RUNNING'].includes(batch?.status);

export function batchStage(batch) {
  if (!batch) return 'Na fila';
  if (batch.status === 'COMPLETED') return Number(batch.failed_count || batch.falha || 0) > 0 ? 'Concluído com falhas' : 'Concluído';
  if (batch.status === 'FAILED') return 'Falhou';
  if (batch.phase === 'RETRY') return batch.status === 'PENDING' ? 'Aguardando retentativa' : 'Retentando falhas';
  return batch.status === 'RUNNING' ? 'Processando' : 'Na fila';
}

export function firstPassPercent(batch) {
  return batch?.total > 0 ? Math.max(0, Math.min(100, Math.round(100 * Number(batch.processed || 0) / batch.total))) : 0;
}

export function batchFromOperation(operation) {
  const values = operation?.dados_adicionais || {};
  return {
    id: values.batch_id || operation.origem_id || operation.referencia_id,
    marketplace_integration_id: values.integration_id, created_by: operation.owner_user_id,
    status: values.batch_status || ({ AGUARDANDO: 'PENDING', EM_ANDAMENTO: 'RUNNING', CONCLUIDO: 'COMPLETED', ERRO: 'FAILED' })[operation.status],
    phase: values.phase || 'FIRST_PASS', processed: values.processed ?? operation.progresso_atual ?? 0,
    total: values.total ?? operation.progresso_total ?? 0,
    success_count: values.sucesso || 0, failed_count: values.falha || 0,
    retry_pending_count: values.retry_pending_count || 0, running_count: values.running_count || 0,
    retry_total: values.retry_total || 0, retry_processed: values.retry_processed || 0,
    available_at: values.next_attempt_at, started_at: values.started_at,
    finished_at: values.finished_at, created_at: operation.created_at,
    updated_at: values.updated_at || operation.updated_at,
  };
}

export function mergeBatchSnapshots(current, incoming) {
  const snapshots = new Map(current.map(batch => [String(batch.id), batch]));
  for (const batch of incoming) {
    const previous = snapshots.get(String(batch.id));
    if (previous?.updated_at && batch.updated_at && new Date(previous.updated_at) > new Date(batch.updated_at)) continue;
    if (previous && !isBatchActive(previous) && isBatchActive(batch)) continue;
    snapshots.set(String(batch.id), { ...previous, ...batch });
  }
  return [...snapshots.values()].sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0)).slice(0, 5);
}
