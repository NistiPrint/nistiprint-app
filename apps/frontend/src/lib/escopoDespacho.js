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
