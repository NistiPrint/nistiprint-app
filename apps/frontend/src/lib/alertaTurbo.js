export function calcularRestante(compromissoEm, agora = Date.now()) {
  if (!compromissoEm) return null;
  const compromisso = new Date(compromissoEm).getTime();
  return Number.isFinite(compromisso) ? compromisso - agora : null;
}

export function formatarRestante(ms) {
  if (!Number.isFinite(ms)) return 'prazo indisponível';

  const negativo = ms < 0;
  const total = Math.floor(Math.abs(ms) / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const corpo = h > 0
    ? `${h}h${String(m).padStart(2, '0')}`
    : `${m}:${String(s).padStart(2, '0')}`;
  return negativo ? `atrasado há ${corpo}` : corpo;
}
