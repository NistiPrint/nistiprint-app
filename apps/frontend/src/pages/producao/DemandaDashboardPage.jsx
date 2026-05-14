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
import { Label } from '@/components/ui/label'
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
import { useLayout } from '@/contexts/LayoutContext'
import useLocalAgent from '@/hooks/useLocalAgent'
import usePermissionsHook from '@/hooks/usePermissions'
import useDebounce from '@/lib/hooks/useDebounce'
import { supabase } from '@/lib/supabase'
import {
    ArrowLeft,
    Calendar,
    CheckCircle,
    Copy,
    FileText,
    Flame,
    History,
    List,
    Loader2,
    Package,
    Printer,
    Receipt,
    Save,
    Search,
    TrendingUp,
    Truck,
    X,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { toast } from 'sonner'

function DemandaDashboardPage() {
  const { id } = useParams()
  const { user } = useAuth()
  const { canEditField, canExecuteAction } = usePermissionsHook()
  const { isAgentOnline, printMappedFile, getMappedFileForProduct } =
    useLocalAgent()
  const [demanda, setDemanda] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const { setIsLeftSidebarOpen } = useLayout()

  // Collapse sidebar on mount for this specific page, restore on unmount
  useEffect(() => {
    setIsLeftSidebarOpen(false)
    return () => setIsLeftSidebarOpen(true)
  }, [setIsLeftSidebarOpen])

  // Batch Editing State
  const [pendingChanges, setPendingChanges] = useState({})
  const [isSaving, setIsSaving] = useState(false)
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
  const nfeEventSourceRef = useRef(null)

  const debouncedSearchQuery = useDebounce(searchQuery, 300)

  const hasPendingChanges = Object.keys(pendingChanges).length > 0

  const fetchDemanda = useCallback(
    async (silent = false) => {
      if (!silent) setLoading(true)
      try {
        const response = await fetch(`/api/v2/demanda_producao/${id}`, {
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
    [id],
  )

  // Ref para pendingChanges para acesso seguro dentro do fetch sem causar re-renders do useCallback
  const pendingChangesRef = useRef(pendingChanges)
  useEffect(() => {
    pendingChangesRef.current = pendingChanges
  }, [pendingChanges])

  useEffect(() => {
    return () => {
      if (nfeEventSourceRef.current) {
        nfeEventSourceRef.current.close()
      }
    }
  }, [])

  useEffect(() => {
    fetchDemanda()

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
  }, [id, fetchDemanda, isSaving])

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
      const isProntoParaFechar =
        !isFinalizado &&
        (
          (orig.status_item === 'Fechando') ||
          (
            (orig.capas_prontas_retirada_qtd || 0) >= item.quantidade_total &&
            (orig.miolos_prontos_retirada_qtd || 0) >= item.quantidade_total
          )
        )

      if (statusFilter === 'finalizados') {
        return isFinalizado
      }

      if (statusFilter === 'prontos') {
        return isProntoParaFechar
      }

      if (statusFilter === 'ativos') {
        // Se já está pronto para fechar, deve sair da aba de ativos (produção)
        return !isFinalizado && !isProntoParaFechar
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
    try {
      const response = await fetch(
        `/api/v2/demanda_producao/${demandaId}/coletar`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ quantidade_coletar: quantity }),
        },
      )
      const data = await response.json()
      if (data.success) {
        toast.success('Coleta registrada!')
        fetchDemanda()
      } else {
        toast.error(data.message)
      }
    } catch (e) {
      toast.error(e.message)
    }
  }

  const handlePrintDemanda = async mode => {
    if (
      !confirm(
        `Enviar ${mode === 'full' ? 'TODOS' : 'PENDENTES'} os arquivos de producao para impressao?`,
      )
    )
      return
    try {
      const response = await fetch(
        `/api/v2/printing/demanda/${id}/print?mode=${mode}`,
        { method: 'POST' },
      )
      const data = await response.json()
      if (response.ok) {
        toast.success(`Jobs criados: ${data.count}`)
      } else {
        toast.error(data.error || 'Erro ao criar jobs')
      }
    } catch (e) {
      toast.error(e.message)
    }
  }

  const escapeHtml = value =>
    String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;')

  const handleCopyOrderChunk = async chunk => {
    try {
      await navigator.clipboard.writeText(chunk)
      toast.success('Lista de pedidos copiada.')
    } catch {
      toast.error('Nao foi possivel copiar a lista.')
    }
  }

  const handlePrintOrderPapers = async () => {
    const pedidos = demanda?.pedidos_origem || []
    const orderIds = pedidos.map(p => p.pedido_id).filter(Boolean)

    if (orderIds.length === 0) {
      toast.warning('Esta demanda nao possui pedidos relacionados.')
      return
    }

    try {
      const response = await fetch(
        `/api/v2/pedidos/impressao?order_ids=${orderIds.join(',')}`,
      )
      const payload = await response.json()
      if (!response.ok || !payload.success) {
        throw new Error(payload.message || 'Erro ao carregar pedidos.')
      }

      const orders = payload.data?.orders || []
      if (orders.length === 0) {
        toast.warning('Nenhum papel de pedido encontrado para impressao.')
        return
      }

      const cardsHtml = orders
        .map(
          order => `
          <section class="stamp-card">
            <header class="stamp-header">
              <div>
                <div><strong>Nome:</strong> ${escapeHtml(order.contato?.nome || 'N/A')}</div>
                <div><strong>CPF:</strong> ${escapeHtml(order.contato?.numeroDocumento || 'N/A')}</div>
                ${order.contato?.endereco ? `<div>${escapeHtml(order.contato.endereco)}</div>` : ''}
              </div>
              <div class="order-platform">
                <div>${escapeHtml(order.plataforma || 'Pedido')}</div>
                <div>${escapeHtml(order.numeroLoja || 'N/A')}</div>
              </div>
            </header>
            <main class="stamp-content">
              <div class="order-title">Pedido ${escapeHtml(order.numero || order.id || 'N/A')}</div>
              ${(order.itens || [])
                .map(
                  item => `
                    <div class="item">
                      <div class="item-details">
                        <div>${escapeHtml(item.descricao || 'N/A')}</div>
                        ${item.variacao ? `<div class="muted">${escapeHtml(item.variacao)}</div>` : ''}
                        <strong>${escapeHtml(item.codigo || '')}</strong>
                        ${(item.personalizations || [])
                          .map(p =>
                            p.customization_name
                              ? `<div class="custom-name">${escapeHtml(p.customization_name)}${p.customization_initial ? ` (${escapeHtml(p.customization_initial)})` : ''}${p.quantity_to_personalize > 1 ? ` x${escapeHtml(p.quantity_to_personalize)}` : ''}</div>`
                              : '',
                          )
                          .join('')}
                      </div>
                      <div class="item-qty">${escapeHtml(item.quantidade || 1)}</div>
                      <div class="item-price">R$ ${Number(item.valor || 0).toFixed(2)}</div>
                    </div>
                  `,
                )
                .join('')}
              <div class="total-items">${escapeHtml(order.total_items || 0)} ${(order.total_items || 0) > 1 ? 'itens' : 'item'}</div>
            </main>
          </section>
        `,
        )
        .join('')

      const iframe = document.createElement('iframe')
      iframe.style.position = 'absolute'
      iframe.style.top = '-9999px'
      iframe.style.left = '-9999px'
      document.body.appendChild(iframe)

      iframe.onload = () => {
        iframe.contentWindow.print()
        setTimeout(() => iframe.remove(), 1000)
      }

      iframe.contentDocument.open()
      iframe.contentDocument.write(`
        <html>
          <head>
            <meta charset="utf-8" />
            <title>Papeis dos Pedidos</title>
            <style>
              * { box-sizing: border-box; }
              body { margin: 0; font-family: Arial, sans-serif; color: #111; }
              .stamp-card { width: 210mm; min-height: 297mm; padding: 20mm; page-break-after: always; display: flex; flex-direction: column; }
              .stamp-header { display: flex; justify-content: space-between; gap: 24px; font-size: 20px; margin-bottom: 32px; }
              .stamp-header div div { padding: 8px 0; }
              .order-platform { text-align: right; font-weight: 700; }
              .stamp-content { flex: 1; display: flex; flex-direction: column; }
              .order-title { text-align: center; font-size: 36px; font-weight: 700; margin-bottom: 32px; }
              .item { display: flex; align-items: center; border-top: 1px solid #ddd; padding: 14px 0; }
              .item-details { flex: 1; font-size: 18px; }
              .muted { font-size: 13px; color: #666; }
              .item-qty { width: 12%; text-align: center; font-size: 24px; font-weight: 700; }
              .item-price { width: 14%; text-align: right; font-size: 13px; }
              .custom-name { display: inline-block; margin-top: 8px; padding: 4px 8px; border: 2px solid #111; font-weight: 700; text-transform: uppercase; }
              .total-items { margin-top: auto; text-align: center; font-size: 36px; font-weight: 700; }
            </style>
          </head>
          <body>${cardsHtml}</body>
        </html>
      `)
      iframe.contentDocument.close()
    } catch (error) {
      toast.error(error.message || 'Erro ao imprimir papeis dos pedidos.')
    }
  }

  const handleGenerateDemandNfe = blingIntegrationId => {
    const pedidos = demanda?.pedidos_origem || []
    if (pedidos.length === 0) {
      toast.warning('Esta demanda nao possui pedidos relacionados.')
      return
    }

    if (nfeEventSourceRef.current) {
      nfeEventSourceRef.current.close()
    }

    setNfeResults([])
    setNfeGenerating(true)
    setNfeSidebarOpen(true)

    const params = blingIntegrationId
      ? `?bling_integration_id=${encodeURIComponent(blingIntegrationId)}`
      : ''
    const eventSource = new EventSource(`/api/v2/demanda_producao/${id}/nfe${params}`)
    nfeEventSourceRef.current = eventSource

    eventSource.onmessage = event => {
      const data = JSON.parse(event.data)
      if (data.status === 'complete') {
        setNfeGenerating(false)
        toast.success('Processamento de NFs concluido.')
        eventSource.close()
        return
      }
      setNfeResults(prev => [...prev, data])
      if (data.status === 'error' || data.success === false) {
        toast.error(data.error || 'Erro ao gerar NF.')
      }
    }

    eventSource.onerror = () => {
      toast.error('Erro na conexao com o servidor de NF.')
      setNfeGenerating(false)
      eventSource.close()
    }
  }

  const handlePrintItem = async (item, mode) => {
    // Quantidade a imprimir
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

    // Tentar impressão local se agente estiver online
    if (isAgentOnline && item.produto_id) {
      try {
        const mappedFile = await getMappedFileForProduct(item.produto_id)
        if (mappedFile) {
          if (
            confirm(
              `Arquivo local encontrado: ${mappedFile.file_path}

Deseja imprimir ${quantity} cópias localmente?`,
            )
          ) {
            try {
              await printMappedFile(item.produto_id, quantity)
              toast.success(`Enviado para impressora local: ${quantity} cópias`)
            } catch (printError) {
              console.error('Erro na impressão local:', printError)
              // Extrai mensagem de erro detalhada se disponível
              const errorMsg =
                printError.response?.data?.detail ||
                printError.message ||
                'Erro desconhecido'
              toast.error(`Erro ao imprimir localmente: ${errorMsg}`)
            }
            return // Interrompe fluxo para não tentar nuvem (pois o usuário escolheu local)
          }
        }
      } catch (localError) {
        console.warn(
          'Falha na verificação local (ignorado), tentando nuvem...',
          localError,
        )
      }
    }

    // Fallback para impressão via Nuvem (Print Node / Server)
    try {
      const response = await fetch(
        `/api/v2/printing/item/${item.id}/print?mode=${mode}`,
        { method: 'POST' },
      )
      const data = await response.json()
      if (response.ok) {
        toast.success(`Jobs criados (Nuvem): ${data.count}`)
      } else {
        toast.error(data.error || 'Erro ao criar jobs')
      }
    } catch (e) {
      toast.error(e.message)
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

  const columnTitles = {
    produto_miolo: 'Produto / Miolo',
    total: 'Total',
    capas_impressas: 'Capas Imp.',
    capas_produzidas: 'Capas Prod.',
    capas_prontas: 'Capas Prontas',
    miolos_prontos: 'Miolos Prontos',
    expedicao_capas: 'Exp. Capas',
    expedicao_miolos: 'Exp. Miolos',
    acoes: 'Finalização',
  }

  const columnClasses = {
    capas_impressas: 'text-center bg-gray-50/50 w-24',
    capas_produzidas: 'text-center bg-orange-50/50 w-24',
    capas_prontas: 'text-center bg-blue-50/50 w-24',
    miolos_prontos: 'text-center bg-blue-50/50 w-24',
    expedicao_capas: 'text-center bg-green-50/50 w-24',
    expedicao_miolos: 'text-center bg-green-50/50 w-24',
    acoes: 'text-right w-40', // Aumentar largura para caber as infos
  }

  const getViewColumns = () => {
    switch (viewMode) {
      case 'capas_miolos':
        return [
          'produto_miolo',
          'total',
          'capas_impressas',
          'capas_produzidas',
          'capas_prontas',
          'miolos_prontos',
        ]
      case 'expedicao':
        return [
          'produto_miolo',
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
        if ((item.finalizados_qtd || 0) > 0) {
          statusBadge = (
            <Badge
              variant='outline'
              className='border-blue-300 text-blue-600 bg-blue-50'>
              Parcialmente Finalizado
            </Badge>
          )
        } else if (
          !(
            (item.expedicao_capas_retiradas_qtd || 0) > 0 ||
            (item.expedicao_miolos_retirados_qtd || 0) > 0
          ) &&
          (item.capas_prontas_retirada_qtd || 0) >= item.quantidade_total &&
          (item.miolos_prontos_retirada_qtd || 0) >= item.quantidade_total
        ) {
          statusBadge = (
            <Badge
              variant='outline'
              className='border-green-300 text-green-600 bg-green-50'>
              Pronto p/ Expedição
            </Badge>
          )
        }
      }

      return (
        <TableCell key='produto_miolo' className='max-w-[300px] group relative'>
          <div className='flex justify-between items-start'>
            <div>
              <div
                className='font-medium text-sm leading-tight mb-1'
                title={item.item_descricao}>
                {item.produto_id ? (
                  <Link
                    to={`/produtos/${item.produto_id}/editar`}
                    className='text-blue-600 hover:underline'>
                    {item.item_descricao}
                  </Link>
                ) : (
                  item.item_descricao
                )}
              </div>
              <div className='text-xs text-muted-foreground leading-tight mb-1'>
                <span className='font-semibold text-gray-500'>Var:</span>{' '}
                {item.variacao || item.variation || '-'} <br />
                <span className='font-semibold text-gray-500'>Mio: </span>
                {item.id_produto_miolo ? (
                  <Link
                    to={`/produtos/${item.id_produto_miolo}/editar`}
                    className='text-blue-600 hover:underline'>
                    {item.miolo_name || item.miolo || '-'}
                  </Link>
                ) : (
                  item.miolo_name || item.miolo || '-'
                )}
              </div>
              {statusBadge}
            </div>

            <div className='opacity-0 group-hover:opacity-100 transition-opacity flex gap-1'>
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
          </div>
        </TableCell>
      )
    }

    if (columnName === 'total')
      return (
        <TableCell key={columnName} className='text-center font-bold text-sm'>
          {item.quantidade_total}
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
          user?.is_admin || canExecuteAction('revert_finalize_item')
        return (
          <TableCell key={columnName} className='text-right'>
            <div className='flex items-center justify-end gap-2'>
              <Badge className='bg-green-100 text-green-700 border-green-200'>
                {item.quantidade_total}/{item.quantidade_total} FINALIZADO
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

      if (!user?.is_admin && !canExecuteAction('finalize_item')) {
        return (
          <TableCell key={columnName} className='text-right'>
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
        <TableCell key={columnName} className='text-right'>
          <div className='flex flex-col items-end gap-1'>
            {finalizados_qtd > 0 && (
              <span className='text-[10px] text-green-600 font-bold'>
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
                className='w-16 h-7 text-xs'
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
      (user?.is_admin || canEditField(fieldName)) &&
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
      <TableCell key={columnName} className={`${columnClasses[columnName]}`}>
        <div className='flex flex-col items-center gap-1'>
          <IncrementalInput
            currentValue={item[fieldName] || 0}
            fieldName={fieldName}
            itemId={item.id}
            onSave={handleLocalChange}
            disabled={!canEdit}
            maxValue={maxValue}
            totalQuantity={item.quantidade_total}
          />
          {estoqueDisponivel !== null && (
            <div
              className={`text-[9px] font-bold px-1 rounded ${estoqueDisponivel > 0 ? 'text-green-600 bg-green-50' : 'text-gray-400 bg-gray-50'}`}>
              Est: {estoqueDisponivel}
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

  return (
    <div className='container mx-auto py-6 px-4 max-w-7xl relative'>
      {selectedItemForHistory && (
        <StockHistoryViewer
          itemId={selectedItemForHistory}
          onClose={() => setSelectedItemForHistory(null)}
        />
      )}
      {/* Botão Flutuante */}
      {hasPendingChanges && (
        <div className='fixed bottom-8 right-8 z-50 bg-white p-4 rounded-lg shadow-2xl border-2 border-primary animate-in fade-in slide-in-from-bottom-4 flex items-center gap-4'>
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
      <div className='flex items-start justify-between mb-6'>
        <div>
          <div className='flex items-center gap-2'>
            <h1 className='text-2xl font-bold text-gray-900'>{demanda.nome}</h1>
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
        <div className='flex flex-wrap justify-end gap-2'>
          <Button variant='outline' onClick={() => setShowPedidosOrigem(true)} className='gap-2'>
            <List className='h-4 w-4' /> Ver Pedidos Relacionados
          </Button>
          <Button variant='outline' onClick={handlePrintOrderPapers} className='gap-2'>
            <FileText className='h-4 w-4' /> Imprimir Papeis dos Pedidos
          </Button>
          <Button variant='outline' onClick={() => handleGenerateDemandNfe()} disabled={nfeGenerating} className='gap-2'>
            {nfeGenerating ? <Loader2 className='h-4 w-4 animate-spin' /> : <Receipt className='h-4 w-4' />}
            Gerar NFs dos Pedidos
          </Button>
          <Link to='/producao/impressao'>
            <Button variant='outline' size='icon' title='Fila de arquivos de producao'>
              <List className='h-4 w-4' />
            </Button>
          </Link>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant='outline' title='Impressao de arquivos de producao'>
                <Printer className='h-4 w-4 mr-2' /> Arquivos de Producao
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent>
              <DropdownMenuItem onClick={() => handlePrintDemanda('full')}>
                Enviar todos os arquivos
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => handlePrintDemanda('balance')}>
                Enviar arquivos pendentes
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>

          <Link to='/producao/demanda'>
            <Button variant='ghost' size='icon'>
              <ArrowLeft className='h-4 w-4' />
            </Button>
          </Link>
          {demanda.status !== 'Coletado' &&
            canExecuteAction('collect_demand') && (
              <Button
                onClick={handleCollectDemand}
                className='bg-green-600 hover:bg-green-700'>
                <Truck className='mr-2 h-4 w-4' /> Coletar
              </Button>
            )}
        </div>
      </div>

      {/* Stats */}
      <div className='grid grid-cols-1 md:grid-cols-4 gap-4 mb-6'>
        <Card className='p-3 flex items-center gap-3'>
          <TrendingUp className='h-5 w-5 text-blue-500' />
          <div className='flex-1'>
            <p className='text-[10px] text-muted-foreground uppercase font-bold'>
              Progresso
            </p>
            <div className='flex items-center justify-between'>
              <span className='text-sm font-bold'>
                {demanda.progresso_percentual}%
              </span>
              <span className='text-[10px]'>
                {demanda.itens_concluidos}/{demanda.total_itens}
              </span>
            </div>
            <Progress
              value={demanda.progresso_percentual}
              className='h-1.5 mt-1'
            />
          </div>
        </Card>
        <Card className='p-3 flex items-center gap-3'>
          <Calendar
            className={`h-5 w-5 ${isUrgente ? 'text-red-500' : 'text-green-500'}`}
          />
          <div>
            <p className='text-[10px] text-muted-foreground uppercase font-bold'>
              Entrega
            </p>
            <p className='text-sm font-bold'>
              {new Date(demanda.data_entrega).toLocaleDateString('pt-BR')}
            </p>
          </div>
        </Card>
        <Card className='p-3 flex items-center gap-3'>
          <Package className='h-5 w-5 text-purple-500' />
          <div>
            <p className='text-[10px] text-muted-foreground uppercase font-bold'>
              Total Unidades
            </p>
            <p className='text-sm font-bold'>{demanda.total_quantidade}</p>
          </div>
        </Card>
        <div className='relative'>
          <Search className='absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground' />
          <Input
            placeholder='Buscar itens...'
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            className='pl-9 h-full'
          />
        </div>
      </div>

      <div className='flex items-center justify-between mb-4 gap-4'>
        <div className='flex gap-4 items-end'>
          <div className='flex flex-col gap-1'>
            <Label className='text-xs text-muted-foreground'>Ver como</Label>
            <div className='flex gap-1'>
              <Button
                variant={viewMode === 'producao' ? 'default' : 'outline'}
                size='sm'
                onClick={() => setViewMode('producao')}>
                Geral
              </Button>
              <Button
                variant={viewMode === 'capas_miolos' ? 'default' : 'outline'}
                size='sm'
                onClick={() => setViewMode('capas_miolos')}>
                Capas / Miolos
              </Button>
              <Button
                variant={viewMode === 'expedicao' ? 'default' : 'outline'}
                size='sm'
                onClick={() => setViewMode('expedicao')}>
                Expedição
              </Button>
            </div>
          </div>

          <div className='flex flex-col gap-1 border-l pl-4'>
            <Label className='text-xs text-muted-foreground'>
              Status do Item
            </Label>
            <div className='flex gap-1'>
              <Button
                variant={statusFilter === 'ativos' ? 'default' : 'outline'}
                size='sm'
                onClick={() => setStatusFilter('ativos')}>
                Produção
              </Button>
              <Button
                variant={statusFilter === 'prontos' ? 'default' : 'outline'}
                size='sm'
                onClick={() => setStatusFilter('prontos')}>
                Prontos para Fechar
              </Button>
              <Button
                variant={statusFilter === 'finalizados' ? 'default' : 'outline'}
                size='sm'
                onClick={() => setStatusFilter('finalizados')}>
                Finalizados
              </Button>
            </div>
          </div>
        </div>
      </div>

      <Card>
        <CardContent className='p-0'>
          <Table>
            <TableHeader>
              <TableRow>
                {activeColumns.map(col => (
                  <TableHead key={col} className={columnClasses[col]}>
                    <div className='flex items-center justify-between'>
                      <span>{columnTitles[col]}</span>
                      {[
                        'capas_impressas',
                        'capas_produzidas',
                        'capas_prontas',
                        'miolos_prontos',
                        'expedicao_capas',
                        'expedicao_miolos',
                      ].includes(col) &&
                        statusFilter === 'ativos' &&
                        (user?.is_admin || canEditField(fieldMapping[col])) && (
                          <Button
                            variant='ghost'
                            size='icon'
                            className='h-4 w-4'
                            onClick={() => handleFillAllForColumn(col)}>
                            <CheckCircle className='h-3 w-3 text-green-600' />
                          </Button>
                        )}
                    </div>
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredItems.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={activeColumns.length}
                    className='text-center py-8 text-muted-foreground font-medium'>
                    {statusFilter === 'ativos'
                      ? 'Nenhum item em andamento.'
                      : 'Nenhum item com quantidade total finalizada.'}
                  </TableCell>
                </TableRow>
              ) : (
                filteredItems.map(item => (
                  <TableRow key={item.id}>
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
      />

      {/* Dialog for viewing related orders */}
      <Dialog open={showPedidosOrigem} onOpenChange={setShowPedidosOrigem}>
        <DialogContent className="max-w-4xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Pedidos Relacionados - {demanda.nome}</DialogTitle>
          </DialogHeader>
          {demanda.pedidos_origem && demanda.pedidos_origem.length > 0 ? (
            <div className="space-y-4">
              <div className="flex flex-wrap gap-2">
                <Button variant="outline" size="sm" onClick={handlePrintOrderPapers} className="gap-2">
                  <FileText className="h-4 w-4" /> Imprimir Papeis dos Pedidos
                </Button>
                <Button variant="outline" size="sm" onClick={() => handleGenerateDemandNfe()} disabled={nfeGenerating} className="gap-2">
                  {nfeGenerating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Receipt className="h-4 w-4" />}
                  Gerar NFs dos Pedidos
                </Button>
              </div>

              {demanda.pedidos_origem_por_bling?.length > 0 && (
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

              {demanda.pedidos_origem_chunks?.length > 0 && (
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

      <div className={`fixed inset-y-0 right-0 z-50 w-96 bg-white shadow-2xl transform transition-transform duration-300 ease-in-out ${nfeSidebarOpen ? 'translate-x-0' : 'translate-x-full'}`}>
        <div className="flex h-full flex-col">
          <div className="flex items-center justify-between border-b bg-muted p-4">
            <h3 className="text-lg font-bold">Notas Fiscais dos Pedidos</h3>
            <Button variant="ghost" size="sm" onClick={() => setNfeSidebarOpen(false)}>
              <X className="h-5 w-5" />
            </Button>
          </div>
          <div className="flex-1 overflow-y-auto p-4">
            {nfeGenerating && nfeResults.length === 0 && (
              <div className="flex h-full flex-col items-center justify-center text-muted-foreground">
                <Loader2 className="mb-2 h-8 w-8 animate-spin" />
                <p>Processando pedidos...</p>
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
          </div>
        </div>
      </div>
    </div>
  )
}

export default DemandaDashboardPage
