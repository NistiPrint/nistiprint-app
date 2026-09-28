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

  checkUpdates: async () => {
    const response = await axios.get(`${LOCAL_AGENT_BASE_URL}/updates/check`, { timeout: 15000 });
    return response.data;
  },

  installUpdate: async () => {
    const response = await axios.post(`${LOCAL_AGENT_BASE_URL}/updates/install`, {}, { timeout: 120000 });
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
  mapFile: async (sku, artworkId = null) => {
    const response = await axios.post(`${LOCAL_AGENT_BASE_URL}/map-file`, { sku, artwork_id: artworkId });
    return response.data;
  },

  saveMapping: async (mapping) => {
    const response = await axios.post(`${LOCAL_AGENT_BASE_URL}/mappings`, mapping);
    return response.data;
  },

  /**
   * Get the mapped file path for a product ID
   */
  getMappedFile: async (sku, productId) => {
    const query = productId ? `?product_id=${encodeURIComponent(productId)}` : '';
    const response = await axios.get(`${LOCAL_AGENT_BASE_URL}/mappings/${encodeURIComponent(sku)}${query}`);
    return response.data;
  },

  getMappedArtwork: async (artworkId) => {
    const response = await axios.get(`${LOCAL_AGENT_BASE_URL}/mappings/artwork/${encodeURIComponent(artworkId)}`);
    return response.data;
  },

  /**
   * Print the mapped file for a product ID
   */
  printFile: async (sku, copies = 1, productId) => {
    const response = await axios.post(`${LOCAL_AGENT_BASE_URL}/print`, { sku, product_id: productId, copies });
    return response.data;
  },

  printWithDialog: async (sku, copies, requestId, productId, artworkId = null) => {
    const response = await axios.post(`${LOCAL_AGENT_BASE_URL}/print-dialog`, {
      sku: sku || '', product_id: productId, artwork_id: artworkId, copies, request_id: requestId,
    });
    return response.data;
  },

  openMappedPdf: async (sku, requestId, productId, artworkId = null) => {
    const response = await axios.post(`${LOCAL_AGENT_BASE_URL}/open`, {
      sku: sku || '', product_id: productId, artwork_id: artworkId, request_id: requestId,
    });
    return response.data;
  },

  getPrintJob: async (jobId) => {
    const response = await axios.get(`${LOCAL_AGENT_BASE_URL}/jobs/${encodeURIComponent(jobId)}`);
    return response.data;
  }
};

export default LocalAgentService;
