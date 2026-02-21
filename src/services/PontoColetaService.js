import api from './api';

const PontoColetaService = {
  getAll: async (activeOnly = false) => {
    const response = await api.get(`/cadastros/ponto-coleta?active_only=${activeOnly}`);
    return response.data.pontos;
  },

  getById: async (id) => {
    const response = await api.get(`/cadastros/ponto-coleta/${id}`);
    return response.data.ponto;
  },

  create: async (data) => {
    const response = await api.post('/cadastros/ponto-coleta', data);
    return response.data.ponto;
  },

  update: async (id, data) => {
    const response = await api.put(`/cadastros/ponto-coleta/${id}`, data);
    return response.data.ponto;
  },

  delete: async (id) => {
    const response = await api.delete(`/cadastros/ponto-coleta/${id}`);
    return response.data;
  }
};

export default PontoColetaService;
