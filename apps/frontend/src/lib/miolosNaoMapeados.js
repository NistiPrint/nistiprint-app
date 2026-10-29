export function normalizarChaveMiolo(value) {
  const text = String(value ?? '').trim().replace(/\s+/g, ' ');
  return text.replace(/^miolo(?:\s+|-\s*|:\s*|_\s*)/i, '').trim().toLocaleUpperCase('pt-BR');
}

export function agruparMiolosNaoMapeados(rows = []) {
  const groups = new Map();

  rows.forEach((row, index) => {
    const miolo = row.miolo_key || row.miolo_nome || row.miolo_name;
    const mioloNome = normalizarChaveMiolo(miolo);
    const identity = mioloNome ? `miolo:${mioloNome}` : `item:${row.item_id ?? index}`;
    const key = `${row.demanda_id}:${identity}`;
    if (!groups.has(key)) {
      groups.set(key, {
        key,
        demanda_id: row.demanda_id,
        demanda_nome: row.demanda_nome,
        simulacao: row.simulacao,
        miolo_nome: mioloNome || null,
        pendente: 0,
        rows: [],
      });
    }
    const group = groups.get(key);
    const pending = Number(row.pendente);
    group.pendente += Number.isFinite(pending) ? pending : 0;
    group.rows.push(row);
  });

  return [...groups.values()].map((group) => ({
    ...group,
    quantidade_linhas: group.rows.length,
  }));
}
