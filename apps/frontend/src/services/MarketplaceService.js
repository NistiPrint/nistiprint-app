import api from './api';

// Base endpoint for marketplace operations
const BASE_URL = '/marketplace';

/**
 * Get all available integration modules in the marketplace
 */
export const getAvailableModules = async (filters = {}) => {
  try {
    const params = new URLSearchParams(filters).toString();
    const response = await api.get(`${BASE_URL}/modules${params ? `?${params}` : ''}`);
    return response.data.modules;
  } catch (error) {
    throw error.response?.data || error;
  }
};

/**
 * Get details of a specific module by ID
 */
export const getModuleDetails = async (moduleId) => {
  try {
    const response = await api.get(`${BASE_URL}/modules/${moduleId}`);
    return response.data.module;
  } catch (error) {
    throw error.response?.data || error;
  }
};

/**
 * Install a new module instance
 */
export const installModule = async (installData) => {
  try {
    const response = await api.post(`${BASE_URL}/install`, installData);
    return response.data;
  } catch (error) {
    throw error.response?.data || error;
  }
};

/**
 * Initialize OAuth flow
 */
export const initAuth = async (moduleId, config, instanceId, redirectUri = null) => {
  try {
    const response = await api.post(`${BASE_URL}/auth/init/${moduleId}`, {
      config,
      instance_id: instanceId,
      redirect_uri: redirectUri
    });
    return response.data;
  } catch (error) {
    throw error.response?.data || error;
  }
};

/**
 * Exchange auth code manually
 */
export const exchangeCode = async (moduleId, code, instanceId, shopId = null) => {
  try {
    const response = await api.post(`${BASE_URL}/auth/exchange/${moduleId}`, {
      code,
      instance_id: instanceId,
      shop_id: shopId
    });
    return response.data;
  } catch (error) {
    throw error.response?.data || error;
  }
};

/**
 * Get all installed integrations
 */
export const getInstalledIntegrations = async () => {
  try {
    const response = await api.get(`${BASE_URL}/installed`);
    return { success: true, ...response.data };
  } catch (error) {
    // Return structured error for consistent handling in UI
    return { success: false, error: error.response?.data?.error || error.message };
  }
};

/**
 * Get one installed integration by ID
 */
export const getInstallation = async (instanceId) => {
  try {
    const response = await api.get(`${BASE_URL}/installed/${instanceId}`);
    return response.data.installation;
  } catch (error) {
    throw error.response?.data || error;
  }
};

/**
 * Get details of a specific order from a marketplace integration
 */
export const getMarketplaceOrderDetail = async (instanceId, orderId) => {
  try {
    const response = await api.post(`${BASE_URL}/orders/detail`, {
      instance_id: instanceId,
      order_sn_list: orderId
    });
    return response.data;
  } catch (error) {
    return { success: false, error: error.response?.data?.message || error.message };
  }
};

/**
 * Renew token for an installation
 */
export const renewToken = async (instanceId) => {
  try {
    const response = await api.post(`${BASE_URL}/installed/${instanceId}/renew`);
    return response.data;
  } catch (error) {
    throw error.response?.data || error;
  }
};

/**
 * Test an installation
 */
export const testIntegration = async (instanceId) => {
  try {
    const response = await api.post(`${BASE_URL}/installed/${instanceId}/test`);
    return response.data;
  } catch (error) {
    throw error.response?.data || error;
  }
};

/**
 * Uninstall an integration
 */
export const uninstallModule = async (instanceId) => {
  try {
    const response = await api.delete(`${BASE_URL}/installed/${instanceId}`);
    return response.data;
  } catch (error) {
    throw error.response?.data || error;
  }
};

/**
 * Import tokens from Firebase to the encrypted vault in Supabase
 */
export const importTokensFromFirebase = async () => {
  try {
    const response = await api.post('/integracoes/sync-firestore', { mode: 'import' });
    return response.data;
  } catch (error) {
    throw error.response?.data || error;
  }
};

/**
 * Publish tokens from the encrypted vault back to Firebase on demand
 */
export const publishTokensToFirebase = async () => {
  try {
    const response = await api.post('/integracoes/sync-firestore', { mode: 'publish' });
    return response.data;
  } catch (error) {
    throw error.response?.data || error;
  }
};

export const syncFirestore = async (mode = 'import') => {
  try {
    const response = await api.post('/integracoes/sync-firestore', { mode });
    return response.data;
  } catch (error) {
    throw error.response?.data || error;
  }
};

/**
 * Get available Bling stores
 */
export const getBlingStores = async () => {
  try {
    const response = await api.get('/integracoes/bling/lojas');
    return response.data;
  } catch (error) {
    throw error.response?.data || error;
  }
};

/**
 * Create a link between channel and Bling store
 */
export const createChannelLink = async (linkData) => {
  try {
    const response = await api.post('/integracao-canais/configuracoes', linkData);
    return response.data;
  } catch (error) {
    throw error.response?.data || error;
  }
};

/**
 * Lista vínculos integracao_canais_config (canal ↔ loja Bling ↔ integrações).
 */
export const listIntegracaoCanaisConfigs = async (params = {}) => {
  try {
    const response = await api.get('/integracao-canais/configuracoes', { params });
    return response.data;
  } catch (error) {
    throw error.response?.data || error;
  }
};

/**
 * Importa/atualiza pedidos Em Andamento do Bling para o vínculo informado.
 */
export const importarPedidosEmAndamento = async (payload) => {
  try {
    const response = await api.post('/integracao-canais/importar-pedidos-em-andamento', payload);
    return response.data;
  } catch (error) {
    throw error.response?.data || error;
  }
};

/**
 * Update installation details
 */
export const updateInstallation = async (instanceId, data) => {
  try {
    const response = await api.put(`${BASE_URL}/installed/${instanceId}`, data);
    return response.data;
  } catch (error) {
    throw error.response?.data || error;
  }
};

export const getInstallationAppProfiles = async (instanceId) => {
  try {
    const response = await api.get(`${BASE_URL}/installed/${instanceId}/app-profile`);
    return response.data;
  } catch (error) {
    throw error.response?.data || error;
  }
};

export const updateInstallationAppProfile = async (instanceId, appProfileId) => {
  try {
    const response = await api.put(`${BASE_URL}/installed/${instanceId}/app-profile`, {
      app_profile_id: appProfileId,
    });
    return response.data;
  } catch (error) {
    throw error.response?.data || error;
  }
};

export const getAppProfiles = async (moduleId = null) => {
  try {
    const response = await api.get(`${BASE_URL}/app-profiles`, {
      params: moduleId ? { module_id: moduleId } : {}
    });
    return response.data.profiles || [];
  } catch (error) {
    throw error.response?.data || error;
  }
};

export const getAppProfileSpecs = async (moduleId = null) => {
  try {
    const response = await api.get(`${BASE_URL}/app-profile-specs`, {
      params: moduleId ? { module_id: moduleId } : {}
    });
    return moduleId ? response.data.spec : (response.data.specs || []);
  } catch (error) {
    throw error.response?.data || error;
  }
};

export const createAppProfile = async (data) => {
  try {
    const response = await api.post(`${BASE_URL}/app-profiles`, data);
    return response.data;
  } catch (error) {
    throw error.response?.data || error;
  }
};

export const updateAppProfile = async (profileId, data) => {
  try {
    const response = await api.put(`${BASE_URL}/app-profiles/${profileId}`, data);
    return response.data;
  } catch (error) {
    throw error.response?.data || error;
  }
};

export const backfillIntegrationSecrets = async () => {
  try {
    const response = await api.post(`${BASE_URL}/admin/backfill-secrets`);
    return response.data;
  } catch (error) {
    throw error.response?.data || error;
  }
};

const MarketplaceService = {
  getAvailableModules,
  getModuleDetails,
  installModule,
  initAuth,
  exchangeCode,
  getInstalledIntegrations,
  getInstallation,
  getMarketplaceOrderDetail,
  renewToken,
  testIntegration,
  uninstallModule,
  importTokensFromFirebase,
  publishTokensToFirebase,
  syncFirestore,
  getBlingStores,
  createChannelLink,
  listIntegracaoCanaisConfigs,
  importarPedidosEmAndamento,
  updateInstallation,
  getInstallationAppProfiles,
  updateInstallationAppProfile,
  getAppProfiles,
  getAppProfileSpecs,
  createAppProfile,
  updateAppProfile,
  backfillIntegrationSecrets,
};

export default MarketplaceService;
