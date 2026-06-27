import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

import FiltrosPedidos from '@/components/pedidos/FiltrosPedidos'
import ProductionOrdersTable from '@/components/pedidos/ProductionOrdersTable'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { TooltipProvider } from '@/components/ui/tooltip'
import { getOrderTimestamps } from '@/lib/orderTimestamps'
import { CheckCircle2, ChevronDown, LayoutTemplate } from 'lucide-react'

function normalizeModalidade(order) {
  const raw = String(order.modalidade_logistica || '').trim().toUpperCase()
  if (raw === 'FLEX') return 'EXPRESS'
  if (raw) return raw
  if (order.is_flex) return 'EXPRESS'
  if (order.is_fulfillment) return 'FULFILLMENT'
  return 'STANDARD'
}

export default function PedidosListPageLotAware() {
  const navigate = useNavigate()

  const [pedidos, setPedidos] = useState([])
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [limit, setLimit] = useState(50)
  const [total, setTotal] = useState(0)
  const [pedidosSelecionados, setPedidosSelecionados] = useState([])
  const [availableIntegrations, setAvailableIntegrations] = useState([])
  const [loadingIntegrations, setLoadingIntegrations] = useState(false)
  const [statusOpcoes, setStatusOpcoes] = useState([])
  const [alterarSituacaoModalOpen, setAlterarSituacaoModalOpen] = useState(false)

  const [filtros, setFiltros] = useState({
    search: '',
    status_id: 2,
    bling_integration_id: null,
    canal_venda_id: null,
    origem_pedido_key: null,
    has_demanda: null,
    is_flex: null,
    is_fulfillment: null,
    is_personalizado: null,
    delivery_start: '',
    delivery_end: '',
    pedido_date_start: '',
    pedido_date_end: '',
  })

  const carregarStatusOpcoes = async () => {
    try {
      const response = await fetch('/api/v2/pedidos/status-opcoes')
      const data = await response.json()
      if (data.success) {
        setStatusOpcoes(data.data.status || [])
      }
    } catch (error) {
      console.error(error)
    }
  }

  const carregarPedidos = async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({
        page: page.toString(),
        limit: limit.toString(),
        sort: 'data_compra_marketplace',
        order: 'desc',
      })

      Object.entries(filtros).forEach(([key, value]) => {
        if (key === 'origem_pedido_key') {
          params.append(key, value || '')
        } else if (value !== null && value !== '') {
          params.append(key, value)
        }
      })

      const response = await fetch(`/api/v2/order/list-advanced?${params}`)
      const data = await response.json()
      if (!data.success) {
        toast.error(data.message || 'Erro ao carregar pedidos.')
        setPedidos([])
        setTotal(0)
        return
      }

      const responseData = data.data || {}
      const ordersData = responseData.orders || responseData.pedidos || []
      const mappedOrders = ordersData.map((order) => {
        const timestamps = getOrderTimestamps(order)
        return {
          ...order,
          numero_pedido: order.numero_pedido || order.numeroPedido || order.id,
          codigo_pedido_externo: order.codigo_pedido_externo || order.codigoPedidoExterno,
          canal_venda_nome:
            order.marketplace_nome ||
            order.canal_venda_nome ||
            order.canalVendaNome ||
            order.canal?.nome,
          data_compra_marketplace: timestamps.compra,
          data_pagamento_marketplace: timestamps.pagamento,
          data_coleta: timestamps.coleta,
          data_envio_marketplace: timestamps.envio,
          data_limite_envio: timestamps.limite,
          tem_demanda: order.tem_demanda || order.temDemanda || order.has_demanda || false,
          is_personalizado: order.is_personalizado || false,
          modalidade_logistica: normalizeModalidade(order),
          status: order.status || {
            id: order.situacao_pedido_id,
            nome: order.situacao_nome,
            cor: order.situacao_cor,
          },
        }
      })
      setPedidos(mappedOrders)
      setTotal(responseData.total ?? mappedOrders.length)
    } catch (error) {
      console.error(error)
      toast.error('Erro ao carregar pedidos.')
      setPedidos([])
      setTotal(0)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    carregarStatusOpcoes()
  }, [])

  useEffect(() => {
    carregarPedidos()
  }, [page, limit, filtros])

  const handleFiltroChange = (novoFiltro) => {
    setFiltros((current) => ({ ...current, ...novoFiltro }))
    setPage(1)
  }

  const handleLimparFiltros = () => {
    setFiltros({
      search: '',
      status_id: 2,
      bling_integration_id: null,
      canal_venda_id: null,
      origem_pedido_key: null,
      has_demanda: null,
      is_flex: null,
      is_fulfillment: null,
      is_personalizado: null,
      delivery_start: '',
      delivery_end: '',
      pedido_date_start: '',
      pedido_date_end: '',
    })
    setPage(1)
  }

  const handleSelecionarPedido = (pedidoId) => {
    setPedidosSelecionados((current) =>
      current.includes(pedidoId)
        ? current.filter((id) => id !== pedidoId)
        : [...current, pedidoId]
    )
  }

  const handleSelecionarTodos = () => {
    if (pedidosSelecionados.length === pedidos.length) {
      setPedidosSelecionados([])
      return
    }
    setPedidosSelecionados(pedidos.map((pedido) => pedido.id))
  }

  const loadAvailableIntegrations = async () => {
    if (!pedidosSelecionados.length) return
    setLoadingIntegrations(true)
    try {
      const response = await fetch('/api/v2/pedidos/sync-available-integrations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pedido_ids: pedidosSelecionados }),
      })
      const data = await response.json()
      if (data.integrations) {
        setAvailableIntegrations(data.integrations)
      }
    } catch (error) {
      console.error(error)
      toast.error('Erro ao carregar integracoes disponiveis.')
    } finally {
      setLoadingIntegrations(false)
    }
  }

  const handleSyncWithIntegration = async (integrationId, moduleId, instanceName) => {
    if (!pedidosSelecionados.length) {
      toast.error('Selecione pelo menos um pedido.')
      return
    }

    try {
      const response = await fetch('/api/v2/pedidos/sync-with-integration', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          pedido_ids: pedidosSelecionados,
          integration_id: integrationId,
          module_id: moduleId,
        }),
      })
      const data = await response.json()
      if (data.batch_id) {
        toast.info(`Sincronizacao iniciada com ${instanceName}.`)
        pollSyncProgress(data.batch_id)
        return
      }
      toast.error(data.error || 'Erro ao iniciar sincronizacao.')
    } catch (error) {
      console.error(error)
      toast.error('Erro ao iniciar sincronizacao.')
    }
  }

  const pollSyncProgress = (batchId) => {
    const interval = setInterval(async () => {
      try {
        const response = await fetch(`/api/v2/pedidos/sync-bling-status/${batchId}`)
        const data = await response.json()
        if (data.status === 'CONCLUIDO') {
          clearInterval(interval)
          toast.success(`Sincronizacao concluida: ${data.sucesso} sucesso, ${data.falha} falha.`)
          setPedidosSelecionados([])
          carregarPedidos()
        } else if (data.status === 'ERRO') {
          clearInterval(interval)
          toast.error('Erro no processamento da sincronizacao.')
        }
      } catch (error) {
        console.error(error)
      }
    }, 2000)
  }

  const handleAlterarSituacao = async (situacaoId, observacoes) => {
    if (!pedidosSelecionados.length) {
      toast.error('Selecione pelo menos um pedido.')
      return
    }

    try {
      const response = await fetch('/api/v2/pedidos/bulk-update-status', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          pedido_ids: pedidosSelecionados,
          situacao_pedido_id: situacaoId,
          observacoes,
        }),
      })

      const data = await response.json()
      if (response.ok) {
        toast.success(`Situacao alterada para ${pedidosSelecionados.length} pedido(s).`)
        setAlterarSituacaoModalOpen(false)
        setPedidosSelecionados([])
        carregarPedidos()
        return
      }
      toast.error(data.message || 'Erro ao alterar situacao.')
    } catch (error) {
      console.error(error)
      toast.error('Erro ao alterar situacao.')
    }
  }

  return (
    <div className='flex w-full max-w-7xl flex-col pb-20'>
      <div className='mb-8 flex flex-col gap-4 rounded-lg border bg-white p-4 shadow-sm lg:flex-row lg:items-center lg:justify-between'>
        <div>
          <h1 className='text-2xl font-bold tracking-tight'>Pedidos</h1>
          <p className='text-muted-foreground'>
            Use os pedidos para acompanhar a operacao e cair direto no lote sugerido.
          </p>
        </div>

        <div className='flex gap-3'>
          <Button variant='outline' onClick={() => navigate('/producao/demanda?tab=planning')} className='gap-2'>
            <LayoutTemplate className='h-4 w-4' />
            Ver planejamento
          </Button>
        </div>
      </div>

      <FiltrosPedidos
        filtros={filtros}
        onFiltroChange={handleFiltroChange}
        onLimparFiltros={handleLimparFiltros}
      />

      {pedidosSelecionados.length > 0 && (
        <Card className='mb-4 border-primary/20 bg-primary/5'>
          <CardContent className='flex items-center justify-between py-3'>
            <div className='flex items-center gap-2'>
              <CheckCircle2 className='h-5 w-5 text-primary' />
              <span className='font-medium'>
                {pedidosSelecionados.length} pedido(s) selecionado(s)
              </span>
            </div>
            <div className='flex gap-2'>
              <Button variant='outline' size='sm' onClick={() => setPedidosSelecionados([])}>
                Limpar selecao
              </Button>
              <Button
                variant='outline'
                size='sm'
                onClick={() => navigate('/producao/demanda?tab=planning')}
              >
                Ver lotes sugeridos
              </Button>
              <DropdownMenu
                onOpenChange={(open) => {
                  if (open) loadAvailableIntegrations()
                }}
              >
                <DropdownMenuTrigger asChild>
                  <Button variant='outline' size='sm'>
                    Sincronizar
                    <ChevronDown className='ml-2 h-4 w-4' />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align='end'>
                  {loadingIntegrations ? (
                    <DropdownMenuItem disabled>Carregando integracoes...</DropdownMenuItem>
                  ) : availableIntegrations.length === 0 ? (
                    <DropdownMenuItem disabled>Nenhuma integracao disponivel</DropdownMenuItem>
                  ) : (
                    availableIntegrations.map((integration) => (
                      <DropdownMenuItem
                        key={integration.id}
                        onClick={() =>
                          handleSyncWithIntegration(
                            integration.id,
                            integration.module_id,
                            integration.instance_name
                          )
                        }
                      >
                        {integration.instance_name}
                      </DropdownMenuItem>
                    ))
                  )}
                </DropdownMenuContent>
              </DropdownMenu>
              <Button variant='outline' size='sm' onClick={() => setAlterarSituacaoModalOpen(true)}>
                Alterar situacao
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      <TooltipProvider>
        <ProductionOrdersTable
          pedidos={pedidos}
          loading={loading}
          pedidosSelecionados={pedidosSelecionados}
          onSelecionarPedido={handleSelecionarPedido}
          onSelecionarTodos={handleSelecionarTodos}
          page={page}
          limit={limit}
          total={total}
          onPageChange={setPage}
          onLimitChange={setLimit}
        />
      </TooltipProvider>

      <AlterarSituacaoModal
        open={alterarSituacaoModalOpen}
        onOpenChange={setAlterarSituacaoModalOpen}
        statusOpcoes={statusOpcoes}
        onAlterar={handleAlterarSituacao}
        quantidadePedidos={pedidosSelecionados.length}
      />
    </div>
  )
}

function AlterarSituacaoModal({
  open,
  onOpenChange,
  statusOpcoes,
  onAlterar,
  quantidadePedidos,
}) {
  const [situacaoSelecionada, setSituacaoSelecionada] = useState('')
  const [observacoes, setObservacoes] = useState('')
  const [alterando, setAlterando] = useState(false)

  const handleAlterar = async () => {
    if (!situacaoSelecionada) {
      toast.error('Selecione uma situacao.')
      return
    }

    setAlterando(true)
    try {
      await onAlterar(parseInt(situacaoSelecionada, 10), observacoes)
      setSituacaoSelecionada('')
      setObservacoes('')
    } finally {
      setAlterando(false)
    }
  }

  if (!open) return null

  return (
    <div className='fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4'>
      <div className='w-full max-w-md rounded-lg bg-background'>
        <div className='border-b p-6'>
          <h2 className='text-2xl font-bold'>Alterar situacao em massa</h2>
          <p className='text-muted-foreground'>{quantidadePedidos} pedido(s) selecionado(s)</p>
        </div>

        <div className='space-y-4 p-6'>
          <div className='space-y-2'>
            <Label htmlFor='situacao'>Nova situacao</Label>
            <Select value={situacaoSelecionada} onValueChange={setSituacaoSelecionada}>
              <SelectTrigger id='situacao'>
                <SelectValue placeholder='Selecione a situacao' />
              </SelectTrigger>
              <SelectContent>
                {statusOpcoes.map((status) => (
                  <SelectItem key={status.id} value={String(status.id)}>
                    {status.nome}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className='space-y-2'>
            <Label htmlFor='obs'>Observacoes</Label>
            <Textarea
              id='obs'
              value={observacoes}
              onChange={(event) => setObservacoes(event.target.value)}
              rows={3}
            />
          </div>
        </div>

        <div className='flex justify-end gap-2 border-t p-6'>
          <Button variant='outline' onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button onClick={handleAlterar} disabled={alterando || !situacaoSelecionada}>
            {alterando ? 'Alterando...' : 'Confirmar alteracao'}
          </Button>
        </div>
      </div>
    </div>
  )
}
