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
  async listarModalidades(marketplaceIntegrationId = null, incluirInativas = false) {
    const qs = marketplaceIntegrationId
      ? `?marketplace_integration_id=${marketplaceIntegrationId}`
      : '';
    const response = await api.get(`${BASE_URL}/modalidades${qs}${incluirInativas ? `${qs ? '&' : '?'}incluir_inativas=true` : ''}`);
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
  async associarCanal({ moduleId, chave, modalidadeId, campoOrigem = null, condicoes = {}, associacaoId = null }) {
    const response = await api.post(`${BASE_URL}/canais/associar`, {
      module_id: moduleId,
      chave,
      modalidade_id: modalidadeId,
      campo_origem: campoOrigem,
      condicoes,
      associacao_id: associacaoId
    });
    return response.data?.data || null;
  },
  async salvarModalidade(payload, id = null) {
    const res = id ? await api.put(`${BASE_URL}/modalidades/${id}`, payload) : await api.post(`${BASE_URL}/modalidades`, payload);
    return res.data.data;
  },
  async listarAssociacoes(moduleId = null) {
    const res = await api.get(`${BASE_URL}/associacoes`, { params: moduleId ? { module_id: moduleId } : {} });
    return res.data.data || [];
  },
  async consultarAgenda(integrationId, inicio, fim) {
    const res = await api.get(`${BASE_URL}/agenda`, { params: { marketplace_integration_id: integrationId, inicio, fim } });
    return res.data.data;
  },
  async sincronizar(integrationId) {
    const res = await api.post(`${BASE_URL}/sincronizar`, { marketplace_integration_id: Number(integrationId) });
    return res.data.data;
  },
  async salvarExcecao(regraId, dia, payload) {
    const res = payload === null ? await api.delete(`${BASE_URL}/regras/${regraId}/excecoes/${dia}`)
      : await api.put(`${BASE_URL}/regras/${regraId}/excecoes/${dia}`, payload);
    return res.data.data;
  }
};

export default LogisticaIntegracaoService;
