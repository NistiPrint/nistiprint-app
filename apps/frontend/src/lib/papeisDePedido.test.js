import test from 'node:test';
import assert from 'node:assert/strict';

import {
  buscarPapeisDePedido,
  imprimirPapeisDePedido,
  montarDocumentoDePapeis,
} from './papeisDePedido.js';


function jsonResponse(data, { ok = true } = {}) {
  return {
    ok,
    json: async () => data,
  };
}


test('envia lotes por POST no corpo e agrega o resultado com progresso', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  const responses = [
    jsonResponse({
      success: true,
      data: {
        orders: Array.from({ length: 24 }, (_, index) => ({ id: index + 1 })),
        blocked_orders: [{ pedido_id: 25 }],
      },
    }),
    jsonResponse({
      success: true,
      data: { orders: [{ id: 26 }], blocked_orders: [] },
    }),
  ];
  globalThis.fetch = async (...args) => {
    calls.push(args);
    return responses.shift();
  };

  try {
    const progress = [];
    const ids = Array.from({ length: 26 }, (_, index) => index + 1);
    const result = await buscarPapeisDePedido(ids, {
      onProgress: (value) => progress.push(value),
    });

    assert.equal(calls.length, 2);
    assert.equal(calls[0][0], '/api/v2/pedidos/impressao');
    assert.equal(calls[1][0], '/api/v2/pedidos/impressao');
    assert.equal(calls[0][1].method, 'POST');
    assert.deepEqual(calls[0][1].headers, { 'Content-Type': 'application/json' });
    assert.deepEqual(JSON.parse(calls[0][1].body), {
      order_ids: ids.slice(0, 25),
    });
    assert.deepEqual(JSON.parse(calls[1][1].body), {
      order_ids: [26],
    });
    assert.equal(result.orders.length, 25);
    assert.equal(result.orders[0].id, 1);
    assert.equal(result.orders[23].id, 24);
    assert.deepEqual(result.blocked, [{ pedido_id: 25 }]);
    assert.deepEqual(progress, [
      { processados: 0, total: 26 },
      { processados: 25, total: 26 },
      { processados: 26, total: 26 },
    ]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});


test('nao inicia nova janela de lotes quando uma fatia retorna erro', async () => {
  const originalFetch = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    return jsonResponse(
      { success: false, message: 'Falha ao preparar o lote' },
      { ok: false },
    );
  };

  try {
    const ids = Array.from({ length: 126 }, (_, index) => index + 1);
    await assert.rejects(
      buscarPapeisDePedido(ids),
      /Falha ao preparar o lote/,
    );
    assert.equal(calls, 4);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('processa lotes de 400 pedidos com no máximo quatro requisições simultâneas', async () => {
  const originalFetch = globalThis.fetch;
  const chamadas = [];
  let ativas = 0;
  let maximoAtivo = 0;
  globalThis.fetch = async (_url, options) => {
    const { order_ids: lote } = JSON.parse(options.body);
    chamadas.push(lote);
    ativas += 1;
    maximoAtivo = Math.max(maximoAtivo, ativas);
    await new Promise((resolve) => setTimeout(resolve, 2));
    ativas -= 1;
    return jsonResponse({
      success: true,
      data: { orders: lote.map((id) => ({ id })), blocked_orders: [] },
    });
  };

  try {
    const ids = Array.from({ length: 400 }, (_, index) => index + 1);
    const resultado = await buscarPapeisDePedido(ids);
    assert.equal(chamadas.length, 16);
    assert.ok(maximoAtivo > 1);
    assert.ok(maximoAtivo <= 4);
    assert.equal(resultado.orders.length, 400);
    assert.deepEqual(resultado.orders.map((order) => order.id), ids);
  } finally {
    globalThis.fetch = originalFetch;
  }
});


test('identifica explicitamente pedidos omitidos pela API', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => jsonResponse({
    success: true,
    data: { orders: [{ id: 1 }], blocked_orders: [] },
  });

  try {
    await assert.rejects(buscarPapeisDePedido([1, 2]), /não retornou resultado.*2/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});


test('agrega todos os lotes em um unico documento de impressao', async () => {
  const originalFetch = globalThis.fetch;
  const originalDocument = globalThis.document;
  let appendedIframes = 0;
  let writtenHtml = '';
  const iframe = {
    setAttribute: () => {},
    style: {},
    contentDocument: {
      open: () => {},
      write: (html) => { writtenHtml = html; },
      close: () => {},
    },
  };
  globalThis.fetch = async (_url, options) => {
    const { order_ids: lote } = JSON.parse(options.body);
    return jsonResponse({
      success: true,
      data: { orders: lote.map((id) => ({ id, itens: [] })), blocked_orders: [] },
    });
  };
  globalThis.document = {
    createElement: () => iframe,
    body: {
      appendChild: () => { appendedIframes += 1; },
    },
  };

  try {
    const ids = Array.from({ length: 26 }, (_, index) => index + 1);
    const result = await imprimirPapeisDePedido(ids);

    assert.equal(result.total, 26);
    assert.equal(appendedIframes, 1);
    assert.match(writtenHtml, /Pedido 1/);
    assert.match(writtenHtml, /Pedido 26/);
  } finally {
    globalThis.fetch = originalFetch;
    if (originalDocument === undefined) delete globalThis.document;
    else globalThis.document = originalDocument;
  }
});


test('prioriza nome identificado e omite mensagem do comprador', () => {
  const html = montarDocumentoDePapeis([{
    id: 1,
    itens: [{
      descricao: 'Capa personalizada',
      personalizations: [{ customization_name: '  Maria  ' }],
    }],
    mensagem_comprador: 'Gravar outro texto',
  }]);

  assert.match(html, />Maria</);
  assert.doesNotMatch(html, /Mensagem do comprador/);
  assert.doesNotMatch(html, /Gravar outro texto/);
});


test('usa mensagem do comprador quando nao existe nome identificado', () => {
  const html = montarDocumentoDePapeis([{
    id: 2,
    itens: [{
      descricao: 'Capa personalizada',
      personalizations: [{ customization_name: '   ' }],
    }],
    mensagem_comprador: 'Nome ainda nao identificado',
  }]);

  assert.match(html, /Mensagem do comprador/);
  assert.match(html, /Nome ainda nao identificado/);
  assert.doesNotMatch(html, /custom-name-display">\s+</);
});


test('exibe o pacote no cabecalho e reaproveita o numero sem ERP no pedido', () => {
  const html = montarDocumentoDePapeis([{
    id: 3,
    numero: '9007199254740999',
    numeroLoja: 'ordem-externa',
    marketplace_order_id: '9007199254740993',
    pack_id: '9007199254740999',
    plataforma_slug: 'mercadolivre',
    itens: [],
  }]);

  assert.match(html, /<div>9007199254740999<\/div>/);
  assert.match(html, /Pedido 9007199254740999/);
  assert.doesNotMatch(html, /ordem-externa/);
});


test('usa o numero do pedido no cabecalho quando o Mercado Livre nao tem pacote', () => {
  const html = montarDocumentoDePapeis([{
    id: 5,
    numeroLoja: '8001234567890',
    marketplace_order_id: '8001234567890',
    pack_id: null,
    plataforma_slug: 'mercadolivre',
    itens: [],
  }]);

  assert.match(html, /<div>8001234567890<\/div>/);
  assert.match(html, /Pedido 8001234567890/);
  assert.doesNotMatch(html, /Pacote não informado/);
});


test('combina pedidos do mesmo pacote Mercado Livre em uma unica folha', () => {
  const html = montarDocumentoDePapeis([
    {
      id: 10,
      numero: '9001',
      marketplace_order_id: '9001',
      pack_id: 'pack-42',
      plataforma_slug: 'mercadolivre',
      total_items: 2,
      totalProdutos: 30,
      itens: [{ descricao: 'Produto A', quantidade: 2, valor: 10 }],
    },
    {
      id: 11,
      numero: '9002',
      marketplace_order_id: '9002',
      pack_id: 'pack-42',
      plataforma_slug: 'mercadolivre',
      total_items: 1,
      totalProdutos: 15,
      itens: [{ descricao: 'Produto B', quantidade: 1, valor: 15 }],
    },
    {
      id: 12,
      numero: '9003',
      marketplace_order_id: '9003',
      pack_id: 'pack-43',
      plataforma_slug: 'mercadolivre',
      total_items: 1,
      totalProdutos: 20,
      itens: [{ descricao: 'Produto C', quantidade: 1, valor: 20 }],
    },
  ]);

  assert.equal((html.match(/class="stamp-card"/g) || []).length, 2);
  assert.match(html, /<div>Pedido 9001<\/div>/);
  assert.doesNotMatch(html, /Pedido 9002/);
  assert.match(html, /Produto A[\s\S]*Produto B/);
  assert.match(html, /<div>pack-42<\/div>/);
  assert.match(html, /<div>pack-43<\/div>/);
});


test('nao combina pedidos ML sem pacote nem pedidos de outros canais', () => {
  const html = montarDocumentoDePapeis([
    { id: 1, numero: '100', plataforma_slug: 'mercadolivre', pack_id: null, itens: [] },
    { id: 2, numero: '200', plataforma_slug: 'shopee', pack_id: 'mesmo-valor', itens: [] },
    { id: 3, numero: '201', plataforma_slug: 'shopee', pack_id: 'mesmo-valor', itens: [] },
  ]);

  assert.equal((html.match(/class="stamp-card"/g) || []).length, 3);
});


test('personalizacao pendente omite nomes, iniciais e mensagem de comprador', () => {
  const html = montarDocumentoDePapeis([{
    id: 4,
    plataforma_slug: 'mercadolivre',
    personalizacao_pendente: true,
    itens: [{
      descricao: 'Capa personalizada',
      personalizations: [{ customization_name: 'Maria', customization_initial: 'M' }],
    }],
    mensagem_comprador: 'Gravar o nome enviado na conversa',
  }]);

  assert.doesNotMatch(html, /Maria|Gravar o nome enviado|<div class="custom-name-display">/);
  assert.doesNotMatch(html, /revisão|revisar|pendente/i);
});
