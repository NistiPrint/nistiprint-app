// Formatadores compartilhados das telas de Produção (pt-BR).
const FORMATO_NUMERO = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 4 })

export const numero = (value) => FORMATO_NUMERO.format(Number(value) || 0)

export const dataCurta = (value, vazio = 'Sem prazo') =>
  value ? new Date(`${String(value).slice(0, 10)}T12:00:00`).toLocaleDateString('pt-BR') : vazio
