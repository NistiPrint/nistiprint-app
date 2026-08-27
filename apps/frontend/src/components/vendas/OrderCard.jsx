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

  if (order.needs_ai_processing) {
    return { label: 'Pendente IA', className: 'bg-amber-100 text-amber-900 border-amber-300' }
  }
  if (personalizations.some(p => p.status === 'NEEDS_REVIEW')) {
    return { label: 'A revisar', className: 'bg-orange-100 text-orange-900 border-orange-300' }
  }
  if (personalizations.some(p => p.customization_name)) {
    return { label: 'Nome identificado', className: 'bg-green-100 text-green-900 border-green-300' }
  }
  if (
    personalizations.some(
      p => p.status === 'NO_PERSONALIZATION_FOUND' || (!p.customization_name && p.status === 'SUCCESS'),
    ) ||
    order.ai_status === 'NO_PERSONALIZATION_FOUND'
  ) {
    return { label: 'Sem nome', className: 'bg-slate-100 text-slate-800 border-slate-300' }
  }
  if (!order.has_chat_messages) {
    return { label: 'Sem chat', className: 'bg-zinc-100 text-zinc-700 border-zinc-300' }
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

  return (
    <Card className='border shadow-sm transition-shadow duration-200 hover:shadow-md'>
      <CardContent className='space-y-2 px-4 py-3'>
        {/* Identificacao */}
        <div className='flex flex-wrap items-center gap-x-3 gap-y-1'>
          <Link
            to={`/vendas/pedidos/${order.id}`}
            className='text-base font-semibold text-blue-600 transition-colors hover:text-blue-800 hover:underline'
            title='Abrir a tela do pedido'>
            #{order.numero}
          </Link>

          {order.numeroLoja && (
            <span className='font-mono text-xs text-gray-500' title='Codigo do pedido na Shopee'>
              {order.numeroLoja}
            </span>
          )}

          {order.shopee?.username && (
            <span className='text-sm text-gray-700'>@{order.shopee.username}</span>
          )}

          <Badge variant='outline' className={`${statusBadge.className} text-xs`}>
            {statusBadge.label}
          </Badge>

          {order.chat_context_ambiguous && (
            <Badge variant='outline' className='border-amber-300 text-xs text-amber-700'>
              Contexto requer revisao
            </Badge>
          )}

          <div className='ml-auto flex items-center gap-1'>
            {/* O chat fica fora do menu porque e a acao que fecha o trabalho:
                ler a conversa e o que produz o nome que falta. */}
            <Button
              size='sm'
              variant={order.has_chat_messages ? 'outline' : 'ghost'}
              className='h-8 gap-1.5 px-2.5'
              disabled={!order.shopee?.username}
              onClick={() => onOpenChat(order.shopee?.username, order.numero, order)}
              title={
                order.shopee?.username
                  ? order.has_chat_messages
                    ? 'Abrir chat do comprador'
                    : 'Sem mensagens registradas para este comprador'
                  : 'Comprador nao identificado'
              }>
              <MessageCircleMore
                className={`h-4 w-4 ${order.has_chat_messages ? '' : 'text-gray-400'}`}
              />
              <span className='hidden sm:inline'>Chat</span>
            </Button>

            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button size='sm' variant='ghost' className='h-8 w-8 p-0' title='Mais acoes'>
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
                  Forcar reprocessamento
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

        {/* Mensagem do comprador no ato da compra: costuma conter o nome, entao
            fica no corpo e nao escondida atras de um clique. */}
        {order.shopee?.message && (
          <div className='flex items-start gap-2 rounded border border-blue-200 bg-blue-50 px-2.5 py-1.5 text-xs text-blue-800'>
            <MessageCircleMore className='mt-0.5 h-3.5 w-3.5 flex-shrink-0' />
            <span>{order.shopee.message}</span>
          </div>
        )}

        {/* Itens e personalizacao */}
        <div className='space-y-1'>
          {(order.itens || []).map((item, idx) => (
            <div
              key={idx}
              className={`flex flex-wrap items-baseline gap-x-2 gap-y-1 rounded px-2 py-1 text-sm ${
                item.personalizado ? 'bg-yellow-50' : ''
              }`}>
              <span className='font-semibold text-gray-700'>{item.quantidade}x</span>
              <span className='min-w-0 flex-1 truncate text-gray-900' title={item.descricao}>
                {item.descricao || 'Produto sem descricao'}
              </span>

              {item.personalizations?.length > 0 &&
                item.personalizations.map((p, pIdx) =>
                  p.customization_name ? (
                    <Badge
                      key={pIdx}
                      variant='outline'
                      className='cursor-pointer border-blue-200 transition-colors hover:bg-blue-50'
                      onClick={() => handleCopy(p.customization_name)}
                      title='Clique para copiar'>
                      <span className='font-semibold text-blue-700'>{p.customization_name}</span>
                      {p.customization_initial && (
                        <span className='ml-1 text-blue-600'>({p.customization_initial})</span>
                      )}
                      {p.quantity_to_personalize > 1 && (
                        <span className='ml-1 text-orange-700'>x{p.quantity_to_personalize}</span>
                      )}
                    </Badge>
                  ) : (
                    <Badge key={pIdx} variant='outline' className='border-slate-300 text-slate-600'>
                      Sem nome
                    </Badge>
                  ),
                )}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

export default OrderCard
