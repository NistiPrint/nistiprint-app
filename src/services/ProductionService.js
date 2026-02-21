import api from './api';

const ProductionService = {
  getControleData: async (tipo) => {
    const response = await api.get(`/producao/api/controle?tipo=${tipo}`);
    return response.data;
  },

  registerProduction: async (data) => {
    // data: { product_id, quantity, date }
    const response = await api.post('/producao/registrar-item', data);
    return response.data;
  },

  registerRemoval: async (data) => {
    // data: { product_id, quantity, date, distributions }
    const response = await api.post('/demanda_producao/registrar-saida', data);
    return response.data;
  },

  getPendingItems: async (mioloId) => {
    const response = await api.get(`/demanda_producao/miolo/${mioloId}/itens-pendentes`);
    return response.data;
  },

  getLogs: async (productId, date) => {
    const response = await api.get(`/producao/logs/${productId}/${date}`);
    return response.data;
  },

  deleteLog: async (logId) => {
    const response = await api.post(`/producao/logs/delete/${logId}`);
    return response.data;
  },

  getPainelSetores: async () => {
    const response = await api.get('/producao/painel-setores');
    return response.data;
  },

  updateItemProgress: async (demandaId, itemId, updates) => {
    const response = await api.post(`/demanda_producao/${demandaId}/item/${itemId}/registrar-producao`, {
      producao_incremental: updates
    });
    return response.data;
  },

  registerProductionBatch: async (demandaId, updates) => {
    // updates: [{ item_id, producao_incremental: { field: delta } }]
    const response = await api.post(`/demanda_producao/${demandaId}/itens/registrar-producao-lote`, {
      updates
    });
    return response.data;
  },

  getDailySummary: async () => {
    const response = await api.get('/demanda_producao/daily-summary');
    return response.data;
  },

  getMioloDemandSummary: async () => {
    const response = await api.get('/demanda_producao/miolo-demand-summary');
    return response.data;
  },

  getCapaDemandInfo: async () => {
    const response = await api.get('/demanda_producao/capa-demand-info');
    return response.data;
  },

  getConsolidadoProducao: async (params = {}) => {
    // params: { trilha, agrupado }
    const response = await api.get('/demanda_producao/consolidado', { params });
    return response.data;
  },

  registrarRetiradaExpedicao: async (demandaId, itemId, quantidade) => {
    const response = await api.post(`/demanda_producao/${demandaId}/item/${itemId}/retirar-expedicao`, {
      quantidade
    });
    return response.data;
  }
};

export default ProductionService;
