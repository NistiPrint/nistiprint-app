// Dia operacional do despacho.
//
// `new Date().toISOString()` devolve a data em UTC. Em Sao Paulo (UTC-3) isso
// significa que a partir das 21h a data "de hoje" ja e a de amanha — e foi
// exatamente o que aconteceu: as 21h a torre passou a tratar amanha como hoje,
// jogando os pedidos de hoje para o balde de atrasados.
//
// A data que interessa aqui e a do galpao, nao a do meridiano de Greenwich.
// `sv-SE` e usado so porque seu formato nativo ja e YYYY-MM-DD.
export function dataOperacionalHoje(timeZone = 'America/Sao_Paulo') {
  try {
    return new Date().toLocaleDateString('sv-SE', { timeZone });
  } catch {
    // Ambiente sem suporte a IANA: cai para a data local do navegador, que
    // ainda e melhor que UTC para quem opera no Brasil.
    const agora = new Date();
    const p = (n) => String(n).padStart(2, '0');
    return `${agora.getFullYear()}-${p(agora.getMonth() + 1)}-${p(agora.getDate())}`;
  }
}
