/**
 * Serviço para reprocessamento de pedidos
 */

export const reprocessamentoService = {
  /**
   * Reprocessar um pedido individual
   */
  async reprocessOrder(pedidoId, integrationId = null) {
    const payload = { pedido_id: pedidoId };
    if (integrationId) {
      payload.integration_id = integrationId;
    }

    const response = await fetch('/api/admin/orders/reprocess', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: JSON.stringify(payload),
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.message || 'Erro ao reprocessar pedido');
    }

    return data;
  },

  /**
   * Reprocessar um lote de pedidos
   */
  async reprocessBatch(pedidoIds, integrationId = null) {
    const payload = { pedido_ids: pedidoIds };
    if (integrationId) {
      payload.integration_id = integrationId;
    }

    const response = await fetch('/api/admin/orders/reprocess-batch', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: JSON.stringify(payload),
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.message || 'Erro ao reprocessar lote');
    }

    return data;
  },

  /**
   * Reprocessar pedidos por canal
   */
  async reprocessByCanal(canalVendaId, dateRange = null, integrationId = null) {
    const payload = { canal_venda_id: canalVendaId };
    if (dateRange) {
      payload.date_range = dateRange;
    }
    if (integrationId) {
      payload.integration_id = integrationId;
    }

    const response = await fetch('/api/admin/orders/reprocess-by-canal', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: JSON.stringify(payload),
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.message || 'Erro ao reprocessar pedidos do canal');
    }

    return data;
  },
};
