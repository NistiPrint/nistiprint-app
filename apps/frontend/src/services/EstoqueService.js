/**
 * Serviço centralizado para operações de estoque
 * Centraliza todas as chamadas de API relacionadas ao estoque
 */

class EstoqueService {
  constructor() {
    this.baseURL = '/api/v2/estoque';
  }

  /**
   * Método auxiliar para fazer requisições HTTP
   */
  async _makeRequest(endpoint, options = {}) {
    const url = `${this.baseURL}${endpoint}`;

    const defaultOptions = {
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
    };

    const mergedOptions = {
      ...defaultOptions,
      ...options,
      headers: {
        ...defaultOptions.headers,
        ...options.headers,
      },
    };

    try {
      const response = await fetch(url, mergedOptions);

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.error || `Erro HTTP: ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error(`Erro na requisição ${endpoint}:`, error);
      throw error;
    }
  }

  /**
   * Busca dados do dashboard de estoque
   */
  async getDashboardData() {
    return this._makeRequest('/');
  }

  /**
   * Busca posição de estoque com filtros
   */
  async getPosicaoEstoque(filters = {}) {
    const params = new URLSearchParams();

    if (filters.produto_id) params.append('produto_id', filters.produto_id);
    if (filters.deposito_id) params.append('deposito_id', filters.deposito_id);

    const queryString = params.toString();
    const endpoint = `/posicao${queryString ? `?${queryString}` : ''}`;

    return this._makeRequest(endpoint);
  }

  /**
   * Busca histórico de movimentações com filtros
   */
  async getHistorico(filters = {}) {
    const params = new URLSearchParams();

    if (filters.produto_id) params.append('produto_id', filters.produto_id);
    if (filters.deposito_id) params.append('deposito_id', filters.deposito_id);
    if (filters.tipo_movimento) params.append('tipo_movimento', filters.tipo_movimento);
    if (filters.data_inicio) params.append('data_inicio', filters.data_inicio);
    if (filters.data_fim) params.append('data_fim', filters.data_fim);
    if (filters.limit) params.append('limit', filters.limit);

    const queryString = params.toString();
    const endpoint = `/historico${queryString ? `?${queryString}` : ''}`;

    return this._makeRequest(endpoint);
  }

  /**
   * Busca histórico consolidado: movimentações agrupadas por
   * (correlation_id, estagio) com título de negócio (FINALIZACAO/JIT/CONSUMO)
   * e a árvore de movimentos crus em "movimentos".
   */
  async getHistoricoConsolidado(filters = {}) {
    const params = new URLSearchParams();

    if (filters.produto_id) params.append('produto_id', filters.produto_id);
    if (filters.deposito_id) params.append('deposito_id', filters.deposito_id);
    if (filters.demanda_id) params.append('demanda_id', filters.demanda_id);
    if (filters.item_demanda_id) params.append('item_demanda_id', filters.item_demanda_id);
    if (filters.tipo_bloco) params.append('tipo_bloco', filters.tipo_bloco);
    if (filters.data_inicio) params.append('data_inicio', filters.data_inicio);
    if (filters.data_fim) params.append('data_fim', filters.data_fim);
    if (filters.limit) params.append('limit', filters.limit);

    const queryString = params.toString();
    const endpoint = `/historico-consolidado${queryString ? `?${queryString}` : ''}`;

    return this._makeRequest(endpoint);
  }

  /**
   * Busca reservas de estoque ativas
   */
  async getReservas() {
    return this._makeRequest('/reservas');
  }

  /**
   * Busca alertas de estoque
   */
  async getAlertas() {
    return this._makeRequest('/alertas');
  }

  /**
   * Busca produtos para autocomplete
   */
  async searchProdutos(query, deposito_id = null) {
    if (!query || query.length < 3) {
      return { results: [] };
    }

    const params = new URLSearchParams();
    params.append('q', query);
    if (deposito_id) params.append('deposito_id', deposito_id);

    const endpoint = `/produtos-busca?${params.toString()}`;

    return this._makeRequest(endpoint);
  }

  /**
   * Registra uma nova movimentação de estoque
   */
  async registrarMovimentacao(data) {
    return this._makeRequest('/movimentar', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  /**
   * Busca depósitos disponíveis para movimentação
   */
  async getDepositos() {
    return this._makeRequest('/movimentar', {
      method: 'GET',
    });
  }

  /**
   * Realiza ajuste de inventário
   */
  async realizarAjuste(data) {
    return this._makeRequest('/ajuste', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  /**
   * Libera uma reserva de estoque
   */
  async liberarReserva(data) {
    return this._makeRequest('/liberar-reserva', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  /**
   * Busca saldos específicos para produtos em depósito
   */
  async getSaldosBatch(data) {
    return this._makeRequest('/saldos-batch', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  /**
   * Busca saldo específico de produto em depósito
   */
  async getSaldo(produto_id, deposito_id) {
    return this._makeRequest(`/saldo/${produto_id}/${deposito_id}`);
  }

  /**
   * Reverte uma movimentação de estoque
   */
  async reverterMovimentacao(data) {
    return this._makeRequest('/reverter-movimentacao', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  /**
   * Busca relatório Curva ABC
   */
  async getRelatorioABC(days = 30) {
    return this._makeRequest(`/api/v2/relatorios/abc?days=${days}`);
  }

  /**
   * Busca relatório de Valorização de Estoque
   */
  async getRelatorioValorizacao() {
    return this._makeRequest('/api/v2/relatorios/valorizacao');
  }
}

// Exportar instância singleton
export const estoqueService = new EstoqueService();
export default estoqueService;
