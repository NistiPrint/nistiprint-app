import CollectedDemandsModal from '@/components/producao/CollectedDemandsModal'
import DailyProductionModal from '@/components/producao/DailyProductionModal'
import DemandaCard from '@/components/producao/DemandaCard'
import FiltersSection from '@/components/producao/FiltersSection'
import HeaderSection from '@/components/producao/HeaderSection'
import SummaryCards from '@/components/producao/SummaryCards'
import { Button } from '@/components/ui/button'
import { TooltipProvider } from '@/components/ui/tooltip'
import { useAuth } from '@/contexts/AuthContext'
import { useLayout } from '@/contexts/LayoutContext'
import { usePermissions } from '@/contexts/PermissionsContext'
import useDebounce from '@/lib/hooks/useDebounce'
import { useRealtimeDemandas } from '@/lib/hooks/useRealtimeDemandas'
import { CheckSquare, Factory, RefreshCw, Truck, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'

import PartialCollectionModal from '@/components/producao/PartialCollectionModal'

function DemandaListPage() {
  const { user } = useAuth()
  const { canExecuteAction } = usePermissions()
  const { setIsLeftSidebarOpen } = useLayout()
  const userSetor =
    user?.setor_nome || (user?.is_admin ? 'Administrador' : null)

  // Collapse sidebar on mount for this specific page, restore on unmount
  useEffect(() => {
    setIsLeftSidebarOpen(false)
    return () => setIsLeftSidebarOpen(true)
  }, [setIsLeftSidebarOpen])

  const [totals, setTotals] = useState(null)
  const [dashboardSummary, setDashboardSummary] = useState(null)

  // Ticker for real-time countdowns
  const [, setTick] = useState(0)
  useEffect(() => {
    const timer = setInterval(() => setTick(t => t + 1), 60000)
    return () => clearInterval(timer)
  }, [])

  // Selection state
  const [selectedDemandIds, setSelectedDemandIds] = useState([])

  // Applied filter states (used for filtering)
  const [appliedSearchTerm, setAppliedSearchTerm] = useState('')
  const debouncedSearchTerm = useDebounce(appliedSearchTerm, 300)
  const [statusFilter, setStatusFilter] = useState('all')
  const [channelFilter, setChannelFilter] = useState('all')
  const [modalidadeFilter, setModalidadeFilter] = useState('all')
  const [classificacaoFilter, setClassificacaoFilter] = useState('all')
  const [viewMode, setViewMode] = useState('done')

  // Temporary filter states (for UI)
  const [tempSearchTerm, setTempSearchTerm] = useState('')
  const [tempStatusFilter, setTempStatusFilter] = useState('all')
  const [tempChannelFilter, setTempChannelFilter] = useState('all')
  const [tempModalidadeFilter, setTempModalidadeFilter] = useState('all')
  const [tempClassificacaoFilter, setTempClassificacaoFilter] = useState('all')

  const [savingField, setSavingField] = useState(false) 
  const [pendingChanges, setPendingChanges] = useState({}) 

  // Modal States
  const [isDailyTotalsModalOpen, setIsDailyTotalsModalOpen] = useState(false)
  const [isCollectedDemandsModalOpen, setIsCollectedDemandsModalOpen] =
    useState(false)
  const [isPartialCollectionModalOpen, setIsPartialCollectionModalOpen] = useState(false)
  const [selectedDemandIdForCollection, setSelectedDemandIdForCollection] = useState(null)

  const hasPendingChanges = Object.keys(pendingChanges).length > 0
  const { demandas, setDemandas, loading, error, refresh } = useRealtimeDemandas(pendingChanges)

  const fetchTotals = useCallback(async () => {
    try {
      const response = await fetch(
        '/api/v2/demanda_producao/dashboard-totals',
        { headers: { Accept: 'application/json' } }
      )
      if (response.ok) {
        const data = await response.json()
        if (data.success) setTotals(data)
      }
    } catch (e) {
      console.error('Erro ao carregar totais:', e)
    }
  }, [])

  const fetchDashboardSummary = useCallback(async () => {
    try {
      const response = await fetch(
        '/api/v2/demanda_producao/dashboard-summary',
        { headers: { Accept: 'application/json' } }
      )
      if (response.ok) {
        const data = await response.json()
        if (data.success) setDashboardSummary(data)
      }
    } catch (e) {
      console.error('Erro ao carregar resumo dashboard:', e)
    }
  }, [])

  // Debounce para evitar chamadas em excesso
  const debounceRef = useRef(null);
  const refreshIntervalRef = useRef(null);
  
  const refreshStats = useCallback(() => {
    fetchTotals();
    fetchDashboardSummary();
  }, [fetchTotals, fetchDashboardSummary]);

  useEffect(() => {
    // Refresh inicial
    refreshStats();
    
    // Refresh periódico a cada 1 minuto (60000ms)
    refreshIntervalRef.current = setInterval(refreshStats, 60000);

    return () => {
      if (refreshIntervalRef.current) {
        clearInterval(refreshIntervalRef.current);
      }
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }
    };
  }, [refreshStats])

  const uniqueChannels = useMemo(() => {
    const channels = new Set(
      demandas.map(d => d.canal_venda_nome || d.canal_venda_id).filter(Boolean)
    )
    return Array.from(channels).sort()
  }, [demandas])

  const filteredDemandas = useMemo(() => {
    return demandas.filter(demanda => {
      const searchLower = debouncedSearchTerm.toLowerCase()
      const matchesSearch =
        !debouncedSearchTerm ||
        demanda.nome?.toLowerCase().includes(searchLower) ||
        demanda.id?.toString().includes(searchLower)

      if (!matchesSearch) return false

      if (statusFilter !== 'all') {
        if (statusFilter === 'draft' && !['RASCUNHO', 'AGUARDANDO'].includes(demanda.status)) return false
        if (statusFilter === 'completed' && !['FINALIZADO', 'CONCLUIDO', 'COLETADO'].includes(demanda.status)) return false
        if (statusFilter === 'production' && !['EM_PRODUCAO', 'EM_ANDAMENTO', 'COLETA_PARCIAL'].includes(demanda.status)) return false
        if (statusFilter === 'pending' && !['PENDENTE', 'AGUARDANDO'].includes(demanda.status)) return false
      } else {
        // DEFAULT: Show only active demands (excluding Drafts, Finalized and Collected)
        const excludedStatuses = ['RASCUNHO', 'AGUARDANDO', 'FINALIZADO', 'CONCLUIDO', 'COLETADO']
        if (excludedStatuses.includes(demanda.status)) return false
      }

      if (channelFilter !== 'all') {
        const channelName = demanda.canal_venda_nome || demanda.canal_venda_id
        if (channelName !== channelFilter) return false
      }

      if (modalidadeFilter !== 'all') {
        if (modalidadeFilter === 'standard' && demanda.modalidade_logistica !== 'STANDARD') return false
        if (modalidadeFilter === 'express' && demanda.modalidade_logistica !== 'EXPRESS') return false
        if (modalidadeFilter === 'fulfillment' && demanda.modalidade_logistica !== 'FULFILLMENT') return false
        if (modalidadeFilter === 'retirada' && demanda.modalidade_logistica !== 'RETIRADA') return false
      }

      if (classificacaoFilter !== 'all') {
        if (classificacaoFilter === 'b2c' && demanda.classificacao_cliente !== 'B2C') return false
        if (classificacaoFilter === 'b2b' && demanda.classificacao_cliente !== 'B2B') return false
        if (classificacaoFilter === 'interno' && demanda.classificacao_cliente !== 'INTERNO') return false
      }

      return true
    })
  }, [demandas, debouncedSearchTerm, statusFilter, channelFilter, modalidadeFilter, classificacaoFilter])

  const demandasColetadas = useMemo(() => {
    // Demandas com status Coletado (independente da data)
    return demandas.filter(d => {
      return ['Coletado', 'COLETADO'].includes(d.status)
    })
  }, [demandas])

  const demandasAguardandoColeta = useMemo(() => {
    // Demandas finalizadas que AINDA NÃO foram coletadas
    // Lista mutuamente exclusiva com demandasColetadas
    return demandas.filter(d => {
      const statusFinalizado = ['Finalizado', 'CONCLUIDO'].includes(d.status)
      // Não incluir se já estiver coletado
      const naoColetado = !['Coletado', 'COLETADO'].includes(d.status)
      return statusFinalizado && naoColetado
    })
  }, [demandas])
  const demandasAtivas = filteredDemandas

  const clearFilters = () => {
    setAppliedSearchTerm('')
    setTempSearchTerm('')
    setStatusFilter('all')
    setTempStatusFilter('all')
    setChannelFilter('all')
    setTempChannelFilter('all')
    setModalidadeFilter('all')
    setTempModalidadeFilter('all')
    setClassificacaoFilter('all')
    setTempClassificacaoFilter('all')
    setViewMode('done')
  }

  const onApplyFilters = () => {
    setAppliedSearchTerm(tempSearchTerm)
    setStatusFilter(tempStatusFilter)
    setChannelFilter(tempChannelFilter)
    setModalidadeFilter(tempModalidadeFilter)
    setClassificacaoFilter(tempClassificacaoFilter)
  }

  const hasActiveFilters = appliedSearchTerm || statusFilter !== 'all' || channelFilter !== 'all' || modalidadeFilter !== 'all' || classificacaoFilter !== 'all'

  const { demandasPrincipais, demandasLaterais } = useMemo(() => {
    const main = []
    const lateral = []

    filteredDemandas.forEach(demanda => {
      // Cálculo de dias restantes simplificado para comparação
      const entrega = new Date(demanda.data_entrega)
      const hoje = new Date()
      hoje.setHours(0, 0, 0, 0)
      
      const diffTime = entrega - hoje
      const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24))

      // Regras para Lateral (Normalizadas para evitar erros de case):
      const tipo = (demanda.tipo_demanda || '').toUpperCase();
      const modalidade = (demanda.modalidade_logistica || '').toUpperCase();

      // 1. B2B (ou legado 'Empresas')
      // 2. Fulfillment
      // 3. Estoque Interno / Interno
      // 4. Data entrega > 3 dias
      const isLateralByNature = 
        tipo === 'B2B' || 
        tipo === 'EMPRESAS' ||
        modalidade === 'FULFILLMENT' || 
        tipo === 'ESTOQUE_INTERNO' || 
        tipo === 'INTERNO';

      if (isLateralByNature || diffDays > 3) {
        lateral.push(demanda)
      } else {
        main.push(demanda)
      }
    })

    // Ordenação Linha Principal: Horário de coleta
    main.sort((a, b) => (a.horario_coleta || '23:59').localeCompare(b.horario_coleta || '23:59'))
    
    // Ordenação Trilhas Laterais: Readiness Score (maior primeiro)
    lateral.sort((a, b) => (b.readiness_score || 0) - (a.readiness_score || 0))

    return { demandasPrincipais: main, demandasLaterais: lateral }
  }, [filteredDemandas])

  const handleFieldUpdate = useCallback((demandaId, fieldName, newValue) => {
    setPendingChanges(prev => {
      const demandChanges = prev[demandaId] || {}
      return { ...prev, [demandaId]: { ...demandChanges, [fieldName]: newValue } }
    })
    setDemandas(prev => prev.map(item => item.id === demandaId ? { ...item, [fieldName]: newValue } : item))
  }, [setDemandas])

  const handleBulkSave = async () => {
    const demandIds = Object.keys(pendingChanges)
    if (demandIds.length === 0) return
    setSavingField(true)
    try {
      const promises = demandIds.map(async (id) => {
        const payload = pendingChanges[id]
        const response = await fetch(`/api/v2/demanda_producao/demanda/${id}/detalhes`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        })
        if (!response.ok) throw new Error(`Erro ao salvar demanda ${id}`)
      })
      await Promise.all(promises)
      toast.success('Alterações salvas!')
      setPendingChanges({})
    } catch (e) {
      toast.error(`Erro ao salvar: ${e.message}`)
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
    if (!canExecuteAction(userSetor, 'finalize_item')) return toast.error('Sem permissão')
    if (!window.confirm('Finalizar demanda?')) return
    try {
      const res = await fetch(`/api/v2/demanda_producao/${id}/finalizar_demanda`, { method: 'POST' })
      if (res.ok) { toast.success('Finalizada!'); refresh(); }
    } catch (e) { toast.error(e.message) }
  }, [userSetor, refresh])

  const handleCollectDemand = useCallback(async (id) => {
    if (!canExecuteAction(userSetor, 'collect_demand')) return toast.error('Sem permissão')
    
    setSelectedDemandIdForCollection(id);
    setIsPartialCollectionModalOpen(true);
  }, [userSetor])

  const handleConfirmPartialCollection = async (demandaId, quantity) => {
    try {
        const res = await fetch(`/api/v2/demanda_producao/${demandaId}/coletar`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ quantidade_coletar: quantity })
        });
        
        if (res.ok) {
            const data = await res.json();
            toast.success(data.message || 'Coleta registrada!');
            refresh();
        } else {
            const err = await res.json();
            toast.error(err.message || 'Erro ao registrar coleta.');
        }
    } catch (e) {
        toast.error('Erro de conexão: ' + e.message);
    }
  };

  const handleBatchCollect = async () => {
    if (!canExecuteAction(userSetor, 'collect_demand')) return toast.error('Sem permissão')
    if (!window.confirm(`Marcar ${selectedDemandIds.length} demandas como coletadas?`)) return
    
    try {
      const res = await fetch('/api/v2/demanda_producao/batch/coletar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: selectedDemandIds })
      })
      if (res.ok) {
        toast.success(`${selectedDemandIds.length} demandas coletadas!`)
        setSelectedDemandIds([])
        refresh()
      } else {
        const err = await res.json()
        toast.error(`Erro: ${err.message}`)
      }
    } catch (e) { toast.error(e.message) }
  }

  const handleSelectDemand = (id) => {
    setSelectedDemandIds(prev => 
      prev.includes(id) ? prev.filter(i => i !== id) : [...prev, id]
    )
  }

  const selectAllFiltered = () => {
    const allIds = demandasAtivas.map(d => d.id)
    setSelectedDemandIds(allIds)
  }

  const handlePublishDemand = useCallback(async (id) => {
    if (!['Administrador', 'Administrativo', 'CPD'].includes(userSetor)) return toast.error('Sem permissão')
    if (!window.confirm('Publicar demanda?')) return
    try {
      const res = await fetch(`/api/v2/demanda_producao/${id}/publicar`, { method: 'POST' })
      if (res.ok) { toast.success('Publicada!'); refresh(); }
    } catch (e) { toast.error(e.message) }
  }, [userSetor, refresh])

  const handleDeleteDemand = useCallback(async (id) => {
    if (!canExecuteAction(userSetor, 'delete_demand')) return toast.error('Sem permissão')
    if (!window.confirm('Deletar permanentemente?')) return
    try {
      const res = await fetch(`/api/v2/demanda_producao/${id}`, { method: 'DELETE' })
      if (res.ok) { toast.success('Deletada!'); refresh(); }
    } catch (e) { toast.error(e.message) }
  }, [userSetor, refresh])

  const handlePrintDemand = useCallback(async (id) => {
    if (!window.confirm('Enviar todos os itens para impressão?')) return
    try {
      const res = await fetch(`/api/v2/printing/demanda/${id}/print`, { method: 'POST' })
      if (res.ok) {
        const data = await res.json()
        toast.success(`Enviado! ${data.count} jobs criados.`)
      } else {
        const err = await res.json()
        toast.error(`Erro: ${err.error}`)
      }
    } catch (e) { toast.error(e.message) }
  }, [])

  if (loading && demandas.length === 0) return <div className='text-center py-4'>Carregando...</div>
  if (error) return <div className='text-center py-4 text-red-500'>Erro: {error}</div>

  return (
    <div className='container mx-auto py-8 pb-32'>
      <HeaderSection
        isCollectedDemandsModalOpen={isCollectedDemandsModalOpen}
        setIsCollectedDemandsModalOpen={setIsCollectedDemandsModalOpen}
        setIsDailyTotalsModalOpen={setIsDailyTotalsModalOpen}
        demandasColetadas={demandasColetadas}
        demandasAguardandoColeta={demandasAguardandoColeta}
      />

      {/* Botão de Refresh Manual */}
      <div className='flex justify-end mb-4'>
        <Button
          variant='outline'
          size='sm'
          onClick={refreshStats}
          className='gap-2'
        >
          <RefreshCw className='h-4 w-4' />
          Atualizar
        </Button>
      </div>

      {hasPendingChanges && (
        <div className="fixed bottom-8 right-8 z-50 bg-white p-4 rounded-lg shadow-2xl border-2 border-primary animate-in fade-in slide-in-from-bottom-4">
          <div className="flex items-center gap-4">
            <span className="text-sm font-medium text-black">Alterações pendentes ({Object.keys(pendingChanges).length})</span>
            <Button variant="outline" size="sm" onClick={handleCancelChanges} disabled={savingField}>Cancelar</Button>
            <Button size="sm" onClick={handleBulkSave} disabled={savingField}>{savingField ? 'Salvando...' : 'Salvar Tudo'}</Button>
          </div>
        </div>
      )}

      {selectedDemandIds.length > 0 && (
        <div className="fixed bottom-8 left-1/2 -translate-x-1/2 z-50 bg-gray-900 text-white p-3 px-6 rounded-full shadow-2xl animate-in zoom-in slide-in-from-bottom-10">
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-2">
              <CheckSquare className="h-5 w-5 text-primary" />
              <span className="text-sm font-bold">{selectedDemandIds.length} selecionadas</span>
            </div>
            <div className="h-6 w-px bg-gray-700" />
            <div className="flex items-center gap-2">
              <Button size="sm" variant="ghost" className="text-white hover:bg-gray-800" onClick={handleBatchCollect}>
                <Truck className="h-4 w-4 mr-2" /> Coleta em Lote
              </Button>
              <Button size="sm" variant="ghost" className="text-white hover:bg-gray-800" onClick={() => setSelectedDemandIds([])}>
                <X className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>
      )}

      {['Administrativo', 'CPD'].includes(userSetor) && (
        <SummaryCards dashboardSummary={dashboardSummary} totals={totals} />
      )}

      <FiltersSection
        searchTerm={tempSearchTerm} setSearchTerm={setTempSearchTerm}
        statusFilter={tempStatusFilter} setStatusFilter={setTempStatusFilter}
        channelFilter={tempChannelFilter} setChannelFilter={setTempChannelFilter}
        modalidadeFilter={tempModalidadeFilter} setModalidadeFilter={setTempModalidadeFilter}
        classificacaoFilter={tempClassificacaoFilter} setClassificacaoFilter={setTempClassificacaoFilter}
        viewMode={viewMode} setViewMode={setViewMode}
        uniqueChannels={uniqueChannels} clearFilters={clearFilters} hasActiveFilters={hasActiveFilters}
        onApplyFilters={onApplyFilters}
      />
      
      <div className="flex justify-end mb-4">
        <Button variant="ghost" size="sm" onClick={selectAllFiltered} className="text-xs font-bold text-gray-500 hover:text-primary">
          Selecionar Todas Visíveis
        </Button>
      </div>

      {filteredDemandas.length === 0 ? (
        <div className='text-center py-12 text-muted-foreground'>
          <Factory className='mx-auto h-12 w-12 text-muted-foreground/50 mb-4' />
          <p className='text-lg'>Nenhuma demanda ativa encontrada.</p>
        </div>
      ) : (
        <div className="flex flex-col lg:flex-row gap-8 items-start">
          {/* COLUNA ESQUERDA: LINHA PRINCIPAL */}
          <section className="flex-1 lg:w-2/3 w-full">
            <div className="flex items-center gap-3 mb-6 border-b pb-2">
              <div>
                <h2 className="text-xl font-bold text-gray-900">📅 PRINCIPAL</h2>
                <p className="text-xs text-gray-500">Demandas prioritárias ordenadas por horário de coleta</p>
              </div>
            </div>

            {demandasPrincipais.length === 0 ? (
              <div className="bg-gray-50 border-2 border-dashed border-gray-200 rounded-xl p-8 text-center">
                <p className="text-gray-400 text-sm">Nenhuma demanda prioritária para hoje.</p>
              </div>
            ) : (
              <div className='grid gap-4 grid-cols-1'>
                {demandasPrincipais.map(demanda => (
                  <DemandaCard
                    key={demanda.id} demanda={demanda} userSetor={userSetor}
                    viewMode={viewMode}
                    handleFieldUpdate={handleFieldUpdate}
                    handleFinalizeDemand={handleFinalizeDemand}
                    handleCollectDemand={handleCollectDemand}
                    handleDeleteDemand={handleDeleteDemand}
                    handlePublishDemand={handlePublishDemand}
                    handlePrintDemand={handlePrintDemand}
                    isSelected={selectedDemandIds.includes(demanda.id)}
                    onSelect={handleSelectDemand}
                    isMainLine={true}
                  />
                ))}
              </div>
            )}
          </section>

          {/* COLUNA DIREITA: TRILHAS LATERAIS */}
          <section id="side-tracks-section" className="lg:w-1/3 w-full sticky top-8">
            <div className="flex items-center gap-3 mb-6 border-b pb-2">
              <div>
                <h2 className="text-xl font-bold text-gray-900">🔄 PRÓXIMOS</h2>
                <p className="text-xs text-gray-500">Oportunidades de adiantamento</p>
              </div>
            </div>

            {demandasLaterais.length === 0 ? (
              <div className="bg-gray-50 border-2 border-dashed border-gray-200 rounded-xl p-8 text-center">
                <p className="text-gray-400 text-sm">Nenhum encaixe disponível no momento.</p>
              </div>
            ) : (
              <div className='grid gap-4 grid-cols-1'>
                {demandasLaterais.map(demanda => (
                  <DemandaCard
                    key={demanda.id} demanda={demanda} userSetor={userSetor}
                    viewMode={viewMode}
                    handleFieldUpdate={handleFieldUpdate}
                    handleFinalizeDemand={handleFinalizeDemand}
                    handleCollectDemand={handleCollectDemand}
                    handleDeleteDemand={handleDeleteDemand}
                    handlePublishDemand={handlePublishDemand}
                    handlePrintDemand={handlePrintDemand}
                    isSelected={selectedDemandIds.includes(demanda.id)}
                    onSelect={handleSelectDemand}
                    isLateral={true}
                  />
                ))}
              </div>
            )}
          </section>
        </div>
      )}

      <DailyProductionModal isOpen={isDailyTotalsModalOpen} onClose={() => setIsDailyTotalsModalOpen(false)} totals={totals} loading={loading} />
      <CollectedDemandsModal isOpen={isCollectedDemandsModalOpen} onClose={() => setIsCollectedDemandsModalOpen(false)} demandasColetadas={demandasColetadas} demandasAguardandoColeta={demandasAguardandoColeta} handleCollectDemand={handleCollectDemand} />
      <PartialCollectionModal 
          isOpen={isPartialCollectionModalOpen}
          onClose={() => { setIsPartialCollectionModalOpen(false); setSelectedDemandIdForCollection(null); }}
          demandaId={selectedDemandIdForCollection}
          onConfirm={handleConfirmPartialCollection}
      />
    </div>
  )
}

export default function DemandaListPageWrapped() {
  return <TooltipProvider><DemandaListPage /></TooltipProvider>
}
