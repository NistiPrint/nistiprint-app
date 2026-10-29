import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  calcularFinalizacaoPrevista,
  datasRapidas,
  horarioJaPassou,
  janelasColeta,
  modalidadesDisponiveis,
  montarPayloadDemanda,
  normalizarHora,
  somarDias,
  urlCriacaoDemanda,
} from './novaDemanda.js';

const canalComRegras = {
  id: 7,
  nome: 'Shopee Principal',
  color: '#ee4d2d',
  horario_coleta: '18:00:00',
  flex: true,
  fulfillment: false,
  regras_logisticas: {
    STANDARD: [
      { horario_limite: '15:00:00', tipo: 'COLETA_LOCAL', prioridade_uso: 2 },
      { horario_limite: '17:30:00', tipo: 'PONTO_COLETA', ponto_coleta_nome: 'Agência Centro', prioridade_uso: 1 },
    ],
    EXPRESS: [{ horario_limite: '11:00', tipo: 'COLETA_LOCAL', prioridade_uso: 1 }],
  },
};

const canalSemRegras = { id: 9, nome: 'Loja própria', horario_coleta: '16:45:00', regras_logisticas: {} };

test('normalizarHora aceita HH:MM e HH:MM:SS e descarta o resto', () => {
  assert.equal(normalizarHora('15:00:00'), '15:00');
  assert.equal(normalizarHora('9:5'), '09:05');
  assert.equal(normalizarHora(''), '');
  assert.equal(normalizarHora('24:00'), '');
  assert.equal(normalizarHora('abc'), '');
});

test('modalidadesDisponiveis deriva das flags e das regras do canal', () => {
  assert.deepEqual(modalidadesDisponiveis(canalComRegras, 'venda_diaria'), ['STANDARD', 'EXPRESS']);
  assert.deepEqual(modalidadesDisponiveis(canalSemRegras, 'venda_diaria'), ['STANDARD']);
  // O fluxo de fulfillment sempre oferece a própria modalidade.
  assert.deepEqual(modalidadesDisponiveis(canalSemRegras, 'fulfillment'), ['STANDARD', 'FULFILLMENT']);
  assert.deepEqual(
    modalidadesDisponiveis({ ...canalSemRegras, regras_logisticas: { RETIRADA: [{ horario_limite: '10:00' }] } }, 'venda_diaria'),
    ['STANDARD', 'RETIRADA']
  );
});

test('janelasColeta respeita a modalidade e a ordem devolvida pela API', () => {
  const standard = janelasColeta(canalComRegras, 'STANDARD');
  assert.equal(standard.length, 2);
  assert.equal(standard[0].horario, '15:00');
  assert.equal(standard[1].ponto, 'Agência Centro');

  assert.deepEqual(janelasColeta(canalComRegras, 'EXPRESS'), [
    { horario: '11:00', tipo: 'COLETA_LOCAL', ponto: null },
  ]);
});

test('janelasColeta cai no horario_coleta do canal quando não há regra', () => {
  assert.deepEqual(janelasColeta(canalSemRegras, 'STANDARD'), [{ horario: '16:45', tipo: null, ponto: null }]);
  assert.deepEqual(janelasColeta(canalComRegras, 'RETIRADA'), [{ horario: '18:00', tipo: null, ponto: null }]);
  assert.deepEqual(janelasColeta({ nome: 'Sem nada' }, 'STANDARD'), []);
});

test('calcularFinalizacaoPrevista desconta uma hora e pode virar o dia anterior', () => {
  assert.equal(calcularFinalizacaoPrevista('2026-10-28', '15:00'), '2026-10-28T14:00');
  assert.equal(calcularFinalizacaoPrevista('2026-10-28', '00:30'), '2026-10-27T23:30');
  assert.equal(calcularFinalizacaoPrevista('2026-10-28', '08:00', { antecedenciaMinutos: 90 }), '2026-10-28T06:30');
  assert.equal(calcularFinalizacaoPrevista('2026-10-28', ''), '');
  assert.equal(calcularFinalizacaoPrevista('', '15:00'), '');
});

test('horarioJaPassou usa a tolerância de 10 minutos do backend', () => {
  const agora = new Date(2026, 9, 28, 15, 0, 0);
  assert.equal(horarioJaPassou('2026-10-28', '14:55', agora), false, 'dentro da tolerância');
  assert.equal(horarioJaPassou('2026-10-28', '14:49', agora), true, 'fora da tolerância');
  assert.equal(horarioJaPassou('2026-10-28', '16:00', agora), false);
  assert.equal(horarioJaPassou('2026-10-29', '', agora), false, 'sem horário vale até 23:59:59');
  assert.equal(horarioJaPassou('2026-10-27', '', agora), true);
  assert.equal(horarioJaPassou('', '10:00', agora), false);
});

test('somarDias e datasRapidas atravessam a virada do mês', () => {
  assert.equal(somarDias('2026-10-31', 1), '2026-11-01');
  assert.equal(somarDias('2026-12-31', 2), '2027-01-02');
  assert.deepEqual(
    datasRapidas('2026-10-28').map((d) => d.value),
    ['2026-10-28', '2026-10-29', '2026-10-30']
  );
});

const valoresBase = {
  fluxo_demanda: 'venda_diaria',
  nome: 'Shopee 28/10',
  canal_venda_id: '7',
  data_entrega: '2026-10-28',
  horario_coleta_especifico: '15:00',
  data_finalizacao_prevista: '',
  observacoes: '',
  modalidade_logistica: 'STANDARD',
  empresa_cliente_nome: 'ACME',
  itens: [{ product_id: '12', id_produto_miolo: '34', quantidade: '3', descricao: 'Caderno', sku: 'CAD-1' }],
};

test('montarPayloadDemanda mapeia o fluxo e não muta a entrada', () => {
  const entrada = structuredClone(valoresBase);
  const payload = montarPayloadDemanda(entrada);

  assert.deepEqual(entrada, valoresBase, 'os valores do formulário seguem intactos');
  assert.equal(payload.tipo_demanda, 'PLATAFORMA');
  assert.equal(payload.classificacao_cliente, 'B2C');
  assert.equal(payload.modalidade_logistica, 'STANDARD');
  assert.equal(payload.is_flex, false);
  assert.equal(payload.fulfillment, false);
  assert.equal(payload.is_draft, false);
  assert.equal(payload.data_entrega, '2026-10-28', 'data não passa por UTC');
  assert.equal(payload.data_finalizacao_prevista, null);
  assert.deepEqual(payload.itens, [
    {
      product_id: 12,
      id_produto_miolo: 34,
      quantidade: 3,
      descricao: 'Caderno',
      sku: 'CAD-1',
      variacao: '',
      miolo_nome: '',
      observacoes: '',
    },
  ]);
  assert.equal('empresa_cliente_nome' in payload, false, 'campos B2B ficam fora quando não é B2B');
});

test('montarPayloadDemanda cobre os quatro fluxos', () => {
  const corporativa = montarPayloadDemanda({ ...valoresBase, fluxo_demanda: 'venda_corporativa' }, { isDraft: true });
  assert.equal(corporativa.tipo_demanda, 'B2B');
  assert.equal(corporativa.classificacao_cliente, 'B2B');
  assert.equal(corporativa.empresa_cliente_nome, 'ACME');
  assert.equal(corporativa.empresa_responsavel_nome, null);
  assert.equal(corporativa.is_draft, true);

  const full = montarPayloadDemanda({ ...valoresBase, fluxo_demanda: 'fulfillment', modalidade_logistica: 'FULFILLMENT' });
  assert.equal(full.tipo_demanda, 'FULFILLMENT');
  assert.equal(full.fulfillment, true);
  assert.equal(full.is_flex, false);

  const interna = montarPayloadDemanda({ ...valoresBase, fluxo_demanda: 'producao_interna' });
  assert.equal(interna.tipo_demanda, 'ESTOQUE_INTERNO');
  assert.equal(interna.classificacao_cliente, 'INTERNO');

  const express = montarPayloadDemanda({ ...valoresBase, modalidade_logistica: 'EXPRESS' });
  assert.equal(express.is_flex, true);
});

test('urlCriacaoDemanda separa B2B do restante', () => {
  assert.equal(urlCriacaoDemanda('venda_diaria'), '/api/v2/demanda_producao/');
  assert.equal(urlCriacaoDemanda('venda_corporativa'), '/api/v2/demanda_producao/empresas');
  assert.equal(urlCriacaoDemanda('fulfillment'), '/api/v2/demanda_producao/');
});
