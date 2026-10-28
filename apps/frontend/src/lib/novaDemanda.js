// Regras de preenchimento do formulario de nova demanda.
//
// Tudo aqui e funcao pura: e a unica camada que o repositorio consegue testar
// (`npm run test:unit`), e e tambem onde moram as decisoes que o formulario
// antigo espalhava em useEffects.
import { dataOperacionalHoje } from './dataOperacional.js';
import { getDemandFlowConfig } from './demandaFlow.js';

export const MODALIDADES = ['STANDARD', 'EXPRESS', 'FULFILLMENT', 'RETIRADA'];

const DATA_ISO_RE = /^\d{4}-\d{2}-\d{2}$/;
const TOLERANCIA_PASSADO_MINUTOS = 10;

const doisDigitos = (valor) => String(valor).padStart(2, '0');

function regrasDoCanal(canal) {
  const regras = canal?.regras_logisticas;
  if (!regras || typeof regras !== 'object' || Array.isArray(regras)) return {};
  return regras;
}

/** 'HH:MM:SS' ou 'HH:MM' -> 'HH:MM'. Qualquer outra coisa -> ''. */
export function normalizarHora(valor) {
  if (!valor) return '';
  const partes = String(valor).trim().split(':');
  if (partes.length < 2) return '';
  const hora = Number(partes[0]);
  const minuto = Number(partes[1]);
  if (!Number.isInteger(hora) || !Number.isInteger(minuto)) return '';
  if (hora < 0 || hora > 23 || minuto < 0 || minuto > 59) return '';
  return `${doisDigitos(hora)}:${doisDigitos(minuto)}`;
}

/**
 * Modalidades que fazem sentido oferecer para um canal.
 * STANDARD sempre existe; EXPRESS e FULFILLMENT vem das flags do canal ou de
 * uma regra logistica cadastrada; RETIRADA so aparece se houver regra.
 */
export function modalidadesDisponiveis(canal, fluxoId) {
  const regras = regrasDoCanal(canal);
  const temRegra = (modalidade) => Array.isArray(regras[modalidade]) && regras[modalidade].length > 0;

  const disponiveis = new Set(['STANDARD', getDemandFlowConfig(fluxoId).modalidade_logistica]);
  if (canal?.flex || temRegra('EXPRESS')) disponiveis.add('EXPRESS');
  if (canal?.fulfillment || temRegra('FULFILLMENT')) disponiveis.add('FULFILLMENT');
  if (temRegra('RETIRADA')) disponiveis.add('RETIRADA');

  return MODALIDADES.filter((modalidade) => disponiveis.has(modalidade));
}

/**
 * Janelas de coleta do canal para a modalidade, na ordem de prioridade que a
 * API ja devolve. Sem regras cadastradas, usa o `horario_coleta` do canal.
 */
export function janelasColeta(canal, modalidade) {
  const regras = regrasDoCanal(canal)[modalidade];

  if (Array.isArray(regras) && regras.length > 0) {
    const janelas = regras
      .map((regra) => ({
        horario: normalizarHora(regra?.horario_limite),
        tipo: regra?.tipo || regra?.tipo_envio || null,
        ponto: regra?.ponto_coleta_nome || null,
      }))
      .filter((janela) => janela.horario);

    if (janelas.length > 0) return janelas;
  }

  const padrao = normalizarHora(canal?.horario_coleta);
  return padrao ? [{ horario: padrao, tipo: null, ponto: null }] : [];
}

export function sugerirHorarioColeta(canal, modalidade) {
  return janelasColeta(canal, modalidade)[0]?.horario || '';
}

/**
 * Finalizacao prevista = entrega - antecedencia. Devolve o formato que o
 * `<input type="datetime-local">` espera, montado por componentes para nao
 * passar por UTC.
 */
export function calcularFinalizacaoPrevista(dataEntrega, horarioColeta, { antecedenciaMinutos = 60 } = {}) {
  if (!DATA_ISO_RE.test(String(dataEntrega || ''))) return '';

  const hora = normalizarHora(horarioColeta);
  if (!hora) return '';

  const [ano, mes, dia] = dataEntrega.split('-').map(Number);
  const [horas, minutos] = hora.split(':').map(Number);

  const quando = new Date(ano, mes - 1, dia, horas, minutos);
  if (Number.isNaN(quando.getTime())) return '';
  quando.setMinutes(quando.getMinutes() - antecedenciaMinutos);

  return [
    `${quando.getFullYear()}-${doisDigitos(quando.getMonth() + 1)}-${doisDigitos(quando.getDate())}`,
    `${doisDigitos(quando.getHours())}:${doisDigitos(quando.getMinutes())}`,
  ].join('T');
}

/**
 * Espelha a recusa do backend: data + horario de coleta nao podem estar no
 * passado (com 10 minutos de tolerancia). Sem horario, o backend assume
 * 23:59:59 do dia da entrega.
 */
export function horarioJaPassou(dataEntrega, horarioColeta, agora = new Date()) {
  if (!DATA_ISO_RE.test(String(dataEntrega || ''))) return false;

  const [ano, mes, dia] = dataEntrega.split('-').map(Number);
  const hora = normalizarHora(horarioColeta);
  const limite = hora
    ? new Date(ano, mes - 1, dia, Number(hora.slice(0, 2)), Number(hora.slice(3, 5)), 0)
    : new Date(ano, mes - 1, dia, 23, 59, 59);

  return limite.getTime() < agora.getTime() - TOLERANCIA_PASSADO_MINUTOS * 60000;
}

export function somarDias(dataIso, dias) {
  if (!DATA_ISO_RE.test(String(dataIso || ''))) return '';
  const [ano, mes, dia] = dataIso.split('-').map(Number);
  const quando = new Date(ano, mes - 1, dia + dias);
  return `${quando.getFullYear()}-${doisDigitos(quando.getMonth() + 1)}-${doisDigitos(quando.getDate())}`;
}

export function datasRapidas(hoje = dataOperacionalHoje()) {
  return [
    { label: 'Hoje', value: hoje },
    { label: 'Amanhã', value: somarDias(hoje, 1) },
    { label: '+2 dias', value: somarDias(hoje, 2) },
  ];
}

const CAMPOS_EMPRESA = [
  'empresa_cliente_nome',
  'empresa_wire_o_cor',
  'empresa_elastico_cor',
  'empresa_interacao_status',
  'empresa_pedido_plataforma_numero',
  'empresa_responsavel_id',
  'empresa_responsavel_nome',
];

const paraInteiro = (valor) => {
  const numero = parseInt(valor, 10);
  return Number.isNaN(numero) ? null : numero;
};

/** Monta o corpo do POST/PUT sem tocar no objeto recebido do formulario. */
export function montarPayloadDemanda(values, { isDraft = false } = {}) {
  const fluxo = getDemandFlowConfig(values.fluxo_demanda);
  const modalidade = values.modalidade_logistica || fluxo.modalidade_logistica;

  const payload = {
    nome: values.nome,
    canal_venda_id: values.canal_venda_id,
    data_entrega: values.data_entrega,
    horario_coleta_especifico: values.horario_coleta_especifico || null,
    data_finalizacao_prevista: values.data_finalizacao_prevista
      ? new Date(values.data_finalizacao_prevista).toISOString()
      : null,
    observacoes: values.observacoes || null,
    is_draft: isDraft,
    tipo_demanda: fluxo.tipo_demanda,
    classificacao_cliente: fluxo.classificacao_cliente,
    modalidade_logistica: modalidade,
    // Campos antigos que partes da operacao ainda leem.
    is_flex: modalidade === 'EXPRESS',
    fulfillment: modalidade === 'FULFILLMENT',
    itens: (values.itens || []).map((item) => ({
      product_id: item.product_id ? paraInteiro(item.product_id) : null,
      id_produto_miolo: item.id_produto_miolo ? paraInteiro(item.id_produto_miolo) : null,
      quantidade: Number(item.quantidade) || 1,
      descricao: item.descricao || '',
      sku: item.sku || '',
      variacao: item.variacao || '',
      miolo_nome: item.miolo_nome || '',
      observacoes: item.observacoes || '',
    })),
  };

  if (fluxo.tipo_demanda === 'B2B') {
    CAMPOS_EMPRESA.forEach((campo) => {
      payload[campo] = values[campo] || null;
    });
  }

  return payload;
}

/** Endpoint de criacao conforme o fluxo escolhido. */
export function urlCriacaoDemanda(fluxoId) {
  return getDemandFlowConfig(fluxoId).tipo_demanda === 'B2B'
    ? '/api/v2/demanda_producao/empresas'
    : '/api/v2/demanda_producao/';
}
