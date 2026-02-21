import axios from 'axios';

// Base URL for the local agent service
const LOCAL_AGENT_BASE_URL = 'http://localhost:8181';

const LocalAgentService = {
  /**
   * Check if the local agent is running
   */
  checkHealth: async () => {
    try {
      const response = await axios.get(`${LOCAL_AGENT_BASE_URL}/health`);
      return response.data;
    } catch (error) {
      // If the agent is not running, this will throw an error
      throw error;
    }
  },

  /**
   * Map a product ID to a local file path by opening a file dialog
   */
  mapFile: async (productId) => {
    try {
      const response = await axios.post(`${LOCAL_AGENT_BASE_URL}/map-file`, {
        product_id: productId
      });
      return response.data;
    } catch (error) {
      console.error('Error mapping file:', error);
      throw error;
    }
  },

  /**
   * Get the mapped file path for a product ID
   */
  getMappedFile: async (productId) => {
    try {
      const response = await axios.get(`${LOCAL_AGENT_BASE_URL}/get-mapped-file/${productId}`);
      return response.data;
    } catch (error) {
      console.error('Error getting mapped file:', error);
      throw error;
    }
  },

  /**
   * Print the mapped file for a product ID
   */
  printFile: async (productId, copies = 1) => {
    try {
      const response = await axios.post(`${LOCAL_AGENT_BASE_URL}/print`, {
        product_id: productId,
        copies: copies
      });
      return response.data;
    } catch (error) {
      console.error('Error printing file:', error);
      throw error;
    }
  }
};

export default LocalAgentService;