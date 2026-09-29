import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { Check, Clipboard, ExternalLink, Printer, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import useLocalAgent from '@/hooks/useLocalAgent'
import LocalAgentService from '@/services/LocalAgentService'
import ProductService from '@/services/ProductService'
import capaPrintService from '@/services/capaPrintService'
import { summarizeProductPrint } from '@/lib/printPlanPresentation'

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
    const unresolvedSku = item.sku_capa || (key?.startsWith('sem_capa|') ? key.split('|')[1] : '')
    const group = groups.get(key) || {
      key, title: item.capa_nome || (unresolvedSku ? 'SKU ' + unresolvedSku : 'Item sem produto identificado'),
      sku: item.sku_capa, artworkId: item.arte_id, productId: item.produto_final_id,
      coverId: item.produto_capa_id, roles: item.papeis || [], items: [],
    }
    group.items.push(item)
    groups.set(key, group)
  }
  return [...groups.values()]
}

export default function CapaPrintPlanner({ pedidoIds = [], lines = [], previsaoVersao = null, demandaId = null, planId = null, standalone = false, onPlanChange = null }) {
  const { isAgentOnline, checkingAgent } = useLocalAgent()
  const [plan, setPlan] = useState(null)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState('')
  const [mappings, setMappings] = useState({})
  const [confirmValues, setConfirmValues] = useState({})
  const [reconcileValues, setReconcileValues] = useState({})
  const [productDetails, setProductDetails] = useState({})
  const rawGroups = useMemo(() => groupItems(plan?.itens), [plan?.itens])
  const detailIds = useMemo(() => [...new Set(rawGroups.flatMap((group) => [
    ...((group.productId && !plan?.produtos?.[group.productId]) ? [String(group.productId)] : []),
    ...((!group.artworkId && group.coverId) ? [String(group.coverId)] : []),
  ]))], [rawGroups, plan?.produtos])
  useEffect(() => {
    if (!standalone) return undefined
    const missing = detailIds.filter((id) => !productDetails[id])
    if (!missing.length) return undefined
    let active = true
    Promise.all(missing.map(async (id) => {
      try {
        const result = await ProductService.getById(id)
        const product = result.produto || result
        return [id, {
          name: product.nome || product.name || null,
          allowsArtwork: product.permite_arte === true,
          loaded: true,
        }]
      } catch {
        return [id, { name: null, allowsArtwork: false, loaded: true, error: true }]
      }
    })).then((entries) => {
      if (active) setProductDetails((current) => ({ ...current, ...Object.fromEntries(entries) }))
    })
    return () => { active = false }
  }, [standalone, detailIds, productDetails])

  const groups = useMemo(() => rawGroups.filter((group) =>
    group.artworkId || !group.coverId || productDetails[String(group.coverId)]?.allowsArtwork === true,
  ), [rawGroups, productDetails])
  const checkingComponents = rawGroups.some((group) => !group.artworkId && group.coverId && !productDetails[String(group.coverId)])
  const detailFailures = detailIds.filter((id) => productDetails[id]?.error).length
  const artworkCount = new Set(groups.filter((group) => group.artworkId).map((group) => group.artworkId)).size
  const unboundCount = groups.filter((group) => !group.artworkId).length
  const productSections = useMemo(() => {
    const sections = new Map()
    for (const group of groups) {
      const productId = group.productId ? String(group.productId) : null
      const key = productId || 'unresolved'
      if (!sections.has(key)) sections.set(key, {
        key,
        title: productId
          ? (plan?.produtos?.[productId] || productDetails[productId]?.name || (productDetails[productId]?.loaded ? 'Nome do produto indisponível' : 'Carregando produto…'))
          : 'Itens sem produto identificado',
        groups: [],
      })
      sections.get(key).groups.push(group)
    }
    for (const section of sections.values()) section.summary = summarizeProductPrint(section.groups)
    return [...sections.values()].sort((left, right) =>
      left.key === 'unresolved' ? 1 : right.key === 'unresolved' ? -1 : left.title.localeCompare(right.title, 'pt-BR'))
  }, [groups, plan?.produtos, productDetails])
  const recordsByGroup = useMemo(() => new Map((plan?.grupos || []).map((record) => [record.chave_grupo, record])), [plan?.grupos])
  const sendsByGroup = useMemo(() => {
    const index = new Map()
    for (const send of plan?.envios || []) {
      if (!index.has(send.chave_grupo)) index.set(send.chave_grupo, [])
      index.get(send.chave_grupo).push(send)
    }
    return index
  }, [plan?.envios])
  // Descrição e miolo não participam do cálculo; evite salvar o plano a cada
  // edição desses campos na consolidação.
  const scopeSignature = demandaId ? null : JSON.stringify({
    pedidoIds,
    previsaoVersao,
    lines: lines.map(({ ordem, sku, variacao, quantidade, produto_id }) =>
      [ordem, sku, variacao, quantidade, produto_id]),
  })

  const load = useCallback(async (rebuild = false) => {
    setLoading(true)
    try {
      let next
      if (planId) {
        next = await capaPrintService.getPlan({ plano_id: planId })
        if (!next) throw new Error('Plano não encontrado.')
      } else if (demandaId) {
        next = rebuild ? null : await capaPrintService.getPlan({ demanda_id: demandaId })
        if (!next) next = await capaPrintService.savePlan({ demanda_id: demandaId })
      } else {
        const scope = JSON.parse(scopeSignature)
        const relevantLines = scope.lines.map(([ordem, sku, variacao, quantidade, produto_id]) =>
          ({ ordem, sku, variacao, quantidade, produto_id }))
        next = await capaPrintService.savePlan({ pedido_ids: scope.pedidoIds, linhas: relevantLines, previsao_versao: scope.previsaoVersao })
      }
      setPlan(next)
      setProductDetails((current) => Object.fromEntries(Object.entries(current).filter(([, detail]) => !detail.error)))
      onPlanChange?.(next)
    } catch (error) {
      toast.error('Plano de impressão: ' + error.message)
    } finally {
      setLoading(false)
    }
  }, [planId, demandaId, scopeSignature, onPlanChange])

  useEffect(() => {
    if (standalone && (planId || demandaId)) { load(); return undefined }
    if (!standalone) return undefined
    const scope = JSON.parse(scopeSignature)
    if (!scope.pedidoIds.length || !scope.previsaoVersao) return undefined
    const timer = window.setTimeout(() => load(), 450)
    return () => window.clearTimeout(timer)
  }, [standalone, planId, demandaId, scopeSignature, load])

  useEffect(() => {
    if (!isAgentOnline) { setMappings({}); return undefined }
    let active = true
    LocalAgentService.getMappings().then((result) => {
      if (active) setMappings(result.mappings || {})
    }).catch(() => { if (active) setMappings({}) })
    return () => { active = false }
  }, [isAgentOnline, standalone])

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
    const record = recordsByGroup.get(group.key)
    const legacy = number(record?.quantidade_legada)
    const sends = sendsByGroup.get(group.key) || []
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
    setBusy('confirm-item')
    try { setPlan(await capaPrintService.confirmItem(plan.id, item.id, number(item.quantidade_planejada))) }
    catch (error) { toast.error(error.message) }
    finally { setBusy('') }
  }

  const confirmAllCustom = async (items) => {
    const pending = items.filter((item) => !item.pendencia && !item.revisao_pendente &&
      number(item.quantidade_confirmada) < number(item.quantidade_planejada))
    if (!pending.length) return
    setBusy('confirm-all')
    let confirmed = 0
    try {
      for (const item of pending) {
        const updated = await capaPrintService.confirmItem(plan.id, item.id, number(item.quantidade_planejada))
        setPlan(updated)
        confirmed += 1
      }
      toast.success(`${confirmed} nome(s) confirmado(s).`)
    } catch (error) {
      toast.error(`${confirmed} de ${pending.length} nome(s) confirmados. ${error.message}`)
    } finally {
      setBusy('')
    }
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

  const copyName = async (name) => {
    try { await navigator.clipboard.writeText(name); toast.success('Nome copiado.') }
    catch { toast.error('Não foi possível copiar o nome.') }
  }

  const printBatch = async () => {
    for (const group of groups) {
      const state = stateFor(group)
      if (state.staticItems.length && state.ready && state.planned > state.sent) await printGroup(group)
    }
  }

  if (!planId && !demandaId && (!pedidoIds.length || !previsaoVersao)) return null

  const openPage = async () => {
    const tab = window.open('', '_blank')
    if (!tab) { toast.error('Permita a abertura de novas guias para ver o plano.'); return }
    tab.document.title = 'Preparando plano de impressão'
    tab.document.body.textContent = 'Preparando plano de impressão…'
    setLoading(true)
    try {
      const next = await capaPrintService.savePlan(demandaId
        ? { demanda_id: demandaId }
        : { pedido_ids: pedidoIds, linhas: lines, previsao_versao: previsaoVersao })
      onPlanChange?.(next)
      tab.location.replace(`/despacho/plano-impressao?plano_id=${encodeURIComponent(next.id)}`)
    } catch (error) { tab.close(); toast.error('Plano de impressão: ' + error.message) }
    finally { setLoading(false) }
  }

  const content = <>
        <div className="flex flex-wrap items-center justify-between gap-2 border-b pb-3 text-sm">
          <span>Agente {checkingAgent ? 'verificando' : isAgentOnline ? 'online' : 'offline'} · {loading ? 'atualizando plano' : `${artworkCount} arte(s) · ${unboundCount} pendência(s) de vínculo`}</span>
          <div className="flex gap-2">
            <Button type="button" size="sm" variant="outline" onClick={() => load(Boolean(demandaId))} disabled={loading}><RefreshCw className="mr-1 h-4 w-4" /> Atualizar</Button>
            <Button type="button" size="sm" onClick={printBatch} disabled={!isAgentOnline || Boolean(busy) || !groups.some((group) => { const state = stateFor(group); return state.staticItems.length && state.ready && state.planned > state.sent })}><Printer className="mr-1 h-4 w-4" /> Imprimir lote</Button>
          </div>
        </div>
        {!isAgentOnline && <p className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm">Inicie o agente local para abrir ou imprimir os PDFs.</p>}
        {plan && !rawGroups.length && <p className="rounded-md border px-3 py-2 text-sm">Nenhum produto para impressão neste plano.</p>}
        {rawGroups.length > 0 && !groups.length && <p className="text-sm text-muted-foreground">{checkingComponents ? 'Verificando os componentes dos produtos…' : 'Nenhuma arte ou componente imprimível neste plano.'}</p>}
        {detailFailures > 0 && <p className="text-xs text-amber-800">Não foi possível consultar {detailFailures} produto(s). Atualize o plano para tentar novamente.</p>}
        <div className="space-y-2">{productSections.filter((section) => section.key !== 'unresolved').map((section) => {
          const artGroups = section.groups.filter((group) => group.artworkId)
          const withoutArt = section.groups.filter((group) => !group.artworkId)
          return <article key={section.key} className="rounded-lg border bg-background px-4 py-3">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b pb-2">
              <Link to={`/produtos/${section.key}/editar`} className="font-semibold text-foreground hover:text-primary hover:underline">{section.title}</Link>
              <Badge variant="secondary" className="text-sm">Qtde: {format(section.summary.quantity)}</Badge>
            </div>
            {artGroups.length ? artGroups.map((group) => {
              const state = stateFor(group)
              const origins = [...new Set(group.items.map((item) => item.pedido_codigo || item.pedido_id).filter(Boolean))]
              return <div key={group.key} className="border-b py-2 last:border-0 last:pb-0">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="min-w-0 text-sm"><span className="font-medium">Arte: {group.title}</span><span className="ml-2 text-muted-foreground">({group.roles.map((role) => ROLES[role] || role).join(' | ')})</span></div>
                  <div className="flex gap-1.5">
                    <Button type="button" size="sm" variant="outline" onClick={() => openEditor(group)} disabled={!isAgentOnline || !state.mapping?.file_path?.toLowerCase().endsWith('.pdf') || Boolean(busy)}><ExternalLink className="mr-1 h-3.5 w-3.5" /> Abrir</Button>
                    {state.staticItems.length > 0 && <Button type="button" size="sm" onClick={() => printGroup(group)} disabled={!state.ready || Boolean(busy) || state.planned <= state.sent}><Printer className="mr-1 h-3.5 w-3.5" /> Imprimir</Button>}
                  </div>
                </div>
                {!state.mapping && isAgentOnline && <p className="mt-1 text-xs text-amber-800">PDF não associado nesta máquina. <Link className="underline" to={`/produtos/${section.key}/editar`}>Configurar</Link></p>}
                {state.issues.filter((issue) => !issue.includes('sem nome identificado')).map((issue) => <p key={issue} className="mt-1 text-xs text-amber-800">{issue}</p>)}
                <div className="mt-2 text-xs text-muted-foreground"><p className="font-medium text-foreground">Detalhes e confirmações</p>
                  <div className="mt-2 space-y-2 rounded-md bg-muted/40 p-2">
                    <p>Pedidos: {origins.join(', ') || 'não identificados'}</p>
                    {state.issues.map((issue) => <p key={issue} className="text-amber-800">{issue}</p>)}
                    {state.record?.revisao_pendente && <div className="flex flex-wrap items-center gap-2"><span>Já impressas:</span><input aria-label={'Cópias antigas de ' + group.title} className="h-8 w-20 rounded border px-2" type="number" min="0" max={state.planned} value={reconcileValues[group.key] ?? 0} onChange={(event) => setReconcileValues((current) => ({ ...current, [group.key]: event.target.value }))} /><Button type="button" size="sm" onClick={() => reconcile(group)}>Conciliar histórico</Button></div>}
                    {state.staticItems.length > 0 && <div className="flex flex-wrap items-center gap-2"><span>{format(state.planned)} previstas · {format(state.sent)} enviadas · {format(state.record?.quantidade_confirmada)} confirmadas</span><input aria-label={'Quantidade impressa de ' + group.title} className="h-8 w-20 rounded border px-2" type="number" min="0" max={state.sent} value={confirmValues[group.key] ?? Math.min(state.planned, state.sent)} onChange={(event) => setConfirmValues((current) => ({ ...current, [group.key]: event.target.value }))} /><Button type="button" size="sm" variant="outline" onClick={() => confirmGroup(group, state)} disabled={Boolean(state.record?.revisao_pendente)}><Check className="mr-1 h-3.5 w-3.5" /> Confirmar impressas</Button></div>}
                    {state.custom.length > 0 && <div className="space-y-2 border-t pt-2">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-sm font-semibold text-foreground">Itens personalizados</p>
                        <Button type="button" size="sm" variant="outline" onClick={() => confirmAllCustom(state.custom)} disabled={Boolean(busy) || !state.custom.some((item) => !item.pendencia && !item.revisao_pendente && number(item.quantidade_confirmada) < number(item.quantidade_planejada))}><Check className="mr-1 h-3.5 w-3.5" /> Confirmar todos</Button>
                      </div>
                      {state.custom.map((item) => {
                        const confirmed = number(item.quantidade_confirmada) >= number(item.quantidade_planejada)
                        return <div key={item.id} className="grid grid-cols-[minmax(90px,1fr)_minmax(0,2fr)_auto] items-center gap-3 rounded-md bg-background px-3 py-2">
                          <span className="text-sm text-muted-foreground">Pedido {item.pedido_codigo || item.pedido_id || '—'}</span>
                          <button type="button" className="min-w-0 text-left text-base font-semibold text-foreground hover:text-primary hover:underline disabled:cursor-default disabled:hover:no-underline" onClick={() => copyName(item.nome_personalizado)} disabled={!item.nome_personalizado} title={item.nome_personalizado ? 'Copiar nome' : undefined} aria-label={`Copiar nome ${item.nome_personalizado || ''}`}>{item.nome_personalizado || 'Nome não identificado'} {item.nome_personalizado && <Clipboard className="ml-1 inline h-3.5 w-3.5 opacity-60" />}</button>
                          {item.revisao_pendente ? <div className="flex items-center gap-1"><input aria-label={'Já impressas para ' + item.nome_personalizado} className="h-8 w-16 rounded border px-2" type="number" min="0" max={item.quantidade_planejada} value={reconcileValues[item.id] ?? 0} onChange={(event) => setReconcileValues((current) => ({ ...current, [item.id]: event.target.value }))} /><Button type="button" size="sm" onClick={() => reconcileItem(item)}>Conciliar</Button></div> : <Button type="button" size="icon" variant={confirmed ? 'secondary' : 'outline'} disabled={Boolean(busy) || Boolean(item.pendencia) || confirmed} onClick={() => confirmItem(item)} aria-label={confirmed ? `Nome ${item.nome_personalizado} confirmado` : `Confirmar nome ${item.nome_personalizado}`} title={confirmed ? 'Confirmado' : 'Confirmar'}><Check className="h-4 w-4" /></Button>}
                        </div>
                      })}
                    </div>}
                    {state.sends.map((send) => <p key={send.id}>{format(send.quantidade)} cópia(s) · {statusText(send.status)} · {send.printer_name || 'sem impressora'}{send.mensagem ? ' · ' + send.mensagem : ''}</p>)}
                  </div>
                </div>
              </div>
            }) : <div className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm"><span className="font-medium text-amber-800">Sem arte associada</span><Link className="text-primary underline" to={`/produtos/${section.key}/editar`}>Configurar arte</Link></div>}
            {artGroups.length > 0 && withoutArt.length > 0 && <p className="mt-1 text-xs text-amber-800">{withoutArt.length} componente(s) ainda sem arte. <Link className="underline" to={`/produtos/${section.key}/editar`}>Configurar</Link></p>}
            {section.summary.personalized && <p className="mt-2 text-sm"><strong>{format(section.summary.namesIdentified)} nomes identificados</strong>{section.summary.namesPending > 0 && <span className="ml-2 text-amber-800">· {format(section.summary.namesPending)} pendentes</span>}</p>}
          </article>
        })}</div>
        {productSections.filter((section) => section.key === 'unresolved').map((section) => <details key={section.key} className="rounded-lg border px-4 py-3 text-sm"><summary className="cursor-pointer font-medium">{section.groups.length} itens sem produto identificado</summary><div className="mt-2 space-y-1 border-t pt-2">{section.groups.map((group) => <div key={group.key} className="flex justify-between gap-2"><span>{group.title}</span><span className="text-muted-foreground">Qtde: {format(summarizeProductPrint([group]).quantity)}</span></div>)}</div></details>)}
        {plan?.envios?.some((send) => !groups.some((group) => group.key === send.chave_grupo)) && <details className="rounded-md border p-3 text-xs"><summary className="cursor-pointer">Histórico dos vínculos antigos</summary><div className="mt-2 space-y-1">{plan.envios.filter((send) => !groups.some((group) => group.key === send.chave_grupo)).map((send) => <div key={send.id}>{send.sku_capa} · {format(send.quantidade)} cópia(s) · {statusText(send.status)}</div>)}</div></details>}
        <p className="text-xs text-muted-foreground">Confirme apenas as impressões concluídas. Personalizações são abertas no editor e confirmadas por nome.</p>
  </>

  if (standalone) return <main className="mx-auto max-w-6xl space-y-4 px-4 py-6 sm:px-6">
    <header><h1 className="text-2xl font-semibold">Plano de impressão</h1><p className="text-sm text-muted-foreground">{loading ? 'Carregando plano…' : 'Impressão por produto'}</p></header>
    {content}
  </main>

  return <div className="inline-block">
    <Button type="button" variant="outline" onClick={openPage} disabled={loading} title="Abrir plano em uma nova guia"><Printer className="mr-2 h-4 w-4" /> {loading ? 'Preparando…' : 'Plano de impressão'} <ExternalLink className="ml-2 h-3.5 w-3.5" /></Button>
  </div>
}
