import api from './api';

const DepositoService = {
  getAll: async () => {
    const response = await api.get('/cadastros/deposito');
    return response.data.depositos;
  },

  getById: async (id) => {
    const response = await api.get(`/cadastros/deposito/${id}`);
    return response.data;
  },

  create: async (data) => {
    const response = await api.post('/cadastros/deposito', data);
    return response.data;
  },

  update: async (id, data) => {
    const response = await api.put(`/cadastros/deposito/${id}`, data);
    return response.data;
  },

  delete: async (id) => {
    const response = await api.delete(`/cadastros/deposito/${id}`);
    return response.data;
  }
};

export default DepositoService;
