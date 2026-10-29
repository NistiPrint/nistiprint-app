const HORIZONTES = {
  hoje: ['atrasado', 'hoje', 'sem_prazo'],
  amanha: ['amanha'],
  proximos: ['depois'],
};

export function horizonteDaAba(aba) {
  return [...(HORIZONTES[aba] || HORIZONTES.hoje)];
}

export function alternarPrazo(horizonte, prazo) {
  if (!horizonte.includes(prazo)) return [...horizonte, prazo];
  return horizonte.length === 1 ? horizonte : horizonte.filter((item) => item !== prazo);
}

// Espelha public.despacho_aba_do_bucket; sem_prazo cai em "hoje" porque prazo
// desconhecido e a hipotese mais urgente, nao a menos.
const ABA_DO_BUCKET = {
  atrasado: 'hoje',
  hoje: 'hoje',
  sem_prazo: 'hoje',
  amanha: 'amanha',
  depois: 'proximos',
};

export function abaDoBucketPrazo(bucket) {
  return ABA_DO_BUCKET[bucket] || 'proximos';
}

// Caminho da tela de escopo de um lote. Usado pela Torre e pela previsao de
// miolos, para que "Conferir lote" abra exatamente o mesmo escopo nos dois.
export function urlDoEscopo({ integrationId, modalidadeIds, nomeMarketplace, nomeModalidade, aba, incluirPronto }) {
  const params = new URLSearchParams();
  if (integrationId !== null && integrationId !== undefined) params.set('integration_id', integrationId);
  // O escopo e o lote inteiro: todos os canais que dividem a janela.
  // O singular vai junto de proposito: uma API que ainda nao conhece lotes le
  // `modalidade_id` e devolve o canal principal — menos do que o esperado, mas
  // nunca uma lista vazia. Ja aconteceu de a tela zerar por essa diferenca.
  (modalidadeIds || []).forEach((id) => params.append('modalidade_ids', id));
  if (modalidadeIds && modalidadeIds.length > 0) params.set('modalidade_id', modalidadeIds[0]);
  params.set('marketplace_nome', nomeMarketplace || '');
  params.set('modalidade_nome', nomeModalidade || '');
  params.set('aba', aba);
  if (incluirPronto) params.set('incluir_pronto', 'true');
  return `/despacho/escopo?${params.toString()}`;
}
