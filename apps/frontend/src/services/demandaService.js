/**
 * Service para gerenciamento de demandas de produção
 * API: /api/v2/demandas
 */

import api from './api';

const BASE_URL = '/demandas';

/**
 * Busca pedidos vinculados a uma demanda
 * @param {string} demandaId - ID da demanda
 * @returns {Promise<Object>} Dados dos pedidos vinculados
 */
export async function getDemandaPedidos(demandaId) {
  const response = await api.get(`${BASE_URL}/${demandaId}/pedidos`);
  return response.data?.data || { pedidos: [] };
}

/**
 * Busca timeline unificada de uma demanda
 * @param {string} demandaId - ID da demanda
 * @returns {Promise<Object>} Timeline de eventos
 */
export async function getDemandaTimeline(demandaId) {
  const response = await api.get(`${BASE_URL}/${demandaId}/timeline`);
  return response.data?.data || { timeline: [] };
}

export default {
  getDemandaPedidos,
  getDemandaTimeline
};
