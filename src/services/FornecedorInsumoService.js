// frontend/src/services/FornecedorInsumoService.js
import api from './api'; // Assumindo que você tem um arquivo `api.js` para a instância do axios

const FornecedorInsumoService = {
  getLinksForProduct: async (productId) => {
    // Este endpoint precisará ser criado no backend
    const response = await api.get(`/produtos/${productId}/fornecedores`);
    return response.data;
  },

  createLink: async (linkData) => {
    // Este endpoint precisará ser criado no backend
    const response = await api.post('/fornecedor-insumos', linkData);
    return response.data;
  },

  updateLink: async (linkId, linkData) => {
    // Este endpoint precisará ser criado no backend
    const response = await api.put(`/fornecedor-insumos/${linkId}`, linkData);
    return response.data;
  },

  deleteLink: async (linkId) => {
    // Este endpoint precisará ser criado no backend
    const response = await api.delete(`/fornecedor-insumos/${linkId}`);
    return response.data;
  },
};

export default FornecedorInsumoService;
