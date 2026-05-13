/**
 * Service para gerenciamento de pedidos
 * API: /api/v2/pedidos
 */

import api from './api';
import { formatAppDate } from '@/lib/dateTime';

const BASE_URL = '/pedidos';

/**
 * Busca detalhes completos de um pedido
 * @param {number} pedidoId - ID do pedido
 * @returns {Promise<Object>} Dados completos do pedido
 */
export async function getPedidoDetalhe(pedidoId) {
  const response = await api.get(`${BASE_URL}/${pedidoId}`);
  return response.data?.data || null;
}

/**
 * Busca demandas vinculadas a um pedido
 * @param {number} pedidoId - ID do pedido
 * @returns {Promise<Object>} Dados das demandas vinculadas
 */
export async function getPedidoDemandas(pedidoId) {
  const response = await api.get(`${BASE_URL}/${pedidoId}/demandas`);
  return response.data?.data || { demandas: [] };
}

/**
 * Busca timeline de eventos de um pedido
 * @param {number} pedidoId - ID do pedido
 * @returns {Promise<Array>} Lista de eventos
 */
export async function getPedidoEventos(pedidoId) {
  const response = await api.get(`${BASE_URL}/${pedidoId}/eventos`);
  return response.data?.data || [];
}

/**
 * Busca timeline consolidada de logs do pedido
 * @param {number} pedidoId - ID do pedido
 * @returns {Promise<Object>} Timeline e contexto
 */
export async function getPedidoLogs(pedidoId) {
  const response = await api.get(`${BASE_URL}/${pedidoId}/logs`);
  return response.data?.data || { pedido: null, contexto: null, timeline: [] };
}

/**
 * Reprocessa um pedido
 * @param {number} pedidoId - ID do pedido
 * @returns {Promise<Object>} Resultado da operação
 */
export async function reprocessarPedido(pedidoId) {
  const response = await api.post(`${BASE_URL}/${pedidoId}/reprocessar`);
  return response.data?.data || null;
}

/**
 * Atualiza o status de um pedido
 * @param {number} pedidoId - ID do pedido
 * @param {number} situacaoPedidoId - Novo status ID
 * @param {string} [observacoes] - Observações opcionais
 * @returns {Promise<Object>} Resultado da atualização
 */
export async function updatePedidoStatus(pedidoId, situacaoPedidoId, observacoes = '') {
  const response = await api.put(`${BASE_URL}/${pedidoId}/status`, {
    situacao_pedido_id: situacaoPedidoId,
    observacoes
  });
  return response.data;
}

/**
 * Gera dados formatados para impressão do pedido
 * @param {number} pedidoId - ID do pedido
 * @returns {Promise<Object>} Dados formatados para impressão
 */
export async function imprimirPedido(pedidoId) {
  const response = await api.post(`${BASE_URL}/${pedidoId}/imprimir`);
  return response.data?.data || null;
}

/**
 * Copia número do pedido para clipboard
 * @param {string} numero - Número do pedido
 * @param {string} [tipo] - Tipo (interno ou externo)
 */
export function copiarNumeroPedido(numero, tipo = 'interno') {
  const texto = `[${tipo}] ${numero}`;
  navigator.clipboard.writeText(texto).catch(err => {
    console.error('Erro ao copiar:', err);
  });
}

/**
 * Formata dados do pedido para exibição
 * @param {Object} pedido - Dados do pedido
 * @returns {Object} Dados formatados
 */
export function formatarPedido(pedido) {
  if (!pedido) return null;
  
  return {
    cliente: {
      ...pedido.cliente,
      nome: pedido.cliente?.nome || 'Não informado',
      documento: pedido.cliente?.documento || '-',
    },
    financeiro: {
      ...pedido.financeiro,
      total: pedido.financeiro?.total || 0,
      moeda: pedido.financeiro?.moeda || 'BRL'
    },
    itens: pedido.itens || [],
    statusFormatado: {
      nome: pedido.status?.nome || 'Pendente',
      cor: pedido.status?.cor || '#f59e0b',
      descricao: pedido.status?.descricao || ''
    },
    logistica: {
      ...pedido.logistica,
      canal_venda: {
        ...pedido.logistica?.canal_venda,
        cor: pedido.logistica?.canal_venda?.cor || '#007bff',
        nome: pedido.logistica?.canal_venda?.nome || 'Canal Desconhecido'
      }
    },
    totalFormatado: new Intl.NumberFormat('pt-BR', {
      style: 'currency',
      currency: pedido.financeiro?.moeda || 'BRL'
    }).format(pedido.financeiro?.total || 0),
    dataVendaFormatada: pedido.datas?.venda 
      ? formatAppDate(pedido.datas.venda)
      : '-',
    dataLimiteEnvioFormatada: pedido.datas?.limite_envio
      ? formatAppDate(pedido.datas.limite_envio)
      : null
  };
}

export default {
  getPedidoDetalhe,
  getPedidoDemandas,
  getPedidoEventos,
  getPedidoLogs,
  updatePedidoStatus,
  imprimirPedido,
  reprocessarPedido,
  copiarNumeroPedido,
  formatarPedido
};
