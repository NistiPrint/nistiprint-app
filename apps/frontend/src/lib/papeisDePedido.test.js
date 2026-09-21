import test from 'node:test';
import assert from 'node:assert/strict';

import {
  buscarPapeisDePedido,
  imprimirPapeisDePedido,
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
      data: { orders: [{ id: 1 }], blocked_orders: [{ pedido_id: 2 }] },
    }),
    jsonResponse({
      success: true,
      data: { orders: [{ id: 121 }], blocked_orders: [] },
    }),
  ];
  globalThis.fetch = async (...args) => {
    calls.push(args);
    return responses.shift();
  };

  try {
    const progress = [];
    const ids = Array.from({ length: 121 }, (_, index) => index + 1);
    const result = await buscarPapeisDePedido(ids, {
      onProgress: (value) => progress.push(value),
    });

    assert.equal(calls.length, 2);
    assert.equal(calls[0][0], '/api/v2/pedidos/impressao');
    assert.equal(calls[1][0], '/api/v2/pedidos/impressao');
    assert.equal(calls[0][1].method, 'POST');
    assert.deepEqual(calls[0][1].headers, { 'Content-Type': 'application/json' });
    assert.deepEqual(JSON.parse(calls[0][1].body), {
      order_ids: ids.slice(0, 120),
    });
    assert.deepEqual(JSON.parse(calls[1][1].body), {
      order_ids: [121],
    });
    assert.deepEqual(result, {
      orders: [{ id: 1 }, { id: 121 }],
      blocked: [{ pedido_id: 2 }],
    });
    assert.deepEqual(progress, [
      { processados: 0, total: 121 },
      { processados: 120, total: 121 },
      { processados: 121, total: 121 },
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
    const ids = Array.from({ length: 121 }, (_, index) => index + 1);
    await assert.rejects(
      buscarPapeisDePedido(ids),
      /Falha ao preparar o lote/,
    );
    assert.equal(calls, 1);
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
  const responses = [
    jsonResponse({
      success: true,
      data: { orders: [{ id: 1, itens: [] }], blocked_orders: [] },
    }),
    jsonResponse({
      success: true,
      data: { orders: [{ id: 121, itens: [] }], blocked_orders: [] },
    }),
  ];
  globalThis.fetch = async () => responses.shift();
  globalThis.document = {
    createElement: () => iframe,
    body: {
      appendChild: () => { appendedIframes += 1; },
    },
  };

  try {
    const ids = Array.from({ length: 121 }, (_, index) => index + 1);
    const result = await imprimirPapeisDePedido(ids);

    assert.equal(result.total, 2);
    assert.equal(appendedIframes, 1);
    assert.match(writtenHtml, /Pedido 1/);
    assert.match(writtenHtml, /Pedido 121/);
  } finally {
    globalThis.fetch = originalFetch;
    if (originalDocument === undefined) delete globalThis.document;
    else globalThis.document = originalDocument;
  }
});
