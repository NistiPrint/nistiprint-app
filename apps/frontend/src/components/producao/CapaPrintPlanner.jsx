import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { Check, Clipboard, ExternalLink, Printer, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import useLocalAgent from '@/hooks/useLocalAgent'
import LocalAgentService from '@/services/LocalAgentService'
import capaPrintService from '@/services/capaPrintService'

const number = (value) => Number(value || 0)
const format = (value) => number(value).toLocaleString('pt-BR', { maximumFractionDigits: 2 })
const requestId = () => globalThis.crypto?.randomUUID?.() || 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (digit) => {
  const random = Math.floor(Math.random() * 16)
  return (digit === 'x' ? random : (random & 0x3) | 0x8).toString(16)
})
const ROLES = { capa: 'Capa', contra: 'Contra', miolo: 'Miolo' }
const statusText = (status) => ({
  queued: 'Na fila', na_fila: 'Na fila', preparing: 'Preparando', printing: 'Imprimindo',
  impresso: 'Saiu da fila', saiu_da_fila: 'Saiu da fila', sem_rastreio: 'Enviado, sem rastreio',
  erro: 'Erro', sem_papel: 'Sem papel', impressora_offline: 'Impressora offline',
  file_opened: 'Editor aberto', cancelled: 'Cancelado',
}[status] || status || 'Sem estado')

function sentQuantity(sends) {
  return sends.filter((send) => send.status !== 'erro' || send.agent_job_id)
    .reduce((total, send) => total + number(send.quantidade), 0)
}

function groupItems(items = []) {
  const groups = new Map()
  for (const item of items) {
    if (number(item.quantidade_planejada) <= 0) continue
    const key = item.chave_grupo
    const group = groups.get(key) || {
      key, title: item.capa_nome || item.sku_capa || 'Arquivo sem cadastro',
      sku: item.sku_capa, artworkId: item.arte_id, productId: item.produto_final_id,
      coverId: item.produto_capa_id, roles: item.papeis || [], items: [],
    }
    group.items.push(item)
    groups.set(key, group)
  }
  return [...groups.values()]
}

export default function CapaPrintPlanner({ pedidoIds = [], lines = [], previsaoVersao = null, demandaId = null, onPlanChange = null }) {
  const { isAgentOnline, checkingAgent } = useLocalAgent()
  const [plan, setPlan] = useState(null)
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState('')
  const [mappings, setMappings] = useState({})
  const [confirmValues, setConfirmValues] = useState({})
  const [reconcileValues, setReconcileValues] = useState({})
  const groups = useMemo(() => groupItems(plan?.itens), [plan?.itens])
  const scopeSignature = JSON.stringify({ pedidoIds, lines, previsaoVersao })

  const load = useCallback(async (rebuild = false) => {
    setLoading(true)
    try {
      let next
      if (demandaId) {
        next = rebuild ? null : await capaPrintService.getPlan({ demanda_id: demandaId })
        if (!next) next = await capaPrintService.savePlan({ demanda_id: demandaId })
      } else {
        next = await capaPrintService.savePlan({ pedido_ids: pedidoIds, linhas: lines, previsao_versao: previsaoVersao })
      }
      setPlan(next)
      onPlanChange?.(next)
    } catch (error) {
      toast.error('Plano de impressão: ' + error.message)
    } finally {
      setLoading(false)
    }
  }, [demandaId, pedidoIds, lines, previsaoVersao, onPlanChange])

  useEffect(() => {
    if (demandaId) { load(); return undefined }
    if (!pedidoIds.length || !previsaoVersao) return undefined
    const timer = window.setTimeout(() => load(), 450)
    return () => window.clearTimeout(timer)
  }, [demandaId, scopeSignature])

  useEffect(() => {
    if (!isAgentOnline) { setMappings({}); return undefined }
    let active = true
    LocalAgentService.getMappings().then((result) => {
      if (active) setMappings(result.mappings || {})
    }).catch(() => { if (active) setMappings({}) })
    return () => { active = false }
  }, [isAgentOnline, open])

  useEffect(() => {
    if (!isAgentOnline || !plan?.envios?.some((send) => send.agent_job_id)) return undefined
    let active = true
    const poll = async () => {
      for (const send of plan.envios) {
        if (!send.agent_job_id || !['queued', 'na_fila', 'preparando', 'imprimindo', 'enviado'].includes(send.status)) continue
        try {
          const result = await LocalAgentService.getPrintJob(send.agent_job_id)
          if (!active || result.queue_status === send.status) continue
          const updated = await capaPrintService.updateSend(plan.id, send.request_id, {
            status: result.queue_status, mensagem: result.message || null,
          })
          if (active) setPlan(updated)
        } catch (error) {
          if (error.response?.status !== 404 || !active) continue
          const updated = await capaPrintService.updateSend(plan.id, send.request_id, {
            status: 'sem_rastreio', mensagem: 'Trabalho indisponível na fila local.',
          }).catch(() => null)
          if (updated && active) setPlan(updated)
        }
      }
    }
    const interval = window.setInterval(poll, 8000)
    poll()
    return () => { active = false; window.clearInterval(interval) }
  }, [isAgentOnline, plan?.id, plan?.envios])

  const stateFor = (group) => {
    const staticItems = group.items.filter((item) => item.tipo === 'estatica')
    const custom = group.items.filter((item) => item.tipo === 'personalizada')
    const issues = [...new Set(group.items.map((item) => item.pendencia).filter(Boolean))]
    const planned = staticItems.reduce((total, item) => total + number(item.quantidade_planejada), 0)
    const record = (plan?.grupos || []).find((entry) => entry.chave_grupo === group.key)
    const legacy = number(record?.quantidade_legada)
    const sends = (plan?.envios || []).filter((send) => send.chave_grupo === group.key)
    const sent = legacy + sentQuantity(sends.filter((send) => send.tipo === 'estatica'))
    const mapping = group.artworkId ? mappings['arte:' + group.artworkId] :
      (mappings[group.sku] || Object.values(mappings).find((entry) => String(entry.product_id || '') === String(group.coverId || '')))
    return { staticItems, custom, issues, planned, legacy, sends, sent, record, mapping,
      ready: Boolean(isAgentOnline && mapping?.file_path?.toLowerCase().endsWith('.pdf') && !issues.length && !record?.revisao_pendente) }
  }

  const register = async (group, id, type, copies, result) => {
    if (result.status === 'cancelled' || result.status === 'cancelled_size_warning') return
    const updated = await capaPrintService.registerSend(plan.id, {
      request_id: id, chave_grupo: group.key, sku_capa: group.sku || 'arte:' + group.artworkId,
      arte_id: group.artworkId || null, tipo: type, quantidade: copies,
      printer_name: result.printer_name || null, agent_job_id: result.job_id || null,
      status: result.status || 'sem_rastreio', mensagem: result.message || null,
    })
    setPlan(updated)
  }

  const printGroup = async (group) => {
    const state = stateFor(group)
    if (!state.ready || state.planned <= state.sent) return
    setBusy(group.key)
    const id = requestId()
    let result = null
    let attempted = false
    let remaining = state.planned - state.sent
    try {
      remaining = (await capaPrintService.prepareGroup(plan.id, group.key)).quantidade_pendente
      if (remaining <= 0) { toast.info('Não há cópias pendentes para este PDF.'); return }
      attempted = true
      result = await LocalAgentService.printWithDialog(group.sku, remaining, id, group.coverId, group.artworkId)
      await register(group, id, 'estatica', number(result.copies) || remaining, result)
      if (result.status !== 'cancelled' && result.status !== 'cancelled_size_warning') toast.success(format(result.copies || remaining) + ' cópia(s) enviadas.')
    } catch (error) {
      if (!result) {
        if (attempted) await register(group, id, 'estatica', remaining, { status: 'erro', message: error.message }).catch(() => null)
        toast.error(error.response?.data?.error || error.message)
      } else {
        toast.error('A impressora recebeu o trabalho, mas o registro falhou. Confira a fila antes de reenviar. Solicitação: ' + id)
      }
    } finally {
      setBusy('')
    }
  }

  const openEditor = async (group) => {
    const state = stateFor(group)
    if (!isAgentOnline || !state.mapping?.file_path?.toLowerCase().endsWith('.pdf')) return
    setBusy(group.key)
    const id = requestId()
    try {
      const result = await LocalAgentService.openMappedPdf(group.sku, id, group.coverId, group.artworkId)
      await register(group, id, 'abrir_editor', 0, result)
      toast.success('PDF base aberto no editor.')
    } catch (error) {
      toast.error(error.response?.data?.error || error.message)
    } finally {
      setBusy('')
    }
  }

  const confirmGroup = async (group, state) => {
    const quantity = number(confirmValues[group.key] ?? Math.min(state.planned, state.sent))
    if (quantity < 0 || quantity > state.sent) { toast.warning('Confirme no máximo a quantidade enviada.'); return }
    try { setPlan(await capaPrintService.confirmGroup(plan.id, group.key, quantity)); toast.success('Impressão confirmada.') }
    catch (error) { toast.error(error.message) }
  }

  const confirmItem = async (item) => {
    try { setPlan(await capaPrintService.confirmItem(plan.id, item.id, number(item.quantidade_planejada))) }
    catch (error) { toast.error(error.message) }
  }

  const reconcileItem = async (item) => {
    try {
      const quantity = Number(reconcileValues[item.id] ?? 0)
      setPlan(await capaPrintService.reconcileItem(plan.id, item.id, quantity))
      toast.success('Nome conciliado.')
    } catch (error) { toast.error(error.message) }
  }

  const reconcile = async (group) => {
    try {
      const quantity = Number(reconcileValues[group.key] ?? 0)
      setPlan(await capaPrintService.reconcileGroup(plan.id, group.key, quantity))
      toast.success('Histórico conciliado.')
    } catch (error) { toast.error(error.message) }
  }

  const copyNames = async (group) => {
    const names = group.items.filter((item) => item.tipo === 'personalizada' && item.nome_personalizado)
      .flatMap((item) => Array(Math.max(1, Math.floor(number(item.quantidade_planejada)))).fill(item.nome_personalizado))
    try { await navigator.clipboard.writeText(names.join('\n')); toast.success('Nomes copiados.') }
    catch { toast.error('Não foi possível copiar os nomes.') }
  }

  const printBatch = async () => {
    for (const group of groups) {
      const state = stateFor(group)
      if (state.staticItems.length && state.ready && state.planned > state.sent) await printGroup(group)
    }
  }

  if (!demandaId && (!pedidoIds.length || !previsaoVersao)) return null

  return <div className="inline-block">
    <Button type="button" variant="outline" onClick={() => setOpen(true)}><Printer className="mr-2 h-4 w-4" /> Impressão dos arquivos <Badge variant="secondary" className="ml-2">{groups.length}</Badge></Button>
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-h-[90vh] w-[calc(100%-2rem)] max-w-5xl overflow-y-auto">
        <DialogHeader><DialogTitle>Arquivos para impressão</DialogTitle><DialogDescription>{demandaId ? 'Arquivos dos pedidos desta demanda.' : 'Arquivos dos pedidos neste escopo.'} Um PDF marcado para capa e contracapa é enviado uma vez por unidade.</DialogDescription></DialogHeader>
        <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
          <div>Agente {checkingAgent ? 'verificando' : isAgentOnline ? 'online' : 'offline'} · {loading ? 'atualizando plano' : groups.length + ' arquivo(s)'}</div>
          <div className="flex gap-2"><Button type="button" size="sm" variant="outline" onClick={() => load(Boolean(demandaId))} disabled={loading}><RefreshCw className="mr-1 h-4 w-4" /> Atualizar</Button><Button type="button" size="sm" onClick={printBatch} disabled={!isAgentOnline || Boolean(busy) || !groups.some((group) => { const state = stateFor(group); return state.staticItems.length && state.ready && state.planned > state.sent })}><Printer className="mr-1 h-4 w-4" /> Imprimir lote</Button></div>
        </div>
        {!isAgentOnline && <p className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm">Inicie o agente local para abrir ou imprimir os PDFs desta máquina.</p>}
        {plan && !groups.length && <p className="rounded-md border p-4 text-sm">Nenhuma capa configurada para os pedidos deste plano.</p>}
        <div className="space-y-3">{groups.map((group) => {
          const state = stateFor(group)
          const origins = [...new Set(group.items.map((item) => item.pedido_codigo || item.pedido_id).filter(Boolean))]
          const customPlanned = state.custom.reduce((total, item) => total + number(item.quantidade_planejada), 0)
          const customConfirmed = state.custom.reduce((total, item) => total + number(item.quantidade_confirmada), 0)
          return <article key={group.key} className="rounded-lg border p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div><h3 className="font-semibold">{group.title}</h3><div className="mt-1 flex flex-wrap gap-1">{group.roles.map((role) => <Badge key={role} variant="secondary">{ROLES[role] || role}</Badge>)}{!group.artworkId && <Badge variant="outline">Vínculo antigo</Badge>}</div>
                <p className="mt-1 text-xs text-muted-foreground">{origins.length} pedido(s) · {origins.slice(0, 5).join(', ')}{origins.length > 5 ? '…' : ''}</p>
              </div>
              <div className="text-right text-sm">{state.staticItems.length > 0 && <div><strong>{format(state.planned)} cópia(s)</strong><div className="text-xs text-muted-foreground">{format(state.sent)} enviadas ou conciliadas · {format(state.record?.quantidade_confirmada)} confirmadas</div></div>}{state.custom.length > 0 && <div><strong>{format(customPlanned)} nome(s)</strong><div className="text-xs text-muted-foreground">{format(customConfirmed)} confirmados</div></div>}</div>
            </div>
            {state.issues.map((issue) => <p key={issue} className="mt-2 rounded-md border border-amber-300 bg-amber-50 p-2 text-sm text-amber-900">{issue}</p>)}
            {state.record?.revisao_pendente && <div className="mt-3 flex flex-wrap items-center gap-2 rounded-md border border-amber-400 bg-amber-50 p-3 text-sm"><span>Histórico antigo exige conferência. Quantas cópias deste PDF já estão impressas?</span><input aria-label={'Cópias antigas de ' + group.title} className="h-9 w-20 rounded border px-2" type="number" min="0" max={state.planned} value={reconcileValues[group.key] ?? 0} onChange={(event) => setReconcileValues((current) => ({ ...current, [group.key]: event.target.value }))} /><Button type="button" size="sm" onClick={() => reconcile(group)}>Conciliar</Button></div>}
            {state.staticItems.length > 0 && <div className="mt-3 flex flex-wrap items-center gap-2"><Button type="button" size="sm" onClick={() => printGroup(group)} disabled={!state.ready || Boolean(busy) || state.planned <= state.sent}><Printer className="mr-1 h-4 w-4" /> Imprimir {format(Math.max(0, state.planned - state.sent))}</Button><input aria-label={'Quantidade impressa de ' + group.title} className="h-9 w-20 rounded border px-2" type="number" min="0" max={state.sent} value={confirmValues[group.key] ?? Math.min(state.planned, state.sent)} onChange={(event) => setConfirmValues((current) => ({ ...current, [group.key]: event.target.value }))} /><Button type="button" size="sm" variant="outline" onClick={() => confirmGroup(group, state)} disabled={Boolean(state.record?.revisao_pendente)}><Check className="mr-1 h-4 w-4" /> Confirmar impressas</Button></div>}
            {state.custom.length > 0 && <div className="mt-3 space-y-2"><div className="flex flex-wrap gap-2"><Button type="button" size="sm" variant="outline" onClick={() => copyNames(group)}><Clipboard className="mr-1 h-4 w-4" /> Copiar nomes</Button><Button type="button" size="sm" variant="outline" onClick={() => openEditor(group)} disabled={!isAgentOnline || !state.mapping?.file_path?.toLowerCase().endsWith('.pdf') || Boolean(busy)}><ExternalLink className="mr-1 h-4 w-4" /> Abrir modelo</Button></div><div className="grid gap-2 sm:grid-cols-2">{state.custom.map((item) => <div key={item.id} className="flex flex-wrap items-center justify-between gap-2 rounded-md bg-muted/40 px-3 py-2 text-sm"><span>{item.nome_personalizado} · pedido {item.pedido_codigo || item.pedido_id}{number(item.quantidade_planejada) > 1 ? ' × ' + format(item.quantidade_planejada) : ''}</span>{item.revisao_pendente ? <div className="flex items-center gap-1"><input aria-label={'Já impressas para ' + item.nome_personalizado} className="h-8 w-16 rounded border px-2" type="number" min="0" max={item.quantidade_planejada} value={reconcileValues[item.id] ?? 0} onChange={(event) => setReconcileValues((current) => ({ ...current, [item.id]: event.target.value }))} /><Button type="button" size="sm" onClick={() => reconcileItem(item)}>Conciliar</Button></div> : <Button type="button" size="sm" variant="outline" disabled={Boolean(item.pendencia)} onClick={() => confirmItem(item)}>{number(item.quantidade_confirmada) >= number(item.quantidade_planejada) ? 'Feito' : 'Confirmar'}</Button>}</div>)}</div></div>}
            {!state.mapping && isAgentOnline && <p className="mt-2 text-xs text-amber-800">PDF não associado nesta máquina.</p>}
            <div className="mt-3 flex flex-wrap items-center gap-3 text-xs">{(group.productId || group.coverId) && <Link className="text-primary underline" to={'/produtos/' + (group.productId || group.coverId) + '/editar'}>Configurar PDF e componentes</Link>}<details><summary className="cursor-pointer text-primary">Ver pedidos e trabalhos</summary><div className="mt-2 space-y-1 text-muted-foreground"><div>Pedidos: {origins.join(', ') || 'não identificados'}</div>{state.sends.map((send) => <div key={send.id}>{format(send.quantidade)} cópia(s) · {statusText(send.status)} · {send.printer_name || 'sem impressora'}{send.mensagem ? ' · ' + send.mensagem : ''}</div>)}</div></details></div>
          </article>
        })}</div>
        {plan?.envios?.some((send) => !groups.some((group) => group.key === send.chave_grupo)) && <details className="rounded-md border p-3 text-xs"><summary className="cursor-pointer">Histórico dos vínculos antigos</summary><div className="mt-2 space-y-1">{plan.envios.filter((send) => !groups.some((group) => group.key === send.chave_grupo)).map((send) => <div key={send.id}>{send.sku_capa} · {format(send.quantidade)} cópia(s) · {statusText(send.status)}</div>)}</div></details>}
        <p className="text-xs text-muted-foreground">O estado da fila informa o envio. Confirme apenas o que saiu corretamente da impressora; impressões feitas no editor são confirmadas por nome.</p>
      </DialogContent>
    </Dialog>
  </div>
}
