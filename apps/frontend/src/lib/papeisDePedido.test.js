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


test('interrompe os lotes seguintes quando a API retorna erro', async () => {
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
    const ids = Array.from({ length: 26 }, (_, index) => index + 1);
    await assert.rejects(
      buscarPapeisDePedido(ids),
      /Falha ao preparar o lote/,
    );
    assert.equal(calls, 1);
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


test('exibe pacote no cabecalho e numero do marketplace no pedido', () => {
  const html = montarDocumentoDePapeis([{
    id: 3,
    numero: 'Bling-123',
    numeroLoja: 'ordem-externa',
    marketplace_order_id: '9007199254740993',
    pack_id: '9007199254740999',
    plataforma_slug: 'mercadolivre',
    itens: [],
  }]);

  assert.match(html, /Pacote 9007199254740999/);
  assert.match(html, /Pedido 9007199254740993/);
  assert.doesNotMatch(html, /ordem-externa/);
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
