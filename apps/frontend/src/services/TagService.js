import api from './api';

const TagService = {
  getAll: async () => {
    const response = await api.get('/cadastros/tag');
    return response.data.tags;
  },

  getById: async (id) => {
    const response = await api.get(`/cadastros/tag/${id}`);
    return response.data;
  },

  create: async (data) => {
    const response = await api.post('/cadastros/tag', data);
    return response.data;
  },

  update: async (id, data) => {
    const response = await api.put(`/cadastros/tag/${id}`, data);
    return response.data;
  },

  delete: async (id) => {
    const response = await api.delete(`/cadastros/tag/${id}`);
    return response.data;
  }
};

export default TagService;