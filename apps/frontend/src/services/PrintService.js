import api from './api';

const PrintService = {
  /**
   * Send artwork to printing workflow
   */
  sendToPrint: async (productId, artworkId = null) => {
    try {
      const response = await api.post(`/produtos/${productId}/print`, {
        artwork_id: artworkId  // If null, system will use the latest artwork
      });
      return response.data;
    } catch (error) {
      console.error('Error sending to print:', error);
      throw error;
    }
  },

  /**
   * Get print job status
   */
  getPrintJobStatus: async (jobId) => {
    try {
      const response = await api.get(`/printing/job/${jobId}`);
      return response.data;
    } catch (error) {
      console.error('Error getting print job status:', error);
      throw error;
    }
  },

  /**
   * Get all print jobs for a product
   */
  getProductPrintJobs: async (productId) => {
    try {
      const response = await api.get(`/printing/product/${productId}/jobs`);
      return response.data;
    } catch (error) {
      console.error('Error getting product print jobs:', error);
      throw error;
    }
  },

  /**
   * Cancel a print job
   */
  cancelPrintJob: async (jobId) => {
    try {
      const response = await api.delete(`/printing/job/${jobId}`);
      return response.data;
    } catch (error) {
      console.error('Error cancelling print job:', error);
      throw error;
    }
  }
};

export default PrintService;