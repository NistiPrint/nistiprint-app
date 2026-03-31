/**
 * Service para gerenciamento de vínculos de integração
 * API: /api/integracao-canais
 */

import api from './api';

const BASE_URL = 'integracao-canais';

/**
 * Lista todas as configurações de vínculos
 * @param {Object} params - Parâmetros de filtro
 * @param {string} params.plataforma - Filtrar por plataforma (shopee, amazon, etc.)
 * @param {number} params.canal_venda_id - Filtrar por canal específico
 * @param {boolean} params.include_inactive - Incluir configurações inativas
 * @returns {Promise<Array>} Lista de configurações
 */
export async function listarConfiguracoes(params = {}) {
  const queryParams = new URLSearchParams();
  
  if (params.plataforma) queryParams.append('plataforma', params.plataforma);
  if (params.canal_venda_id) queryParams.append('canal_venda_id', params.canal_venda_id);
  if (params.include_inactive) queryParams.append('include_inactive', params.include_inactive);
  
  const response = await api.get(`${BASE_URL}/configuracoes?${queryParams.toString()}`);
  return response.data?.data || [];
}

/**
 * Cria novo vínculo entre canal e loja Bling
 * @param {Object} data - Dados do vínculo
 * @param {number} data.canal_venda_id - ID do canal de venda
 * @param {number} data.bling_loja_id - ID da loja no Bling
 * @param {string} data.plataforma_nome - Nome da plataforma (shopee, amazon, etc.)
 * @param {number} [data.bling_integration_id] - ID da instância de integração Bling (opcional)
 * @param {number} [data.marketplace_integration_id] - ID da instância de integração Marketplace (opcional)
 * @param {boolean} [data.is_primary] - Se é o vínculo primário
 * @param {Object} [data.config_json] - Configurações adicionais
 * @returns {Promise<Object>} Configuração criada
 */
export async function criarVinculo(data) {
  const response = await api.post(`${BASE_URL}/configuracoes`, data);
  return response.data?.data || null;
}

/**
 * Atualiza vínculo existente
 * @param {string} configId - ID da configuração
 * @param {Object} updates - Campos a atualizar
 * @returns {Promise<Object>} Configuração atualizada
 */
export async function atualizarVinculo(configId, updates) {
  const response = await api.put(`${BASE_URL}/configuracoes/${configId}`, updates);
  return response.data?.data || null;
}

/**
 * Remove vínculo (soft delete)
 * @param {string} configId - ID da configuração
 * @returns {Promise<boolean>} True se removido com sucesso
 */
export async function removerVinculo(configId) {
  const response = await api.delete(`${BASE_URL}/configuracoes/${configId}`);
  return response.data?.success || false;
}

/**
 * Resolve qual canal usar baseado no bling_loja_id
 * @param {number} blingLojaId - ID da loja no Bling
 * @param {string} [plataforma] - Nome da plataforma (opcional, para fallback)
 * @returns {Promise<Object>} Dados do canal resolvido
 */
export async function resolverCanal(blingLojaId, plataforma = null) {
  const queryParams = new URLSearchParams({ bling_loja_id: blingLojaId.toString() });
  if (plataforma) queryParams.append('plataforma', plataforma);
  
  const response = await api.get(`${BASE_URL}/resolver/canal?${queryParams.toString()}`);
  return response.data?.data || null;
}

/**
 * Resolve qual bling_loja_id usar baseado no canal
 * @param {number} canalVendaId - ID do canal de venda
 * @param {string} [plataforma] - Nome da plataforma (opcional)
 * @returns {Promise<Object>} Dados da loja Bling resolvida
 */
export async function resolverBlingLoja(canalVendaId, plataforma = null) {
  const queryParams = new URLSearchParams({ canal_venda_id: canalVendaId.toString() });
  if (plataforma) queryParams.append('plataforma', plataforma);
  
  const response = await api.get(`${BASE_URL}/resolver/bling-loja?${queryParams.toString()}`);
  return response.data?.data || null;
}

/**
 * Lista todas as plataformas com suas configurações
 * @returns {Promise<Array>} Lista de plataformas com vínculos
 */
export async function listarPlataformas() {
  const response = await api.get(`${BASE_URL}/plataformas`);
  return response.data?.data || [];
}

/**
 * Busca canais de venda disponíveis
 * @returns {Promise<Array>} Lista de canais
 */
export async function listarCanais() {
  // Rota correta: /api/v2/integracao-canais/canais (endpoint dedicado)
  const response = await api.get('integracao-canais/canais');
  // O endpoint retorna { success: true, data: [...], contas_bling: [...] }
  return response.data?.data || [];
}

/**
 * Busca integrações instaladas
 * @returns {Promise<Array>} Lista de integrações
 */
export async function listarIntegracoes() {
  // Rota correta: /api/v2/integracao-canais/integracoes (endpoint dedicado)
  const response = await api.get('integracao-canais/integracoes');
  // O endpoint retorna { success: true, data: [...] }
  return response.data?.data || [];
}

/**
 * Renova o token de uma integração instalada
 * @param {string} instanceId - ID da instância de integração
 * @returns {Promise<Object>} Resultado da renovação
 */
export async function renewToken(instanceId) {
  const response = await api.post(`/marketplace/installed/${instanceId}/renew`);
  return response.data;
}

/**
 * Sincroniza tokens do Bling do Firestore para o Supabase
 * @returns {Promise<Object>} Resultado da sincronização
 */
export async function syncFirestore() {
  const response = await api.post('/integracoes/sync-firestore');
  return response.data;
}

/**
 * Obtém análise de status dos vínculos
 * @returns {Promise<Object>} Análise com completos, incompletos, orfaos, placeholders
 */
export async function getAnaliseStatus() {
  const response = await api.get(`${BASE_URL}/analise-status`);
  return response.data?.data || null;
}

export default {
  listarConfiguracoes,
  criarVinculo,
  atualizarVinculo,
  removerVinculo,
  resolverCanal,
  resolverBlingLoja,
  listarPlataformas,
  listarCanais,
  listarIntegracoes,
  renewToken,
  syncFirestore,
  getAnaliseStatus,
};
