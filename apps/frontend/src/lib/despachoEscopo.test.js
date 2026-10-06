import assert from 'node:assert/strict';
import test from 'node:test';
import { carregarEscopoDespacho } from './despachoEscopo.js';
import { totalizarLinhas } from './consolidacaoEditavel.js';

const params = new URLSearchParams('integration_id=6&modalidade_ids=1&horizonte=amanha&data=2026-10-05');
const itens = [
  { linha_chave: 'agenda-azul', descricao: 'Agenda diária', sku_externo: 'AGD-AZ', miolo_nome: 'Azul', quantidade: 24 },
  { linha_chave: 'agenda-rosa', descricao: 'Agenda diária', sku_externo: 'AGD-RS', miolo_nome: 'Rosa', quantidade: 12 },
];
const previsao = { itens, previsao_versao: 'versao-1', total_pedidos: 74, total_pecas: 36 };
const escopo = { total: 74, pedidos: Array.from({ length: 74 }, (_, index) => ({ id: index + 1 })) };
const resposta = (data) => ({ ok: true, status: 200, json: async () => ({ success: true, data }) });

test('usa a consolidação incluída no escopo sem fazer consulta complementar', async () => {
  const chamadas = [];
  const carregar = await carregarEscopoDespacho(async (url, options) => {
    chamadas.push({ url, options });
    return resposta({ ...escopo, previsao });
  }, params, new AbortController().signal);

  assert.equal(chamadas.length, 1);
  assert.equal(carregar.previsao.itens.length, 2);
  assert.equal(totalizarLinhas(carregar.previsao.itens), 36);
});

test('recupera a consolidação pela rota anterior quando o escopo não a inclui', async () => {
  const chamadas = [];
  const controller = new AbortController();
  const carregar = await carregarEscopoDespacho(async (url, options) => {
    chamadas.push({ url, options });
    return resposta(url.includes('/previsao?') ? previsao : escopo);
  }, params, controller.signal);

  assert.equal(chamadas.length, 2);
  assert.ok(chamadas[0].url.includes('/despacho/escopo?'));
  assert.ok(chamadas[1].url.includes('/despacho/previsao?'));
  assert.equal(new URL(`http://local${chamadas[0].url}`).search, new URL(`http://local${chamadas[1].url}`).search);
  assert.equal(chamadas[0].options.signal, controller.signal);
  assert.equal(chamadas[1].options.signal, controller.signal);
  assert.equal(carregar.previsao.itens.length, 2);
  assert.equal(totalizarLinhas(carregar.previsao.itens), 36);
});

test('falha em resposta inválida sem fornecer consolidação vazia', async () => {
  await assert.rejects(
    carregarEscopoDespacho(async (url) => resposta(url.includes('/previsao?') ? { itens: [] } : escopo), params),
    /consolidação está incompleta/,
  );
});
