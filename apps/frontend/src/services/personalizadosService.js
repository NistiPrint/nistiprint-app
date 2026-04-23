/**
 * Serviço para APIs de Pedidos Personalizados com IA.
 * Centraliza todas as chamadas relacionadas a personalizações.
 */

const BASE = '/api/v2/personalizados';

export const personalizadosService = {
  /**
   * Lista pedidos com itens personalizados.
   * @param {Object} params - { order_sn?, limit? }
   */
  listar: async (params = {}) => {
    const qs = new URLSearchParams(params).toString();
    const res = await fetch(`${BASE}?${qs}`, {
      headers: { Accept: 'application/json' },
    });
    return res.json();
  },

  /**
   * Dispara processamento de IA (sob demanda).
   * @param {Object} data - { order_sn?, limit? }
   */
  processar: async (data = {}) => {
    const res = await fetch(`${BASE}/processar`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    return res.json();
  },

  /**
   * Verifica status de uma task Celery.
   * @param {string} taskId
   */
  statusTask: async (taskId) => {
    const res = await fetch(`${BASE}/status/${taskId}`, {
      headers: { Accept: 'application/json' },
    });
    return res.json();
  },

  /**
   * Reprocessa um pedido específico.
   * @param {string} orderSn
   */
  reprocessar: async (orderSn) => {
    const res = await fetch(`${BASE}/reprocessar/${encodeURIComponent(orderSn)}`, {
      method: 'POST',
    });
    return res.json();
  },

  /**
   * Obtém logs de execução da IA para um pedido.
   * @param {string} orderSn
   */
  getLogs: async (orderSn) => {
    const res = await fetch(`${BASE}/logs/${encodeURIComponent(orderSn)}`, {
      headers: { Accept: 'application/json' },
    });
    return res.json();
  },

  /**
   * Lista TODOS os logs de execução da IA (com filtros).
   * @param {Object} params - { order_sn?, status?, limit?, offset? }
   */
  getAllLogs: async (params = {}) => {
    const qs = new URLSearchParams(params).toString();
    const res = await fetch(`${BASE}/logs?${qs}`, {
      headers: { Accept: 'application/json' },
    });
    return res.json();
  },

  /**
   * Deleta logs de execução de um pedido específico.
   * @param {string} orderSn
   */
  deleteLogs: async (orderSn) => {
    const res = await fetch(`${BASE}/logs/${encodeURIComponent(orderSn)}`, {
      method: 'DELETE',
    });
    return res.json();
  },

  /**
   * Deleta logs de execução em lote (com filtros).
   * @param {Object} params - { order_sn?, status?, all? }
   */
  deleteLogsBatch: async (params = {}) => {
    const qs = new URLSearchParams(params).toString();
    const res = await fetch(`${BASE}/logs?${qs}`, {
      method: 'DELETE',
    });
    return res.json();
  },

  /**
   * Deleta TODOS os logs de execução.
   */
  deleteAllLogs: async () => {
    const res = await fetch(`${BASE}/logs?all=true`, {
      method: 'DELETE',
    });
    return res.json();
  },

  /**
   * Salva feedback do usuário sobre extração.
   * @param {Object} data - { order_sn, avaliacao (1-5), texto_feedback? }
   */
  salvarFeedback: async (data) => {
    const res = await fetch(`${BASE}/feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    return res.json();
  },

  /**
   * Obtém configurações de IA (prompt + modelo).
   */
  getConfig: async () => {
    const res = await fetch(`${BASE}/config`, {
      headers: { Accept: 'application/json' },
    });
    return res.json();
  },

  /**
   * Atualiza configurações de IA.
   * @param {Object} data - { prompt_template?, model_name?, max_processing? }
   */
  updateConfig: async (data) => {
    const res = await fetch(`${BASE}/config`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    return res.json();
  },

  /**
   * Obtém mensagens de chat de um comprador Shopee.
   * @param {string} username
   * @param {Object} params - { limit? }
   */
  getChat: async (username, params = {}) => {
    const qs = new URLSearchParams(params).toString();
    const res = await fetch(
      `${BASE}/chat/${encodeURIComponent(username)}?${qs}`,
      { headers: { Accept: 'application/json' } },
    );
    return res.json();
  },
};
