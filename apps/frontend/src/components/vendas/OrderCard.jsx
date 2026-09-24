import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Brain,
  ExternalLink,
  FileText,
  Flag,
  Loader2,
  MessageCircleMore,
  MoreHorizontal,
  RefreshCw,
} from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'

/**
 * Uma linha de status por pedido, nao uma por personalizacao.
 *
 * A lista existe para responder "o que ainda falta extrair?", entao o rotulo
 * segue a ordem de urgencia do operador: o que precisa de acao aparece primeiro,
 * mesmo que o pedido tambem se encaixe num estado mais tranquilo depois.
 */
function getStatusBadge(order) {
  const personalizations = (order.itens || []).flatMap(item => item.personalizations || [])

  if (personalizations.some(p => p.status === 'NEEDS_REVIEW')) {
    return { label: 'A revisar', className: 'bg-orange-100 text-orange-900 border-orange-300' }
  }
  if (personalizations.some(p => p.status === 'SUCCESS' && p.customization_name?.trim())) {
    return {
      label: 'Nome identificado',
      className: 'bg-green-100 text-green-900 border-green-300',
      title: order.needs_ai_processing
        ? 'Nome já identificado. Há mensagem nova e o pedido será reprocessado pela IA.'
        : 'Nome identificado pela IA',
    }
  }
  if (order.needs_ai_processing) {
    return { label: 'Pendente IA', className: 'bg-amber-100 text-amber-900 border-amber-300' }
  }
  if (
    personalizations.some(
      p => p.status === 'NO_PERSONALIZATION_FOUND' || (!p.customization_name && p.status === 'SUCCESS'),
    ) ||
    order.ai_status === 'NO_PERSONALIZATION_FOUND'
  ) {
    return { label: 'Sem nome', className: 'bg-slate-100 text-slate-800 border-slate-300' }
  }
  return { label: 'Sem processamento', className: 'bg-gray-100 text-gray-700 border-gray-300' }
}

/**
 * Card enxuto de pedido personalizado.
 *
 * A tela e um painel de triagem: o operador percorre dezenas de pedidos
 * procurando o nome a gravar. Por isso o card mostra so o que se le de relance
 * — numero no Bling, codigo Shopee, comprador, itens e a personalizacao — e o
 * chat, que e a acao feita a partir da propria lista. Data, cliente do Bling,
 * carimbos de execucao e o resto vivem na tela do pedido, a um clique do
 * numero; acoes de manutencao vivem no menu, onde nao competem com a leitura.
 */
function OrderCard({ order, onOpenChat, onOpenAiLogs, onProcessAI, onReportProblem }) {
  const [isProcessing, setIsProcessing] = useState(false)
  const statusBadge = getStatusBadge(order)
  const buyerMessage = String(order.shopee?.message ?? '').trim()

  const handleCopy = async name => {
    try {
      await navigator.clipboard.writeText(name)
      toast.success('Nome copiado para a area de transferencia!')
    } catch {
      toast.error('Erro ao copiar nome')
    }
  }

  const handleProcessClick = async force => {
    setIsProcessing(true)
    try {
      await onProcessAI(order.numeroLoja, force)
    } finally {
      setIsProcessing(false)
    }
  }

  const orderDate = order.data ? String(order.data).slice(0, 10) : ''
  const formattedOrderDate = /^\d{4}-\d{2}-\d{2}$/.test(orderDate)
    ? orderDate.split('-').reverse().join('/')
    : orderDate

  return (
    <Card className='border shadow-sm transition-shadow duration-200 hover:shadow-md'>
      <CardContent className='p-3 sm:p-4'>
        <div className='grid gap-3 md:grid-cols-[minmax(190px,1fr)_minmax(0,4fr)_auto] md:gap-4'>
          <section className='space-y-2 md:border-r md:pr-4' aria-label='Dados do pedido'>
            <div>
              <Link
                to={`/vendas/pedidos/${order.id}`}
                className='text-lg font-semibold text-blue-700 transition-colors hover:text-blue-900 hover:underline'
                title='Abrir a tela do pedido'>
                #{order.numero}
              </Link>
              {order.numeroLoja && (
                <div className='mt-0.5 break-all font-mono text-xs text-gray-500' title='Código do pedido na Shopee'>
                  {order.numeroLoja}
                </div>
              )}
            </div>

            <div className='space-y-1 text-sm text-gray-600'>
              <div className='truncate font-medium text-gray-800' title={order.contato?.nome || order.nome_cliente || ''}>
                {order.contato?.nome || order.nome_cliente || 'Cliente não identificado'}
              </div>
              {order.shopee?.username && <div className='truncate'>@{order.shopee.username}</div>}
              {formattedOrderDate && <time className='block text-xs text-gray-500'>{formattedOrderDate}</time>}
            </div>

            <div className='flex flex-wrap gap-1.5'>
              <Badge variant='outline' title={statusBadge.title} className={`${statusBadge.className} text-xs`}>
                {statusBadge.label}
              </Badge>
              {order.chat_context_ambiguous && (
                <Badge variant='outline' className='border-amber-300 text-xs text-amber-700'>
                  Contexto requer revisão
                </Badge>
              )}
            </div>
          </section>

          <section className='min-w-0 space-y-2' aria-label='Produtos e personalizações'>
            {buyerMessage && (
              <div className='flex items-start gap-2 rounded border border-blue-200 bg-blue-50 px-2.5 py-2 text-sm text-blue-800'>
                <MessageCircleMore className='mt-0.5 h-4 w-4 flex-shrink-0' />
                <div className='min-w-0'>
                  <span className='font-semibold'>Mensagem do comprador:</span>{' '}
                  <span className='whitespace-pre-wrap break-words'>{buyerMessage}</span>
                </div>
              </div>
            )}

            <div className='space-y-2'>
              {(order.itens || []).map((item, idx) => (
                <div
                  key={item.id ?? idx}
                  className={`rounded-md border p-3 ${
                    item.personalizado
                      ? 'border-amber-300 bg-amber-50/60'
                      : 'border-gray-200 bg-white'
                  }`}>
                  <div className='flex items-start gap-2'>
                    <span className='min-w-9 pt-0.5 text-right text-base font-bold tabular-nums text-gray-800'>
                      {item.quantidade || 1}×
                    </span>
                    <div className='min-w-0 flex-1 space-y-1'>
                      <div className='font-semibold leading-snug text-gray-900' title={item.descricao}>
                        {item.descricao || 'Produto sem descrição'}
                      </div>
                      {item.codigo && <div className='text-xs text-gray-500'>{item.codigo}</div>}

                      {item.personalizations?.length > 0 && (
                        <div className='flex flex-wrap gap-2 pt-1'>
                          {item.personalizations.map((personalization, pIdx) =>
                            personalization.customization_name ? (
                              <button
                                key={personalization.id ?? pIdx}
                                type='button'
                                className='inline-flex max-w-full items-center gap-1.5 rounded-md border border-sky-300 bg-white px-3 py-1.5 text-left text-lg font-bold leading-snug text-sky-900 shadow-sm transition-colors hover:bg-sky-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-600'
                                onClick={() => handleCopy(personalization.customization_name)}
                                title={`Clique para copiar ${personalization.customization_name}`}>
                                <span className='break-words'>{personalization.customization_name}</span>
                                {personalization.customization_initial && (
                                  <span className='shrink-0 font-semibold text-sky-700'>
                                    ({personalization.customization_initial})
                                  </span>
                                )}
                                {personalization.quantity_to_personalize > 1 && (
                                  <span className='shrink-0 rounded bg-amber-100 px-1.5 py-0.5 text-sm font-semibold text-amber-900'>
                                    ×{personalization.quantity_to_personalize}
                                  </span>
                                )}
                              </button>
                            ) : (
                              <Badge
                                key={personalization.id ?? pIdx}
                                variant='outline'
                                className='border-slate-300 text-slate-600'>
                                Sem nome
                              </Badge>
                            ),
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </section>

          <div className='flex items-center gap-1 md:flex-col md:items-stretch md:justify-start'>
            <Button
              size='sm'
              variant={order.has_chat_messages ? 'outline' : 'ghost'}
              className='h-9 gap-1.5 px-2.5'
              disabled={!order.shopee?.username}
              onClick={() => onOpenChat(order.shopee?.username, order.numero, order)}
              title={
                order.shopee?.username
                  ? order.has_chat_messages
                    ? 'Abrir chat do comprador'
                    : 'Sem mensagens registradas para este comprador'
                  : 'Comprador não identificado'
              }>
              <MessageCircleMore
                className={`h-4 w-4 ${order.has_chat_messages ? '' : 'text-gray-400'}`}
              />
              <span>Chat</span>
            </Button>

            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button size='sm' variant='ghost' className='h-9 w-9 p-0' title='Mais ações' aria-label='Mais ações'>
                  {isProcessing ? (
                    <Loader2 className='h-4 w-4 animate-spin' />
                  ) : (
                    <MoreHorizontal className='h-4 w-4' />
                  )}
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align='end' className='w-56'>
                <DropdownMenuItem
                  disabled={!order.numeroLoja || isProcessing}
                  onSelect={() => handleProcessClick(false)}>
                  <Brain className='mr-2 h-4 w-4' />
                  {order.needs_ai_processing ? 'Processar com IA' : 'Processar (se pendente)'}
                </DropdownMenuItem>
                <DropdownMenuItem
                  disabled={!order.numeroLoja || isProcessing}
                  onSelect={() => handleProcessClick(true)}>
                  <RefreshCw className='mr-2 h-4 w-4' />
                  Forçar reprocessamento
                </DropdownMenuItem>
                <DropdownMenuItem
                  disabled={!order.numeroLoja}
                  onSelect={() => onOpenAiLogs(order.numeroLoja)}>
                  <FileText className='mr-2 h-4 w-4' />
                  Ver logs da IA
                </DropdownMenuItem>

                <DropdownMenuSeparator />

                <DropdownMenuItem asChild>
                  <a
                    href={`https://www.bling.com.br/vendas.php#edit/${order.id}`}
                    target='_blank'
                    rel='noopener noreferrer'>
                    <ExternalLink className='mr-2 h-4 w-4' />
                    Abrir no Bling
                  </a>
                </DropdownMenuItem>

                <DropdownMenuSeparator />

                <DropdownMenuItem
                  className='text-red-600 focus:bg-red-50 focus:text-red-700'
                  disabled={!order.numeroLoja}
                  onSelect={() => onReportProblem(order.numeroLoja)}>
                  <Flag className='mr-2 h-4 w-4' />
                  Relatar problema
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

export default OrderCard
