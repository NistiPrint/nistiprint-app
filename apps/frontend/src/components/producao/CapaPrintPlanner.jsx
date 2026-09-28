import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { Check, Clipboard, Loader2, Printer, RefreshCw, ExternalLink, Wifi, WifiOff } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import useLocalAgent from '@/hooks/useLocalAgent'
import LocalAgentService from '@/services/LocalAgentService'
import capaPrintService from '@/services/capaPrintService'

const requestId = () => globalThis.crypto?.randomUUID?.() || 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (digit) => {
  const random = Math.floor(Math.random() * 16)
  return (digit === 'x' ? random : (random & 0x3) | 0x8).toString(16)
})
const quantity = (value) => Number(value || 0)
const sentQuantity = (sends) => sends.filter((send) => send.status !== 'erro' || send.agent_job_id)
  .reduce((sum, send) => sum + quantity(send.quantidade), 0)
const displayQuantity = (value) => Number(value || 0).toLocaleString('pt-BR', { maximumFractionDigits: 2 })
const EMPTY_LINES = []

function statusText(status) {
  const labels = {
    queued: 'Na fila', na_fila: 'Na fila', preparing: 'Preparando', printing: 'Imprimindo', sent: 'Enviado',
    impresso: 'Saiu da fila', saiu_da_fila: 'Saiu da fila', sem_rastreio: 'Enviado, sem rastreio',
    erro: 'Erro na impressora', sem_papel: 'Sem papel', impressora_offline: 'Impressora offline',
    paused: 'Pausado', file_opened: 'Editor aberto', cancelled: 'Cancelado',
  }
  return labels[status] || status || 'Sem envio'
}

function groupItems(items = []) {
  const groups = new Map()
  for (const item of items.filter((entry) => quantity(entry.quantidade_planejada) > 0)) {
    const key = item.chave_grupo || `${item.produto_capa_id}|${item.sku_capa}|${item.variacao || ''}`
    const group = groups.get(key) || {
      key,
      sku: item.sku_capa,
      coverId: item.produto_capa_id,
      title: item.capa_nome || item.sku_capa || 'Capa sem cadastro',
      variation: item.variacao || '',
      items: [],
      types: new Set(),
    }
    group.items.push(item)
    group.types.add(item.tipo)
    groups.set(key, group)
  }
  return [...groups.values()]
}

export default function CapaPrintPlanner({ pedidoIds = [], lines = EMPTY_LINES, previsaoVersao = null, demandaId = null, onPlanChange = null }) {
  const { isAgentOnline, checkingAgent } = useLocalAgent()
  const [plan, setPlan] = useState(null)
  const [isOpen, setIsOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState('')
  const [confirmValues, setConfirmValues] = useState({})
  const [mappings, setMappings] = useState({})
  const groups = useMemo(() => groupItems(plan?.itens), [plan?.itens])
  const linesSignature = useMemo(() => JSON.stringify(lines), [lines])
  const groupSkusSignature = useMemo(() => groups.map((group) => group.sku).filter(Boolean).join('|'), [groups])

  useEffect(() => {
    let alive = true
    if (!isAgentOnline) {
      setMappings({})
      return undefined
    }
    LocalAgentService.getMappings().then((result) => {
      if (alive) setMappings(result.mappings || {})
    }).catch(() => {
      if (alive) setMappings({})
    })
    return () => { alive = false }
  }, [isAgentOnline, groupSkusSignature])

  const loadDemandPlan = useCallback(async () => {
    if (!demandaId) return
    setLoading(true)
    try {
      const next = await capaPrintService.getPlan({ demanda_id: demandaId })
      setPlan(next)
      onPlanChange?.(next)
    } catch (error) {
      toast.error(error.message)
    } finally {
      setLoading(false)
    }
  }, [demandaId, onPlanChange])

  useEffect(() => {
    if (demandaId) {
      loadDemandPlan()
      return undefined
    }
    if (!previsaoVersao || pedidoIds.length === 0) {
      setPlan(null)
      onPlanChange?.(null)
      return undefined
    }
    let alive = true
    onPlanChange?.(null)
    const timer = window.setTimeout(async () => {
      setLoading(true)
      try {
        const next = await capaPrintService.savePlan({
          pedido_ids: pedidoIds,
          linhas: lines,
          previsao_versao: previsaoVersao,
        })
        if (alive) {
          setPlan(next)
          onPlanChange?.(next)
        }
      } catch (error) {
        if (alive) toast.error(`Plano de impressão: ${error.message}`)
      } finally {
        if (alive) setLoading(false)
      }
    }, 450)
    return () => { alive = false; window.clearTimeout(timer) }
  }, [demandaId, loadDemandPlan, pedidoIds, lines, linesSignature, previsaoVersao, onPlanChange])

  useEffect(() => {
    if (!plan?.envios?.length || !isAgentOnline) return undefined
    let alive = true
    const poll = async () => {
      for (const send of plan.envios) {
        if (!send.agent_job_id || !['queued', 'na_fila', 'preparando', 'imprimindo', 'enviado'].includes(send.status)) continue
        try {
          const status = await LocalAgentService.getPrintJob(send.agent_job_id)
          if (!alive || status.queue_status === send.status) continue
          const updated = await capaPrintService.updateSend(plan.id, send.request_id, {
            status: status.queue_status,
            mensagem: status.message || null,
          })
          if (alive) setPlan(updated)
        } catch (error) {
          if (error.response?.status === 404 && alive) {
            try {
              const updated = await capaPrintService.updateSend(plan.id, send.request_id, {
                status: 'sem_rastreio',
                mensagem: 'O trabalho já não está disponível na fila local deste agente.',
              })
              if (alive) setPlan(updated)
            } catch {
              // O estado mais recente continua salvo localmente no plano.
            }
          }
        }
      }
    }
    const interval = window.setInterval(poll, 8000)
    poll()
    return () => { alive = false; window.clearInterval(interval) }
  }, [plan?.id, plan?.envios, isAgentOnline])

  const copyNames = async (group) => {
    const nameItems = group.items.filter((item) => item.tipo === 'personalizada' && item.nome_personalizado)
    const names = nameItems.flatMap((item) => {
      const count = quantity(item.quantidade_planejada)
      return Number.isInteger(count) && count > 1
        ? Array(count).fill(item.nome_personalizado)
        : [count > 1 ? `${item.nome_personalizado} × ${displayQuantity(count)}` : item.nome_personalizado]
    }).join('\n')
    try {
      await navigator.clipboard.writeText(names)
      toast.success(`${nameItems.reduce((sum, item) => sum + quantity(item.quantidade_planejada), 0)} capa(s) personalizada(s) copiada(s).`)
    } catch {
      toast.error('Não foi possível copiar os nomes.')
    }
  }

  const registerResult = async (group, result, type, copies) => {
    if (result.status === 'cancelled' || result.status === 'cancelled_size_warning') return
    try {
      const updated = await capaPrintService.registerSend(plan.id, {
        request_id: result.request_id,
        chave_grupo: group.key,
        sku_capa: group.sku,
        tipo: type,
        quantidade: copies,
        printer_name: result.printer_name || null,
        agent_job_id: result.job_id || null,
        status: result.status === 'queued' ? 'queued' : (result.status || 'sem_rastreio'),
        mensagem: result.message || null,
      })
      setPlan(updated)
    } catch (error) {
      toast.error(`O agente respondeu, mas o envio não foi salvo no plano: ${error.message}`)
    }
  }

  const registerFailure = async (group, id, type, copies, error) => {
    if (!id) return
    try {
      const updated = await capaPrintService.registerSend(plan.id, {
        request_id: id,
        chave_grupo: group.key,
        sku_capa: group.sku,
        tipo: type,
        quantidade: copies,
        status: 'erro',
        mensagem: error.response?.data?.error || error.message || 'Falha ao enviar para o agente local',
      })
      setPlan(updated)
    } catch {
      // A mensagem da operação continua visível mesmo quando a API também falha.
    }
  }

  const printGroup = async (group, fromBatch = false) => {
    if (!isAgentOnline || (!group.sku && !group.coverId)) {
      toast.warning('O agente está offline ou a capa não possui identificador no cadastro.')
      return
    }
    const planned = group.items.filter((item) => item.tipo === 'estatica')
      .reduce((sum, item) => sum + quantity(item.quantidade_planejada), 0)
    const sent = sentQuantity((plan.envios || []).filter((send) => send.chave_grupo === group.key && send.tipo === 'estatica'))
    const copies = Math.floor(planned - sent)
    if (copies <= 0) {
      toast.info('Não há cópias estáticas pendentes neste modelo.')
      return
    }
    if (copies !== planned - sent) {
      toast.warning('A quantidade calculada não é inteira; ajuste a ficha de materiais ou o plano antes de imprimir.')
      return
    }
    setBusy(group.key)
    let id = null
    try {
      const mapping = await LocalAgentService.getMappedFile(group.sku, group.coverId)
      if (!mapping || !mapping.file_path?.toLowerCase().endsWith('.pdf')) {
        toast.warning(`Associe um PDF ao SKU ${group.sku} no cadastro da capa.`)
        return
      }
      id = requestId()
      const result = await LocalAgentService.printWithDialog(group.sku, copies, id, group.coverId)
      await registerResult(group, result, 'estatica', copies)
      if (result.status === 'cancelled' || result.status === 'cancelled_size_warning') toast.info('Impressão cancelada.')
      else toast.success(`Trabalho enviado: ${copies} cópia(s) · ${statusText(result.status)}`)
    } catch (error) {
      await registerFailure(group, id, 'estatica', copies, error)
      toast.error(`Falha ao imprimir ${group.title}: ${error.response?.data?.error || error.message}`)
    } finally {
      setBusy(fromBatch ? '__batch__' : '')
    }
  }

  const openEditor = async (group) => {
    if (!isAgentOnline || (!group.sku && !group.coverId)) {
      toast.warning('O agente está offline ou a capa não possui identificador no cadastro.')
      return
    }
    setBusy(group.key)
    let id = null
    try {
      const mapping = await LocalAgentService.getMappedFile(group.sku, group.coverId)
      if (!mapping || !mapping.file_path?.toLowerCase().endsWith('.pdf')) {
        toast.warning(`Associe um PDF ao SKU ${group.sku} no cadastro da capa.`)
        return
      }
      id = requestId()
      const result = await LocalAgentService.openMappedPdf(group.sku, id, group.coverId)
      await registerResult(group, result, 'abrir_editor', 0)
      toast.success('PDF base aberto no editor padrão.')
    } catch (error) {
      await registerFailure(group, id, 'abrir_editor', 0, error)
      toast.error(`Não foi possível abrir o PDF base: ${error.response?.data?.error || error.message}`)
    } finally {
      setBusy('')
    }
  }

  const confirmStatic = async (group) => {
    const planned = group.items.filter((item) => item.tipo === 'estatica')
      .reduce((sum, item) => sum + quantity(item.quantidade_planejada), 0)
    const sent = sentQuantity((plan.envios || []).filter((send) => send.chave_grupo === group.key && send.tipo === 'estatica'))
    const value = Number(confirmValues[group.key] ?? Math.min(planned, sent))
    if (value > sent) {
      toast.warning('Confirme no máximo a quantidade enviada para este modelo.')
      return
    }
    try {
      setPlan(await capaPrintService.confirmGroup(plan.id, group.key, value))
      toast.success('Quantidade impressa confirmada.')
    } catch (error) {
      toast.error(error.message)
    }
  }

  const confirmPersonalized = async (item) => {
    try {
      setPlan(await capaPrintService.confirmItem(plan.id, item.id, quantity(item.quantidade_planejada)))
      toast.success(`${item.nome_personalizado} confirmado.`)
    } catch (error) {
      toast.error(error.message)
    }
  }

  const printBatch = async () => {
    const staticGroups = groups.filter((group) => group.items.some((item) => item.tipo === 'estatica'))
    if (!staticGroups.length) return
    setBusy('__batch__')
    try {
      for (const group of staticGroups) {
        await printGroup(group, true)
      }
    } finally {
      setBusy('')
    }
  }

  if (!demandaId && (!pedidoIds.length || !previsaoVersao)) return null
  const allSendEvents = plan?.envios || []

  return (
    <div className="inline-block">
      <Button type="button" variant="outline" onClick={() => setIsOpen(true)}>
        <Printer className="mr-2 h-4 w-4" /> Controle de impressão de capas
        {groups.length > 0 && <Badge variant="secondary" className="ml-2">{groups.length}</Badge>}
      </Button>
      <Dialog open={isOpen} onOpenChange={setIsOpen}>
        <DialogContent className="max-h-[90vh] w-[calc(100%-2rem)] max-w-6xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Controle de impressão de capas</DialogTitle>
            <DialogDescription>
              {demandaId ? `Plano vinculado à demanda ${demandaId}.` : 'Capas e quantidades deste lote, calculadas pela prévia atual.'}
            </DialogDescription>
          </DialogHeader>
    <section className="space-y-3" aria-label="Planejamento de impressão de capas">
      <div className="flex flex-wrap items-center gap-2">
        <div>
          <h2 className="text-lg font-semibold">Plano de impressão de capas</h2>
          <p className="text-sm text-muted-foreground">Capas agrupadas pela ficha de materiais · progresso salvo entre telas</p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <Badge variant={isAgentOnline ? 'default' : 'secondary'}>
            {checkingAgent ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : isAgentOnline ? <Wifi className="mr-1 h-3 w-3" /> : <WifiOff className="mr-1 h-3 w-3" />}
            {checkingAgent ? 'Verificando agente' : isAgentOnline ? 'Agente online' : 'Agente offline'}
          </Badge>
          {demandaId && <Button type="button" size="sm" variant="outline" onClick={loadDemandPlan} disabled={loading}><RefreshCw className="mr-2 h-4 w-4" /> Atualizar</Button>}
          {!demandaId && loading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" aria-label="Atualizando plano" />}
          {groups.some((group) => group.items.some((item) => item.tipo === 'estatica')) && <Button type="button" size="sm" onClick={printBatch} disabled={!isAgentOnline || Boolean(busy)}><Printer className="mr-2 h-4 w-4" /> Imprimir lote</Button>}
        </div>
      </div>

      {!isAgentOnline && <Card className="border-amber-300 bg-amber-50/60"><CardContent className="py-3 text-sm text-amber-900">O plano continua disponível. Inicie o agente local nesta máquina para abrir ou imprimir arquivos.</CardContent></Card>}
      {plan?.previsao_versao && plan.previsao_versao !== previsaoVersao && !demandaId && <Card className="border-amber-300"><CardContent className="py-3 text-sm">A quantidade da prévia mudou; confira novamente o plano antes do envio.</CardContent></Card>}
      {plan && groups.length === 0 && <Card><CardContent className="py-4 text-sm text-muted-foreground">Nenhuma capa configurada na ficha de materiais para este lote.</CardContent></Card>}
      {groups.length > 0 && <div className="overflow-x-auto rounded-md border bg-background">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Capa</TableHead>
              <TableHead>Tipo</TableHead>
              <TableHead className="text-right">Prevista</TableHead>
              <TableHead>Andamento</TableHead>
              <TableHead className="text-right">Ação</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
      {groups.map((group) => {
        const custom = group.items.filter((item) => item.tipo === 'personalizada')
        const pending = group.items.filter((item) => item.tipo === 'pendente')
        const staticItems = group.items.filter((item) => item.tipo === 'estatica')
        const isStatic = staticItems.length > 0
        const mapping = (group.sku ? mappings[group.sku] : null)
          || Object.values(mappings).find((entry) => String(entry.product_id || '') === String(group.coverId || ''))
        const hasPdf = Boolean(mapping?.file_path?.toLowerCase().endsWith('.pdf'))
        const planned = staticItems.reduce((sum, item) => sum + quantity(item.quantidade_planejada), 0)
        const sends = allSendEvents.filter((send) => send.chave_grupo === group.key && send.tipo === 'estatica')
        const sent = sentQuantity(sends)
        const confirmed = (plan.grupos || []).find((entry) => entry.chave_grupo === group.key)?.quantidade_confirmada || 0
        const customConfirmed = custom.reduce((sum, item) => sum + quantity(item.quantidade_confirmada), 0)
        const customPlanned = custom.reduce((sum, item) => sum + quantity(item.quantidade_planejada), 0)
        return (
          <Fragment key={group.key}>
            <TableRow>
              <TableCell className="min-w-[220px]">
                <div className="font-medium">{group.title}{group.variation ? ` — ${group.variation}` : ''}</div>
                <div className="text-xs text-muted-foreground">SKU {group.sku || 'não resolvido'}</div>
              </TableCell>
              <TableCell>{isStatic ? 'Estática' : custom.length > 0 ? 'Personalizada' : 'Revisar'}</TableCell>
              <TableCell className="text-right">{isStatic ? `${displayQuantity(planned)} cópia(s)` : `${displayQuantity(customPlanned)} nome(s)`}</TableCell>
              <TableCell className="min-w-[190px] text-xs">
                {isStatic ? <div>Enviadas {displayQuantity(sent)} · Confirmadas {displayQuantity(confirmed)}</div> : <div>Confirmadas {displayQuantity(customConfirmed)} / {displayQuantity(customPlanned)}</div>}
                {sends.length > 0 && <div className="text-muted-foreground">Último envio: {statusText(sends[0].status)}</div>}
                {pending.length > 0 && <div className="text-amber-800">{pending.length} pendência(s)</div>}
              </TableCell>
              <TableCell className="min-w-[190px] text-right">
                {isStatic ? <div className="flex justify-end gap-2">
                  <input aria-label={`Quantidade impressa de ${group.title}`} className="h-9 w-16 rounded-md border bg-background px-2 text-right text-sm" type="number" min="0" max={planned} value={confirmValues[group.key] ?? Math.min(planned, sent)} onChange={(event) => setConfirmValues((current) => ({ ...current, [group.key]: event.target.value }))} />
                  <Button size="sm" variant="outline" onClick={() => confirmStatic(group)} aria-label={`Confirmar impressas de ${group.title}`}><Check className="h-4 w-4" /></Button>
                  <Button size="sm" onClick={() => printGroup(group)} disabled={!isAgentOnline || !hasPdf || Boolean(busy) || planned <= sent}>
                    {busy === group.key ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Printer className="mr-2 h-4 w-4" />} Imprimir
                  </Button>
                </div> : custom.length > 0 ? <div className="flex justify-end gap-2">
                  <Button size="sm" variant="ghost" onClick={() => copyNames(group)}><Clipboard className="mr-2 h-4 w-4" /> Copiar nomes</Button>
                  <Button size="sm" variant="outline" onClick={() => openEditor(group)} disabled={!isAgentOnline || !hasPdf || Boolean(busy)}>
                    {busy === group.key ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <ExternalLink className="mr-2 h-4 w-4" />} Abrir editor
                  </Button>
                </div> : <span className="text-amber-800">Sem ação</span>}
              </TableCell>
            </TableRow>
            {(custom.length > 0 || pending.length > 0 || sends.length > 0 || !group.sku || (group.sku && isAgentOnline && !hasPdf)) && <TableRow>
              <TableCell colSpan={5} className="space-y-3 bg-muted/20">
                {custom.length > 0 && <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {custom.map((item) => <div key={item.id} className="flex items-center justify-between gap-2 rounded-md bg-background px-3 py-2 text-sm">
                    <span>{item.nome_personalizado}{quantity(item.quantidade_planejada) > 1 ? ` × ${displayQuantity(item.quantidade_planejada)}` : ''}</span>
                    <Button size="sm" variant={quantity(item.quantidade_confirmada) >= quantity(item.quantidade_planejada) ? 'secondary' : 'outline'} onClick={() => confirmPersonalized(item)} disabled={Boolean(item.pendencia)}>
                      <Check className="mr-1 h-3.5 w-3.5" /> {quantity(item.quantidade_confirmada) >= quantity(item.quantidade_planejada) ? 'Feito' : 'Confirmar'}
                    </Button>
                  </div>)}
                </div>}
                {pending.map((item) => <div key={item.id} className="rounded-md border border-amber-300 bg-amber-50/60 px-3 py-2 text-sm text-amber-950">
                  <strong>Pendente:</strong> {item.pendencia || `${displayQuantity(item.quantidade_planejada)} unidade(s) sem nome identificado pela IA.`}
                </div>)}
                {sends.length > 0 && <div className="space-y-1 text-xs text-muted-foreground">
                  {sends.slice(0, 4).map((send) => <div key={send.id} className="flex flex-wrap gap-x-2"><span>{displayQuantity(send.quantidade)} cópia(s)</span><span>· {statusText(send.status)}</span><span>· {send.printer_name || 'impressora não informada'}</span>{send.agent_job_id && <span>· trabalho {send.agent_job_id}</span>}{send.mensagem && <span>· {send.mensagem}</span>}</div>)}
                </div>}
                {allSendEvents.some((send) => send.chave_grupo === group.key && send.tipo === 'abrir_editor') && <p className="text-xs text-muted-foreground">PDF base aberto no editor. Marque cada nome após preparar a arte.</p>}
                {!group.sku && <p className="text-xs text-amber-800">SKU da capa não resolvido; confira a ficha de materiais.</p>}
                {group.sku && isAgentOnline && !hasPdf && <p className="text-xs text-amber-800">PDF não associado a esta capa nesta máquina. Configure no cadastro para liberar a impressão.</p>}
                {group.coverId && <Link className="text-xs text-primary underline" to={`/produtos/${group.coverId}/editar`}>Configurar PDF e impressora desta capa</Link>}
              </TableCell>
            </TableRow>}
          </Fragment>
        )
      })}
          </TableBody>
        </Table>
      </div>}
      {plan && <p className="text-xs text-muted-foreground">Os estados da fila ajudam a acompanhar o envio. Confirme somente a quantidade que saiu corretamente da impressora.</p>}
    </section>
        </DialogContent>
      </Dialog>
    </div>
  )
}
