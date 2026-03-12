import api from './api';

export const getUnifiedOrders = async (filters) => {
  try {
    const response = await api.get('/vendas/unified-orders', { params: filters });
    return response.data;
  } catch (error) {
    console.error('Error fetching unified orders:', error);
    return { success: false, error: error.message };
  }
};

export const getOrderStatusOptions = async () => {
  try {
    const response = await api.get('/vendas/order-status-options');
    return response.data;
  } catch (error) {
    console.error('Error fetching order status options:', error);
    return { success: false, error: error.message };
  }
};

export const getCanalVendaOptions = async () => {
  try {
    const response = await api.get('/vendas/canal-venda-options');
    return response.data;
  } catch (error) {
    console.error('Error fetching canal venda options:', error);
    return { success: false, error: error.message };
  }
};

export const updateOrderStatus = async (orderId, newStatus) => {
  try {
    // Implementar esta rota no backend futuramente se necessário
    console.warn(`Attempted to update status for order ${orderId} to ${newStatus}. Backend route not implemented yet.`);
    return { success: true, message: "Status update simulated (backend route not implemented)." };
    // const response = await api.put(`/v2/vendas/unified-orders/${orderId}/status`, { status: newStatus });
    // return response.data;
  } catch (error) {
    console.error('Error updating order status:', error);
    return { success: false, error: error.message };
  }
};
