const BASE = '/api/v2/impressao-capas/planos'

async function request(url, options = {}) {
  const response = await fetch(url, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json', ...(options.headers || {}) },
    ...options,
  })
  const body = await response.json()
  if (!response.ok || body.success === false) {
    throw new Error(body.error || body.message || 'Não foi possível atualizar o plano de capas.')
  }
  return body.data
}

const capaPrintService = {
  savePlan: (data) => request(BASE, { method: 'POST', body: JSON.stringify(data) }),
  getPlan: (params) => request(`${BASE}?${new URLSearchParams(params)}`),
  listPlans: () => request(BASE),
  registerSend: (planId, data) => request(`${BASE}/${planId}/envios`, { method: 'POST', body: JSON.stringify(data) }),
  prepareGroup: (planId, groupKey) => request(`${BASE}/${planId}/grupos/${encodeURIComponent(groupKey)}/preparar`, { method: 'POST' }),
  updateSend: (planId, requestId, data) => request(`${BASE}/${planId}/envios/${requestId}`, { method: 'PATCH', body: JSON.stringify(data) }),
  confirmItem: (planId, itemId, quantity) => request(`${BASE}/${planId}/itens/${itemId}/confirmar`, {
    method: 'POST', body: JSON.stringify({ quantidade: quantity }),
  }),
  reconcileItem: (planId, itemId, quantity) => request(`${BASE}/${planId}/itens/${itemId}/reconciliar`, {
    method: 'POST', body: JSON.stringify({ quantidade_ja_impressa: quantity }),
  }),
  confirmGroup: (planId, groupKey, quantity) => request(`${BASE}/${planId}/grupos/${encodeURIComponent(groupKey)}/confirmar`, {
    method: 'POST', body: JSON.stringify({ quantidade: quantity }),
  }),
  reconcileGroup: (planId, groupKey, quantity) => request(`${BASE}/${planId}/grupos/${encodeURIComponent(groupKey)}/reconciliar`, {
    method: 'POST', body: JSON.stringify({ quantidade_ja_impressa: quantity }),
  }),
}

export default capaPrintService
