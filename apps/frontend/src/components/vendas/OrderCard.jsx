import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Brain,
  ExternalLink,
  FileText,
  Loader2,
  MessageCircleMore,
  ThumbsDown,
  ThumbsUp,
} from 'lucide-react'
import { toast } from 'sonner'
import { useState } from 'react'

function OrderCard({
  order,
  onOpenChat,
  onOpenAiLogs,
  onProcessAI,
  onFeedback,
}) {
  const [isProcessing, setIsProcessing] = useState(false);

  const handleCopyPersonalization = async name => {
    try {
      await navigator.clipboard.writeText(name)
      toast.success('Nome copiado para a área de transferência!')
    } catch (err) {
      toast.error('Erro ao copiar nome')
    }
  }

  const handleProcessClick = async () => {
    setIsProcessing(true);
    try {
      await onProcessAI(order.numeroLoja);
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <Card className='border shadow-sm hover:shadow-md transition-shadow duration-200'>
      <CardContent className='p-0'>
        <div className='grid grid-cols-1 md:grid-cols-12 gap-0'>
          {/* Coluna 1: Informações do Pedido */}
          <div className='md:col-span-3 p-4 border-r border-gray-200'>
            <div className='space-y-3'>
              {/* Número do Pedido */}
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

              {/* Informações do Cliente */}
              <div className='space-y-1'>
                <div className='flex items-center gap-2 text-sm text-gray-600'>
                  <span className='font-medium'>Cliente:</span>
                  <span>{order.contato?.nome || 'Não identificado'}</span>
                </div>
                {order.shopee?.username && (
                  <div className='flex items-center gap-2 text-sm text-gray-500'>
                    <span className='font-medium'>@</span>
                    <span>{order.shopee.username}</span>
                  </div>
                )}
              </div>

              {/* Data */}
              <div className='flex items-center gap-2 text-sm text-gray-600'>
                <span className='font-medium'>Data:</span>
                <span>{new Date(order.data).toLocaleDateString('pt-BR')}</span>
              </div>

              {/* Número da Loja */}
              <div className='flex items-center gap-2 text-sm'>
                <span className='font-medium text-gray-600'>Loja:</span>
                <span className='font-semibold'>
                  {order.numeroLoja || 'N/A'}
                </span>
              </div>
            </div>
          </div>

          {/* Coluna 2: Produtos */}
          <div className='md:col-span-6 p-4 border-r border-gray-200'>
            <div className='space-y-4'>
              {/* Mensagem do Shopee */}
              {order.shopee?.message && (
                <div className='bg-blue-50 border border-blue-200 rounded-lg p-3'>
                  <div className='flex items-start gap-2'>
                    <MessageCircleMore className='h-4 w-4 text-blue-600 mt-0.5 flex-shrink-0' />
                    <div className='text-sm text-blue-800'>
                      {order.shopee.message}
                    </div>
                  </div>
                </div>
              )}

              {/* Itens do Pedido */}
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
                      {/* Quantidade */}
                      <div className='flex-shrink-0 w-12 text-right'>
                        <span className='text-lg font-bold text-gray-700'>
                          {item.quantidade}x
                        </span>
                      </div>

                      {/* Detalhes do Produto */}
                      <div className='flex-grow min-w-0'>
                        <div className='font-medium text-gray-900 mb-1'>
                          {item.descricao || 'Produto sem descrição'}
                        </div>
                        {item.codigo && (
                          <div className='text-sm text-gray-600 mb-2'>
                            Código: {item.codigo}
                          </div>
                        )}

                        {/* Personalizações */}
                        {item.personalizations?.length > 0 && (
                          <div className='flex flex-wrap gap-2 mt-2'>
                            {item.personalizations.map(
                              (p, pIdx) =>
                                p.customization_name && (
                                  <div
                                    key={pIdx}
                                    className='flex items-center gap-2'>
                                    <Badge
                                      variant='outline'
                                      className='cursor-pointer hover:bg-blue-50 transition-colors border-blue-200'
                                      onClick={() =>
                                        handleCopyPersonalization(
                                          p.customization_name,
                                        )
                                      }
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
                                    {p.quantity_to_personalize > 1 && (
                                      <Badge
                                        variant='secondary'
                                        className='bg-orange-100 text-orange-800 border-orange-200'>
                                        x{p.quantity_to_personalize}
                                      </Badge>
                                    )}
                                  </div>
                                ),
                            )}
                          </div>
                        )}

                        {/* Descrição Detalhada */}
                        {item.produto?.descricaoDetalhada && (
                          <div className='mt-3 p-3 bg-white border border-gray-200 rounded-md'>
                            <div className='text-xs font-medium text-gray-600 mb-1'>
                              Descrição detalhada:
                            </div>
                            <div className='text-sm text-gray-800'>
                              {item.produto.descricaoDetalhada}
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Coluna 3: Ações */}
          <div className='md:col-span-3 p-4'>
            <div className='flex flex-col h-full'>
              <div className='flex-grow space-y-2'>
                {/* Botão Chat */}
                {order.has_chat_messages && (
                  <Button
                    size='sm'
                    variant='outline'
                    className='w-full justify-start'
                    onClick={() =>
                      onOpenChat(order.shopee?.username, order.numero, order)
                    }>
                    <MessageCircleMore className='h-4 w-4 mr-2' />
                    Abrir Chat
                  </Button>
                )}

                {/* Botão Logs IA */}
                <Button
                  size='sm'
                  variant='outline'
                  className='w-full justify-start'
                  onClick={() => onOpenAiLogs(order.numeroLoja)}>
                  <FileText className='h-4 w-4 mr-2' />
                  Ver Logs IA
                </Button>

                {/* Botão Processar IA */}
                <Button
                  size='sm'
                  variant='default'
                  className='w-full justify-start'
                  onClick={handleProcessClick}
                  disabled={!order.numeroLoja || isProcessing}
                  title={
                    !order.numeroLoja
                      ? 'Número do pedido Shopee não encontrado'
                      : 'Processar este pedido com IA'
                  }>
                  {isProcessing ? (
                    <Loader2 className='h-4 w-4 mr-2 animate-spin' />
                  ) : (
                    <Brain className='h-4 w-4 mr-2' />
                  )}
                  {isProcessing ? 'Processando...' : 'Processar IA'}
                </Button>
              </div>

              {/* Botões de Feedback */}
              <div className='flex gap-2 mt-4 pt-4 border-t border-gray-200'>
                <Button
                  size='sm'
                  variant='outline'
                  className='flex-1 h-8 text-green-600 border-green-200 hover:bg-green-50'
                  onClick={() => onFeedback(order.numero, 1)}
                  title='Marcar como correto'>
                  <ThumbsUp className='h-3 w-3' />
                </Button>
                <Button
                  size='sm'
                  variant='outline'
                  className='flex-1 h-8 text-red-600 border-red-200 hover:bg-red-50'
                  onClick={() => onFeedback(order.numero, 0)}
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
