import api from './api';

const PlataformaService = {
  getAll: async () => {
    const response = await api.get('/cadastros/plataforma');
    return response.data.plataformas;
  },

  getById: async (id) => {
    const response = await api.get(`/cadastros/plataforma/${id}`);
    return response.data;
  },

  create: async (data) => {
    const response = await api.post('/cadastros/plataforma', data);
    return response.data;
  },

  update: async (id, data) => {
    const response = await api.put(`/cadastros/plataforma/${id}`, data);
    return response.data;
  },

  delete: async (id) => {
    const response = await api.delete(`/cadastros/plataforma/${id}`);
    return response.data;
  }
};

export default PlataformaService;
