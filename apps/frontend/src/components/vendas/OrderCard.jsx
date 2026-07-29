import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Brain,
  Clock3,
  ExternalLink,
  FileText,
  Loader2,
  MessageCircleMore,
  RefreshCw,
  ThumbsDown,
  ThumbsUp,
} from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

function getPersonalizationSummary(order) {
  const personalizations = (order.itens || []).flatMap(item => item.personalizations || [])
  const hasName = personalizations.some(p => p.customization_name)
  const needsReview = personalizations.some(p => p.status === 'NEEDS_REVIEW')
  const noName = personalizations.some(
    p => p.status === 'NO_PERSONALIZATION_FOUND' || (!p.customization_name && p.status === 'SUCCESS'),
  )

  if (order.needs_ai_processing) {
    return { label: 'Pendente IA', className: 'bg-amber-100 text-amber-900 border-amber-300' }
  }
  if (needsReview) {
    return { label: 'A revisar', className: 'bg-orange-100 text-orange-900 border-orange-300' }
  }
  if (hasName) {
    return { label: 'Nome identificado', className: 'bg-green-100 text-green-900 border-green-300' }
  }
  if (noName || order.ai_status === 'NO_PERSONALIZATION_FOUND') {
    return { label: 'Sem nome', className: 'bg-slate-100 text-slate-800 border-slate-300' }
  }
  if (!order.has_chat_messages) {
    return { label: 'Sem chat', className: 'bg-zinc-100 text-zinc-700 border-zinc-300' }
  }
  return { label: 'Sem processamento', className: 'bg-gray-100 text-gray-700 border-gray-300' }
}

function formatDateTime(value) {
  if (!value) return null
  try {
    return new Date(value).toLocaleString('pt-BR')
  } catch {
    return null
  }
}

function OrderCard({
  order,
  onOpenChat,
  onOpenAiLogs,
  onProcessAI,
  onFeedback,
}) {
  const [isProcessing, setIsProcessing] = useState(false)
  const statusBadge = getPersonalizationSummary(order)
  const processButtonLabel = order.needs_ai_processing ? 'Processar IA' : 'Reprocessar IA'

  const handleCopyPersonalization = async name => {
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

  return (
    <Card className='border shadow-sm hover:shadow-md transition-shadow duration-200'>
      <CardContent className='p-0'>
        <div className='grid grid-cols-1 md:grid-cols-12 gap-0'>
          <div className='md:col-span-3 p-4 border-r border-gray-200'>
            <div className='space-y-3'>
              <div>
                <a
                  href={`https://www.bling.com.br/vendas.php#edit/${order.id}`}
                  target='_blank'
                  rel='noopener noreferrer'
                  className='inline-flex items-center gap-2 text-lg font-semibold text-blue-600 hover:text-blue-800 transition-colors'>
                  #{order.numero}
                  <ExternalLink className='h-4 w-4' />
                </a>
              </div>

              <div className='flex flex-wrap gap-2'>
                <Badge variant='outline' className={statusBadge.className}>
                  {statusBadge.label}
                </Badge>
                {order.chat_context_ambiguous && (
                  <Badge variant='outline' className='border-amber-300 text-amber-700'>
                    Contexto requer revisao
                  </Badge>
                )}
                {order.ai_status && (
                  <Badge variant='outline' className='border-slate-300 text-slate-700'>
                    {String(order.ai_status).replaceAll('_', ' ')}
                  </Badge>
                )}
              </div>

              <div className='space-y-1'>
                <div className='flex items-center gap-2 text-sm text-gray-600'>
                  <span className='font-medium'>Cliente:</span>
                  <span>{order.contato?.nome || 'Nao identificado'}</span>
                </div>
                {order.shopee?.username && (
                  <div className='flex items-center gap-2 text-sm text-gray-500'>
                    <span className='font-medium'>@</span>
                    <span>{order.shopee.username}</span>
                  </div>
                )}
              </div>

              <div className='flex items-center gap-2 text-sm text-gray-600'>
                <span className='font-medium'>Data:</span>
                <span>{new Date(order.data).toLocaleDateString('pt-BR')}</span>
              </div>

              <div className='flex items-center gap-2 text-sm'>
                <span className='font-medium text-gray-600'>Loja:</span>
                <span className='font-semibold'>{order.numeroLoja || 'N/A'}</span>
              </div>

              {(order.last_ai_executed_at || order.last_buyer_message_at) && (
                <div className='space-y-1 text-xs text-gray-500'>
                  {order.last_ai_executed_at && (
                    <div className='flex items-start gap-2'>
                      <Clock3 className='h-3.5 w-3.5 mt-0.5' />
                      <span>IA: {formatDateTime(order.last_ai_executed_at)}</span>
                    </div>
                  )}
                  {order.last_buyer_message_at && (
                    <div className='flex items-start gap-2'>
                      <MessageCircleMore className='h-3.5 w-3.5 mt-0.5' />
                      <span>Ultima msg comprador: {formatDateTime(order.last_buyer_message_at)}</span>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          <div className='md:col-span-6 p-4 border-r border-gray-200'>
            <div className='space-y-4'>
              {order.shopee?.message && (
                <div className='bg-blue-50 border border-blue-200 rounded-lg p-3'>
                  <div className='flex items-start gap-2'>
                    <MessageCircleMore className='h-4 w-4 text-blue-600 mt-0.5 flex-shrink-0' />
                    <div className='text-sm text-blue-800'>{order.shopee.message}</div>
                  </div>
                </div>
              )}

              <div className='space-y-3'>
                {order.itens?.map((item, idx) => (
                  <div
                    key={idx}
                    className={`border rounded-lg p-3 ${
                      item.personalizado
                        ? 'border-yellow-300 bg-yellow-50'
                        : 'border-gray-200 bg-gray-50'
                    }`}>
                    <div className='flex items-start gap-3'>
                      <div className='flex-shrink-0 w-12 text-right'>
                        <span className='text-lg font-bold text-gray-700'>
                          {item.quantidade}x
                        </span>
                      </div>

                      <div className='flex-grow min-w-0'>
                        <div className='font-medium text-gray-900 mb-1'>
                          {item.descricao || 'Produto sem descricao'}
                        </div>
                        {item.codigo && (
                          <div className='text-sm text-gray-600 mb-2'>Codigo: {item.codigo}</div>
                        )}

                        {item.personalizations?.length > 0 && (
                          <div className='flex flex-wrap gap-2 mt-2'>
                            {item.personalizations.map((p, pIdx) => (
                              <div key={pIdx} className='flex items-center gap-2 flex-wrap'>
                                {p.customization_name ? (
                                  <Badge
                                    variant='outline'
                                    className='cursor-pointer hover:bg-blue-50 transition-colors border-blue-200'
                                    onClick={() => handleCopyPersonalization(p.customization_name)}
                                    title='Clique para copiar'>
                                    <span className='font-semibold text-blue-700'>
                                      {p.customization_name}
                                    </span>
                                    {p.customization_initial && (
                                      <span className='ml-1 text-blue-600'>
                                        ({p.customization_initial})
                                      </span>
                                    )}
                                  </Badge>
                                ) : (
                                  <Badge variant='outline' className='border-slate-300 text-slate-600'>
                                    Sem nome identificado
                                  </Badge>
                                )}

                                {p.quantity_to_personalize > 1 && (
                                  <Badge
                                    variant='secondary'
                                    className='bg-orange-100 text-orange-800 border-orange-200'>
                                    x{p.quantity_to_personalize}
                                  </Badge>
                                )}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className='md:col-span-3 p-4'>
            <div className='flex flex-col h-full'>
              <div className='flex-grow space-y-2'>
                {order.has_chat_messages && (
                  <Button
                    size='sm'
                    variant='outline'
                    className='w-full justify-start'
                    onClick={() => onOpenChat(order.shopee?.username, order.numero, order)}>
                    <MessageCircleMore className='h-4 w-4 mr-2' />
                    Abrir Chat
                  </Button>
                )}

                <Button
                  size='sm'
                  variant='outline'
                  className='w-full justify-start'
                  onClick={() => onOpenAiLogs(order.numeroLoja)}>
                  <FileText className='h-4 w-4 mr-2' />
                  Ver Logs IA
                </Button>

                <Button
                  size='sm'
                  variant='default'
                  className='w-full justify-start'
                  onClick={() => handleProcessClick(false)}
                  disabled={!order.numeroLoja || isProcessing}
                  title={!order.numeroLoja ? 'Numero do pedido Shopee nao encontrado' : 'Processar este pedido com IA'}>
                  {isProcessing ? (
                    <Loader2 className='h-4 w-4 mr-2 animate-spin' />
                  ) : (
                    <Brain className='h-4 w-4 mr-2' />
                  )}
                  {isProcessing ? 'Processando...' : processButtonLabel}
                </Button>

                {!order.needs_ai_processing && (
                  <Button
                    size='sm'
                    variant='outline'
                    className='w-full justify-start'
                    onClick={() => handleProcessClick(true)}
                    disabled={!order.numeroLoja || isProcessing}>
                    <RefreshCw className='h-4 w-4 mr-2' />
                    Forcar reprocessamento
                  </Button>
                )}
              </div>

              <div className='flex gap-2 mt-4 pt-4 border-t border-gray-200'>
                <Button
                  size='sm'
                  variant='outline'
                  className='flex-1 h-8 text-green-600 border-green-200 hover:bg-green-50'
                  onClick={() => onFeedback(order.numeroLoja, 1)}
                  title='Marcar como correto'>
                  <ThumbsUp className='h-3 w-3' />
                </Button>
                <Button
                  size='sm'
                  variant='outline'
                  className='flex-1 h-8 text-red-600 border-red-200 hover:bg-red-50'
                  onClick={() => onFeedback(order.numeroLoja, 0)}
                  title='Reportar erro'>
                  <ThumbsDown className='h-3 w-3' />
                </Button>
              </div>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

export default OrderCard
