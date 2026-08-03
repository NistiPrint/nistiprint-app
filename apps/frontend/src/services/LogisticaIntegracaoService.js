import api from './api';

const BASE_URL = 'integracao-canais/logistica';

const LogisticaIntegracaoService = {
  async listarRegras(marketplaceIntegrationId = null) {
    const qs = marketplaceIntegrationId
      ? `?marketplace_integration_id=${marketplaceIntegrationId}`
      : '';
    const response = await api.get(`${BASE_URL}/regras${qs}`);
    return response.data?.data || [];
  },

  async criarRegra(payload) {
    const response = await api.post(`${BASE_URL}/regras`, payload);
    return response.data?.data || null;
  },

  async atualizarRegra(id, payload) {
    const response = await api.put(`${BASE_URL}/regras/${id}`, payload);
    return response.data?.data || null;
  },

  async removerRegra(id) {
    const response = await api.delete(`${BASE_URL}/regras/${id}`);
    return !!response.data?.success;
  },

  /** Modalidades cadastradas do marketplace da integração selecionada. */
  async listarModalidades(marketplaceIntegrationId = null) {
    const qs = marketplaceIntegrationId
      ? `?marketplace_integration_id=${marketplaceIntegrationId}`
      : '';
    const response = await api.get(`${BASE_URL}/modalidades${qs}`);
    return response.data?.data || [];
  },

  /**
   * Canais de envio observados no tráfego real. Não é catálogo cadastrado:
   * é o distinct do que a origem de fato mandou, alimentado pelo ingest.
   */
  async listarCanais(marketplaceIntegrationId = null) {
    const qs = marketplaceIntegrationId
      ? `?marketplace_integration_id=${marketplaceIntegrationId}`
      : '';
    const response = await api.get(`${BASE_URL}/canais${qs}`);
    return response.data?.data || [];
  },

  /** modalidadeId null desassocia o canal. */
  async associarCanal({ moduleId, chave, modalidadeId, campoOrigem = null }) {
    const response = await api.post(`${BASE_URL}/canais/associar`, {
      module_id: moduleId,
      chave,
      modalidade_id: modalidadeId,
      campo_origem: campoOrigem
    });
    return response.data?.data || null;
  }
};

export default LogisticaIntegracaoService;
