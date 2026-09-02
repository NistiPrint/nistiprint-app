// Aplica, no cliente, os mesmos ajustes que o banco vai aplicar ao publicar.
//
// Por que existe: o operador precisa VER o resultado antes de confirmar. A
// conta que vale é a de `despacho_materializar_itens` (migration
// 20260901100000) — este arquivo é a prévia dela, e as duas seguem a mesma
// regra, na mesma ordem:
//
//   remover     tira a linha
//   quantidade  substitui a quantidade da linha
//
// Estas duas operações existem para o que NÃO está cadastrado. Kit cadastrado
// não precisa de ajuste: `despacho_consolidar_pedidos` já entrega a lista com
// ele explodido nos produtos acabados que o compõem (migration 20260901140000).
// O que sobra para a mão do operador é o combo que ainda não virou cadastro:
// remover a linha do código do combo e somar a quantidade nos produtos certos,
// para a demanda ser publicada correta enquanto o cadastro não acompanha.
//
// A chave da linha é (sku, variação, miolo, título) — a mesma pela qual a
// consolidação agrupa. Sem o título, o mesmo SKU anunciado com dois títulos
// diferentes vira duas linhas e o ajuste acerta uma delas em silêncio.

export function chaveDaLinha(linha) {
  return [
    linha.sku_externo ?? '-',
    linha.variacao ?? '-',
    linha.miolo_chave ?? '',
    linha.titulo ?? linha.descricao ?? '',
  ].join('');
}

export function ajusteDaLinha(op, linha, extra = {}) {
  return {
    op,
    sku: linha.sku_externo ?? '-',
    variacao: linha.variacao ?? '-',
    miolo_chave: linha.miolo_chave ?? null,
    titulo: linha.titulo ?? linha.descricao ?? '',
    ...extra,
  };
}

function casa(linha, ajuste) {
  if ((linha.sku_externo ?? '-') !== ajuste.sku) return false;
  if ((linha.variacao ?? '-') !== (ajuste.variacao ?? '-')) return false;
  if ((linha.miolo_chave ?? null) !== (ajuste.miolo_chave ?? null)) return false;
  if (ajuste.titulo) return (linha.titulo ?? linha.descricao ?? '') === ajuste.titulo;
  return true;
}

/**
 * @param {Array} itens    linhas vindas de /despacho/previsao
 * @param {Array} ajustes  operações na ordem em que o operador as fez
 * @returns {Array} a lista resultante, já reordenada como o banco reordena
 */
export function aplicarAjustes(itens, ajustes) {
  let atual = itens.map((item) => ({ ...item }));

  for (const ajuste of ajustes || []) {
    if (ajuste.op === 'remover') {
      atual = atual.filter((linha) => !casa(linha, ajuste));
      continue;
    }

    if (ajuste.op === 'quantidade') {
      atual = atual.map((linha) =>
        casa(linha, ajuste) ? { ...linha, quantidade: Number(ajuste.valor) } : linha
      );
    }
  }

  // Reordena como o banco reordena: miolo com mais carga primeiro e, dentro do
  // miolo, quantidade decrescente. Sem isso a prévia mostraria uma ordem de
  // produção que o lançamento não vai reproduzir.
  const carga = new Map();
  for (const linha of atual) {
    const chave = linha.miolo_chave ?? '';
    carga.set(chave, (carga.get(chave) || 0) + Number(linha.quantidade || 0));
  }
  const rank = new Map(
    [...carga.entries()]
      .sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0])))
      .map(([chave], indice) => [chave, indice + 1])
  );
  atual.sort((a, b) => {
    const ra = rank.get(a.miolo_chave ?? '') ?? 0;
    const rb = rank.get(b.miolo_chave ?? '') ?? 0;
    if (ra !== rb) return ra - rb;
    if (Number(b.quantidade) !== Number(a.quantidade)) return Number(b.quantidade) - Number(a.quantidade);
    return String(a.sku_externo).localeCompare(String(b.sku_externo));
  });
  atual.forEach((linha, indice) => { linha.ordem = indice + 1; });

  return atual;
}

export function resumoDaLista(itens) {
  return {
    total_linhas: itens.length,
    total_pecas: itens.reduce((soma, item) => soma + Number(item.quantidade || 0), 0),
    sem_estoque: itens.filter((item) => !item.contabiliza_estoque).length,
    total_miolos: new Set(itens.map((item) => item.miolo_chave)).size,
  };
}
