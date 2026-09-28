import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { RefreshCw, Loader2, Printer } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import capaPrintService from '@/services/capaPrintService'
import useLocalAgent from '@/hooks/useLocalAgent'
import LocalAgentService from '@/services/LocalAgentService'

const statusLabel = (status) => ({
  queued: 'Na fila', na_fila: 'Na fila', preparando: 'Preparando', imprimindo: 'Imprimindo',
  enviado: 'Enviado', impresso: 'Saiu da fila', saiu_da_fila: 'Saiu da fila',
  sem_rastreio: 'Enviado, sem rastreio', erro: 'Falha na impressão',
  file_opened: 'PDF aberto no editor',
}[status] || status || 'Sem estado')

export default function CapaPrintQueuePage() {
  const { isAgentOnline } = useLocalAgent()
  const [plans, setPlans] = useState([])
  const [loading, setLoading] = useState(true)
  const load = useCallback(async () => {
    setLoading(true)
    try {
      setPlans(await capaPrintService.listPlans() || [])
    } catch (error) {
      toast.error(error.message)
    } finally {
      setLoading(false)
    }
  }, [])
  useEffect(() => { load() }, [load])

  useEffect(() => {
    if (!isAgentOnline || plans.length === 0) return undefined
    let alive = true
    const poll = async () => {
      for (const plan of plans) {
        for (const send of plan.envios || []) {
          if (!send.agent_job_id || !['queued', 'na_fila', 'preparando', 'imprimindo', 'enviado'].includes(send.status)) continue
          try {
            const result = await LocalAgentService.getPrintJob(send.agent_job_id)
            if (!alive || result.queue_status === send.status) continue
            const updated = await capaPrintService.updateSend(plan.id, send.request_id, {
              status: result.queue_status,
              mensagem: result.message || null,
            })
            if (alive) setPlans((current) => current.map((entry) => entry.id === plan.id ? updated : entry))
          } catch (error) {
            if (error.response?.status !== 404 || !alive) continue
            try {
              const updated = await capaPrintService.updateSend(plan.id, send.request_id, {
                status: 'sem_rastreio',
                mensagem: 'O trabalho já não está disponível na fila local deste agente.',
              })
              if (alive) setPlans((current) => current.map((entry) => entry.id === plan.id ? updated : entry))
            } catch {
              // O último estado conhecido permanece salvo na API.
            }
          }
        }
      }
    }
    const interval = window.setInterval(poll, 8000)
    poll()
    return () => { alive = false; window.clearInterval(interval) }
  }, [isAgentOnline, plans])

  return (
    <div className="space-y-5 p-6">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex-1">
          <h1 className="text-2xl font-bold">Fila de impressão de capas</h1>
          <p className="text-sm text-muted-foreground">Planos ativos, quantidades enviadas e confirmações de produção.</p>
        </div>
        <span className="text-xs text-muted-foreground">Agente {isAgentOnline ? 'online' : 'offline'}</span>
        <Button variant="outline" onClick={load} disabled={loading}><RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} /> Atualizar</Button>
      </div>
      {loading && <div className="flex justify-center py-12"><Loader2 className="h-6 w-6 animate-spin" /></div>}
      {!loading && plans.length === 0 && <Card><CardContent className="py-12 text-center text-sm text-muted-foreground">Ainda não há planos de impressão de capas.</CardContent></Card>}
      {!loading && plans.map((plan) => {
        const items = plan.itens || []
        const staticItems = items.filter((item) => item.tipo === 'estatica')
        const customItems = items.filter((item) => item.tipo === 'personalizada')
        const pending = items.filter((item) => item.tipo === 'pendente')
        const sends = plan.envios || []
        const sent = (plan.envios || []).filter((entry) => entry.tipo === 'estatica' && (entry.status !== 'erro' || entry.agent_job_id)).reduce((total, entry) => total + Number(entry.quantidade || 0), 0)
        const confirmed = (plan.grupos || []).reduce((total, entry) => total + Number(entry.quantidade_confirmada || 0), 0) + customItems.reduce((total, entry) => total + Number(entry.quantidade_confirmada || 0), 0)
        return (
          <Card key={plan.id}>
            <CardContent className="flex flex-wrap items-center gap-4 py-4">
              <div className="rounded-full bg-primary/10 p-3 text-primary"><Printer className="h-5 w-5" /></div>
              <div className="min-w-[240px] flex-1">
                <h2 className="font-semibold">{plan.demanda_id ? `Demanda ${plan.demanda_id}` : `Escopo com ${(plan.pedido_ids || []).length} pedidos`}</h2>
                <p className="text-xs text-muted-foreground">Atualizado {plan.updated_at ? new Date(plan.updated_at).toLocaleString('pt-BR') : '—'}</p>
              </div>
              <div className="text-sm">{staticItems.length} linha(s) estática(s) · {customItems.length} nome(s) · {pending.length} pendência(s)</div>
              <div className="text-sm">{sent} enviada(s) · {confirmed} confirmada(s)</div>
              {plan.demanda_id && <Link className="text-sm text-primary underline" to={`/producao/demanda/${plan.demanda_id}/dashboard`}>Abrir demanda</Link>}
            </CardContent>
            {sends.length > 0 && <CardContent className="space-y-2 border-t py-3">
              <h3 className="text-sm font-medium">Últimos trabalhos</h3>
              {sends.slice(0, 5).map((send) => {
                const item = items.find((entry) => entry.chave_grupo === send.chave_grupo)
                return <div key={send.id} className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
                  <span className="font-medium text-foreground">{item?.capa_nome || send.sku_capa}</span>
                  <span>{send.tipo === 'abrir_editor' ? 'Editor' : `${send.quantidade} cópia(s)`}</span>
                  <span>· {statusLabel(send.status)}</span>
                  {send.printer_name && <span>· {send.printer_name}</span>}
                  {send.agent_job_id && <span>· trabalho {send.agent_job_id}</span>}
                  {send.mensagem && <span>· {send.mensagem}</span>}
                </div>
              })}
            </CardContent>}
          </Card>
        )
      })}
    </div>
  )
}
