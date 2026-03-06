import api from './api';

// Base endpoint for unified order operations
const BASE_URL = '/order';

/**
 * Get unified orders with optional filters
 */
export const getUnifiedOrders = async (filters = {}) => {
  try {
    const response = await api.post(`${BASE_URL}/list`, filters);
    // Garantir que a estrutura de dados seja consistente
    return {
      success: true,
      data: response.data.orders || response.data,
      ...response.data
    };
  } catch (error) {
    return { success: false, error: error.response?.data?.message || error.message };
  }
};

/**
 * Get available order status options
 */
export const getOrderStatusOptions = async () => {
  try {
    const response = await api.get(`${BASE_URL}/status-options`);
    // Garantir que a estrutura de dados seja consistente
    return {
      success: true,
      data: response.data.status_options || response.data,
      ...response.data
    };
  } catch (error) {
    return { success: false, error: error.response?.data?.message || error.message };
  }
};

/**
 * Update order status
 */
export const updateOrderStatus = async (orderId, newStatus) => {
  try {
    const response = await api.post(`${BASE_URL}/update-status`, {
      order_id: orderId,
      new_status: newStatus
    });
    // Garantir que a estrutura de dados seja consistente
    return {
      success: true,
      data: response.data.order || response.data,
      ...response.data
    };
  } catch (error) {
    return { success: false, error: error.response?.data?.message || error.message };
  }
};

/**
 * Get order details
 */
export const getOrderDetails = async (orderId) => {
  try {
    const response = await api.get(`${BASE_URL}/details/${orderId}`);
    // Garantir que a estrutura de dados seja consistente
    return {
      success: true,
      data: response.data.order || response.data,
      ...response.data
    };
  } catch (error) {
    return { success: false, error: error.response?.data?.message || error.message };
  }
};

const OrderService = {
  getUnifiedOrders,
  getOrderStatusOptions,
  updateOrderStatus,
  getOrderDetails
};

export default OrderService;