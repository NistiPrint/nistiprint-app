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
 * Get live orders list from a marketplace integration
 */
export const getMarketplaceOrdersList = async (instanceId, filters = {}) => {
  try {
    const response = await api.post(`${BASE_URL}/orders/list`, {
      instance_id: instanceId,
      filters
    });
    return response.data;
  } catch (error) {
    return { success: false, error: error.response?.data?.message || error.message };
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

const MarketplaceService = {
  getAvailableModules,
  getModuleDetails,
  installModule,
  initAuth,
  exchangeCode,
  getInstalledIntegrations,
  getMarketplaceOrdersList,
  getMarketplaceOrderDetail,
  renewToken,
  testIntegration,
  uninstallModule
};

export default MarketplaceService;
