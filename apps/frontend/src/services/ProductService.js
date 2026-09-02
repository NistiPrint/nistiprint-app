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

  copyBOMFromParent: async (productId) => {
    const response = await api.post(`/produtos/${productId}/bom/copy-from-parent`);
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

  // Local artwork tree (files remain on the local Windows agent)
  getRecursiveArtworks: async (productId) => {
    const response = await api.get(`/produtos/${productId}/artes-recursivas`);
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

  getVariationAxes: async (parentId = null) => {
    const response = await api.get(parentId ? `/produtos/${parentId}/variation-axes` : '/produtos/variation-axes');
    return response.data.eixos || [];
  },

  // Fila de revisão de eixos. O backfill gravou só o MIOLO (o segmento do SKU
  // que corresponde a um produto cadastrado); estampa e acabamento ficaram para
  // decisão humana, porque 17 dos 44 acabados nem seguem a gramática de três
  // segmentos e adivinhar ali seria gravar erro no banco.
  getVariationReviewQueue: async () => {
    const response = await api.get('/produtos/variacoes/pendentes');
    return response.data;
  },

  setVariationValues: async (productId, valores) => {
    const response = await api.put(`/produtos/${productId}/variacao-valores`, { valores });
    return response.data;
  },

  // Uma estampa nova da coleção é exatamente uma opção de eixo.
  createAxisOption: async (axisCode, codigo, nome) => {
    const response = await api.post(`/produtos/eixos/${encodeURIComponent(axisCode)}/opcoes`, { codigo, nome });
    return response.data.opcao;
  },

  // Códigos que aparecem em pedido e não chegam a produto interno nenhum.
  getPendingCodes: async () => {
    const response = await api.get('/produtos/kits/pendentes');
    return response.data.pendentes || [];
  },

  configureVariationAxes: async (parentId, axisCodes) => {
    const response = await api.put(`/produtos/${parentId}/variation-axes`, { eixos: axisCodes });
    return response.data.eixos || [];
  },

  getReadiness: async ({ tagId, estagio } = {}) => {
    const params = {};
    if (tagId) params.tag_id = tagId;
    if (estagio && estagio !== 'all') params.estagio = estagio;
    const response = await api.get('/produtos/readiness', { params });
    return response.data.produtos || [];
  },

  getAds: async (orphansOnly = false) => {
    const response = await api.get('/produtos/anuncios', { params: { orfaos: orphansOnly ? 'true' : 'false' } });
    return response.data.anuncios || [];
  },

  linkAd: async (adId, productId) => {
    const response = await api.put(`/produtos/anuncios/${adId}/vincular`, { produto_id: productId });
    return response.data.anuncio;
  },

  getAliases: async (productId = null) => {
    const response = await api.get('/produtos/aliases', { params: productId ? { produto_id: productId } : {} });
    return response.data.aliases || [];
  },

  addAlias: async (data) => {
    const response = await api.post('/produtos/aliases', data);
    return response.data.alias;
  },

  getPrices: async (productId) => {
    const response = await api.get(`/produtos/${productId}/precos`);
    return response.data.precos || [];
  },

  addPrice: async (productId, data) => {
    const response = await api.post(`/produtos/${productId}/precos`, data);
    return response.data.preco;
  },

  publish: async (productId) => {
    const response = await api.post(`/produtos/${productId}/publicar`);
    return response.data.produto;
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
