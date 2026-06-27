import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'

import DemandaCard from '@/components/producao/DemandaCard'
import CollectedDemandsModal from '@/components/producao/CollectedDemandsModal'
import DailyProductionModal from '@/components/producao/DailyProductionModal'
import LotSuggestionCard from '@/components/producao/LotSuggestionCard'
import LotSuggestionReviewDialog from '@/components/producao/LotSuggestionReviewDialog'
import PartialCollectionModal from '@/components/producao/PartialCollectionModal'
import SummaryCards from '@/components/producao/SummaryCards'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { TooltipProvider } from '@/components/ui/tooltip'
import { useAuth } from '@/contexts/AuthContext'
import { useLayout } from '@/contexts/LayoutContext'
import { useRealtimeDemandas } from '@/lib/hooks/useRealtimeDemandas'
import { deriveDemandFlow, DEMANDA_FLOW_OPTIONS } from '@/lib/demandaFlow'
import { listLotSuggestions } from '@/services/productionLotSuggestionsService'
import {
  CheckSquare,
  ClipboardList,
  Factory,
  Layers3,
  PackageSearch,
  RefreshCw,
  Truck,
  X,
} from 'lucide-react'

const TERMINAL_DEMAND_STATUSES = ['FINALIZADO', 'CONCLUIDO', 'COLETADO', 'CANCELADO']
const DRAFT_DEMAND_STATUSES = ['AGUARDANDO', 'RASCUNHO']

function normalizeDemandStatus(status) {
  return String(status || '').trim().toUpperCase()
}

function normalizeModalidade(value) {
  const raw = String(value || '').trim().toUpperCase()
  if (raw === 'FLEX') return 'EXPRESS'
  return raw || 'STANDARD'
}

export default function DemandasPlanejamentoPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const { user } = useAuth()
  const { setIsLeftSidebarOpen } = useLayout()

  const userSetor = user?.setor_nome || (user?.is_admin ? 'Administrador' : null)
  const normalizedUserSetor = (userSetor || '').trim().toLowerCase()
  const canUseAdminDemandActions = user?.is_admin === true || normalizedUserSetor === 'administrativo'
  const canUseExpeditionDemandActions =
    canUseAdminDemandActions ||
    normalizedUserSetor === 'expediÃ§Ã£o' ||
    normalizedUserSetor === 'expedicao'

  const defaultTab = canUseAdminDemandActions ? 'planning' : 'active'
  const currentTab = searchParams.get('tab') || defaultTab

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

  const [suggestionsPayload, setSuggestionsPayload] = useState({
    updated_at: null,
    suggestions: [],
    exceptions: [],
    legacy_drafts_count: 0,
  })
  const [loadingSuggestions, setLoadingSuggestions] = useState(true)
  const [reviewSuggestion, setReviewSuggestion] = useState(null)

  const { demandas, setDemandas, loading, error, refresh } = useRealtimeDemandas(pendingChanges)

  useEffect(() => {
    setIsLeftSidebarOpen(false)
    return () => setIsLeftSidebarOpen(true)
  }, [setIsLeftSidebarOpen])

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

  const fetchSuggestions = useCallback(async (silent = false) => {
    if (!silent) setLoadingSuggestions(true)
    try {
      const response = await listLotSuggestions(searchTerm)
      setSuggestionsPayload({
        updated_at: response.updated_at,
        suggestions: response.suggestions || [],
        exceptions: response.exceptions || [],
        legacy_drafts_count: response.legacy_drafts_count || 0,
      })
    } catch (fetchError) {
      toast.error(fetchError?.response?.data?.message || 'Nao foi possivel carregar os lotes sugeridos.')
    } finally {
      if (!silent) setLoadingSuggestions(false)
    }
  }, [searchTerm])

  useEffect(() => {
    fetchTotals()
    fetchDashboardSummary()
    fetchSuggestions()
    const interval = setInterval(() => fetchSuggestions(true), 30000)
    return () => clearInterval(interval)
  }, [fetchTotals, fetchDashboardSummary, fetchSuggestions])

  useEffect(() => {
    const highlightedSuggestion = searchParams.get('suggestion')
    if (!highlightedSuggestion) return
    const suggestion = (suggestionsPayload.suggestions || []).find(
      (item) => item.suggestion_key === highlightedSuggestion
    )
    if (suggestion) {
      setReviewSuggestion(suggestion)
      setSearchParams((current) => {
        const next = new URLSearchParams(current)
        next.delete('suggestion')
        return next
      })
    }
  }, [searchParams, setSearchParams, suggestionsPayload.suggestions])

  const filteredDemandas = useMemo(() => {
    const search = searchTerm.trim().toLowerCase()
    return demandas.filter((demanda) => {
      const status = normalizeDemandStatus(demanda.status)
      if (currentTab === 'active' && (TERMINAL_DEMAND_STATUSES.includes(status) || DRAFT_DEMAND_STATUSES.includes(status))) {
        return false
      }
      if (currentTab === 'history' && !TERMINAL_DEMAND_STATUSES.includes(status)) {
        return false
      }
      if (currentTab === 'planning' && !DRAFT_DEMAND_STATUSES.includes(status)) {
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
    const channels = new Set([
      ...demandas
        .map((demanda) => demanda.canal_venda_nome || demanda.canal_venda_id)
        .filter(Boolean),
      ...(suggestionsPayload.suggestions || [])
        .map((suggestion) => suggestion.marketplace_nome)
        .filter(Boolean),
    ])
    return Array.from(channels).sort()
  }, [demandas, suggestionsPayload.suggestions])

  const filteredSuggestions = useMemo(() => {
    return (suggestionsPayload.suggestions || []).filter((suggestion) => {
      if (channelFilter !== 'all' && suggestion.marketplace_nome !== channelFilter) return false
      if (modalidadeFilter !== 'all' && normalizeModalidade(suggestion.modalidade) !== modalidadeFilter) return false
      return true
    })
  }, [channelFilter, modalidadeFilter, suggestionsPayload.suggestions])

  const draftDemandas = useMemo(() => {
    return filteredDemandas.filter((demanda) => DRAFT_DEMAND_STATUSES.includes(normalizeDemandStatus(demanda.status)))
  }, [filteredDemandas])

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
    const response = await fetch(`/api/v2/demanda_producao/${demandaId}/coletar`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ quantidade_coletar: quantity }),
    })
    const data = await response.json()
    if (response.ok) {
      toast.success(data.message || 'Coleta registrada.')
      refresh()
      return
    }
    toast.error(data.message || 'Nao foi possivel registrar a coleta.')
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

  const handlePublishDemand = useCallback(async (id) => {
    if (!canUseAdminDemandActions) return toast.error('Sem permissao.')
    if (!window.confirm('Publicar demanda?')) return
    const response = await fetch(`/api/v2/demanda_producao/${id}/publicar`, { method: 'POST' })
    if (response.ok) {
      toast.success('Demanda publicada.')
      refresh()
      return
    }
    const data = await response.json()
    toast.error(data.message || 'Nao foi possivel publicar.')
  }, [canUseAdminDemandActions, refresh])

  const handleDeleteDemand = useCallback(async (id) => {
    if (!canUseAdminDemandActions) return toast.error('Sem permissao.')
    if (!window.confirm('Deletar permanentemente?')) return
    const response = await fetch(`/api/v2/demanda_producao/${id}`, { method: 'DELETE' })
    if (response.ok) {
      toast.success('Demanda deletada.')
      refresh()
      return
    }
    const data = await response.json()
    toast.error(data.message || 'Nao foi possivel deletar.')
  }, [canUseAdminDemandActions, refresh])

  const handlePrintDemand = useCallback(async (id) => {
    const response = await fetch(`/api/v2/printing/demanda/${id}/print`, { method: 'POST' })
    const data = await response.json()
    if (response.ok) {
      toast.success(`Enviado para impressao. ${data.count || 0} jobs criados.`)
      return
    }
    toast.error(data.error || 'Nao foi possivel imprimir.')
  }, [])

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

  if (loading && demandas.length === 0 && currentTab !== 'planning') {
    return <div className='py-10 text-center text-slate-500'>Carregando demandas...</div>
  }

  if (error) {
    return <div className='py-10 text-center text-red-500'>Erro: {error}</div>
  }

  return (
    <TooltipProvider>
      <div className='container mx-auto py-8 pb-32'>
        <div className='mb-6 flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between'>
          <div>
            <h1 className='text-3xl font-bold text-slate-900'>Demandas</h1>
            <p className='text-sm text-slate-500'>
              Planeje por janelas logisticas e trate pedido avulso como excecao.
            </p>
          </div>

          <div className='flex flex-wrap gap-3'>
            <Link to='/producao/demanda/nova'>
              <Button>Nova demanda</Button>
            </Link>
            <Button variant='outline' onClick={() => setIsCollectedDemandsModalOpen(true)}>
              <Truck className='mr-2 h-4 w-4' />
              Coletas
            </Button>
            <Button variant='outline' onClick={() => setIsDailyTotalsModalOpen(true)}>
              <Factory className='mr-2 h-4 w-4' />
              Producao diaria
            </Button>
            <Button variant='outline' onClick={() => {
              fetchSuggestions()
              fetchTotals()
              fetchDashboardSummary()
              refresh()
            }}>
              <RefreshCw className='mr-2 h-4 w-4' />
              Atualizar
            </Button>
          </div>
        </div>

        {['Administrativo', 'CPD'].includes(userSetor) && (
          <SummaryCards dashboardSummary={dashboardSummary} totals={totals} />
        )}

        <div className='mb-6 rounded-2xl border bg-white shadow-sm'>
          <div className='flex flex-col gap-4 border-b p-4 lg:flex-row lg:items-center lg:justify-between'>
            <Tabs value={currentTab} onValueChange={changeTab}>
              <TabsList>
                <TabsTrigger value='planning'>Sugestoes e rascunhos</TabsTrigger>
                <TabsTrigger value='active'>Ativas</TabsTrigger>
                <TabsTrigger value='history'>Historico</TabsTrigger>
              </TabsList>
            </Tabs>

            <div className='grid gap-3 md:grid-cols-2 xl:grid-cols-4 xl:items-center'>
              <Input
                value={searchTerm}
                onChange={(event) => setSearchTerm(event.target.value)}
                placeholder='Buscar por nome, pedido, cliente...'
              />
              <Select value={channelFilter} onValueChange={setChannelFilter}>
                <SelectTrigger>
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
                <SelectTrigger>
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
                <SelectTrigger>
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
            </div>
          </div>

          <div className='flex flex-wrap items-center gap-2 p-4 text-sm text-slate-500'>
            {currentTab === 'planning' && (
              <>
                <Badge variant='secondary'>{filteredSuggestions.length} lotes sugeridos</Badge>
                <Badge variant='outline'>{suggestionsPayload.exceptions.length} excecoes</Badge>
                {suggestionsPayload.updated_at && <span>Atualizado em tempo quase real.</span>}
              </>
            )}
            {(searchTerm || channelFilter !== 'all' || modalidadeFilter !== 'all' || flowFilter !== 'all') && (
              <Button variant='ghost' size='sm' onClick={clearFilters}>
                Limpar filtros
              </Button>
            )}
          </div>
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

        {currentTab === 'planning' ? (
          <div className='space-y-6'>
            {loadingSuggestions ? (
              <div className='rounded-2xl border bg-white p-10 text-center text-slate-500'>
                Carregando sugestoes de lote...
              </div>
            ) : filteredSuggestions.length === 0 ? (
              <div className='rounded-2xl border bg-white p-10 text-center text-slate-500'>
                <PackageSearch className='mx-auto mb-3 h-10 w-10 text-slate-300' />
                Nenhum lote compativel apareceu com os filtros atuais.
              </div>
            ) : (
              <div className='space-y-4'>
                {filteredSuggestions.map((suggestion) => (
                  <LotSuggestionCard
                    key={suggestion.suggestion_key}
                    suggestion={suggestion}
                    onReview={setReviewSuggestion}
                    highlighted={searchParams.get('suggestion') === suggestion.suggestion_key}
                  />
                ))}
              </div>
            )}

            <div className='grid gap-4 lg:grid-cols-[1.3fr_0.7fr]'>
              <div className='rounded-2xl border bg-white p-5'>
                <div className='mb-3 flex items-center gap-2'>
                  <ClipboardList className='h-4 w-4 text-slate-400' />
                  <h2 className='font-semibold text-slate-900'>Rascunhos legados</h2>
                </div>
                {draftDemandas.length === 0 ? (
                  <p className='text-sm text-slate-500'>Nenhum rascunho persistido aguardando publicacao.</p>
                ) : (
                  <div className='space-y-4'>
                    {draftDemandas.map((demanda) => (
                      <DemandaCard
                        key={demanda.id}
                        demanda={demanda}
                        userSetor={userSetor}
                        viewMode='done'
                        handleFieldUpdate={handleFieldUpdate}
                        handleFinalizeDemand={handleFinalizeDemand}
                        handleCollectDemand={handleCollectDemand}
                        handleDeleteDemand={handleDeleteDemand}
                        handlePublishDemand={handlePublishDemand}
                        handlePrintDemand={handlePrintDemand}
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
              </div>

              <div className='rounded-2xl border bg-white p-5'>
                <div className='mb-3 flex items-center gap-2'>
                  <Layers3 className='h-4 w-4 text-slate-400' />
                  <h2 className='font-semibold text-slate-900'>Fila de excecoes</h2>
                </div>
                {suggestionsPayload.exceptions.length === 0 ? (
                  <p className='text-sm text-slate-500'>Nenhuma excecao pendente.</p>
                ) : (
                  <div className='space-y-3'>
                    {suggestionsPayload.exceptions.slice(0, 8).map((exception) => (
                      <div key={`${exception.pedido_id}-${exception.motivo}`} className='rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900'>
                        <div className='font-medium'>{exception.numero_pedido || `Pedido ${exception.pedido_id}`}</div>
                        <div className='text-xs'>{exception.motivo}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        ) : filteredDemandas.length === 0 ? (
          <div className='rounded-2xl border bg-white p-10 text-center text-slate-500'>
            Nenhuma demanda encontrada nesta aba.
          </div>
        ) : (
          <div className='grid gap-4'>
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
                handlePublishDemand={handlePublishDemand}
                handlePrintDemand={handlePrintDemand}
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

        <LotSuggestionReviewDialog
          open={Boolean(reviewSuggestion)}
          onOpenChange={(nextOpen) => {
            if (!nextOpen) setReviewSuggestion(null)
          }}
          suggestion={reviewSuggestion}
          onConfirmed={(result) => {
            fetchSuggestions()
            refresh()
            if (result?.demanda_id) {
              navigate(`/producao/demanda/${result.demanda_id}/dashboard`)
            }
          }}
        />

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


