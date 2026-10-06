function validarPrevisao(previsao) {
  if (!previsao || typeof previsao !== 'object' || Array.isArray(previsao)) {
    throw new Error('A resposta da consolidação está inválida.');
  }
  if (!Array.isArray(previsao.itens)
    || previsao.itens.some((item) => !item || typeof item !== 'object' || Array.isArray(item))
    || typeof previsao.previsao_versao !== 'string'
    || !previsao.previsao_versao) {
    throw new Error('A resposta da consolidação está incompleta.');
  }
  return previsao;
}

async function lerJson(resposta, mensagem) {
  if (!resposta.ok) throw new Error(`${mensagem} (HTTP ${resposta.status}).`);
  let json;
  try {
    json = await resposta.json();
  } catch {
    throw new Error(`${mensagem}: resposta inválida.`);
  }
  if (!json?.success || !json.data || typeof json.data !== 'object' || Array.isArray(json.data)) {
    throw new Error(json?.error || `${mensagem}: resposta inválida.`);
  }
  return json.data;
}

export async function carregarEscopoDespacho(fetchImpl, params, signal) {
  const query = params.toString();
  const escopo = await lerJson(
    await fetchImpl(`/api/v2/despacho/escopo?${query}`, { signal }),
    'Falha ao carregar o escopo',
  );
  if (!Array.isArray(escopo.pedidos) || typeof escopo.total !== 'number' || !Number.isFinite(escopo.total)) {
    throw new Error('A resposta do escopo está incompleta.');
  }

  let previsao;
  if (Object.hasOwn(escopo, 'previsao')) {
    previsao = validarPrevisao(escopo.previsao);
  } else {
    const complementar = await lerJson(
      await fetchImpl(`/api/v2/despacho/previsao?${query}`, { signal }),
      'Falha ao carregar a consolidação',
    );
    previsao = validarPrevisao(complementar);
  }
  return { ...escopo, previsao };
}
