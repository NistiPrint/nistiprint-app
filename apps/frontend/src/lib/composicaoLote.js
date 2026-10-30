// Quantities are strings so decimal precision is not lost in transit.
export function normalizarQuantidade(value) {
  const text = String(value).trim().replace(',', '.');
  if (!/^\d+(?:\.\d{1,6})?$/.test(text) || !/[1-9]/.test(text)) {
    throw new Error('Informe uma quantidade positiva com até seis casas decimais.');
  }
  const [integer, fraction = ''] = text.split('.');
  if (integer.replace(/^0+/, '').length > 9) throw new Error('Quantidade fora do limite permitido.');
  const whole = integer.replace(/^0+(?=\d)/, '');
  const decimal = fraction.replace(/0+$/, '');
  return decimal ? `${whole}.${decimal}` : whole;
}

export function interpretarColagem(text, row, column, rowCount, columnCount) {
  const lines = text.replace(/\r\n?/g, '\n').split('\n');
  if (lines.length > 1 && lines.at(-1) === '') lines.pop();
  const values = lines.map(line => line.split('\t'));
  if (row + values.length > rowCount || values.some(line => column + line.length > columnCount)) {
    throw new Error('A colagem ultrapassa os limites da matriz.');
  }
  return values.flatMap((line, y) => line.flatMap((value, x) => value.trim()
    ? [{ row: row + y, column: column + x, quantidade: normalizarQuantidade(value) }]
    : []));
}

// State contains only edits; untouched cells are always read from the snapshot.
export function aplicarEdicoes(edicoes, alteracoes) {
  const resultado = { ...edicoes };
  for (const { produtoId, componenteId, acao, quantidade } of alteracoes) {
    const chave = `${produtoId}:${componenteId}`;
    if (acao === 'reverter') {
      delete resultado[chave];
    } else if (acao === 'remover') {
      resultado[chave] = { produto_id: produtoId, componente_id: componenteId, acao };
    } else if (acao === 'definir') {
      resultado[chave] = { produto_id: produtoId, componente_id: componenteId, acao, quantidade: normalizarQuantidade(quantidade) };
    } else {
      throw new Error('Operação de composição inválida.');
    }
  }
  return resultado;
}
