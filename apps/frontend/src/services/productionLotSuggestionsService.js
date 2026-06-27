import api from '@/services/api'

export async function listLotSuggestions(search = '') {
  const response = await api.get('/demanda_producao/lote-suggestions', {
    params: search ? { search } : undefined,
  })
  return response.data
}

export async function getLotSuggestionDetail(suggestionKey) {
  const response = await api.get(
    `/demanda_producao/lote-suggestions/${encodeURIComponent(suggestionKey)}`
  )
  return response.data
}

export async function confirmLotSuggestion(payload) {
  const response = await api.post('/demanda_producao/lote-suggestions/confirm', payload)
  return response.data
}
