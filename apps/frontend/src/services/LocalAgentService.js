import axios from 'axios';

const LOCAL_AGENT_BASE_URL = import.meta.env.VITE_LOCAL_PRINT_AGENT_URL || 'http://localhost:8181';
// O agente autoriza por allowlist de Origin, não por token: um token gerado por
// máquina não tem como bater com um valor único de build, e um valor único de
// build seria um segredo publicado no bundle. Ver apps/local_agent/agent.py.
const agentConfig = () => ({});

const LocalAgentService = {
  /**
   * Check if the local agent is running
   */
  checkHealth: async () => {
    const response = await axios.get(`${LOCAL_AGENT_BASE_URL}/health`, { timeout: 1500 });
    return response.data;
  },

  getPrinters: async () => {
    const response = await axios.get(`${LOCAL_AGENT_BASE_URL}/printers`, agentConfig());
    return response.data;
  },

  getMappings: async () => {
    const response = await axios.get(`${LOCAL_AGENT_BASE_URL}/mappings`, agentConfig());
    return response.data;
  },

  coverage: async (skus) => {
    const response = await axios.post(`${LOCAL_AGENT_BASE_URL}/coverage`, { skus }, agentConfig());
    return response.data;
  },

  /**
   * Map a product ID to a local file path by opening a file dialog
   */
  mapFile: async (sku) => {
    const response = await axios.post(`${LOCAL_AGENT_BASE_URL}/map-file`, { sku }, agentConfig());
    return response.data;
  },

  saveMapping: async (mapping) => {
    const response = await axios.post(`${LOCAL_AGENT_BASE_URL}/mappings`, mapping, agentConfig());
    return response.data;
  },

  /**
   * Get the mapped file path for a product ID
   */
  getMappedFile: async (sku) => {
    const response = await axios.get(`${LOCAL_AGENT_BASE_URL}/mappings/${encodeURIComponent(sku)}`, agentConfig());
    return response.data;
  },

  /**
   * Print the mapped file for a product ID
   */
  printFile: async (sku, copies = 1) => {
    const response = await axios.post(`${LOCAL_AGENT_BASE_URL}/print`, { sku, copies }, agentConfig());
    return response.data;
  }
};

export default LocalAgentService;