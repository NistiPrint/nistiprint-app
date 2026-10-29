import IncrementalInput from '@/components/producao/IncrementalInput'
import PartialCollectionModal from '@/components/producao/PartialCollectionModal'
import StockHistoryViewer from '@/components/producao/StockHistoryViewer'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Progress } from '@/components/ui/progress'
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@/components/ui/table'
import { useAuth } from '@/contexts/AuthContext'
import useLocalAgent from '@/hooks/useLocalAgent'
import usePermissionsHook from '@/hooks/usePermissions'
import useDebounce from '@/lib/hooks/useDebounce'
import { supabase } from '@/lib/supabase'
import { createOperationId } from '@/lib/operationId'
import { dataCurta, numero } from '@/lib/formatoProducao'
import {
    ArrowLeft,
    CheckCircle,
    Copy,
    FileCheck2,
    FileText,
    Flame,
    History,
    Layers,
    Hand,
    List,
    Loader2,
    MoreHorizontal,
    Printer,
    Receipt,
    Save,
    Search,
    Truck,
    X,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { imprimirPapeisDePedido } from '@/lib/papeisDePedido'
import CapaPrintPlanner from '@/components/producao/CapaPrintPlanner'

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

function DemandaDashboardPage() {
  const { id } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const isSimulation = location.pathname.includes('/simulacao/')
  const apiBase = isSimulation ? '/api/v2/demanda-simulacoes' : '/api/v2/demanda_producao'
  const { user, hasPermission } = useAuth()
  const { canEditField, canExecuteAction } = usePermissionsHook()
  const canEditDemand = user?.is_admin === true || hasPermission('demanda_producao', 'editar')
  const { isAgentOnline, printMappedFile, getMappedFileForProduct } =
    useLocalAgent(!isSimulation)
  const [demanda, setDemanda] = useState(null)
  const [simulationEvents, setSimulationEvents] = useState([])
  const simulationActionsAllowed = !isSimulation || (demanda?.status !== 'RASCUNHO' && demanda?.status !== 'COLETADO')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  // Batch Editing State
  const [pendingChanges, setPendingChanges] = useState({})
  const [isSaving, setIsSaving] = useState(false)
  const realtimeSaveState = isSimulation ? false : isSaving
  const [isFinalizingItemId, setIsFinalizingItemId] = useState(null)

  const [viewMode, setViewMode] = useState('producao')
  const [statusFilter, setStatusFilter] = useState('ativos') // ativos, finalizados
  const [searchQuery, setSearchQuery] = useState('')

  // States for Partial Quantities
  const [partialQuantities, setPartialQuantities] = useState({})
  const [isPartialCollectionModalOpen, setIsPartialCollectionModalOpen] =
    useState(false)
  const [selectedItemForHistory, setSelectedItemForHistory] = useState(null)
  const [showPedidosOrigem, setShowPedidosOrigem] = useState(false)
  const [nfeSidebarOpen, setNfeSidebarOpen] = useState(false)
  const [nfeResults, setNfeResults] = useState([])
  const [nfeGenerating, setNfeGenerating] = useState(false)
  const [nfeOperationId, setNfeOperationId] = useState(null)
  const [nfeOperation, setNfeOperation] = useState(null)
  const [progressoImpressao, setProgressoImpressao] = useState(null)

  const debouncedSearchQuery = useDebounce(searchQuery, 300)

  const hasPendingChanges = Object.keys(pendingChanges).length > 0

  const fetchDemanda = useCallback(
    async (silent = false) => {
      if (!silent) setLoading(true)
      try {
        const response = await fetch(`${apiBase}/${id}`, {
          headers: { Accept: 'application/json' },
        })
        if (!response.ok)
          throw new Error(`HTTP error! status: ${response.status}`)
        const data = await response.json()
        if (data.success) {
          let updatedDemanda = data.demanda
          // Não mesclar mudanças locais aqui para permitir o descarte correto
          // As mudanças locais são aplicadas em allProcessedItems
          setDemanda(updatedDemanda)
        } else {
          throw new Error(data.message || 'Erro ao carregar demanda')
        }
      } catch (e) {
        if (!silent) setError(e.message)
        console.error(e)
      } finally {
        if (!silent) setLoading(false)
      }
    },
    [apiBase, id],
  )

  const performSimulationAction = async (action, payload = {}) => {
    const operationKey = `demand-simulation:${id}:${demanda?.version}:${action}:${JSON.stringify(payload)}`
    const operationId = sessionStorage.getItem(operationKey) || createOperationId()
    sessionStorage.setItem(operationKey, operationId)
    const response = await fetch(`${apiBase}/${id}/acoes`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, payload, version: demanda?.version, operation_id: operationId }),
    })
    const result = await response.json()
    if (!response.ok || !result.success) {
      if (response.status === 409) { sessionStorage.removeItem(operationKey); await fetchDemanda(true) }
      throw new Error(result.message || 'Falha ao salvar a simulação')
    }
    sessionStorage.removeItem(operationKey)
    setDemanda(result.demanda)
    return result.demanda
  }

  const deleteSimulation = async () => {
    if (!window.confirm('Excluir esta simulação? Nenhum pedido real será alterado.')) return
    try {
      const response = await fetch(`${apiBase}/${id}`, {
        method: 'DELETE', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ version: demanda.version }),
      })
      const result = await response.json()
      if (!response.ok || !result.success) throw new Error(result.message || 'Falha ao excluir')
      toast.success('Simulação excluída')
      navigate('/despacho')
    } catch (error) { toast.error(error.message) }
  }

  // Ref para pendingChanges para acesso seguro dentro do fetch sem causar re-renders do useCallback
  const pendingChangesRef = useRef(pendingChanges)
  useEffect(() => {
    pendingChangesRef.current = pendingChanges
  }, [pendingChanges])

  useEffect(() => {
    if (!nfeOperationId) return undefined
    let cancelled = false
    let timer
    const refreshOperation = async () => {
      try {
        const response = await fetch(`/api/v2/notifications/operations/${encodeURIComponent(nfeOperationId)}`)
        const result = await response.json()
        if (!response.ok || !result.success) throw new Error(result.error || 'Falha ao consultar emissão de NF-e.')
        if (cancelled) return
        const operation = result.data
        setNfeOperation(operation)
        setNfeResults(operation.dados_adicionais?.resultados || [])
        const finished = ['CONCLUIDO', 'ERRO'].includes(operation.status)
        setNfeGenerating(!finished)
        if (!finished) timer = window.setTimeout(refreshOperation, 2500)
      } catch (error) {
        if (!cancelled) {
          console.warn('Falha temporária ao atualizar processo de NF-e:', error)
          timer = window.setTimeout(refreshOperation, 5000)
        }
      }
    }
    refreshOperation()
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [nfeOperationId])

  useEffect(() => {
    fetchDemanda()

    if (isSimulation) return undefined

    // Supabase Realtime Listener para esta demanda específica ou seus itens
    const channel = supabase
      .channel(`demanda-dashboard-${id}`)
      .on(
        'postgres_changes',
        {
          event: '*',
          schema: 'public',
          table: 'demandas_producao',
          filter: `id=eq.${id}`,
        },
        () => {
          if (!isSaving) fetchDemanda(true)
        },
      )
      .on(
        'postgres_changes',
        {
          event: '*',
          schema: 'public',
          table: 'itens_demanda',
          filter: `demanda_id=eq.${id}`,
        },
        () => {
          if (!isSaving) fetchDemanda(true)
        },
      )
      .subscribe()

    return () => {
      supabase.removeChannel(channel)
    }
  }, [id, fetchDemanda, realtimeSaveState, isSimulation])

  useEffect(() => {
    if (!isSimulation || !demanda?.version) return
    fetch(`${apiBase}/${id}/eventos`).then(response => response.json())
      .then(result => { if (result.success) setSimulationEvents(result.eventos || []) })
      .catch(() => {})
  }, [apiBase, demanda?.version, id, isSimulation])

  // Itens com mudanças locais aplicadas (apenas para exibição dos valores nas células)
  const allProcessedItems = useMemo(() => {
    if (!demanda?.itens) return []
    return demanda.itens.map(item => {
      const changes = pendingChanges[item.id]
      return changes ? { ...item, ...changes } : item
    })
  }, [demanda?.itens, pendingChanges])

  const filteredItems = useMemo(() => {
    const query = debouncedSearchQuery.toLowerCase()

    const itemsWithOriginalValues = allProcessedItems.map(item => ({
      ...item,
      _originalValues: demanda?.itens?.find(i => i.id === item.id) || item,
    }))

    const filtered = itemsWithOriginalValues.filter(item => {
      const orig = item._originalValues

      // Definição mais estrita de cada estado
      // Um item é considerado finalizado se o status for Concluído OU se a quantidade finalizada atingir o total.
      // Status "Fechando" NÃO é considerado finalizado - itens precisam ser explicitamente finalizados via botão.
      const isFinalizado =
        orig.status_item === 'Concluído' ||
        (orig.finalizados_qtd || 0) >= item.quantidade_total

      // Um item está pronto para fechar se:
      // - Já foi produzido (capa e miolo) E NÃO está totalmente finalizado
      // - OU está com status "Fechando" (retirado pela expedição mas não finalizado)
      // Capas e miolos prontos ficam disponíveis para a expedição retirar.
      // Depois de retirados, o casamento capa+miolo passa a estar em fechamento.
      const paresRetirados = Math.min(
        orig.expedicao_capas_retiradas_qtd || 0,
        orig.expedicao_miolos_retirados_qtd || 0,
      )
      const algumComponenteRetirado =
        (orig.expedicao_capas_retiradas_qtd || 0) > 0 ||
        (orig.expedicao_miolos_retirados_qtd || 0) > 0
      const isEmFechamento =
        !isFinalizado &&
        (orig.status_item === 'Fechando' || algumComponenteRetirado)
      // Cada componente pode ser retirado em um momento diferente.
      const capasParaRetirar = Math.max(0, (orig.capas_prontas_retirada_qtd || 0) - (orig.expedicao_capas_retiradas_qtd || 0))
      const miolosParaRetirar = Math.max(0, (orig.miolos_prontos_retirada_qtd || 0) - (orig.expedicao_miolos_retirados_qtd || 0))
      const paresParaRetirar = Math.min(capasParaRetirar, miolosParaRetirar)
      const isParaRetirar = !isFinalizado && (capasParaRetirar > 0 || miolosParaRetirar > 0)
      // Ainda há quantidade que não passou pela retirada da expedição.
      const isEmProducao = !isFinalizado && paresRetirados < item.quantidade_total

      if (statusFilter === 'finalizados') {
        return isFinalizado
      }

      if (statusFilter === 'retirar') {
        return isParaRetirar
      }

      if (statusFilter === 'prontos') {
        return isEmFechamento
      }

      if (statusFilter === 'ativos') {
        return isEmProducao && orig.status_item !== 'Fechando'
      }

      return true // Fallback
    })

    return filtered.filter(
      item =>
        (item.item_descricao || '').toLowerCase().includes(query) ||
        (item.miolo_name || '').toLowerCase().includes(query) ||
        (item.variacao || '').toLowerCase().includes(query),
    )
  }, [demanda?.itens, allProcessedItems, debouncedSearchQuery, statusFilter])

  // Totalizadores por etapa: disponível p/ retirada (expedição) → em fechamento → finalizado
  const stageTotals = useMemo(() => {
    const totals = { capas: 0, miolos: 0, pares: 0, emFechamento: 0, finalizados: 0 }
    for (const item of demanda?.itens || []) {
      const capasRet = item.expedicao_capas_retiradas_qtd || 0
      const miolosRet = item.expedicao_miolos_retirados_qtd || 0
      const capasDisp = Math.max(0, (item.capas_prontas_retirada_qtd || 0) - capasRet)
      const miolosDisp = Math.max(0, (item.miolos_prontos_retirada_qtd || 0) - miolosRet)
      const finalizados = item.finalizados_qtd || 0
      totals.capas += capasDisp
      totals.miolos += miolosDisp
      totals.pares += Math.min(capasDisp, miolosDisp)
      totals.emFechamento += Math.max(0, Math.max(capasRet, miolosRet) - finalizados)
      totals.finalizados += finalizados
    }
    return totals
  }, [demanda?.itens])

  const handleLocalChange = useCallback(
    (itemId, fieldName, delta) => {
      setPendingChanges(prev => {
        const itemChanges = prev[itemId] || {}
        const itemOriginal = demanda.itens.find(
          i => String(i.id) === String(itemId),
        )
        if (!itemOriginal) return prev

        const newPendingItem = { ...itemChanges }

        const updateWithCascade = (field, value) => {
          // Update the current field
          newPendingItem[field] = value

          const dependencies = {
            expedicao_capas_retiradas_qtd: 'capas_prontas_retirada_qtd',
            capas_prontas_retirada_qtd: 'capas_produzidas_qtd',
            capas_produzidas_qtd: 'capas_impressas_qtd',
            expedicao_miolos_retirados_qtd: 'miolos_prontos_retirada_qtd',
          }

          const dependency = dependencies[field]
          if (dependency) {
            const depValue =
              newPendingItem[dependency] !== undefined
                ? newPendingItem[dependency]
                : itemOriginal[dependency] || 0
            if (value > depValue) {
              // Recursive call to update the dependency
              updateWithCascade(dependency, value)
            }
          }
        }

        const currentValue =
          itemChanges[fieldName] !== undefined
            ? itemChanges[fieldName]
            : itemOriginal[fieldName] || 0
        const newValue = currentValue + delta

        updateWithCascade(fieldName, newValue)

        return {
          ...prev,
          [itemId]: newPendingItem,
        }
      })
      return Promise.resolve()
    },
    [demanda],
  )

  const handleBulkSave = async () => {
    if (!hasPendingChanges) return
    setIsSaving(true)
    try {
      const itemIds = Object.keys(pendingChanges)
      const updates = itemIds
        .map(itemId => {
          const changes = pendingChanges[itemId]
          const originalItem = demanda.itens.find(
            i => String(i.id) === String(itemId),
          )

          if (!originalItem) return null

          const producaoIncremental = {}
          Object.keys(changes).forEach(field => {
            const delta = changes[field] - (originalItem[field] || 0)
            if (delta !== 0) producaoIncremental[field] = delta
          })

          if (Object.keys(producaoIncremental).length === 0) return null

          return {
            item_id: itemId,
            producao_incremental: producaoIncremental,
          }
        })
        .filter(Boolean)

      if (updates.length === 0) {
        setPendingChanges({})
        return
      }

      if (isSimulation) {
        await performSimulationAction('producao', { updates })
        setPendingChanges({})
        toast.success('Produção simulada salva')
        return
      }

      console.log(updates)

      const response = await fetch(
        `/api/v2/demanda_producao/${id}/itens/registrar-producao-lote`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ updates }),
        },
      )

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.message || 'Falha ao salvar lote de itens')
      }

      console.log(response)

      toast.success('Alterações salvas!')
      setPendingChanges({})
      await fetchDemanda()
    } catch (e) {
      toast.error(`Erro: ${e.message}`)
    } finally {
      setIsSaving(false)
    }
  }

  const handleCancelChanges = () => setPendingChanges({})

  const handleFinalizeWithQuantity = async (item, quantity) => {
    const saldoRestante = item.quantidade_total - (item.finalizados_qtd || 0)
    const adjustedQuantity = Math.min(quantity, saldoRestante)

    if (adjustedQuantity <= 0) {
      toast.error(`Nenhuma unidade disponível para finalizar.`)
      return
    }

    if (!confirm(`Finalizar ${adjustedQuantity} unidades deste item?`)) return

    setIsFinalizingItemId(item.id)
    try {
      if (isSimulation) {
        await performSimulationAction('finalizar_item', { item_id: item.id, quantidade: adjustedQuantity })
        setPartialQuantities(prev => { const next = { ...prev }; delete next[item.id]; return next })
        toast.success('Finalização simulada registrada')
        return
      }
      const response = await fetch(
        `/api/v2/demanda_producao/${id}/item/${item.id}/finalizar-parcial`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ quantidade_parcial: adjustedQuantity }),
        },
      )
      const data = await response.json()
      if (data.success) {
        toast.success(`${adjustedQuantity} unidades finalizadas!`)
        setPartialQuantities(prev => {
          const newPartials = { ...prev }
          delete newPartials[item.id]
          return newPartials
        })
        await fetchDemanda(true) // Fetch silently
      } else {
        toast.error(data.message)
      }
    } catch (e) {
      toast.error(e.message)
    } finally {
      setIsFinalizingItemId(null)
    }
  }

  const handleRevertFinalization = async item => {
    if (
      !confirm(
        `Tem certeza que deseja reverter a finalização deste item? O status voltará para "Em Andamento"`,
      )
    )
      return

    try {
      if (isSimulation) {
        await performSimulationAction('reverter_item', { item_id: item.id })
        toast.success('Finalização simulada revertida')
        return
      }
      const response = await fetch(
        `/api/v2/demanda_producao/${id}/item/${item.id}/reverter-finalizacao`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        },
      )
      const data = await response.json()
      if (data.success) {
        toast.success(data.message)
        fetchDemanda()
      } else toast.error(data.message)
    } catch (e) {
      toast.error(e.message)
    }
  }

  const handleCollectDemand = () => {
    setIsPartialCollectionModalOpen(true)
  }

  const handleConfirmCollection = async (demandaId, quantity) => {
    if (isSimulation) {
      await performSimulationAction('coletar', { quantidade: quantity })
      toast.success('Coleta simulada registrada')
      return
    }
    const operation = collectionRequestId(demandaId, quantity)
    const response = await fetch(
      `/api/v2/demanda_producao/${demandaId}/coletar`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ quantidade_coletar: quantity, operation_id: operation.id }),
      },
    )
    const data = await response.json()
    if (!response.ok || !data.success) throw new Error(data.message || 'Não foi possível registrar a coleta.')
    sessionStorage.removeItem(operation.key)
    toast.success('Coleta registrada!')
    fetchDemanda()
  }

  const handleCopyOrderChunk = async chunk => {
    try {
      await navigator.clipboard.writeText(chunk)
      toast.success('Lista de pedidos copiada.')
    } catch {
      toast.error('Nao foi possivel copiar a lista.')
    }
  }

  // O papel do pedido e o mesmo documento em qualquer tela que o produza — o
  // template vive em `lib/papeisDePedido`. A copia que existia aqui tinha
  // perdido o rodape com a tag do modelo, que e justamente o que o operador
  // procura primeiro numa folha de personalizado.
  const handlePrintOrderPapers = async () => {
    const pedidos = demanda?.pedidos_origem || []
    const orderIds = pedidos.map(p => p.pedido_id).filter(Boolean)

    if (orderIds.length === 0) {
      toast.warning('Esta demanda nao possui pedidos relacionados.')
      return
    }

    setProgressoImpressao({ processados: 0, total: orderIds.length })
    try {
      const { total, blocked } = await imprimirPapeisDePedido(orderIds, {
        onProgress: setProgressoImpressao,
      })
      if (total === 0) {
        toast.warning('Nenhum papel de pedido encontrado para impressao.')
      } else if (blocked.length > 0) {
        toast.warning(`${total} papeis enviados para impressao. ${blocked.length} ficaram de fora por falta de dados.`)
      } else {
        toast.success(`${total} papeis enviados para impressao.`)
      }
    } catch (error) {
      toast.error(error.message || 'Erro ao imprimir papeis dos pedidos.')
    } finally {
      setProgressoImpressao(null)
    }
  }


  const handleGenerateDemandNfe = async blingIntegrationId => {
    const pedidos = demanda?.pedidos_origem || []
    if (pedidos.length === 0) {
      toast.warning('Esta demanda nao possui pedidos relacionados.')
      return
    }

    setNfeResults([])
    setNfeOperation(null)
    setNfeOperationId(null)
    setNfeGenerating(true)
    setNfeSidebarOpen(true)
    try {
      const response = await fetch(`/api/v2/demanda_producao/${id}/nfe/jobs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ bling_integration_id: blingIntegrationId || null }),
      })
      const result = await response.json()
      if (!response.ok || !result.success) throw new Error(result.message || 'Não foi possível iniciar a emissão de NF-e.')
      const operation = result.data.operation
      setNfeOperation(operation)
      setNfeOperationId(operation.id)
      toast.info('Emissão iniciada. O andamento continuará disponível na central de atividade.')
    } catch (error) {
      setNfeGenerating(false)
      toast.error(error.message || 'Erro ao iniciar emissão de NF-e.')
    }
  }

  const handlePrintItem = async (item, mode) => {
    let quantity = item.quantidade_total
    if (mode === 'balance') {
      quantity = Math.max(
        0,
        item.quantidade_total - (item.capas_impressas_qtd || 0),
      )
    }

    if (quantity <= 0) {
      toast.info('Nada a imprimir.')
      return
    }

    const sku = item.sku || item.sku_externo || item.codigo_sku
    if (!isAgentOnline || !sku) {
      toast.warning('O agente local está offline ou o item não possui SKU.')
      return
    }

    try {
      const mappedFile = await getMappedFileForProduct(sku)
      if (!mappedFile) {
        toast.warning(`Nenhuma arte local está associada ao SKU ${sku}.`)
        return
      }
      const result = await printMappedFile(sku, quantity)
      toast[result.status === 'file_opened' ? 'warning' : 'success'](
        result.message || `Enviado para impressora local: ${quantity} cópias`,
      )
    } catch (error) {
      toast.error(`Erro ao imprimir localmente: ${error.message}`)
    }
  }

  const fieldMapping = {
    capas_impressas: 'capas_impressas_qtd',
    capas_produzidas: 'capas_produzidas_qtd',
    capas_prontas: 'capas_prontas_retirada_qtd',
    miolos_prontos: 'miolos_prontos_retirada_qtd',
    expedicao_capas: 'expedicao_capas_retiradas_qtd',
    expedicao_miolos: 'expedicao_miolos_retirados_qtd',
  }

  // `short` vai no cabeçalho e `label` no tooltip; a borda esquerda marca o
  // início de cada grupo (capa / prontos / expedição) no lugar de pintar a coluna.
  const columnMeta = {
    produto_miolo: { short: 'Produto', label: 'Produto', className: 'w-[30%] min-w-[220px]' },
    miolo: { short: 'Miolo', label: 'Miolo', className: 'w-[18%] min-w-[140px]' },
    total: { short: 'Total', label: 'Quantidade total', className: 'w-[52px] text-center' },
    capas_impressas: { short: 'Imp.', label: 'Capas impressas', icon: FileText, className: 'w-[60px] text-center border-l' },
    capas_produzidas: { short: 'Prod.', label: 'Capas produzidas', icon: Copy, className: 'w-[60px] text-center' },
    capas_prontas: { short: 'Prontas', label: 'Capas prontas para retirada', icon: FileCheck2, className: 'w-[60px] text-center border-l' },
    miolos_prontos: { short: 'Miolos', label: 'Miolos prontos para retirada', icon: Layers, className: 'w-[60px] text-center' },
    expedicao_capas: { short: 'Capas ret.', label: 'Capas retiradas pela expedição', icon: FileText, hand: true, className: 'w-[60px] text-center border-l' },
    expedicao_miolos: { short: 'Miolos ret.', label: 'Miolos retirados pela expedição', icon: Layers, hand: true, className: 'w-[60px] text-center' },
    acoes: { short: 'Finalização', label: 'Finalização', className: 'w-[104px] text-right' },
  }

  const getViewColumns = () => {
    switch (viewMode) {
      case 'capas_miolos':
        return [
          'produto_miolo',
          'miolo',
          'total',
          'capas_impressas',
          'capas_produzidas',
          'capas_prontas',
          'miolos_prontos',
        ]
      case 'expedicao':
        return [
          'produto_miolo',
          'miolo',
          'total',
          'capas_prontas',
          'miolos_prontos',
          'expedicao_capas',
          'expedicao_miolos',
          'acoes',
        ]
      case 'producao':
      default:
        return [
          'produto_miolo',
          'miolo',
          'total',
          'capas_impressas',
          'capas_produzidas',
          'capas_prontas',
          'miolos_prontos',
          'expedicao_capas',
          'expedicao_miolos',
          'acoes',
        ]
    }
  }

  const activeColumns = getViewColumns()

  const handleFillAllForColumn = columnName => {
    const fieldName = fieldMapping[columnName]
    const newPending = { ...pendingChanges }
    filteredItems.forEach(item => {
      if (
        (item[fieldName] || 0) !== item.quantidade_total &&
        item.status_item !== 'Concluído'
      ) {
        newPending[item.id] = {
          ...(newPending[item.id] || {}),
          [fieldName]: item.quantidade_total,
        }
      }
    })
    setPendingChanges(newPending)
    toast.info(`Coluna preenchida localmente.`)
  }

  const getMaxValueForField = (item, fieldName) => {
    switch (fieldName) {
      case 'capas_impressas_qtd':
        return item.quantidade_total
      case 'capas_produzidas_qtd':
        return Math.max(0, item.capas_impressas_qtd || 0)
      case 'capas_prontas_retirada_qtd':
        return Math.max(0, item.capas_produzidas_qtd || 0)
      case 'miolos_prontos_retirada_qtd':
        return item.quantidade_total
      case 'expedicao_capas_retiradas_qtd':
        return Math.max(0, item.capas_prontas_retirada_qtd || 0)
      case 'expedicao_miolos_retirados_qtd':
        return Math.max(0, item.miolos_prontos_retirada_qtd || 0)
      default:
        return undefined
    }
  }

  const renderCell = (item, columnName) => {
    if (columnName === 'produto_miolo') {
      let statusBadge = null
      if (item.status_item !== 'Concluído') {
        const capasParaRetirar = Math.max(0, (item.capas_prontas_retirada_qtd || 0) - (item.expedicao_capas_retiradas_qtd || 0))
        const miolosParaRetirar = Math.max(0, (item.miolos_prontos_retirada_qtd || 0) - (item.expedicao_miolos_retirados_qtd || 0))
        const paresParaRetirar = Math.min(capasParaRetirar, miolosParaRetirar)
        const algumComponenteRetirado =
          (item.expedicao_capas_retiradas_qtd || 0) > 0 ||
          (item.expedicao_miolos_retirados_qtd || 0) > 0
        if (capasParaRetirar > 0 || miolosParaRetirar > 0) {
          const disponibilidade = [
            capasParaRetirar > 0 && `${numero(capasParaRetirar)} cap.`,
            miolosParaRetirar > 0 && `${numero(miolosParaRetirar)} miol.`,
          ].filter(Boolean).join(' · ')
          statusBadge = (
            <Badge
              variant='outline'
              title={`${numero(capasParaRetirar)} capa(s) e ${numero(miolosParaRetirar)} miolo(s) disponível(is) para retirada${paresParaRetirar ? `; ${numero(paresParaRetirar)} par(es) completo(s)` : ''}`}
              className='h-4 shrink-0 px-1.5 text-[10px] tabular-nums border-green-300 text-green-600 bg-green-50'>
              {disponibilidade} p/ retirar
            </Badge>
          )
        } else if (algumComponenteRetirado) {
          statusBadge = (
            <Badge
              variant='outline'
              className='h-4 shrink-0 px-1.5 text-[10px] border-amber-300 text-amber-700 bg-amber-50'>
              Em fechamento
            </Badge>
          )
        } else if ((item.finalizados_qtd || 0) > 0) {
          statusBadge = (
            <Badge
              variant='outline'
              title='Parcialmente finalizado'
              className='h-4 shrink-0 px-1.5 text-[10px] border-blue-300 text-blue-600 bg-blue-50'>
              Parcial
            </Badge>
          )
        }
      }

      const variacao = item.variacao || item.variation || '-'
      const miolo = item.miolo_name || item.miolo || '-'

      return (
        <TableCell key='produto_miolo' className='group relative px-3 py-1.5'>
          <div className='min-w-0'>
            <div
              className='truncate text-[15px] font-semibold leading-tight'
              title={item.item_descricao}>
              {!isSimulation && item.produto_id ? (
                <Link
                  to={`/produtos/${item.produto_id}/editar`}
                  className='hover:text-blue-700 hover:underline'>
                  {item.item_descricao}
                </Link>
              ) : (
                item.item_descricao
              )}
            </div>
            <div className='flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground'>
              <span
                className='truncate'
                title={`Variação: ${variacao}`}>
                {variacao}
              </span>
              {statusBadge}
            </div>
          </div>

          {!isSimulation && (
            <div className='absolute right-1 top-1 flex gap-0.5 rounded bg-background/90 opacity-0 transition-opacity group-hover:opacity-100'>
              <Button
                variant='ghost'
                size='icon'
                className='h-6 w-6'
                onClick={() => setSelectedItemForHistory(item.id)}
                title='Ver Histórico de Estoque'>
                <History className='h-4 w-4 text-purple-600' />
              </Button>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant='ghost'
                    size='icon'
                    className='h-6 w-6'
                    title='Imprimir arquivos de producao deste item'>
                    <Printer className='h-4 w-4 text-gray-500 hover:text-black' />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent>
                  <DropdownMenuItem
                    onClick={() => handlePrintItem(item, 'full')}>
                    Enviar todos os arquivos ({item.quantidade_total})
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onClick={() => handlePrintItem(item, 'balance')}>
                    Enviar arquivos pendentes (
                    {Math.max(
                      0,
                      item.quantidade_total - (item.capas_impressas_qtd || 0),
                    )}
                    )
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          )}
        </TableCell>
      )
    }

    if (columnName === 'miolo') {
      const miolo = item.miolo_name || item.miolo || '-'
      return (
        <TableCell key='miolo' className='px-2 py-1.5 text-sm'>
          {!isSimulation && item.id_produto_miolo ? (
            <Link to={`/produtos/${item.id_produto_miolo}/editar`} className='block truncate text-blue-600 hover:underline' title={miolo}>{miolo}</Link>
          ) : <span className='block truncate' title={miolo}>{miolo}</span>}
        </TableCell>
      )
    }

    if (columnName === 'total')
      return (
        <TableCell
          key={columnName}
          className={`px-2 py-1.5 text-sm font-semibold tabular-nums ${columnMeta.total.className}`}>
          {numero(item.quantidade_total)}
        </TableCell>
      )

    if (columnName === 'acoes') {
      const finalizados_qtd = item.finalizados_qtd || 0
      const isTotalmenteFinalizado =
        item.status_item === 'Concluído' ||
        finalizados_qtd >= item.quantidade_total
      const isItemFinalizing = isFinalizingItemId === item.id

      if (isTotalmenteFinalizado) {
        const canRevert =
          simulationActionsAllowed && (user?.is_admin || (canEditDemand && canExecuteAction('revert_finalize_item')))
        return (
          <TableCell key={columnName} className='px-2 py-1.5 text-right'>
            <div className='flex items-center justify-end gap-1'>
              <Badge className='h-5 px-1.5 text-[10px] tabular-nums bg-green-100 text-green-700 border-green-200'>
                {item.quantidade_total}/{item.quantidade_total} OK
              </Badge>
              {canRevert && (
                <Button
                  variant='outline'
                  size='icon'
                  className='h-7 w-7'
                  onClick={() => handleRevertFinalization(item)}
                  title='Reverter
 Finalização'>
                  <X className='h-3.5 w-3.5 text-red-600' />
                </Button>
              )}
            </div>
          </TableCell>
        )
      }

      if (!simulationActionsAllowed || (!user?.is_admin && !(canEditDemand && canExecuteAction('finalize_item')))) {
        return (
          <TableCell key={columnName} className='px-2 py-1.5 text-right'>
            -
          </TableCell>
        )
      }

      const saldoRestante = item.quantidade_total - finalizados_qtd
      const currentValue =
        partialQuantities[item.id] !== undefined
          ? partialQuantities[item.id]
          : ''

      return (
        <TableCell key={columnName} className='px-2 py-1.5 text-right'>
          <div className='flex flex-col items-end gap-0.5'>
            {finalizados_qtd > 0 && (
              <span className='text-[10px] font-bold tabular-nums text-green-600'>
                Finalizados: {finalizados_qtd}
              </span>
            )}
            <div className='flex justify-end gap-1 items-center'>
              <Input
                type='number'
                min='1'
                max={saldoRestante}
                value={isItemFinalizing ? '...' : currentValue}
                onChange={e => {
                  const value =
                    e.target.value === '' ? '' : parseInt(e.target.value) || 0
                  setPartialQuantities(prev => ({ ...prev, [item.id]: value }))
                }}
                className='h-7 w-11 px-1 text-center text-xs tabular-nums'
                title={`Faltam: ${saldoRestante}`}
                placeholder={saldoRestante > 0 ? saldoRestante.toString() : '0'}
                disabled={saldoRestante <= 0 || isItemFinalizing}
              />
              <Button
                variant='secondary'
                size='icon'
                className='h-7 w-7'
                onClick={() => {
                  const quantityToFinalize =
                    currentValue === '' ? saldoRestante : currentValue
                  handleFinalizeWithQuantity(item, quantityToFinalize)
                }}
                title={`Finalizar ${currentValue === '' ? saldoRestante : currentValue} unidades`}
                disabled={saldoRestante <= 0 || isItemFinalizing}>
                {isItemFinalizing ? (
                  <div className='h-3.5 w-3.5 border-2 border-gray-400 border-t-transparent rounded-full animate-spin' />
                ) : (
                  <CheckCircle className='h-3.5 w-3.5 text-green-600' />
                )}
              </Button>
            </div>
          </div>
        </TableCell>
      )
    }

    const fieldName = fieldMapping[columnName]
    const canEdit =
      simulationActionsAllowed && (user?.is_admin || (canEditDemand && canEditField(fieldName))) &&
      item.status_item !== 'Concluído'
    const maxValue = getMaxValueForField(item, fieldName)

    let estoqueDisponivel = null
    if (columnName === 'miolos_prontos')
      estoqueDisponivel = item.estoque_disponivel_miolo
    if (columnName === 'capas_produzidas')
      estoqueDisponivel = item.estoque_disponivel_capa
    if (columnName === 'capas_impressas')
      estoqueDisponivel = item.estoque_disponivel_impressao

    return (
      <TableCell
        key={columnName}
        className={`px-1 py-1.5 tabular-nums ${columnMeta[columnName].className}`}>
        <div className='flex flex-col items-center gap-0.5'>
          <IncrementalInput
            currentValue={item[fieldName] || 0}
            fieldName={fieldName}
            itemId={item.id}
            onSave={handleLocalChange}
            disabled={!canEdit}
            maxValue={maxValue}
            totalQuantity={item.quantidade_total}
          />
          {!isSimulation && estoqueDisponivel > 0 && (
            <div
              title='Estoque disponível'
              className='rounded bg-green-50 px-1 text-[9px] font-bold tabular-nums text-green-600'>
              {numero(estoqueDisponivel)}
            </div>
          )}
        </div>
      </TableCell>
    )
  }

  if (loading && !demanda)
    return <div className='text-center py-8'>Carregando Dashboard...</div>
  if (error)
    return <div className='text-center py-8 text-red-500'>Erro: {error}</div>
  if (!demanda)
    return <div className='text-center py-8'>Demanda não encontrada.</div>

  const diasRestantes = Math.ceil(
    (new Date(demanda.data_entrega) - new Date()) / (1000 * 60 * 60 * 24),
  )
  const isUrgente = diasRestantes <= 3
  const podePublicarSimulacao = isSimulation && demanda.status === 'RASCUNHO' && canEditDemand
  const podeFinalizarSimulacao =
    isSimulation && demanda.status !== 'RASCUNHO' && demanda.status !== 'COLETADO' &&
    canEditDemand && (user?.is_admin || canExecuteAction('finalize_item'))
  const podeExcluirSimulacao =
    isSimulation && (user?.is_admin || (hasPermission('demanda_producao', 'excluir') && canExecuteAction('delete_demand')))
  const temMaisAcoes = !isSimulation || podePublicarSimulacao || podeFinalizarSimulacao || podeExcluirSimulacao

  return (
    <div className='container mx-auto py-4 px-4 max-w-screen-2xl relative'>
      {!isSimulation && selectedItemForHistory && (
        <StockHistoryViewer
          itemId={selectedItemForHistory}
          onClose={() => setSelectedItemForHistory(null)}
        />
      )}
      {/* Botão Flutuante */}
      {hasPendingChanges && (
        <div className='fixed bottom-8 right-8 z-50 bg-white p-3 rounded-lg shadow-2xl border-2 border-primary animate-in fade-in slide-in-from-bottom-4 flex items-center gap-3'>
          <div className='flex flex-col'>
            <span className='text-sm font-bold'>Alterações Pendentes</span>
            <span className='text-xs text-muted-foreground'>
              {Object.keys(pendingChanges).length} itens
            </span>
          </div>
          <div className='flex gap-2 border-l pl-4'>
            <Button
              variant='outline'
              size='sm'
              onClick={handleCancelChanges}
              disabled={isSaving}>
              <X className='h-4 w-4 mr-1' /> Descartar
            </Button>
            <Button size='sm' onClick={handleBulkSave} disabled={isSaving}>
              {isSaving ? (
                'Salvando...'
              ) : (
                <>
                  <Save className='h-4 w-4 mr-1' /> Salvar Tudo
                </>
              )}
            </Button>
          </div>
        </div>
      )}

      {/* Header */}
      <div className='mb-3 flex items-start justify-between'>
        <div>
          <div className='flex items-center gap-2'>
            <h1 className='text-2xl font-bold text-gray-900'>{demanda.nome}</h1>
            {isSimulation && <Badge className='bg-amber-600 text-white'>SIMULAÇÃO · sem impacto operacional</Badge>}
            {demanda.is_flex && (
              <Badge className='bg-purple-600 text-white border-none animate-pulse'>
                <Flame className='w-3 h-3 mr-1' />
                FLEX
              </Badge>
            )}
          </div>
          <div className='flex items-center gap-2 mt-1'>
            <Badge
              variant='outline'
              className='bg-blue-50 text-blue-700 border-blue-200'>
              {demanda.status}
            </Badge>
            {isUrgente && (
              <Badge className='bg-red-100 text-red-700 border-red-300'>
                Urgente
              </Badge>
            )}
            <span className='text-xs text-muted-foreground ml-2'>
              {demanda.canal_venda_nome}
            </span>
          </div>
        </div>
        <div className='flex flex-wrap items-center justify-end gap-2'>
          <Button variant='outline' size='sm' onClick={() => setShowPedidosOrigem(true)} className='gap-2'>
            <List className='h-4 w-4' /> Pedidos relacionados
          </Button>
          {temMaisAcoes && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant='outline' size='sm' className='gap-2'>
                  <MoreHorizontal className='h-4 w-4' /> Mais ações
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align='end'>
                {podePublicarSimulacao && (
                  <DropdownMenuItem onClick={async () => { try { await performSimulationAction('publicar'); toast.success('Cenário publicado apenas na simulação') } catch (error) { toast.error(error.message) } }}>
                    Publicar na simulação
                  </DropdownMenuItem>
                )}
                {podeFinalizarSimulacao && (
                  <DropdownMenuItem onClick={async () => { if (!window.confirm('Finalizar todos os itens na simulação?')) return; try { await performSimulationAction('finalizar_demanda'); toast.success('Demanda simulada finalizada') } catch (error) { toast.error(error.message) } }}>
                    Finalizar demanda simulada
                  </DropdownMenuItem>
                )}
                {podeExcluirSimulacao && (
                  <DropdownMenuItem onClick={deleteSimulation} className='text-red-600'>
                    Excluir simulação
                  </DropdownMenuItem>
                )}
                {!isSimulation && (
                  <>
                    <DropdownMenuItem onClick={handlePrintOrderPapers} disabled={progressoImpressao !== null}>
                      {progressoImpressao ? <Loader2 className='mr-2 h-4 w-4 animate-spin' /> : <FileText className='mr-2 h-4 w-4' />}
                      {progressoImpressao
                        ? `Preparando ${progressoImpressao.processados}/${progressoImpressao.total}…`
                        : 'Imprimir papéis dos pedidos'}
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={() => handleGenerateDemandNfe()} disabled={nfeGenerating}>
                      {nfeGenerating ? <Loader2 className='mr-2 h-4 w-4 animate-spin' /> : <Receipt className='mr-2 h-4 w-4' />}
                      Gerar NFs dos pedidos
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={() => navigate('/producao/impressao')}>
                      <List className='mr-2 h-4 w-4' /> Fila de impressão
                    </DropdownMenuItem>
                  </>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          )}

          <Link to={isSimulation ? '/despacho' : '/producao/demanda'}>
            <Button variant='ghost' size='icon' className='h-8 w-8' title='Voltar'>
              <ArrowLeft className='h-4 w-4' />
            </Button>
          </Link>
          {demanda.status !== 'Coletado' && demanda.status !== 'COLETADO' && (!isSimulation || demanda.status !== 'RASCUNHO') &&
            canEditDemand && canExecuteAction('collect_demand') && (
              <Button
                size='sm'
                onClick={handleCollectDemand}
                className='bg-green-600 hover:bg-green-700'>
                <Truck className='mr-2 h-4 w-4' /> Coletar
              </Button>
            )}
        </div>
      </div>

      {!isSimulation && <CapaPrintPlanner demandaId={demanda.id} />}

      {isSimulation && <Card className='mb-5 border-amber-300 bg-amber-50/40'><CardContent className='py-3 text-sm'><p className='font-semibold'>Histórico da simulação</p><p className='text-xs text-muted-foreground'>As etapas abaixo existem apenas neste cenário. Pedidos, estoque e coletas reais não foram alterados.</p><div className='mt-2 flex flex-wrap gap-2'>{simulationEvents.map((event, index) => <Badge key={`${event.created_at}-${index}`} variant='outline'>{event.action.replaceAll('_', ' ')} · {new Date(event.created_at).toLocaleString('pt-BR')}</Badge>)}</div></CardContent></Card>}

      {/* Totalizadores numa única faixa */}
      <div className='mb-3 flex flex-wrap items-center gap-x-6 gap-y-2 rounded-lg border bg-muted/30 px-3 py-2 text-sm'>
        <div className='flex items-center gap-2'>
          <span className='text-muted-foreground'>Progresso</span>
          <strong className='tabular-nums'>{demanda.progresso_percentual}%</strong>
          <span className='text-xs tabular-nums text-muted-foreground'>
            {demanda.itens_concluidos}/{demanda.total_itens}
          </span>
          <Progress value={demanda.progresso_percentual} className='h-1 w-20' />
        </div>
        <span className='text-muted-foreground'>
          Entrega
          <strong className={`ml-1 ${isUrgente ? 'text-red-700' : ''}`}>
            {dataCurta(demanda.data_entrega)}
          </strong>
        </span>
        <span className='text-muted-foreground'>
          Unidades <strong className='ml-1 tabular-nums'>{numero(demanda.total_quantidade)}</strong>
        </span>
        <span className='hidden h-4 w-px bg-border sm:block' />
        {[
          ['Capas p/ retirar', stageTotals.capas],
          ['Miolos p/ retirar', stageTotals.miolos],
          ['Pares completos', stageTotals.pares],
          ['Em fechamento', stageTotals.emFechamento],
          ['Finalizados', stageTotals.finalizados],
        ].map(([label, value]) => (
          <span key={label} className='text-muted-foreground'>
            {label} <strong className='ml-1 tabular-nums text-foreground'>{numero(value)}</strong>
          </span>
        ))}
      </div>

      <div className='mb-3 flex flex-wrap items-center gap-2'>
        <div className='relative w-56'>
          <Search className='absolute left-2 top-2.5 h-4 w-4 text-muted-foreground' />
          <Input
            placeholder='Buscar itens...'
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            className='h-9 pl-8'
          />
        </div>
        <div className='flex gap-1' role='group' aria-label='Visão da tabela'>
          {[
            ['producao', 'Geral'],
            ['capas_miolos', 'Capas / Miolos'],
            ['expedicao', 'Expedição'],
          ].map(([mode, label]) => (
            <Button
              key={mode}
              variant={viewMode === mode ? 'default' : 'outline'}
              size='sm'
              onClick={() => setViewMode(mode)}>
              {label}
            </Button>
          ))}
        </div>
        <div className='h-5 w-px bg-border' />
        <div className='flex gap-1' role='group' aria-label='Status do item'>
          {[
            ['ativos', 'Produção'],
            ['retirar', 'Para retirar'],
            ['prontos', 'Em fechamento'],
            ['finalizados', 'Finalizados'],
          ].map(([status, label]) => (
            <Button
              key={status}
              variant={statusFilter === status ? 'default' : 'outline'}
              size='sm'
              onClick={() => setStatusFilter(status)}>
              {label}
            </Button>
          ))}
        </div>
      </div>

      <Card>
        <CardContent className='p-0'>
          <Table containerClassName='overflow-visible'>
            <TableHeader>
              <TableRow>
                {activeColumns.map(col => {
                  const ColumnIcon = columnMeta[col].icon
                  return <TableHead
                    key={col}
                    title={columnMeta[col].label}
                    className={`h-9 px-2 text-xs ${columnMeta[col].className}`}>
                    <div
                      className={`flex items-center gap-1 ${col === 'produto_miolo' ? 'justify-start px-1' : col === 'acoes' ? 'justify-end' : 'justify-center'}`}>
                      {columnMeta[col].icon ? <span className='inline-flex items-center justify-center' aria-label={columnMeta[col].label}>
                        {columnMeta[col].hand ? <span className='relative inline-flex h-5 w-5 items-center justify-center'><ColumnIcon className='h-4 w-4' aria-hidden='true'/><Hand className='absolute -bottom-1 -right-1 h-2.5 w-2.5 rounded-full bg-background' aria-hidden='true'/></span> : <ColumnIcon className='h-4 w-4' aria-hidden='true'/>}
                        <span className='sr-only'>{columnMeta[col].short}</span>
                      </span> : <span>{columnMeta[col].short}</span>}
                      {[
                        'capas_impressas',
                        'capas_produzidas',
                        'capas_prontas',
                        'miolos_prontos',
                        'expedicao_capas',
                        'expedicao_miolos',
                      ].includes(col) &&
                        statusFilter === 'ativos' &&
                        simulationActionsAllowed && (user?.is_admin || (canEditDemand && canEditField(fieldMapping[col]))) && (
                          <Button
                            variant='ghost'
                            size='icon'
                            className='h-4 w-4 shrink-0'
                            onClick={() => handleFillAllForColumn(col)}>
                            <CheckCircle className='h-3 w-3 text-green-600' />
                          </Button>
                        )}
                    </div>
                  </TableHead>
                })}
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredItems.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={activeColumns.length}
                    className='py-8 text-center font-medium text-muted-foreground'>
                    {statusFilter === 'ativos'
                      ? 'Nenhum item em produção ou aguardando retirada.'
                      : statusFilter === 'retirar'
                        ? 'Nenhuma capa ou miolo pronto para retirar.'
                      : statusFilter === 'prontos'
                        ? 'Nenhum produto em fechamento.'
                        : 'Nenhum item com quantidade total finalizada.'}
                  </TableCell>
                </TableRow>
              ) : (
                filteredItems.map(item => (
                  <TableRow key={item.id} className='group/row'>
                    {activeColumns.map(col => renderCell(item, col))}
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <PartialCollectionModal
        isOpen={isPartialCollectionModalOpen}
        onClose={() => setIsPartialCollectionModalOpen(false)}
        demandaId={demanda.id}
        onConfirm={handleConfirmCollection}
        apiBase={apiBase}
      />

      {/* Dialog for viewing related orders */}
      <Dialog open={showPedidosOrigem} onOpenChange={setShowPedidosOrigem}>
        <DialogContent className="max-w-4xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Pedidos Relacionados - {demanda.nome}</DialogTitle>
          </DialogHeader>
          {demanda.pedidos_origem && demanda.pedidos_origem.length > 0 ? (
            <div className="space-y-4">
              {!isSimulation && <div className="flex flex-wrap gap-2">
                <Button variant="outline" size="sm" onClick={handlePrintOrderPapers} className="gap-2" disabled={progressoImpressao !== null}>
                  {progressoImpressao ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />}
                  {progressoImpressao
                    ? `Preparando ${progressoImpressao.processados}/${progressoImpressao.total}…`
                    : 'Imprimir Papeis dos Pedidos'}
                </Button>
                <Button variant="outline" size="sm" onClick={() => handleGenerateDemandNfe()} disabled={nfeGenerating} className="gap-2">
                  {nfeGenerating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Receipt className="h-4 w-4" />}
                  Gerar NFs dos Pedidos
                </Button>
              </div>}

              {!isSimulation && demanda.pedidos_origem_por_bling?.length > 0 && (
                <div className="grid gap-2 md:grid-cols-2">
                  {demanda.pedidos_origem_por_bling.map((grupo, idx) => (
                    <div key={grupo.bling_integration_id || idx} className="rounded-md border p-3">
                      <div className="flex items-center justify-between gap-2">
                        <div>
                          <div className="text-sm font-semibold">{grupo.account_label || 'Conta Bling nao identificada'}</div>
                          <div className="text-xs text-muted-foreground">{grupo.pedidos?.length || 0} pedidos</div>
                        </div>
                        {grupo.bling_integration_id && (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => handleGenerateDemandNfe(grupo.bling_integration_id)}
                            disabled={nfeGenerating}
                            className="gap-2">
                            <Receipt className="h-4 w-4" /> Gerar NFs
                          </Button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {!isSimulation && demanda.pedidos_origem_chunks?.length > 0 && (
                <div className="rounded-md border bg-muted/30 p-3 space-y-2">
                  <div className="text-sm font-semibold">Codigos para busca manual no Bling</div>
                  {demanda.pedidos_origem_chunks.map((chunk, idx) => (
                    <div key={idx} className="flex items-start gap-2">
                      <Input readOnly value={chunk} className="font-mono text-xs" />
                      <Button variant="outline" size="icon" onClick={() => handleCopyOrderChunk(chunk)} title={`Copiar lote ${idx + 1}`}>
                        <Copy className="h-4 w-4" />
                      </Button>
                    </div>
                  ))}
                </div>
              )}

              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Codigo Pedido Externo</TableHead>
                    <TableHead>Numero Pedido</TableHead>
                    <TableHead>Cliente</TableHead>
                    <TableHead>Conta Bling</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {demanda.pedidos_origem.map((pedido, idx) => (
                    <TableRow key={pedido.pedido_id || idx}>
                      <TableCell className="font-mono text-xs">{pedido.codigo_pedido_externo || '-'}</TableCell>
                      <TableCell>{pedido.numero_pedido || '-'}</TableCell>
                      <TableCell>{pedido.cliente_nome || '-'}</TableCell>
                      <TableCell>{pedido.bling_account_label || (pedido.bling_integration_id ? `Conta ${pedido.bling_integration_id}` : '-')}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : (
            <div className="text-center py-8 text-gray-500">
              Nenhum pedido relacionado encontrado.
            </div>
          )}
        </DialogContent>
      </Dialog>

      {!isSimulation && <div className={`fixed inset-y-0 right-0 z-50 w-96 bg-white shadow-2xl transform transition-transform duration-300 ease-in-out ${nfeSidebarOpen ? 'translate-x-0' : 'translate-x-full'}`}>
        <div className="flex h-full flex-col">
          <div className="flex items-center justify-between border-b bg-muted p-4">
            <h3 className="text-lg font-bold">Notas Fiscais dos Pedidos</h3>
            <Button variant="ghost" size="sm" onClick={() => setNfeSidebarOpen(false)}>
              <X className="h-5 w-5" />
            </Button>
          </div>
          <div className="flex-1 overflow-y-auto p-4">
            {nfeGenerating && (
              <div role="status" className="mb-4 flex items-start gap-3 rounded-lg border border-info/20 bg-info-soft p-3 text-sm text-info">
                <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin" />
                <div>
                  <p className="font-semibold">Processo em andamento</p>
                  <p className="mt-1">{nfeOperation?.etapa || 'Preparando emissão'} · {nfeOperation?.progresso_atual || 0} de {nfeOperation?.progresso_total || demanda?.pedidos_origem?.length || 0} pedidos</p>
                  <p className="mt-1 text-xs">Você pode sair desta tela; o andamento está salvo na central de atividade.</p>
                </div>
              </div>
            )}
            {nfeOperation?.status === 'ERRO' && nfeOperation.erro_resumo && (
              <div role="alert" className="mb-4 rounded-lg border border-destructive/20 bg-destructive/5 p-3 text-sm text-destructive">
                {nfeOperation.erro_resumo}
              </div>
            )}
            {nfeResults.length > 0 && (
              <ul className="space-y-2">
                {nfeResults.map((result, idx) => (
                  <li key={idx} className={`rounded-lg border p-3 ${result.success ? 'border-green-200 bg-green-50' : 'border-red-200 bg-red-50'}`}>
                    <div className="mb-1 flex items-center justify-between gap-3">
                      <span className="font-medium">#{result.order?.numero || result.order?.id || 'N/A'}</span>
                      <span className={`text-sm ${result.success ? 'text-green-600' : 'text-red-600'}`}>
                        {result.success ? 'OK' : 'Erro'}
                      </span>
                    </div>
                    {result.account_label && (
                      <p className="text-xs text-muted-foreground">{result.account_label}</p>
                    )}
                    {result.success && result.order?.nfe_id && (
                      <a
                        href={`https://www.bling.com.br/notas.fiscais.php#edit/${result.order.nfe_id}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-sm text-blue-600 hover:underline"
                      >
                        Abrir NF-e
                      </a>
                    )}
                    {result.error && (
                      <p className="mt-1 text-sm text-red-600">{result.error}</p>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {!nfeGenerating && !nfeResults.length && !nfeOperation?.erro_resumo && (
              <div className="py-8 text-center text-sm text-muted-foreground">Nenhum resultado de emissão disponível.</div>
            )}
          </div>
        </div>
      </div>}
    </div>
  )
}

export default DemandaDashboardPage
