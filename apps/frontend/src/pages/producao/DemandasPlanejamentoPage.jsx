import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'

import DemandaCard from '@/components/producao/DemandaCard'
import CollectedDemandsModal from '@/components/producao/CollectedDemandsModal'
import DailyProductionModal from '@/components/producao/DailyProductionModal'
import PartialCollectionModal from '@/components/producao/PartialCollectionModal'
import SummaryCards from '@/components/producao/SummaryCards'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { TooltipProvider } from '@/components/ui/tooltip'
import { useAuth } from '@/contexts/AuthContext'
import { createOperationId } from '@/lib/operationId'
import usePermissionsHook from '@/hooks/usePermissions'
import { useRealtimeDemandas } from '@/lib/hooks/useRealtimeDemandas'
import { deriveDemandFlow, DEMANDA_FLOW_OPTIONS } from '@/lib/demandaFlow'
import {
  BarChart3,
  CheckSquare,
  Factory,
  RefreshCw,
  Truck,
  X,
} from 'lucide-react'

const TERMINAL_DEMAND_STATUSES = ['FINALIZADO', 'CONCLUIDO', 'COLETADO', 'CANCELADO']

// RASCUNHO nao aparece aqui de proposito. Um rascunho e uma consolidacao ainda
// aberta na Torre de Despacho: ela pertence a tela onde o operador a montou e
// pode somar pedidos nela, nao a esta, que existe para acompanhar o que ja foi
// entregue ao galpao. Enquanto os dois moravam juntos, publicar virava uma
// acao possivel em duas telas — e a segunda nao sabia dizer contra qual painel
// de marketplace aquele total tinha sido conferido.
const DRAFT_DEMAND_STATUSES = ['RASCUNHO']
const collectionRequestId = (demandId, quantity) => {
  const key = `demand-collection:${demandId}`
  let saved = null
  try { saved = JSON.parse(sessionStorage.getItem(key) || 'null') } catch { saved = null }
  const quantityKey = String(quantity)
  if (saved?.quantity === quantityKey && saved?.id) return { key, id: saved.id }
  const id = createOperationId()
  sessionStorage.setItem(key, JSON.stringify({ quantity: quantityKey, id }))
  return { key, id }
}

function normalizeDemandStatus(status) {
  return String(status || '').trim().toUpperCase()
}

function normalizeModalidade(value) {
  const raw = String(value || '').trim().toUpperCase()
  if (raw === 'FLEX') return 'EXPRESS'
  return raw || 'STANDARD'
}

export default function DemandasPlanejamentoPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const { user, hasPermission } = useAuth()
  const { canExecuteAction } = usePermissionsHook()

  const userSetor = user?.setor_nome || (user?.is_admin ? 'Administrador' : null)
  const canUseAdminDemandActions = user?.is_admin === true || hasPermission('demanda_producao', 'editar')
  const canDeleteDemand = user?.is_admin === true || (hasPermission('demanda_producao', 'excluir') && canExecuteAction('delete_demand'))
  const canCancelDemand = canDeleteDemand
  const canUseExpeditionDemandActions = user?.is_admin === true || (
    hasPermission('demanda_producao', 'editar') &&
    (canExecuteAction('finalize_item') || canExecuteAction('collect_demand'))
  )

  // 'planning' era a aba de sugestoes automaticas de lote. Um link antigo com
  // ?tab=planning cai em 'active' em vez de numa aba que nao existe mais.
  const rawTab = searchParams.get('tab')
  const currentTab = rawTab === 'active' || rawTab === 'history' ? rawTab : 'active'

  const [searchTerm, setSearchTerm] = useState('')
  const [channelFilter, setChannelFilter] = useState('all')
  const [modalidadeFilter, setModalidadeFilter] = useState('all')
  const [flowFilter, setFlowFilter] = useState('all')

  const [dashboardSummary, setDashboardSummary] = useState(null)
  const [totals, setTotals] = useState(null)

  const [selectedDemandIds, setSelectedDemandIds] = useState([])
  const [pendingChanges, setPendingChanges] = useState({})
  const [savingField, setSavingField] = useState(false)

  const [isDailyTotalsModalOpen, setIsDailyTotalsModalOpen] = useState(false)
  const [isCollectedDemandsModalOpen, setIsCollectedDemandsModalOpen] = useState(false)
  const [isPartialCollectionModalOpen, setIsPartialCollectionModalOpen] = useState(false)
  const [selectedDemandIdForCollection, setSelectedDemandIdForCollection] = useState(null)

  const { demandas, setDemandas, loading, error, refresh, realtimeConnected, lastUpdatedAt } = useRealtimeDemandas(pendingChanges)

  const fetchTotals = useCallback(async () => {
    try {
      const response = await fetch('/api/v2/demanda_producao/dashboard-totals')
      const data = await response.json()
      if (data.success) setTotals(data)
    } catch (fetchError) {
      console.error(fetchError)
    }
  }, [])

  const fetchDashboardSummary = useCallback(async () => {
    try {
      const response = await fetch('/api/v2/demanda_producao/dashboard-summary')
      const data = await response.json()
      if (data.success) setDashboardSummary(data)
    } catch (fetchError) {
      console.error(fetchError)
    }
  }, [])

  useEffect(() => {
    fetchTotals()
    fetchDashboardSummary()
  }, [fetchTotals, fetchDashboardSummary])

  // Simulações não passam pelo fluxo real (sem coleta/exclusão pelos endpoints
  // de demanda): aparecem em seção própria, abrindo o dashboard da simulação.
  const [simulacoes, setSimulacoes] = useState([])
  useEffect(() => {
    if (!hasPermission('demanda_producao', 'ler')) return
    fetch('/api/v2/demanda-simulacoes')
      .then((response) => (response.ok ? response.json() : null))
      .then((json) => { if (json?.success) setSimulacoes(json.data || []) })
      .catch(() => {})
  }, [hasPermission])
  const visibleSimulacoes = useMemo(() => {
    const search = searchTerm.trim().toLowerCase()
    return simulacoes.filter((simulacao) => {
      const terminal = TERMINAL_DEMAND_STATUSES.includes(normalizeDemandStatus(simulacao.status))
      if ((currentTab === 'history') !== terminal) return false
      return !search || String(simulacao.nome || '').toLowerCase().includes(search)
    })
  }, [simulacoes, currentTab, searchTerm])

  const filteredDemandas = useMemo(() => {
    const search = searchTerm.trim().toLowerCase()
    return demandas.filter((demanda) => {
      const status = normalizeDemandStatus(demanda.status)
      // Ativas = tudo que ja foi entregue ao galpao e ainda nao terminou.
      // Consolidacao aberta (RASCUNHO) fica de fora: ela vive na Torre.
      if (currentTab === 'active' && (TERMINAL_DEMAND_STATUSES.includes(status) || DRAFT_DEMAND_STATUSES.includes(status))) {
        return false
      }
      if (currentTab === 'history' && !TERMINAL_DEMAND_STATUSES.includes(status)) {
        return false
      }

      if (search) {
        const haystack = [
          demanda.nome,
          demanda.id,
          demanda.canal_venda_nome,
          demanda.empresa_cliente_nome,
        ]
          .filter(Boolean)
          .join(' ')
          .toLowerCase()
        if (!haystack.includes(search)) return false
      }

      if (channelFilter !== 'all') {
        const channelName = demanda.canal_venda_nome || demanda.canal_venda_id
        if (String(channelName) !== channelFilter) return false
      }

      if (modalidadeFilter !== 'all' && normalizeModalidade(demanda.modalidade_logistica) !== modalidadeFilter) {
        return false
      }

      if (flowFilter !== 'all' && deriveDemandFlow(demanda) !== flowFilter) {
        return false
      }

      return true
    })
  }, [channelFilter, currentTab, demandas, flowFilter, modalidadeFilter, searchTerm])

  const uniqueChannels = useMemo(() => {
    const channels = new Set(
      demandas
        .map((demanda) => demanda.canal_venda_nome || demanda.canal_venda_id)
        .filter(Boolean)
    )
    return Array.from(channels).sort()
  }, [demandas])

  const demandasColetadas = useMemo(() => {
    return demandas.filter((demanda) => normalizeDemandStatus(demanda.status) === 'COLETADO')
  }, [demandas])

  const demandasAguardandoColeta = useMemo(() => {
    return demandas.filter((demanda) => normalizeDemandStatus(demanda.status) === 'CONCLUIDO')
  }, [demandas])

  const handleFieldUpdate = useCallback((demandaId, fieldName, newValue) => {
    setPendingChanges((current) => {
      const nextDemandChanges = current[demandaId] || {}
      return { ...current, [demandaId]: { ...nextDemandChanges, [fieldName]: newValue } }
    })
    setDemandas((current) =>
      current.map((item) => (item.id === demandaId ? { ...item, [fieldName]: newValue } : item))
    )
  }, [setDemandas])

  const handleBulkSave = async () => {
    const demandIds = Object.keys(pendingChanges)
    if (demandIds.length === 0) return
    setSavingField(true)
    try {
      await Promise.all(
        demandIds.map(async (id) => {
          const response = await fetch(`/api/v2/demanda_producao/demanda/${id}/detalhes`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(pendingChanges[id]),
          })
          if (!response.ok) throw new Error(`Erro ao salvar demanda ${id}`)
        })
      )
      toast.success('Alteracoes salvas.')
      setPendingChanges({})
    } catch (saveError) {
      toast.error(saveError.message || 'Nao foi possivel salvar.')
    } finally {
      setSavingField(false)
      refresh()
    }
  }

  const handleCancelChanges = () => {
    setPendingChanges({})
    refresh()
  }

  const handleFinalizeDemand = useCallback(async (id) => {
    if (!canUseExpeditionDemandActions) return toast.error('Sem permissao.')
    if (!window.confirm('Finalizar demanda?')) return
    const response = await fetch(`/api/v2/demanda_producao/${id}/finalizar_demanda`, { method: 'POST' })
    if (response.ok) {
      toast.success('Demanda finalizada.')
      refresh()
      return
    }
    const errorData = await response.json()
    toast.error(errorData.message || 'Nao foi possivel finalizar.')
  }, [canUseExpeditionDemandActions, refresh])

  const handleCollectDemand = useCallback((id) => {
    if (!canUseExpeditionDemandActions) return toast.error('Sem permissao.')
    setSelectedDemandIdForCollection(id)
    setIsPartialCollectionModalOpen(true)
  }, [canUseExpeditionDemandActions])

  const handleConfirmPartialCollection = async (demandaId, quantity) => {
    const operation = collectionRequestId(demandaId, quantity)
    const response = await fetch(`/api/v2/demanda_producao/${demandaId}/coletar`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ quantidade_coletar: quantity, operation_id: operation.id }),
    })
    const data = await response.json()
    if (response.ok && data.success) {
      sessionStorage.removeItem(operation.key)
      toast.success(data.message || 'Coleta registrada.')
      refresh()
      return
    }
    throw new Error(data.message || 'Nao foi possivel registrar a coleta.')
  }

  const handleBatchCollect = async () => {
    if (!selectedDemandIds.length) return
    if (!window.confirm(`Marcar ${selectedDemandIds.length} demandas como coletadas?`)) return

    const response = await fetch('/api/v2/demanda_producao/batch/coletar', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids: selectedDemandIds }),
    })
    const data = await response.json()
    if (response.ok) {
      toast.success(`${selectedDemandIds.length} demandas coletadas.`)
      setSelectedDemandIds([])
      refresh()
      return
    }
    toast.error(data.message || 'Nao foi possivel coletar em lote.')
  }

  // Publicar e o momento em que o galpao assume o lote: e aqui que despachado_em
  // e carimbado e os pedidos saem da torre de despacho. Por isso a rota e a do
  // despacho, e nao a antiga /demanda_producao/:id/publicar, que so mudava o
  // status e deixava os pedidos aparecendo na torre como se ninguem os tivesse
  // assumido.
  const handlePublishDemand = useCallback(async (id) => {
    if (!canUseAdminDemandActions) return toast.error('Sem permissao.')
    if (!window.confirm('Publicar a demanda? Os pedidos saem da torre de despacho e vao para producao.')) return
    const response = await fetch('/api/v2/despacho/publicar', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ demanda_id: id }),
    })
    const data = await response.json().catch(() => ({}))
    if (response.ok && data.success) {
      const d = data.data || {}
      toast.success(`${d.demanda_codigo || 'Demanda'} publicada — ${d.total_pedidos ?? 0} pedidos foram para producao.`)
      refresh()
      return
    }
    toast.error(data.error || data.message || 'Nao foi possivel publicar.')
  }, [canUseAdminDemandActions, refresh])

  // Cancelar e a acao para desfazer um lote que ja andou: o vinculo com os
  // pedidos vira historico, as baixas de coleta sao estornadas e os pedidos
  // voltam para a torre. Deletar so serve para lote que nao deixou rastro.
  const handleCancelDemand = useCallback(async (id) => {
    if (!canCancelDemand) return toast.error('Sem permissao.')
    const motivo = window.prompt('Cancelar a demanda e devolver os pedidos para a torre de despacho.\n\nMotivo (opcional):')
    if (motivo === null) return
    const response = await fetch(`/api/v2/demanda_producao/${id}/cancelar`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ motivo: motivo || null }),
    })
    const data = await response.json().catch(() => ({}))
    if (response.ok && data.success) {
      toast.success(data.message || 'Demanda cancelada.')
      refresh()
      return
    }
    toast.error(data.message || 'Nao foi possivel cancelar.')
  }, [canCancelDemand, refresh])

  // A rota podia responder 200 com success:false; checar so response.ok mostrava
  // "deletada" para uma demanda que continuava viva. Agora o 409 de demanda com
  // estoque oferece o cancelamento em vez de deixar o operador sem saida.
  const handleDeleteDemand = useCallback(async (id) => {
    if (!canDeleteDemand) return toast.error('Sem permissao.')
    if (!window.confirm('Deletar permanentemente? Os pedidos voltam para a torre de despacho.')) return
    const response = await fetch(`/api/v2/demanda_producao/${id}`, { method: 'DELETE' })
    const data = await response.json().catch(() => ({}))
    if (response.ok && data.success) {
      toast.success(data.message || 'Demanda deletada.')
      refresh()
      return
    }
    if (response.status === 409 && data.sugestao === 'cancelar') {
      toast.error(data.message)
      if (window.confirm(`${data.message}\n\nCancelar a demanda agora?`)) handleCancelDemand(id)
      return
    }
    toast.error(data.message || 'Nao foi possivel deletar.')
  }, [canDeleteDemand, refresh, handleCancelDemand])

  const changeTab = (tab) => {
    setSelectedDemandIds([])
    setSearchParams((current) => {
      const next = new URLSearchParams(current)
      next.set('tab', tab)
      return next
    })
  }

  const clearFilters = () => {
    setSearchTerm('')
    setChannelFilter('all')
    setModalidadeFilter('all')
    setFlowFilter('all')
  }

  if (loading && demandas.length === 0) {
    return <div className='py-10 text-center text-slate-500'>Carregando demandas...</div>
  }

  if (error && demandas.length === 0) {
    return <div className='py-10 text-center text-red-500'>Erro: {error}</div>
  }

  return (
    <TooltipProvider>
      <div className='container mx-auto py-4 pb-32'>
        {error ? (
          <div role='status' className='mb-4 rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900'>
            Exibindo dados possivelmente desatualizados. A sincronização falhou: {error}
            <Button variant='link' onClick={refresh}>Tentar novamente</Button>
          </div>
        ) : null}
        <div className='mb-3 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between'>
          <div>
            <h1 className='flex items-center gap-2 text-2xl font-bold text-slate-900'>
              Demandas
              <span
                className={`h-2 w-2 rounded-full ${realtimeConnected ? 'bg-green-500' : 'bg-amber-500'}`}
                title={realtimeConnected
                  ? 'Atualização em tempo real conectada'
                  : 'Tempo real desconectado; recuperação automática ativa'}
              />
            </h1>
            <p className='text-sm text-slate-500'>
              Acompanhe o que ja foi entregue ao galpao. Demanda nova nasce na Torre de Despacho.
            </p>
          </div>

          <div className='flex flex-wrap items-center gap-2'>
            {user?.is_admin || hasPermission('demanda_producao', 'criar') ? (
              <Link to='/producao/demanda/nova'>
                <Button size='sm'>Nova demanda</Button>
              </Link>
            ) : null}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant='outline' size='sm' className='gap-2'>
                  <BarChart3 className='h-4 w-4' />
                  Relatórios
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align='end'>
                <DropdownMenuItem onClick={() => setIsCollectedDemandsModalOpen(true)}>
                  <Truck className='mr-2 h-4 w-4' />
                  Coletas
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => setIsDailyTotalsModalOpen(true)}>
                  <Factory className='mr-2 h-4 w-4' />
                  Producao diaria
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <Button
              variant='outline'
              size='icon'
              className='h-8 w-8'
              title={lastUpdatedAt ? `Atualizar · última atualização ${new Date(lastUpdatedAt).toLocaleTimeString()}` : 'Atualizar'}
              onClick={() => {
                fetchTotals()
                fetchDashboardSummary()
                refresh()
              }}>
              <RefreshCw className='h-4 w-4' />
            </Button>
          </div>
        </div>

        {hasPermission('demanda_producao', 'ler') && (
          <SummaryCards dashboardSummary={dashboardSummary} totals={totals} />
        )}

        <div className='mb-3 flex flex-wrap items-center gap-2 rounded-lg border bg-white p-2'>
          <Tabs value={currentTab} onValueChange={changeTab}>
            <TabsList>
              <TabsTrigger value='active'>Ativas</TabsTrigger>
              <TabsTrigger value='history'>Historico</TabsTrigger>
            </TabsList>
          </Tabs>
          <Input
            className='h-9 min-w-[200px] flex-1'
            value={searchTerm}
            onChange={(event) => setSearchTerm(event.target.value)}
            placeholder='Buscar por nome, pedido, cliente...'
          />
          <Select value={channelFilter} onValueChange={setChannelFilter}>
            <SelectTrigger className='h-9 w-[170px]'>
              <SelectValue placeholder='Origem' />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value='all'>Todas as origens</SelectItem>
              {uniqueChannels.map((channel) => (
                <SelectItem key={channel} value={String(channel)}>
                  {channel}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={modalidadeFilter} onValueChange={setModalidadeFilter}>
            <SelectTrigger className='h-9 w-[170px]'>
              <SelectValue placeholder='Modalidade' />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value='all'>Todas as modalidades</SelectItem>
              <SelectItem value='STANDARD'>Normal</SelectItem>
              <SelectItem value='EXPRESS'>Flex</SelectItem>
              <SelectItem value='FULFILLMENT'>Fulfillment</SelectItem>
              <SelectItem value='RETIRADA'>Retirada</SelectItem>
            </SelectContent>
          </Select>
          <Select value={flowFilter} onValueChange={setFlowFilter}>
            <SelectTrigger className='h-9 w-[170px]'>
              <SelectValue placeholder='Fluxo' />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value='all'>Todos os fluxos</SelectItem>
              {DEMANDA_FLOW_OPTIONS.map((option) => (
                <SelectItem key={option.id} value={option.id}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {(searchTerm || channelFilter !== 'all' || modalidadeFilter !== 'all' || flowFilter !== 'all') && (
            <Button variant='ghost' size='sm' onClick={clearFilters}>
              Limpar filtros
            </Button>
          )}
        </div>

        {Object.keys(pendingChanges).length > 0 && (
          <div className='fixed bottom-8 right-8 z-50 rounded-xl border-2 border-primary bg-white p-4 shadow-2xl'>
            <div className='flex items-center gap-4'>
              <span className='text-sm font-medium text-slate-900'>
                Alteracoes pendentes ({Object.keys(pendingChanges).length})
              </span>
              <Button variant='outline' size='sm' onClick={handleCancelChanges} disabled={savingField}>
                Cancelar
              </Button>
              <Button size='sm' onClick={handleBulkSave} disabled={savingField}>
                {savingField ? 'Salvando...' : 'Salvar tudo'}
              </Button>
            </div>
          </div>
        )}

        {selectedDemandIds.length > 0 && (
          <div className='fixed bottom-8 left-1/2 z-50 flex -translate-x-1/2 items-center gap-6 rounded-full bg-slate-900 px-6 py-3 text-white shadow-2xl'>
            <div className='flex items-center gap-2'>
              <CheckSquare className='h-5 w-5 text-primary' />
              <span className='text-sm font-bold'>{selectedDemandIds.length} selecionadas</span>
            </div>
            <div className='h-6 w-px bg-slate-700' />
            <Button size='sm' variant='ghost' className='text-white hover:bg-slate-800' onClick={handleBatchCollect}>
              <Truck className='mr-2 h-4 w-4' />
              Coleta em lote
            </Button>
            <Button size='sm' variant='ghost' className='text-white hover:bg-slate-800' onClick={() => setSelectedDemandIds([])}>
              <X className='h-4 w-4' />
            </Button>
          </div>
        )}

        {visibleSimulacoes.length > 0 && (
          <div className='mb-4 rounded-2xl border border-amber-300 bg-amber-50/40 p-4'>
            <h2 className='mb-2 text-sm font-semibold'>Simulações</h2>
            <div className='grid gap-2'>
              {visibleSimulacoes.map((simulacao) => (
                <Link
                  key={simulacao.id}
                  to={`/producao/simulacao/${simulacao.id}/dashboard`}
                  className='flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-white p-3 text-sm hover:border-primary/60'
                >
                  <span className='font-medium'>{simulacao.nome}</span>
                  <span className='text-xs text-slate-500'>
                    <span className='mr-2 rounded bg-amber-600 px-1.5 py-0.5 text-white'>Simulação</span>
                    {simulacao.status} · {simulacao.pedido_ids.length} pedidos
                  </span>
                </Link>
              ))}
            </div>
          </div>
        )}

        {filteredDemandas.length === 0 ? (
          <div className='rounded-2xl border bg-white p-10 text-center text-slate-500'>
            Nenhuma demanda encontrada nesta aba.
          </div>
        ) : (
          <div className='grid gap-3'>
            {filteredDemandas.map((demanda) => (
              <DemandaCard
                key={demanda.id}
                demanda={demanda}
                userSetor={userSetor}
                viewMode='done'
                handleFieldUpdate={handleFieldUpdate}
                handleFinalizeDemand={handleFinalizeDemand}
                handleCollectDemand={handleCollectDemand}
                handleDeleteDemand={handleDeleteDemand}
                handleCancelDemand={handleCancelDemand}
                canCancelDemand={canCancelDemand}
                handlePublishDemand={handlePublishDemand}
                isAdmin={user?.is_admin === true}
                isSelected={selectedDemandIds.includes(demanda.id)}
                onSelect={(id) =>
                  setSelectedDemandIds((current) =>
                    current.includes(id) ? current.filter((item) => item !== id) : [...current, id]
                  )
                }
              />
            ))}
          </div>
        )}

        <DailyProductionModal
          isOpen={isDailyTotalsModalOpen}
          onClose={() => setIsDailyTotalsModalOpen(false)}
          totals={totals}
          loading={loading}
        />
        <CollectedDemandsModal
          isOpen={isCollectedDemandsModalOpen}
          onClose={() => setIsCollectedDemandsModalOpen(false)}
          demandasColetadas={demandasColetadas}
          demandasAguardandoColeta={demandasAguardandoColeta}
          handleCollectDemand={handleCollectDemand}
        />
        <PartialCollectionModal
          isOpen={isPartialCollectionModalOpen}
          onClose={() => {
            setIsPartialCollectionModalOpen(false)
            setSelectedDemandIdForCollection(null)
          }}
          demandaId={selectedDemandIdForCollection}
          onConfirm={handleConfirmPartialCollection}
        />
      </div>
    </TooltipProvider>
  )
}
