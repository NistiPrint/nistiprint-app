import axios from 'axios';

const LOCAL_AGENT_BASE_URL = import.meta.env.VITE_LOCAL_PRINT_AGENT_URL || 'http://localhost:8181';

const LocalAgentService = {
  /**
   * Check if the local agent is running
   */
  checkHealth: async () => {
    const response = await axios.get(`${LOCAL_AGENT_BASE_URL}/health`, { timeout: 1500 });
    return response.data;
  },

  getPrinters: async () => {
    const response = await axios.get(`${LOCAL_AGENT_BASE_URL}/printers`);
    return response.data;
  },

  getMappings: async () => {
    const response = await axios.get(`${LOCAL_AGENT_BASE_URL}/mappings`);
    return response.data;
  },

  /**
   * Map a product ID to a local file path by opening a file dialog
   */
  mapFile: async (sku) => {
    const response = await axios.post(`${LOCAL_AGENT_BASE_URL}/map-file`, { sku });
    return response.data;
  },

  saveMapping: async (mapping) => {
    const response = await axios.post(`${LOCAL_AGENT_BASE_URL}/mappings`, mapping);
    return response.data;
  },

  /**
   * Get the mapped file path for a product ID
   */
  getMappedFile: async (sku) => {
    const response = await axios.get(`${LOCAL_AGENT_BASE_URL}/mappings/${encodeURIComponent(sku)}`);
    return response.data;
  },

  /**
   * Print the mapped file for a product ID
   */
  printFile: async (sku, copies = 1) => {
    const response = await axios.post(`${LOCAL_AGENT_BASE_URL}/print`, { sku, copies });
    return response.data;
  }
};

export default LocalAgentService;