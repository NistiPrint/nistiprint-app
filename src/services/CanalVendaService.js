import api from './api';

const CanalVendaService = {
  getAll: async (activeOnly = true) => {
    const params = activeOnly ? '?active_only=true' : '?active_only=false';
    const response = await api.get(`/cadastros/canal-venda${params}`);
    return response.data.canais;
  },

  getById: async (id) => {
    const response = await api.get(`/cadastros/canal-venda/${id}`);
    return response.data;
  },

  create: async (data) => {
    const response = await api.post('/cadastros/canal-venda', data);
    return response.data;
  },

  update: async (id, data) => {
    const response = await api.put(`/cadastros/canal-venda/${id}`, data);
    return response.data;
  },

  delete: async (id) => {
    const response = await api.delete(`/cadastros/canal-venda/${id}`);
    return response.data;
  }
};

export default CanalVendaService;
