import api from './api';

const BlingAccountService = {
  getAll: async () => {
    const response = await api.get('/produtos/bling_accounts');
    return response.data;
  },
  
  search: async (query) => {
    const response = await api.get('/cadastros/conta-bling/search', { params: { q: query } });
    return response.data;
  }
};

export default BlingAccountService;