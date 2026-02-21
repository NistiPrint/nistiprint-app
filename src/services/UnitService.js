import api from './api';

const UnitService = {
  getAll: async () => {
    const response = await api.get('/cadastros/unidade-medida');
    return response.data.unidades;
  },

  getById: async (id) => {
    const response = await api.get(`/cadastros/unidade-medida/${id}`);
    return response.data;
  },

  create: async (data) => {
    const response = await api.post('/cadastros/unidade-medida', data);
    return response.data;
  },

  update: async (id, data) => {
    const response = await api.put(`/cadastros/unidade-medida/${id}`, data);
    return response.data;
  },

  delete: async (id) => {
    const response = await api.delete(`/cadastros/unidade-medida/${id}`);
    return response.data;
  }
};

export default UnitService;