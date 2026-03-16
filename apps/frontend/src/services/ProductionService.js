import api from './api';

const ProductionService = {
  getControleData: async (tipo) => {
    const response = await api.get(`/producao/api/controle?tipo=${tipo}`);
    return response.data;
  },

  registerProduction: async (data) => {
    // data: { product_id, quantity, date, field, origem_tipo, sincrono }
    // default origem_tipo: 3 (CONTROLE_PRODUCAO_LOTE)
    // default sincrono: false (assíncrono via fila), exceto quando explicitado
    const response = await api.post('/producao/registrar-item', {
      ...data,
      origem_tipo: data.origem_tipo || 3,
      sincrono: data.sincrono !== undefined ? data.sincrono : false
    });
    return response.data;
  },

  registerRemoval: async (data) => {
    // data: { product_id, quantity, date, distributions, demanda_id, sincrono }
    const response = await api.post('/demanda_producao/registrar-saida', {
      ...data,
      sincrono: data.sincrono !== undefined ? data.sincrono : false
    });
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

  deleteLog: async (logId, revertStock = true) => {
    const response = await api.post(`/producao/logs/reverter/${logId}`, {
      reverter_estoque: revertStock
    });
    return response.data;
  },

  getPainelSetores: async () => {
    const response = await api.get('/producao/painel-setores');
    return response.data;
  },

  updateItemProgress: async (demandaId, itemId, updates, origem_tipo = 1) => {
    // default origem_tipo: 1 (DASHBOARD_PRODUCAO_INCREMENTAL)
    const response = await api.post(`/demanda_producao/${demandaId}/item/${itemId}/registrar-producao`, {
      producao_incremental: updates,
      origem_tipo
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
