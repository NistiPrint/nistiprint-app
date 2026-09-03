export const COLUNAS_CONSOLIDACAO = ['descricao', 'sku_externo', 'variacao', 'miolo_nome', 'quantidade'];

export function normalizarLinha(linha = {}, indice = 0) {
  return {
    client_id: linha.client_id || linha.linha_chave || `linha-${indice}`,
    linha_chave: linha.linha_chave ?? null,
    descricao: linha.descricao == null ? '' : String(linha.descricao),
    sku_externo: linha.sku_externo == null ? '' : String(linha.sku_externo),
    variacao: linha.variacao == null || linha.variacao === '-' ? '' : String(linha.variacao),
    miolo_nome: linha.miolo_nome == null ? '' : String(linha.miolo_nome),
    quantidade: linha.quantidade === '' || linha.quantidade == null ? '' : Number(linha.quantidade),
    produto_id: linha.produto_id ?? null,
    id_produto_miolo: linha.id_produto_miolo ?? null,
    contabiliza_estoque: linha.contabiliza_estoque !== false,
    sku_status: linha.sku_status || null,
    miolo_status: linha.miolo_status || null,
    manual: Boolean(linha.manual),
  };
}

export function totalizarLinhas(linhas = []) {
  return linhas.reduce((total, linha) => {
    const quantidade = Number(linha.quantidade);
    return total + (Number.isFinite(quantidade) ? quantidade : 0);
  }, 0);
}

export function linhaVazia(linha = {}) {
  return !COLUNAS_CONSOLIDACAO.some((coluna) => {
    const valor = linha[coluna];
    return valor !== '' && valor !== null && valor !== undefined;
  });
}

export function prepararLinhasParaEnvio(linhas = []) {
  return linhas
    .filter((linha) => !linha.manual || !linhaVazia(linha))
    .map((linha, indice) => ({
      linha_chave: linha.linha_chave || null,
      ordem: indice + 1,
      produto: String(linha.descricao ?? ''),
      sku: String(linha.sku_externo ?? ''),
      variacao: String(linha.variacao ?? ''),
      miolo: String(linha.miolo_nome ?? ''),
      quantidade: linha.quantidade === '' ? null : Number(linha.quantidade),
    }));
}

export function linhasParaTsv(linhas = []) {
  const conteudo = prepararLinhasParaEnvio(linhas);
  if (!conteudo.length) return '';
  return `${conteudo.map((linha) => [linha.produto, linha.sku, linha.variacao, linha.miolo, linha.quantidade ?? ''].join('\t')).join('\n')}\n`;
}

export function inserirLinha(linhas, indice, acima = true) {
  const nova = normalizarLinha({ manual: true, quantidade: '' }, indice);
  const destino = Math.max(0, Math.min(linhas.length, acima ? indice : indice + 1));
  return [...linhas.slice(0, destino), nova, ...linhas.slice(destino)];
}

export function moverLinha(linhas, origem, destino) {
  if (origem === destino || origem < 0 || destino < 0 || origem >= linhas.length || destino >= linhas.length) return linhas;
  const copia = [...linhas];
  const [linha] = copia.splice(origem, 1);
  copia.splice(destino, 0, linha);
  return copia;
}
