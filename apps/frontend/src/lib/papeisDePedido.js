// Papeis de pedido — o mesmo papel que sai da consolidacao por planilha.
//
// O papel do pedido e o unico documento que atravessa o galpao inteiro: ele
// diz quem produz o que, e para o personalizado ele diz o modelo (a tag) e o
// nome a ser gravado. O layout aqui reproduz `kb/legado/templates/results.html`
// (`printBlingData`), inclusive o rodape com a tag do modelo — que a versao
// que existia na tela de demanda tinha perdido, deixando o operador sem saber
// qual capa pegar para um pedido personalizado.
//
// A ordem de impressao vem pronta do backend (`_print_sort_key`): Shopee mantém
// personalizados juntos e agrupados por modelo; MercadoLivre usa o numero
// externo crescente. Nao reordene no cliente.

// O backend monta os dados de um pedido por vez; alem disso a lista de ids vai
// na URL. Em lote grande as duas coisas doem, entao a busca vai em fatias.
const PEDIDOS_POR_REQUISICAO = 120;

function escaparHtml(valor) {
  return String(valor ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function moeda(valor) {
  return Number(valor || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
}

/** Busca os dados de impressao de uma lista de pedidos, em fatias. */
export async function buscarPapeisDePedido(pedidoIds) {
  const ids = (pedidoIds || []).filter(Boolean);
  if (ids.length === 0) return { orders: [], blocked: [] };

  const orders = [];
  const blocked = [];
  for (let i = 0; i < ids.length; i += PEDIDOS_POR_REQUISICAO) {
    const fatia = ids.slice(i, i + PEDIDOS_POR_REQUISICAO);
    const res = await fetch(`/api/v2/pedidos/impressao?order_ids=${fatia.join(',')}`);
    const json = await res.json();
    if (!res.ok || !json.success) {
      throw new Error(json.message || json.error || 'Falha ao carregar os papeis dos pedidos.');
    }
    orders.push(...(json.data?.orders || []));
    blocked.push(...(json.data?.blocked_orders || []));
  }
  return { orders, blocked };
}

function personalizacoesHtml(item) {
  return (item.personalizations || [])
    .filter((p) => p.customization_name)
    .map((p) => {
      const inicial = p.customization_initial ? ` (${escaparHtml(p.customization_initial)})` : '';
      const vezes = p.quantity_to_personalize > 1 ? ` x${escaparHtml(p.quantity_to_personalize)}` : '';
      return `<div class="custom-name-display">${escaparHtml(p.customization_name)}${inicial}${vezes}</div>`;
    })
    .join('');
}

function itemHtml(item) {
  const variacao = item.variacao && String(item.variacao).trim() && item.variacao !== '-'
    ? `<div class="variacao">${escaparHtml(item.variacao)}</div>`
    : '';
  return `
    <div class="item">
      <div class="item-details">
        <div>${escaparHtml(item.descricao || 'N/A')}</div>
        ${variacao}
        <div><strong>${escaparHtml(item.codigo || '')}</strong></div>
        ${personalizacoesHtml(item)}
      </div>
      <div class="item-quantity">${escaparHtml(item.quantidade ?? 1)}</div>
      <div class="item-price">${moeda(item.valor)}</div>
    </div>`;
}

function tagsModeloHtml(order) {
  // A tag do modelo fica no fim do corpo, e nao no rodape: assim continua
  // dentro da area util quando o pedido tem varios itens.
  const tags = (order.itens || [])
    .map((item) => (item.custom_tag || '').trim())
    .filter(Boolean);
  const unicas = [...new Set(tags)];
  if (unicas.length === 0) return '';
  return `<div class="custom-tags" aria-label="Modelos">
    ${unicas.map((tag) => `<div class="custom-tag">${escaparHtml(tag)}</div>`).join('')}
  </div>`;
}

function rodapeHtml() {
  return `<div class="stamp-footer">
    <div></div>
    <div class="rodape-data">${escaparHtml(new Date().toLocaleDateString('pt-BR'))}</div>
  </div>`;
}

function mensagemHtml(order) {
  // So aparece quando o pedido e personalizado e nao veio nome estruturado: e
  // o texto cru do comprador ("Nome na capa sera: ..."), que sem isto obrigaria
  // o operador a abrir o painel do marketplace pedido a pedido.
  const mensagem = (order.mensagem_comprador || '').trim();
  if (!mensagem) return '';
  return `<div class="mensagem-comprador">
    <span class="rotulo">Mensagem do comprador</span>
    <div>${escaparHtml(mensagem)}</div>
  </div>`;
}

function cartaoHtml(order) {
  const itens = order.itens || [];
  const totalItens = order.total_items || 0;
  const documento = order.contato?.numeroDocumento
    || order.contato?.documento
    || order.contato?.document
    || order.documento;
  const endereco = order.contato?.endereco
    ? `<div>${escaparHtml(order.contato.endereco)}</div>`
    : '';
  return `
    <div class="stamp-card">
      <div class="stamp-header">
        <div>
          <div>Nome: ${escaparHtml(order.contato?.nome || 'N/A')}</div>
          <div>CPF: ${escaparHtml(documento || 'N/A')}</div>
          ${endereco}
        </div>
        <div></div>
        <div class="origem">
          <div>${escaparHtml(order.plataforma || 'Pedido')}</div>
          <div>${escaparHtml(order.numeroLoja || 'N/A')}</div>
        </div>
      </div>
      <div class="stamp-content">
        <div class="order-info"><div>Pedido ${escaparHtml(order.numero || order.id || 'N/A')}</div></div>
        ${itens.map(itemHtml).join('')}
        ${mensagemHtml(order)}
        <div class="item">
          <div class="item-details"></div>
          <div class="item-quantity"></div>
          <div class="item-price">${moeda(order.totalProdutos)}</div>
        </div>
        ${tagsModeloHtml(order)}
        <div class="total-items">
          <div></div>
          <div><span>${escaparHtml(totalItens)} ${totalItens > 1 ? 'itens' : 'item'}</span></div>
          <div></div>
        </div>
      </div>
      ${rodapeHtml()}
    </div>`;
}

// CSS transcrito do legado (`results.html`, `printBlingData`).
const ESTILO = `
  *{box-sizing:border-box}
  body{margin:0;padding:0;font-family:Arial,sans-serif;color:#000}
  .stamp-card{border:1px solid #000;border-radius:8px;padding:20px;background:#fff;width:100%;
    height:100vh;box-sizing:border-box;page-break-after:always;display:flex;flex-direction:column}
  .stamp-header{display:flex;justify-content:space-between;font-size:1.5rem;margin-bottom:30px}
  .stamp-header div div{padding:15px 0}
  .stamp-header .origem{text-align:right;font-weight:700}
  .stamp-content{flex-grow:1;min-height:0;display:flex;flex-direction:column;justify-content:flex-start}
  .stamp-content .order-info{text-align:center;font-size:2.5rem;margin-bottom:40px}
  .stamp-content .order-info div,.stamp-content .item-details div{margin-bottom:5px}
  .stamp-content .item{display:flex;align-items:center;border-top:1px solid #ddd;padding:15px 0;margin-bottom:15px;flex-shrink:0}
  .stamp-content .item:first-child{border-top:none}
  .stamp-content .item-details{width:80%;font-size:1.2rem}
  .stamp-content .item-details .variacao{font-size:.8rem;color:#666}
  .stamp-content .item-quantity{width:10%;text-align:center;font-size:1.6rem}
  .stamp-content .item-price{width:10%;text-align:center;font-size:.8rem}
  .stamp-content .total-items{display:flex;justify-content:space-between;text-align:center;margin-top:auto;margin-bottom:20px;flex-shrink:0}
  .stamp-content .total-items span{font-size:2.5rem}
  .custom-tags{display:flex;justify-content:center;align-items:center;gap:8px;flex-wrap:wrap;margin:12px 0 16px;flex-shrink:0}
  .custom-tags .custom-tag{font-size:1.8rem;font-weight:bolder;border:1px solid #000;padding:10px 25px}
  .stamp-footer{display:flex;justify-content:space-between;margin-top:0;padding-top:10px;flex-shrink:0}
  .stamp-footer .rodape-data{font-size:.9rem;color:#666;align-self:flex-end}
  .mensagem-comprador{border:2px dashed #000;padding:10px 14px;margin:10px 0;font-size:1.3rem}
  .mensagem-comprador .rotulo{display:block;font-size:.75rem;text-transform:uppercase;letter-spacing:.08em;color:#555;margin-bottom:4px}
  .custom-name-display{font-size:1.8rem;color:#000;font-weight:700;border:2px solid #000;padding:5px 10px;
    margin-top:10px;display:inline-block;text-transform:uppercase}
  @media print{
    .stamp-card{width:210mm;height:297mm;margin:0;padding:20mm;box-shadow:none;border:none;page-break-after:always}
    body{margin:0;padding:0}
  }`;

/** Monta o documento completo dos papeis. Exportado para poder ser testado. */
export function montarDocumentoDePapeis(orders) {
  return `<!doctype html><html><head><meta charset="utf-8" /><title>Papeis dos Pedidos</title>
    <style>${ESTILO}</style></head><body>${orders.map(cartaoHtml).join('')}</body></html>`;
}

/**
 * Busca e manda para a impressora os papeis dos pedidos informados.
 * Retorna { total, blocked } para a tela avisar o que ficou de fora.
 */
export async function imprimirPapeisDePedido(pedidoIds) {
  const { orders, blocked } = await buscarPapeisDePedido(pedidoIds);
  if (orders.length === 0) return { total: 0, blocked };

  const iframe = document.createElement('iframe');
  iframe.setAttribute('aria-hidden', 'true');
  iframe.style.position = 'fixed';
  iframe.style.right = '0';
  iframe.style.bottom = '0';
  iframe.style.width = '0';
  iframe.style.height = '0';
  iframe.style.border = '0';
  document.body.appendChild(iframe);

  iframe.onload = () => {
    iframe.contentWindow.focus();
    iframe.contentWindow.print();
    // O dialogo de impressao e sincrono na maioria dos navegadores, mas nao em
    // todos; a folga evita arrancar o documento debaixo da previa.
    setTimeout(() => iframe.remove(), 60_000);
  };

  iframe.contentDocument.open();
  iframe.contentDocument.write(montarDocumentoDePapeis(orders));
  iframe.contentDocument.close();

  return { total: orders.length, blocked };
}
