import api from './api';

const ProductService = {
  getAll: async (params) => {
    // Include variations in the product list
    const queryParams = { ...params, include_variants: true };
    const response = await api.get('/produtos', { params: queryParams });
    return response.data;
  },

  getById: async (id) => {
    const response = await api.get(`/produtos/${id}`);
    return response.data;
  },

  create: async (data) => {
    const response = await api.post('/produtos', data);
    return response.data;
  },

  update: async (id, data) => {
    const response = await api.put(`/produtos/${id}`, data);
    return response.data;
  },

  delete: async (id) => {
    const response = await api.delete(`/produtos/${id}`);
    return response.data;
  },

  // BOM Operations
  getBOM: async (productId) => {
    const response = await api.get(`/produtos/${productId}/bom`);
    return response.data;
  },

  getCategoryRulesByProductId: async (productId) => {
    const response = await api.get(`/produtos/${productId}/category_rules`);
    return response.data;
  },

  addBOMComponent: async (productId, componentId, quantity) => {
    const response = await api.post(`/produtos/${productId}/bom`, {
      componente_id: componentId,
      quantidade: quantity
    });
    return response.data;
  },

  updateBOMComponent: async (productId, componentId, quantity) => {
    const response = await api.put(`/produtos/${productId}/bom`, {
      component_id: componentId,
      quantity: quantity
    });
    return response.data;
  },

  removeBOMComponent: async (productId, componentId) => {
    const response = await api.delete(`/produtos/${productId}/bom`, {
      params: { componente_id: componentId }
    });
    return response.data;
  },

  // Bling Links Operations
  addBlingLink: async (productId, data) => {
    const response = await api.post(`/produtos/${productId}/bling_links`, data);
    return response.data;
  },

  removeBlingLink: async (productId, blingProductId, blingAccountId) => {
    const response = await api.delete(`/produtos/${productId}/bling_links/${blingProductId}/${blingAccountId}`);
    return response.data;
  },

  searchBlingProducts: async (accountId, query) => {
     const response = await api.get(`/produtos/bling_products/search`, {
         params: { account_id: accountId, q: query }
     });
     return response.data;
  },

  getBlingProduct: async (blingProductId, accountId) => {
      const response = await api.get(`/produtos/bling_products/${blingProductId}`, {
          params: { account_id: accountId }
      });
      return response.data;
  },
  
  searchBlingProductsBySkus: async (accountId, skus) => {
      const response = await api.get(`/produtos/bling_products/search_by_skus`, {
          params: { account_id: accountId, skus: skus }
      });
      return response.data;
  },

  // Autocomplete Search
  search: async (query, params = {}) => {
      const response = await api.get('/produtos/search', { params: { q: query, ...params } });
      return response.data;
  },

  // Bulk Operations
  bulkUpdate: async (productIds, updates) => {
    const response = await api.post('/produtos/bulk_update', { product_ids: productIds, updates });
    return response.data;
  },

  // Artwork Operations
  uploadArtwork: async (productId, formData) => {
    const response = await api.post(`/produtos/${productId}/artwork`, formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    });
    return response.data;
  },

  getArtworks: async (productId) => {
    const response = await api.get(`/produtos/${productId}/artworks`);
    return response.data;
  },

  deleteArtwork: async (artworkId) => {
    const response = await api.delete(`/produtos/artwork/${artworkId}`);
    return response.data;
  },

  // Variations Operations
  createProductWithVariations: async (productId, variationsConfig, variationsData) => {
    const response = await api.post(`/produtos/${productId}/variations`, {
      variations_config: variationsConfig,
      variations_data: variationsData
    });
    return response.data;
  },

  // Clone Product
  cloneProduct: async (productId, newSku, newName = null) => {
    const response = await api.post(`/produtos/${productId}/clone`, {
      new_sku: newSku,
      new_name: newName
    });
    return response.data;
  },

  // Get product variations
  getProductVariations: async (productId) => {
    const response = await api.get(`/produtos/${productId}`);
    return response.data;
  }
};

export default ProductService;
