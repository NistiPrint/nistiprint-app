import api from './api';

const CategoryService = {
  getAll: async () => {
    const response = await api.get('/cadastros/categoria');
    return response.data.categorias;
  },

  getById: async (id) => {
    const response = await api.get(`/cadastros/categoria/${id}`);
    return response.data;
  },

  create: async (data) => {
    const response = await api.post('/cadastros/categoria', data);
    return response.data;
  },

  update: async (id, data) => {
    const response = await api.put(`/cadastros/categoria/${id}`, data);
    return response.data;
  },

  delete: async (id) => {
    const response = await api.delete(`/cadastros/categoria/${id}`);
    return response.data;
  },

  getRules: async (categoryId) => {
    const response = await api.get(`/cadastros/categoria/${categoryId}/regras`);
    return response.data.regras;
  },

  addRule: async (categoryId, data) => {
    const response = await api.post(`/cadastros/categoria/${categoryId}/regras`, data);
    return response.data;
  },

  deleteRule: async (ruleId) => {
    const response = await api.delete(`/cadastros/categoria/regras/${ruleId}`);
    return response.data;
  }
};

export default CategoryService;
