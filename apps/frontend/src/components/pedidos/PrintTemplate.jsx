import { useEffect, useState, useRef } from 'react'
import { Button } from '@/components/ui/button'
import { Printer, Loader2, AlertTriangle } from 'lucide-react'
import { api } from '@/services/api'
import { toast } from 'sonner'
import { formatAppDate } from '@/lib/dateTime'

/**
 * Componente de Template de Impressão (Stamp Cards)
 *
 * Replica a funcionalidade do kb/legado/templates/results.html:
 * - Cada pedido é renderizado como um "stamp card" (cartão A4)
 * - CSS @media print garante que cada card ocupe uma página inteira
 * - Botão "Imprimir" dispara window.print() via iframe off-screen
 */
export function PrintTemplate({ orderIds, onBack }) {
  const [orders, setOrders] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const iframeRef = useRef(null)

  useEffect(() => {
    if (!orderIds || orderIds.length === 0) return
    fetchOrders()
  }, [orderIds])

  const fetchOrders = async () => {
    try {
      setLoading(true)
      setError(null)
      const { data } = await api.get(
        `/pedidos/impressao?order_ids=${orderIds.join(',')}`
      )
      setOrders(data.orders || [])
      if (data.orders?.length === 0) {
        toast.warning('Nenhum pedido encontrado para impressão')
      }
    } catch (err) {
      console.error('Erro ao buscar dados de impressão:', err)
      setError('Erro ao carregar dados dos pedidos')
      toast.error('Erro ao carregar dados dos pedidos')
    } finally {
      setLoading(false)
    }
  }

  const handlePrint = () => {
    const printContent = document.getElementById('print-cards-container')
    if (!printContent) return

    const iframe = document.createElement('iframe')
    iframe.style.position = 'absolute'
    iframe.style.top = '-9999px'
    iframe.style.left = '-9999px'
    document.body.appendChild(iframe)

    const styles = `
      <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: Arial, sans-serif; }
        .grid-container { display: block; padding: 0; }
        .stamp-card {
          border: 1px solid #000;
          border-radius: 8px;
          padding: 20px;
          background-color: #fff;
          box-shadow: 0 2px 4px rgba(0,0,0,0.1);
          width: 100%;
          height: 100vh;
          page-break-after: always;
          display: flex;
          flex-direction: column;
          position: relative;
        }
        .stamp-header {
          display: flex;
          justify-content: space-between;
          font-size: 1.5rem;
          margin-bottom: 30px;
        }
        .stamp-header div div { padding: 15px 0; }
        .stamp-header img { margin-right: 10px; }
        .stamp-content {
          flex-grow: 1;
          display: flex;
          flex-direction: column;
          justify-content: space-between;
        }
        .stamp-content .order-info {
          text-align: center;
          font-size: 2.5rem;
          margin-bottom: 40px;
        }
        .stamp-content .order-info div { margin-bottom: 5px; }
        .stamp-content .item {
          display: flex;
          align-items: center;
          border-top: 1px solid #ddd;
          padding: 15px 0;
          margin-bottom: 15px;
        }
        .stamp-content .item:first-child { border-top: none; }
        .stamp-content .item-details { width: 80%; font-size: 1.2rem; }
        .stamp-content .item-details div { margin-bottom: 5px; }
        .stamp-content .item-quantity {
          width: 10%;
          text-align: center;
          font-size: 1.6rem;
        }
        .stamp-content .item-price {
          width: 10%;
          text-align: center;
          font-size: 0.8rem;
        }
        .custom-name-display {
          font-size: 1.8rem;
          color: #000;
          font-weight: 700;
          border: 2px solid #000;
          padding: 5px 10px;
          margin-top: 10px;
          display: inline-block;
          text-transform: uppercase;
        }
        .custom-tag {
          font-size: 1.8rem;
          font-weight: bolder;
          border: 1px solid #000;
          padding: 10px 25px;
        }
        .stamp-content .total-items {
          text-align: center;
          margin-top: auto;
          margin-bottom: 20px;
        }
        .stamp-content .total-items span { font-size: 2.5rem; }
        .stamp-footer {
          display: flex;
          justify-content: space-between;
          margin-top: auto;
          padding-top: 20px;
        }
        .variacao-text { font-size: 0.8rem; color: #666; }
        .ref-text { font-size: 0.8rem; color: #666; }
        .flex-badge {
          font-size: 1.2rem;
          font-weight: bold;
          color: #dc2626;
          border: 2px solid #dc2626;
          padding: 5px 15px;
          display: inline-block;
        }
        @media print {
          .stamp-card {
            width: 210mm;
            height: 297mm;
            margin: 0;
            padding: 20mm;
            box-shadow: none;
            border: none;
            page-break-after: always;
          }
          .grid-container { display: block; padding: 0; }
          body { margin: 0; padding: 0; }
          .no-print { display: none !important; }
        }
      </style>
    `

    const htmlContent = `
      <html>
        <head>
          <meta charset="utf-8">
          <title>Impressão de Pedidos</title>
          ${styles}
        </head>
        <body>
          <div class="grid-container">
            ${printContent.innerHTML}
          </div>
        </body>
      </html>
    `

    iframe.onload = () => {
      iframe.contentWindow.print()
      setTimeout(() => iframe.remove(), 1000)
    }

    iframe.contentDocument.open()
    iframe.contentDocument.write(htmlContent)
    iframe.contentDocument.close()
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-8 w-8 animate-spin text-blue-600" />
        <span className="ml-3 text-gray-600">Carregando dados de impressão...</span>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-red-600">
        <AlertTriangle className="h-8 w-8 mb-2" />
        <p>{error}</p>
        <Button variant="outline" className="mt-4" onClick={onBack}>
          Voltar
        </Button>
      </div>
    )
  }

  if (orders.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-gray-500">
        <p>Nenhum pedido encontrado</p>
        <Button variant="outline" className="mt-4" onClick={onBack}>
          Voltar
        </Button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Toolbar - não aparece na impressão */}
      <div className="no-print flex items-center justify-between bg-white p-4 rounded-lg shadow-sm border">
        <div>
          <h2 className="text-lg font-semibold">
            {orders.length} pedido{orders.length > 1 ? 's' : ''} para impressão
          </h2>
          <p className="text-sm text-gray-500">
            Cada pedido será impresso em uma página A4 separada
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={onBack}>
            Voltar
          </Button>
          <Button onClick={handlePrint} className="gap-2">
            <Printer className="h-4 w-4" />
            Imprimir
          </Button>
        </div>
      </div>

      {/* Container dos Stamp Cards (visível na tela, usado para print) */}
      <div id="print-cards-container" className="space-y-8">
        {orders.map((order) => (
          <StampCard key={order.id} order={order} />
        ))}
      </div>
    </div>
  )
}

/**
 * Stamp Card individual - replica o layout do results.html legado
 */
function StampCard({ order }) {
  const platformIcon = getPlatformIcon(order.plataforma)

  return (
    <div className="stamp-card border rounded-lg p-5 bg-white shadow-sm" style={{ minHeight: '800px' }}>
      {/* Header */}
      <div className="stamp-header flex justify-between mb-8">
        <div>
          <div className="py-2">
            <span className="font-medium">Nome:</span> {order.contato?.nome || 'Não identificado'}
          </div>
          {order.contato?.numeroDocumento && (
            <div className="py-2">
              <span className="font-medium">CPF:</span> {order.contato.numeroDocumento}
            </div>
          )}
          {order.contato?.endereco && (
            <div className="py-2">{order.contato.endereco}</div>
          )}
        </div>
        <div />
        <div className="text-right">
          <div className="flex items-center justify-end py-2">
            {platformIcon}
            <span className="font-medium">{order.plataforma || 'Pedido'}</span>
          </div>
          <div className="py-2 font-mono">{order.numeroLoja || 'N/A'}</div>
        </div>
      </div>

      {/* Content */}
      <div className="stamp-content flex-grow flex flex-col justify-between">
        {/* Order Info */}
        <div className="order-info text-center mb-10">
          <div className="text-2xl font-bold">Pedido {order.numero}</div>
        </div>

        {/* Items */}
        <div className="space-y-0">
          {order.itens?.map((item, idx) => (
            <div key={idx} className="item flex items-center border-t border-gray-200 py-4">
              <div className="item-details flex-grow pr-4">
                <div className="font-medium">{item.descricao}</div>
                {item.variacao && (
                  <div className="variacao-text">{item.variacao}</div>
                )}
                {item.codigo && (
                  <div className="font-bold mt-1">{item.codigo}</div>
                )}

                {/* Personalizações */}
                {item.personalizations?.length > 0 && (
                  <div className="mt-2">
                    {item.personalizations.map((p, pIdx) =>
                      p.customization_name ? (
                        <div
                          key={pIdx}
                          className="custom-name-display"
                        >
                          <i className="fas fa-pen-nib mr-1"></i>
                          {p.customization_name}
                          {p.customization_initial && (
                            <span className="ml-1">({p.customization_initial})</span>
                          )}
                          {p.quantity_to_personalize > 1 && (
                            <span className="ml-2 inline-block bg-yellow-100 text-yellow-800 text-xs font-semibold px-2 py-1 rounded">
                              x{p.quantity_to_personalize}
                            </span>
                          )}
                        </div>
                      ) : null
                    )}
                  </div>
                )}
              </div>
              <div className="item-quantity w-[10%] text-center text-xl font-bold">
                {item.quantidade}
              </div>
              <div className="item-price w-[10%] text-center text-sm">
                {formatCurrency(item.valor)}
              </div>
            </div>
          ))}

          {/* Total line */}
          <div className="item flex items-center border-t border-gray-200 py-4">
            <div className="item-details flex-grow" />
            <div className="item-quantity w-[10%]" />
            <div className="item-price w-[10%] text-center text-sm font-semibold">
              {formatCurrency(order.totalProdutos)}
            </div>
          </div>
        </div>

        {/* Total Items */}
        <div className="total-items text-center mt-auto mb-5">
          <span className="text-2xl font-bold">
            {order.total_items} {order.total_items > 1 ? 'itens' : 'item'}
          </span>
        </div>

        {/* Footer */}
        <div className="stamp-footer flex justify-between mt-auto pt-5 border-t border-gray-100">
          <div>
            {order.hasCustomItem === 1 &&
              order.itens?.map(
                (item, idx) =>
                  item.custom_tag && (
                    <div key={idx} className="custom-tag">{item.custom_tag}</div>
                  )
              )}
          </div>
          <div>
            {order.is_flex && (
              <div className="flex-badge">FLEX</div>
            )}
          </div>
          <div className="text-gray-500">
            {order.data_pedido ? formatDate(order.data_pedido) : ''}
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Helpers ──

function formatCurrency(value) {
  if (value == null) return 'R$ 0,00'
  return value.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}

function formatDate(dateStr) {
  if (!dateStr) return ''
  return formatAppDate(dateStr, { fallback: '' })
}

function getPlatformIcon(plataforma) {
  const icons = {
    Shopee: (
      <svg className="w-5 h-5 mr-1" viewBox="0 0 24 24" fill="#EE4D2D">
        <circle cx="12" cy="12" r="10" />
        <text x="12" y="16" textAnchor="middle" fill="white" fontSize="10" fontWeight="bold">S</text>
      </svg>
    ),
    Bling: (
      <svg className="w-5 h-5 mr-1" viewBox="0 0 24 24" fill="#0066CC">
        <circle cx="12" cy="12" r="10" />
        <text x="12" y="16" textAnchor="middle" fill="white" fontSize="10" fontWeight="bold">B</text>
      </svg>
    ),
  }
  return icons[plataforma] || null
}
