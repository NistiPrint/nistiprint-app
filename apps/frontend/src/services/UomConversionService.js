import api from './api';

const UomConversionService = {
  getAll: async () => {
    const response = await api.get('/cadastros/uom-conversions');
    return response.data.conversions;
  },

  getById: async (id) => {
    const response = await api.get(`/cadastros/uom-conversions/${id}`);
    return response.data;
  },

  create: async (data) => {
    const response = await api.post('/cadastros/uom-conversions', data);
    return response.data;
  },

  update: async (id, data) => {
    const response = await api.put(`/cadastros/uom-conversions/${id}`, data);
    return response.data;
  },

  delete: async (id) => {
    const response = await api.delete(`/cadastros/uom-conversions/${id}`);
    return response.data;
  }
};

export default UomConversionService;
