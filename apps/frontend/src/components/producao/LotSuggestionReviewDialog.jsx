import { useEffect, useMemo, useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { confirmLotSuggestion, getLotSuggestionDetail } from '@/services/productionLotSuggestionsService'
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'

function buildDefaultName(detail) {
  if (detail?.complemento_demanda) {
    return `Complemento da demanda ${detail.complemento_demanda.demanda_id || detail.complemento_demanda.id}`
  }
  return `Lote ${detail?.marketplace_nome || ''} - ${detail?.modalidade_label || ''} - ${detail?.data_coleta_label || ''}`.trim()
}

export default function LotSuggestionReviewDialog({
  open,
  onOpenChange,
  suggestion,
  onConfirmed,
}) {
  const [loading, setLoading] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [detail, setDetail] = useState(null)
  const [selectedOrderIds, setSelectedOrderIds] = useState([])
  const [nomeDemanda, setNomeDemanda] = useState('')
  const [observacoes, setObservacoes] = useState('')

  useEffect(() => {
    if (!open || !suggestion?.suggestion_key) return

    let active = true
    setLoading(true)
    getLotSuggestionDetail(suggestion.suggestion_key)
      .then((response) => {
        if (!active) return
        const nextDetail = response.detail
        setDetail(nextDetail)
        setSelectedOrderIds((nextDetail.orders || []).map((order) => order.id))
        setNomeDemanda(buildDefaultName(nextDetail))
        setObservacoes('')
      })
      .catch((error) => {
        toast.error(error?.response?.data?.message || 'Nao foi possivel carregar o lote.')
        onOpenChange(false)
      })
      .finally(() => {
        if (active) setLoading(false)
      })

    return () => {
      active = false
    }
  }, [open, suggestion, onOpenChange])

  const selectedItemsSummary = useMemo(() => {
    if (!detail) return { pedidos: 0, itens: 0 }
    const selectedOrders = new Set(selectedOrderIds)
    const pedidos = detail.orders?.filter((order) => selectedOrders.has(order.id)) || []
    const itens = pedidos.reduce((total, order) => total + (order.total_itens || 0), 0)
    return { pedidos: pedidos.length, itens }
  }, [detail, selectedOrderIds])

  const selectedConsolidatedItems = useMemo(() => {
    if (!detail) return []
    const selectedOrders = new Set(selectedOrderIds)
    return (detail.items || [])
      .map((item) => {
        const quantidade = Object.entries(item.quantidades_por_pedido || {}).reduce(
          (total, [pedidoId, itemQuantidade]) => total + (selectedOrders.has(Number(pedidoId)) ? Number(itemQuantidade || 0) : 0),
          0
        )
        return {
          ...item,
          quantidade,
        }
      })
      .filter((item) => item.quantidade > 0)
  }, [detail, selectedOrderIds])
  const handleToggle = (orderId) => {
    setSelectedOrderIds((current) =>
      current.includes(orderId)
        ? current.filter((id) => id !== orderId)
        : [...current, orderId]
    )
  }

  const handleConfirm = async () => {
    if (!detail?.suggestion_key || selectedOrderIds.length === 0) {
      toast.error('Selecione pelo menos um pedido compativel.')
      return
    }

    setConfirming(true)
    try {
      const response = await confirmLotSuggestion({
        suggestion_key: detail.suggestion_key,
        included_order_ids: selectedOrderIds,
        nome_demanda: nomeDemanda,
        observacoes,
      })
      toast.success(response.message || 'Demanda criada com sucesso.')
      onConfirmed?.(response.result)
      onOpenChange(false)
    } catch (error) {
      toast.error(error?.response?.data?.message || 'Nao foi possivel confirmar o lote.')
    } finally {
      setConfirming(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='max-w-5xl max-h-[85vh] overflow-y-auto'>
        <DialogHeader>
          <DialogTitle>Revisao do lote logistico</DialogTitle>
          <DialogDescription>
            Revise os pedidos compativeis, ajuste a selecao e gere a demanda ativa.
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className='flex items-center justify-center py-16 text-slate-500'>
            <Loader2 className='mr-2 h-5 w-5 animate-spin' />
            Carregando lote...
          </div>
        ) : detail ? (
          <div className='space-y-6'>
            <div className='grid gap-4 md:grid-cols-4'>
              <div className='rounded-2xl border bg-slate-50 p-4'>
                <div className='text-xs uppercase tracking-wide text-slate-500'>Origem</div>
                <div className='mt-2 font-semibold text-slate-900'>{detail.marketplace_nome}</div>
              </div>
              <div className='rounded-2xl border bg-slate-50 p-4'>
                <div className='text-xs uppercase tracking-wide text-slate-500'>Modalidade</div>
                <div className='mt-2 font-semibold text-slate-900'>{detail.modalidade_label}</div>
              </div>
              <div className='rounded-2xl border bg-slate-50 p-4'>
                <div className='text-xs uppercase tracking-wide text-slate-500'>Coleta</div>
                <div className='mt-2 font-semibold text-slate-900'>{detail.data_coleta_label}</div>
              </div>
              <div className='rounded-2xl border bg-slate-50 p-4'>
                <div className='text-xs uppercase tracking-wide text-slate-500'>Selecao</div>
                <div className='mt-2 font-semibold text-slate-900'>
                  {selectedItemsSummary.pedidos} pedidos / {selectedItemsSummary.itens} unidades
                </div>
              </div>
            </div>

            <div className='grid gap-6 lg:grid-cols-[1.3fr_0.9fr]'>
              <div className='space-y-4'>
                <div className='rounded-2xl border'>
                  <div className='border-b px-4 py-3'>
                    <div className='font-medium text-slate-900'>Pedidos compativeis</div>
                    <div className='text-sm text-slate-500'>
                      Pode excluir ou reincluir somente pedidos deste mesmo lote.
                    </div>
                  </div>
                  <div className='divide-y'>
                    {(detail.orders || []).map((order) => (
                      <label
                        key={order.id}
                        className='flex cursor-pointer items-start gap-3 px-4 py-3 hover:bg-slate-50'
                      >
                        <Checkbox
                          checked={selectedOrderIds.includes(order.id)}
                          onCheckedChange={() => handleToggle(order.id)}
                        />
                        <div className='flex-1 space-y-1'>
                          <div className='flex flex-wrap items-center gap-2'>
                            <span className='font-medium text-slate-900'>
                              {order.numero_pedido || order.codigo_pedido_externo || `Pedido ${order.id}`}
                            </span>
                            {order.is_personalizado && (
                              <Badge variant='outline' className='border-amber-200 bg-amber-50 text-amber-800'>
                                Personalizado
                              </Badge>
                            )}
                          </div>
                          <div className='text-sm text-slate-600'>
                            {order.cliente_nome || 'Cliente nao informado'}
                          </div>
                          <div className='text-xs text-slate-500'>
                            {order.total_itens} unidades
                          </div>
                        </div>
                      </label>
                    ))}
                  </div>
                </div>

                <div className='rounded-2xl border'>
                  <div className='border-b px-4 py-3 font-medium text-slate-900'>
                    Consolidado previsto ({selectedConsolidatedItems.length || 0} SKUs)
                  </div>
                  <div className='divide-y'>
                    {selectedConsolidatedItems.map((item) => (
                      <div key={`${item.produto_id || 'x'}-${item.sku || 'sem-sku'}`} className='flex items-center justify-between px-4 py-3'>
                        <div>
                          <div className='font-medium text-slate-900'>{item.descricao}</div>
                          <div className='text-xs text-slate-500'>{item.sku || 'Sem SKU'}</div>
                        </div>
                        <div className='text-right font-semibold text-slate-900'>{item.quantidade}</div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div className='space-y-4'>
                <div className='rounded-2xl border bg-slate-50 p-4 space-y-3'>
                  <div className='text-sm font-medium text-slate-900'>Janela logistica</div>
                  <div className='text-sm text-slate-600'>Corte {detail.horario_corte || '--:--'}</div>
                  <div className='text-sm text-slate-600'>Coleta {detail.horario_coleta || '--:--'}</div>
                  {detail.tipo_envio && <div className='text-sm text-slate-600'>{detail.tipo_envio}</div>}
                  {detail.ponto_coleta_nome && <div className='text-sm text-slate-600'>{detail.ponto_coleta_nome}</div>}
                </div>

                <div className='space-y-2'>
                  <label className='text-sm font-medium text-slate-900'>Nome da demanda</label>
                  <Input value={nomeDemanda} onChange={(event) => setNomeDemanda(event.target.value)} />
                </div>

                <div className='space-y-2'>
                  <label className='text-sm font-medium text-slate-900'>Observacoes</label>
                  <Textarea
                    value={observacoes}
                    onChange={(event) => setObservacoes(event.target.value)}
                    placeholder='Opcional'
                    rows={4}
                  />
                </div>

                {detail.exceptions?.length > 0 && (
                  <div className='rounded-2xl border border-amber-200 bg-amber-50 p-4'>
                    <div className='text-sm font-medium text-amber-900'>Excecoes da mesma origem</div>
                    <div className='mt-2 space-y-2 text-sm text-amber-800'>
                      {detail.exceptions.slice(0, 5).map((exception) => (
                        <div key={`${exception.pedido_id}-${exception.motivo}`}>
                          {exception.numero_pedido || exception.pedido_id}: {exception.motivo}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        ) : null}

        <DialogFooter>
          <Button variant='outline' onClick={() => onOpenChange(false)} disabled={confirming}>
            Cancelar
          </Button>
          <Button onClick={handleConfirm} disabled={confirming || selectedOrderIds.length === 0}>
            {confirming ? (
              <>
                <Loader2 className='mr-2 h-4 w-4 animate-spin' />
                Criando demanda...
              </>
            ) : (
              'Confirmar e criar demanda'
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}



