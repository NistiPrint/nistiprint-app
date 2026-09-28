const BASE = '/api/v2/impressao-capas/produtos'

async function request(url, options = {}) {
  const response = await fetch(url, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    ...options,
  })
  const body = await response.json()
  if (!response.ok || body.success === false) throw new Error(body.error || 'Falha ao salvar arte')
  return body.data
}

const printArtworkService = {
  get: (productId) => request(`${BASE}/${productId}/artes`),
  create: (productId, data) => request(`${BASE}/${productId}/artes`, { method: 'POST', body: JSON.stringify(data) }),
  update: (productId, artId, data) => request(`${BASE}/${productId}/artes/${artId}`, { method: 'PUT', body: JSON.stringify(data) }),
  remove: (productId, artId) => request(`${BASE}/${productId}/artes/${artId}`, { method: 'DELETE' }),
}

export default printArtworkService
