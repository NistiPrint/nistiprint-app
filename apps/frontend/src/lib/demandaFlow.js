export const DEMANDA_FLOW_OPTIONS = [
  {
    id: 'venda_diaria',
    label: 'Venda diaria',
    shortLabel: 'Venda diaria',
    description: 'Pedidos do dia a dia vindos de canais e marketplaces.',
    tipo_demanda: 'PLATAFORMA',
    classificacao_cliente: 'B2C',
    modalidade_logistica: 'STANDARD',
  },
  {
    id: 'fulfillment',
    label: 'Fulfillment',
    shortLabel: 'Fulfillment',
    description: 'Reposicao de estoque operacional para canais externos.',
    tipo_demanda: 'FULFILLMENT',
    classificacao_cliente: 'B2C',
    modalidade_logistica: 'FULFILLMENT',
  },
  {
    id: 'venda_corporativa',
    label: 'Venda corporativa',
    shortLabel: 'Corporativa',
    description: 'Pedidos de empresa com aprovacao, arte e acabamentos dedicados.',
    tipo_demanda: 'B2B',
    classificacao_cliente: 'B2B',
    modalidade_logistica: 'STANDARD',
  },
  {
    id: 'producao_interna',
    label: 'Producao interna',
    shortLabel: 'Interna',
    description: 'Amostras, estoque e necessidades internas da operacao.',
    tipo_demanda: 'ESTOQUE_INTERNO',
    classificacao_cliente: 'INTERNO',
    modalidade_logistica: 'STANDARD',
  },
]

export function getDemandFlowConfig(flowId) {
  return DEMANDA_FLOW_OPTIONS.find((item) => item.id === flowId) || DEMANDA_FLOW_OPTIONS[0]
}

export function deriveDemandFlow(demanda = {}) {
  const tipo = String(demanda.tipo_demanda || '').toUpperCase()
  const modalidade = String(demanda.modalidade_logistica || '').toUpperCase()
  const classificacao = String(demanda.classificacao_cliente || '').toUpperCase()

  if (tipo === 'B2B' || classificacao === 'B2B') return 'venda_corporativa'
  if (tipo === 'ESTOQUE_INTERNO' || classificacao === 'INTERNO') return 'producao_interna'
  if (tipo === 'FULFILLMENT' || modalidade === 'FULFILLMENT') return 'fulfillment'
  return 'venda_diaria'
}

export function getDemandFlowLabel(demanda = {}) {
  return getDemandFlowConfig(deriveDemandFlow(demanda)).label
}

export function getModalidadeLabel(modalidade) {
  const labels = {
    STANDARD: 'Padrao',
    EXPRESS: 'Expressa',
    FULFILLMENT: 'Fulfillment',
    RETIRADA: 'Retirada',
  }

  return labels[String(modalidade || '').toUpperCase()] || modalidade || 'Padrao'
}