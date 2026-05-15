import api from './api';

const BASE_URL = 'integracao-canais/logistica/regras';

const LogisticaIntegracaoService = {
  async listarRegras(marketplaceIntegrationId = null) {
    const qs = marketplaceIntegrationId
      ? `?marketplace_integration_id=${marketplaceIntegrationId}`
      : '';
    const response = await api.get(`${BASE_URL}${qs}`);
    return response.data?.data || [];
  },

  async criarRegra(payload) {
    const response = await api.post(BASE_URL, payload);
    return response.data?.data || null;
  },

  async atualizarRegra(id, payload) {
    const response = await api.put(`${BASE_URL}/${id}`, payload);
    return response.data?.data || null;
  },

  async removerRegra(id) {
    const response = await api.delete(`${BASE_URL}/${id}`);
    return !!response.data?.success;
  }
};

export default LogisticaIntegracaoService;
