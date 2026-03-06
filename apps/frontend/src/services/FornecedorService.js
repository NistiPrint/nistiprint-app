// frontend/src/services/FornecedorService.js
import api from './api'; // Assumindo que você tem um arquivo `api.js` para a instância do axios

const FornecedorService = {
  getAll: async () => {
    const response = await api.get('/fornecedores');
    return response.data;
  },

  getById: async (id) => {
    const response = await api.get(`/fornecedores/${id}`);
    return response.data;
  },

  create: async (data) => {
    const response = await api.post('/fornecedores', data);
    return response.data;
  },

  update: async (id, data) => {
    const response = await api.put(`/fornecedores/${id}`, data);
    return response.data;
  },

  delete: async (id) => {
    const response = await api.delete(`/fornecedores/${id}`);
    return response.data;
  },
};

export default FornecedorService;